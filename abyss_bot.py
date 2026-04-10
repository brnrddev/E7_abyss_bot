import random
import sys
import threading
import time
from pathlib import Path

import cv2
import numpy as np
import pyautogui

pyautogui.FAILSAFE = True

try:
    import win32api
    import win32con
    import win32gui
    import win32ui
except ImportError:
    print("❌ pywin32 não encontrado. Instale com: pip install pywin32")
    sys.exit(1)

# ─── Configurações ────────────────────────────────────────────────────────────

TEMPLATES = {
    "floor2":  "images/floor2.png",
    "replay":  "images/replay.png",
    "start":   "images/start.png",
    "confirm": "images/confirm.png",
    "clear":   "images/clear.png",
    "back":    "images/back.png",
}

CONFIDENCE = {
    "floor2":  0.75,
    "replay":  0.75,
    "start":   0.75,
    "confirm": 0.75,
    "clear":   0.72,
    "back":    0.75,
}

CLICK_RAND         = 8
DELAY_AFTER_REPLAY = (2.5, 4.0)
DELAY_AFTER_START  = (3.0, 5.0)
POLL_INTERVAL      = 0.5

# ─── Controle de pausa ────────────────────────────────────────────────────────

_paused = False
_stop   = False


def _hotkey_listener():
    try:
        import keyboard

        def toggle_pause():
            global _paused
            _paused = not _paused
            print(f"\n⚠  Bot {'PAUSADO' if _paused else 'RETOMADO'}. F10 para alternar.")

        def stop_bot():
            global _stop
            _stop = True
            print("\n🛑 Bot parado (F12).")

        keyboard.add_hotkey("F10", toggle_pause)
        keyboard.add_hotkey("F12", stop_bot)
        keyboard.wait()
    except ImportError:
        print("⚠  'keyboard' não encontrado — F10/F12 desativados.")
        print("   Para parar: mova o mouse para o canto superior-esquerdo.\n")


# ─── Captura de tela (win32) ──────────────────────────────────────────────────


def capture_screen() -> np.ndarray:
    """Captura o monitor principal via GDI. Funciona com janelas elevadas."""
    hdesktop = win32gui.GetDesktopWindow()
    width    = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    height   = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
    left     = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    top      = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)

    desktop_dc = win32gui.GetWindowDC(hdesktop)
    img_dc     = win32ui.CreateDCFromHandle(desktop_dc)
    mem_dc     = img_dc.CreateCompatibleDC()

    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(img_dc, width, height)
    mem_dc.SelectObject(bmp)
    mem_dc.BitBlt((0, 0), (width, height), img_dc, (left, top), win32con.SRCCOPY)

    info = bmp.GetInfo()
    data = bmp.GetBitmapBits(True)
    img  = np.frombuffer(data, dtype=np.uint8).reshape(
        (info["bmHeight"], info["bmWidth"], 4)
    )

    mem_dc.DeleteDC()
    img_dc.DeleteDC()
    win32gui.ReleaseDC(hdesktop, desktop_dc)
    win32gui.DeleteObject(bmp.GetHandle())

    return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)


# ─── Utilitários ──────────────────────────────────────────────────────────────


def load_templates() -> dict:
    base = Path(__file__).parent
    out  = {}
    for name, fname in TEMPLATES.items():
        path = base / fname
        if not path.exists():
            print(f"❌ Template não encontrado: {path}")
            sys.exit(1)
        img = cv2.imread(str(path), cv2.IMREAD_GRAYSCALE)
        if img is None:
            print(f"❌ Falha ao carregar: {path}")
            sys.exit(1)
        out[name] = img
        print(f"✅ {fname}  ({img.shape[1]}x{img.shape[0]})")
    return out


