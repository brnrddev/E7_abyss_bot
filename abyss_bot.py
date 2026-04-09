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
    sys.exit(1)

# ─── Configurações ────────────────────────────────────────────────────────────

TEMPLATES = {
    "floor2": "images/floor2.png",
    "replay": "images/replay.png",
    "start": "images/start.png",
    "confirm": "images/confirm.png",
    "clear": "images/clear.png",
    "back": "images/back.png",
}

CONFIDENCE = {
    "floor2": 0.75,
    "replay": 0.75,
    "start": 0.75,
    "confirm": 0.75,
    "clear": 0.72,
    "back": 0.75,
}

CLICK_RAND = 8
DELAY_AFTER_REPLAY = (2.5, 4.0)
DELAY_AFTER_START = (3.0, 5.0)
SCROLL_PAUSE = 0.5
POLL_INTERVAL = 0.5
CLEAR_CLICK_DELAY = 1.2
MAX_SCROLL_ATTEMPTS = 50

# Coordenada onde o scroll é aplicado — dentro da lista de floors
# Baseado na captura: lista fica entre x=808-993, centro ~900
# y=500 = meio vertical da lista
SCROLL_X = 900
SCROLL_Y = 500

# ─── Controle de pausa ────────────────────────────────────────────────────────

_paused = False
_stop = False


def _hotkey_listener():
    try:
        import keyboard

        def toggle_pause():
            global _paused
            _paused = not _paused
            print(
                f"\n Bot {'PAUSADO' if _paused else 'RETOMADO'}. F10 para alternar."
            )

        def stop_bot():
            global _stop
            _stop = True
            print("\n Bot parado (F12).")

        keyboard.add_hotkey("F10", toggle_pause)
        keyboard.add_hotkey("F12", stop_bot)
        keyboard.wait()
    except ImportError:
        print(" 'keyboard' não encontrado — F10/F12 desativados.")
        print("   Para parar: mova o mouse para o canto superior-esquerdo.\n")


# ─── Captura de tela (win32) ──────────────────────────────────────────────────