def find_template(screen_gray, tmpl_gray, confidence):
    res = cv2.matchTemplate(screen_gray, tmpl_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val >= confidence:
        h, w = tmpl_gray.shape
        return max_loc[0] + w // 2, max_loc[1] + h // 2
    return None


def find_template_score(screen_gray, tmpl_gray):
    """Retorna o score do melhor match (para debug)."""
    res = cv2.matchTemplate(screen_gray, tmpl_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    return max_val, max_loc


def rclick(x, y, label=""):
    ox = random.randint(-CLICK_RAND, CLICK_RAND)
    oy = random.randint(-CLICK_RAND, CLICK_RAND)
    fx, fy = x + ox, y + oy
    tag = f" [{label}]" if label else ""
    print(f"   🖱  clique{tag} → ({fx}, {fy})  [base: ({x}, {y}), offset: ({ox}, {oy})]")
    pyautogui.click(fx, fy)
    time.sleep(0.15)


def wait_check():
    while _paused:
        time.sleep(0.3)
    if _stop:
        print("🛑 Encerrando.")
        sys.exit(0)


def wait_for_template(templates, name, timeout=300.0):
    print(f"   🔎 Aguardando template '{name}' (timeout={timeout:.0f}s)...")
    deadline = time.time() + timeout
    attempts = 0
    while time.time() < deadline:
        wait_check()
        screen = capture_screen()
        score, loc = find_template_score(screen, templates[name])
        pos = None
        if score >= CONFIDENCE[name]:
            h, w = templates[name].shape
            pos = (loc[0] + w // 2, loc[1] + h // 2)

        attempts += 1
        if attempts % 6 == 0:
            status = f"encontrado em {pos}" if pos else f"não encontrado (melhor score: {score:.3f})"
            print(f"   🔎 '{name}' — tentativa {attempts} — {status}")

        if pos:
            print(f"   ✅ '{name}' encontrado em {pos} (score={score:.3f})")
            return pos
        time.sleep(POLL_INTERVAL)

    screen = capture_screen()
    score, loc = find_template_score(screen, templates[name])
    raise TimeoutError(
        f"'{name}' não encontrado após {timeout:.0f}s  "
        f"(melhor score foi {score:.3f}, threshold={CONFIDENCE[name]})"
    )


# ─── Lógica principal ─────────────────────────────────────────────────────────


def wait_for_back(templates):
    """
    Loop pós-Confirm:
    - Verifica se o Back está visível
    - Se não, clica em (680, 342) para avançar animações e aguarda 5s
    - Quando Back aparecer, clica em (205, 685) e retorna
    """
    print("\n⚔  [wait_for_back] Entrando no loop de espera pós-partida...")
    loop = 0

    while not _stop:
        loop += 1
        wait_check()

        screen = capture_screen()
        back_score, back_loc = find_template_score(screen, templates["back"])
        clear_score, clear_loc = find_template_score(screen, templates["clear"])

        print(f"   🔁 Loop #{loop} — "
              f"back score={back_score:.3f} (threshold={CONFIDENCE['back']}) | "
              f"clear score={clear_score:.3f} (threshold={CONFIDENCE['clear']})")

        if back_score >= CONFIDENCE["back"]:
            h, w = templates["back"].shape
            back_pos = (back_loc[0] + w // 2, back_loc[1] + h // 2)
            print(f"   ✅ Back detectado em {back_pos} — clicando em (205, 685)")
            rclick(205, 685, label="Back fixo")
            time.sleep(1.5)
            return

        print(f"   ⏳ Back não visível — clicando em (680, 342) para avançar animação")
        rclick(680, 342, label="avanço tela")
        time.sleep(5)


def run_iteration(templates, iteration):
    t_start = time.time()
    print(f"\n{'═'*50}")
    print(f"  Iteração #{iteration}  —  {time.strftime('%H:%M:%S')}")
    print(f"{'═'*50}")

    # 1. Clica 7x em (872, 327)
    print("\n[ETAPA 1] Navegando para Floor 2 — 7 cliques em (872, 327)")
    ##time.sleep(1)
    for i in range(7):
        print(f"   clique {i+1}/7 → (872, 327)")
        win32api.SetCursorPos((872, 327))
        time.sleep(0.15)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTDOWN, 872, 327, 0, 0)
        time.sleep(0.15)
        win32api.mouse_event(win32con.MOUSEEVENTF_LEFTUP, 872, 327, 0, 0)
        time.sleep(0.15)   
    time.sleep(3.0)
    print(f"   ✅ Navegação concluída ({time.time()-t_start:.1f}s)")

    # 2. Replay
    print("\n[ETAPA 2] Procurando Replay...")
    replay_pos = wait_for_template(templates, "replay", timeout=15)
    rclick(*replay_pos, label="Replay")

    # 3. Start
    delay = random.uniform(*DELAY_AFTER_REPLAY)
    print(f"\n[ETAPA 3] Aguardando {delay:.1f}s antes do Start...")
    time.sleep(delay)
    wait_check()
    start_pos = wait_for_template(templates, "start", timeout=20)
    rclick(*start_pos, label="Start")

    # 4. Confirm
    print(f"\n[ETAPA 4] Aguardando 2s antes do Confirm...")
    time.sleep(2)
    wait_check()
    confirm_pos = wait_for_template(templates, "confirm", timeout=20)
    rclick(*confirm_pos, label="Confirm")
    print(f"   ✅ Confirm clicado — partida iniciada ({time.time()-t_start:.1f}s desde início)")

    # 5. Espera pelo Back
    print(f"\n[ETAPA 5] Aguardando fim da partida...")
    wait_for_back(templates)

    elapsed = time.time() - t_start
    print(f"\n✅ Iteração #{iteration} concluída em {elapsed/60:.1f} min")


# ─── Contador de runs ─────────────────────────────────────────────────────────

REPORT_FILE = Path(__file__).parent / "abyss_runs.md"


def update_report(iteration: int, start_time: float):
    elapsed = time.time() - start_time
    hours   = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    seconds = int(elapsed % 60)
    avg_min = (elapsed / max(iteration, 1)) / 60

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("# Abyss Challenge Mode — Floor 2 Bot\n\n")
        f.write("| Campo | Valor |\n")
        f.write("|-------|-------|\n")
        f.write(f"| ✅ Runs completas | **{iteration}** |\n")
        f.write(f"| ⏱ Tempo total | {hours:02d}h {minutes:02d}m {seconds:02d}s |\n")
        f.write(f"| 📊 Média por run | {avg_min:.1f} min |\n")
        f.write(f"| 🕐 Última run | {time.strftime('%d/%m/%Y %H:%M:%S')} |\n")

    print(f"📝 Relatório atualizado → abyss_runs.md  (total: {iteration} runs)")


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    print("╔══════════════════════════════════════╗")
    print("║   Abyss Challenge Floor 2 Bot        ║")
    print("╠══════════════════════════════════════╣")
    print("║  F10 → Pausar / Retomar              ║")
    print("║  F12 → Parar                         ║")
    print("║  Mouse canto sup-esq → Emergência    ║")
    print("╚══════════════════════════════════════╝\n")

    threading.Thread(target=_hotkey_listener, daemon=True).start()

    templates = load_templates()

    print(f"\n⏱  Iniciando em 5 segundos — clique no jogo!\n")
    time.sleep(5)

    iteration  = 1
    start_time = time.time()

    while not _stop:
        try:
            run_iteration(templates, iteration)
            update_report(iteration, start_time)
            iteration += 1
        except TimeoutError as e:
            print(f"\n⚠  Timeout: {e}\n   Reiniciando loop em 3s...")
            time.sleep(3)
        except RuntimeError as e:
            print(f"\n❌ {e}")
            sys.exit(1)

    update_report(iteration - 1, start_time)
    print("\n✅ Bot finalizado.")


if __name__ == "__main__":
    main()