def capture_screen() -> np.ndarray:
    """Captura o monitor principal via GDI. Funciona com janelas elevadas."""
    hdesktop = win32gui.GetDesktopWindow()
    width = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
    left = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    top = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)

    desktop_dc = win32gui.GetWindowDC(hdesktop)
    img_dc = win32ui.CreateDCFromHandle(desktop_dc)
    mem_dc = img_dc.CreateCompatibleDC()

    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(img_dc, width, height)
    mem_dc.SelectObject(bmp)
    mem_dc.BitBlt((0, 0), (width, height), img_dc, (left, top), win32con.SRCCOPY)

    info = bmp.GetInfo()
    data = bmp.GetBitmapBits(True)

    img = np.frombuffer(data, dtype=np.uint8).reshape(
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
    out = {}
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
        print(f" {fname}  ({img.shape[1]}x{img.shape[0]})")
    return out


def find_template(screen_gray, tmpl_gray, confidence):
    res = cv2.matchTemplate(screen_gray, tmpl_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    if max_val >= confidence:
        h, w = tmpl_gray.shape
        return max_loc[0] + w // 2, max_loc[1] + h // 2
    return None


def rclick(x, y):
    ox = random.randint(-CLICK_RAND, CLICK_RAND)
    oy = random.randint(-CLICK_RAND, CLICK_RAND)
    pyautogui.click(x + ox, y + oy)
    time.sleep(0.15)


def wait_check():
    while _paused:
        time.sleep(0.3)
    if _stop:
        print(" Encerrando.")
        sys.exit(0)


def wait_for_template(templates, name, timeout=300.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        wait_check()
        screen = capture_screen()
        pos = find_template(screen, templates[name], CONFIDENCE[name])
        if pos:
            return pos
        time.sleep(POLL_INTERVAL)
    raise TimeoutError(f"'{name}' não encontrado em {timeout:.0f}s")


# ─── Lógica principal ─────────────────────────────────────────────────────────


def select_floor2():
    """Clica direto na coordenada fixa do Floor 2 (872, 327)."""
    print(" Clicando em Floor 2 (coordenada fixa)...")
    rclick(872, 327)
    time.sleep(0.8)


def wait_for_back(templates):
    """
    Após o Confirm:
    - A cada 5s clica em (680, 342)
    - Procura o botão Back continuamente
    - Quando encontrar, clica e sai
    """
    print("  Partida em andamento (modo ativo)...")

    while not _stop:
        wait_check()

        # 1. Captura tela e procura botão Back
        screen = capture_screen()
        pos = find_template(screen, templates["back"], CONFIDENCE["back"])

        if pos:
            print("    Botão Back encontrado! Clicando em (205, 685)...")
            rclick(205, 685)
            time.sleep(1.5)
            return

        # 2. Se não encontrou, clica no ponto fixo
        print("    Back não encontrado → clicando em (680, 342)...")
        rclick(680, 342)

        # 3. Aguarda 5 segundos antes de repetir
        time.sleep(5)


def run_iteration(templates, iteration):
    print(f"\n{'═' * 50}")
    print(f"  Iteração #{iteration}")
    print(f"{'═' * 50}")

    # 1. Clica 7x em (872, 327) para chegar na tela do Floor 2
    time.sleep(1)
    print("Clicando 7x em (872, 327)...")
    for _ in range(7):
        rclick(872, 327)
        time.sleep(0.4)
    time.sleep(0.8)

    # 2. Replay
    print(" Aguardando botão Replay...")
    replay_pos = wait_for_template(templates, "replay", timeout=15)
    print(f"   Clicando em Replay {replay_pos}")
    rclick(*replay_pos)

    # 3. Start
    delay = random.uniform(*DELAY_AFTER_REPLAY)
    print(f" Aguardando {delay:.1f}s → Start...")
    time.sleep(delay)
    wait_check()
    start_pos = wait_for_template(templates, "start", timeout=20)
    print(f"   Clicando em Start {start_pos}")
    rclick(*start_pos)

    # 4. Confirm
    delay = random.uniform(*DELAY_AFTER_START)
    print(f" Aguardando {delay:.1f}s → Confirm...")
    time.sleep(2)
    wait_check()
    confirm_pos = wait_for_template(templates, "confirm", timeout=20)
    print(f"   Clicando em Confirm {confirm_pos}")
    rclick(*confirm_pos)

    # 5. Aguarda fim + clica até achar Back
    print("  Partida em andamento...")
    wait_for_back(templates)


# ─── Contador de runs ─────────────────────────────────────────────────────────

REPORT_FILE = Path(__file__).parent / "abyss_runs.md"


def update_report(iteration: int, start_time: float):
    """Cria/atualiza o arquivo abyss_runs.md com o contador de runs."""
    elapsed = time.time() - start_time
    hours = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    seconds = int(elapsed % 60)
    avg_sec = elapsed / max(iteration, 1)
    avg_min = avg_sec / 60

    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("# Abyss Challenge Mode — Floor 2 Bot\n\n")
        f.write("| Campo | Valor |\n")
        f.write("|-------|-------|\n")
        f.write(f"|  Runs completas | **{iteration}** |\n")
        f.write(f"| Tempo total | {hours:02d}h {minutes:02d}m {seconds:02d}s |\n")
        f.write(f"| Média por run | {avg_min:.1f} min |\n")

    print(f"Relatório atualizado → abyss_runs.md  (total: {iteration} runs)")


# ─── Main ─────────────────────────────────────────────────────────────────────


def main():
    print("╔══════════════════════════════════════╗")
    print("║   Abyss Challenge Floor 2 Bot MVP    ║")
    print("╠══════════════════════════════════════╣")
    print("║  F10 → Pausar / Retomar              ║")
    print("║  F12 → Parar                         ║")
    print("║  Mouse canto sup-esq → Emergência    ║")
    print("╚══════════════════════════════════════╝\n")

    threading.Thread(target=_hotkey_listener, daemon=True).start()

    templates = load_templates()

    print(f"\n  Iniciando em 5 segundos — clique no jogo!\n")
    time.sleep(5)

    iteration = 1
    start_time = time.time()

    while not _stop:
        try:
            run_iteration(templates, iteration)
            update_report(iteration, start_time)
            iteration += 1
        except TimeoutError as e:
            print(f"\n  Timeout: {e}\n   Reiniciando loop em 3s...")
            time.sleep(3)
        except RuntimeError as e:
            print(f"\n❌ {e}")
            sys.exit(1)

    update_report(iteration - 1, start_time)
    print("\n Bot finalizado.")


if __name__ == "__main__":
    main()
