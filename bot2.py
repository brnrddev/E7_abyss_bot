import ctypes
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()

import random
import sys
import threading
import time
from pathlib import Path
import tkinter as tk

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

CLICK_RAND         = 0
DELAY_AFTER_REPLAY = (2.5, 4.0)
DELAY_AFTER_START  = (3.0, 5.0)
POLL_INTERVAL      = 0.5
game_window = "Epic Seven"
# ─── Controle de pausa ────────────────────────────────────────────────────────

_paused = False
_stop   = False

start_time = 0.0
completed_runs = 0
counter_lock = threading.Lock()


def _hotkey_listener():
    try:
        import keyboard

        def stop_bot():
            global _stop
            _stop = True
            print("\n Bot parado (F12).")
        
        keyboard.add_hotkey("F12", stop_bot)
        keyboard.wait()
    except ImportError:
        print(" 'keyboard' não encontrado — F10/F12 desativados.")
        print("   Para parar: mova o mouse para o canto superior-esquerdo.\n")

# ─── Captura de tela (win32) ──────────────────────────────────────────────────

def find_game_window(window_title_keyword=game_window):
    """Encontra a janela do jogo pelo título"""
    hwnd = win32gui.FindWindow(None, window_title_keyword)
    if hwnd == 0:
        windows = []
        win32gui.EnumWindows(lambda h, l: windows.append((h, win32gui.GetWindowText(h))), None)
        for h, title in windows:
            if window_title_keyword.lower() in title.lower():
                return h
    return hwnd

def screen_to_window_coords(hwnd, x, y):
    """Converte coordenadas de desktop para coordenadas relativas à janela"""
    left, top, right, bottom = win32gui.GetWindowRect(hwnd)
    return (x - left, y - top)

def bg_click(hwnd, x, y, label="", relative=False):
    """Clique em janela de background (sem ativar)
    
    Args:
        hwnd: Handle da janela
        x, y: Coordenadas (relativas à janela se relative=True, absolutas do desktop se False)
        label: Descrição do clique
        relative: Se True, x,y são relativas; se False, converte automaticamente
    """
    tag = f" [{label}]" if label else ""
    
    try:
        if not relative:
            # Converte coordenadas absolutas para relativas
            x, y = screen_to_window_coords(hwnd, x, y)
        
        print(f"  clique{tag} → ({x},{y}) [BACKGROUND]")
        
        lparam = win32api.MAKELONG(int(x), int(y))
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONDOWN, win32con.MK_LBUTTON, lparam)
        time.sleep(0.05)
        win32gui.PostMessage(hwnd, win32con.WM_LBUTTONUP, 0, lparam)
        time.sleep(0.15)
    except Exception as e:
        print(f"  ⚠️ Erro ao clicar: {e}")
        
def capture_screen(hwnd=None) -> np.ndarray:
    """Captura a janela especificada ou todo o desktop"""
    if hwnd:
        try:
            left, top, right, bottom = win32gui.GetWindowRect(hwnd)
            width = right - left
            height = bottom - top
            
            desktop_dc = win32gui.GetWindowDC(hwnd)
            img_dc = win32ui.CreateDCFromHandle(desktop_dc)
            mem_dc = img_dc.CreateCompatibleDC()
            
            bmp = win32ui.CreateBitmap()
            bmp.CreateCompatibleBitmap(img_dc, width, height)
            mem_dc.SelectObject(bmp)
            mem_dc.BitBlt((0, 0), (width, height), img_dc, (0, 0), win32con.SRCCOPY)
            
            info = bmp.GetInfo()
            data = bmp.GetBitmapBits(True)
            img = np.frombuffer(data, dtype=np.uint8).reshape(
                (info["bmHeight"], info["bmWidth"], 4)
            )
            
            mem_dc.DeleteDC()
            img_dc.DeleteDC()
            win32gui.ReleaseDC(hwnd, desktop_dc)
            win32gui.DeleteObject(bmp.GetHandle())
            
            return cv2.cvtColor(img, cv2.COLOR_BGRA2GRAY)
        except:
            pass
    
    hdesktop = win32gui.GetDesktopWindow()
    width = win32api.GetSystemMetrics(win32con.SM_CXSCREEN)
    height = win32api.GetSystemMetrics(win32con.SM_CYSCREEN)
    
    desktop_dc = win32gui.GetWindowDC(hdesktop)
    img_dc = win32ui.CreateDCFromHandle(desktop_dc)
    mem_dc = img_dc.CreateCompatibleDC()
    
    bmp = win32ui.CreateBitmap()
    bmp.CreateCompatibleBitmap(img_dc, width, height)
    mem_dc.SelectObject(bmp)
    mem_dc.BitBlt((0, 0), (width, height), img_dc, (0, 0), win32con.SRCCOPY)
    
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
        print(f"{fname}  ({img.shape[1]}x{img.shape[0]})")
    return out


def find_template_score(screen_gray, tmpl_gray):
    res = cv2.matchTemplate(screen_gray, tmpl_gray, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, max_loc = cv2.minMaxLoc(res)
    return max_val, max_loc

# MOSTRAR CONTADOR

def _format_duration(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds = int(seconds % 60)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def show_counter():
    root = tk.Tk()
    root.title("Abyss Bot - Contador de Runs")
    root.geometry("320x110+10+10")
    root.attributes("-topmost", True)
    root.overrideredirect(True)
    root.config(bg="#202020")

    label = tk.Label(
        root,
        text="Runs completas: 0\nTempo: 00:00:00\nRadiance Coins: 0",
        font=("Arial", 12),
        fg="#ffffff",
        bg="#202020",
        justify="left",
    )
    label.pack(padx=12, pady=12)

    def update_label():
        with counter_lock:
            elapsed = time.time() - start_time if start_time else 0.0
            runs = completed_runs
            coins = runs * 30

        label.config(
            text=(
                f"Runs completas: {runs}\n"
                f"Tempo: {_format_duration(elapsed)}\n"
                f"Radiance Coins: {coins}"
            )
        )
        root.after(1000, update_label)

    update_label()
    root.mainloop()

# ─── DPI Scale ───────────────────────────

def _get_dpi_scale() -> float:
    hdc = win32gui.GetDC(0)
    dpi = win32ui.CreateDCFromHandle(hdc).GetDeviceCaps(88)
    win32gui.ReleaseDC(0, hdc)
    return dpi / 96.0

DPI_SCALE = _get_dpi_scale()

def wait_check():
    while _paused:
        time.sleep(0.3)
    if _stop:
        print(" Encerrando.")
        sys.exit(0)


def wait_for_template(templates, name, timeout=300.0, hwnd=None): 
    deadline = time.time() + timeout
    while time.time() < deadline:
        wait_check()
        screen = capture_screen(hwnd)
        score, loc = find_template_score(screen, templates[name])
        if score >= CONFIDENCE[name]:
            h, w = templates[name].shape
            pos = (loc[0] + w // 2, loc[1] + h // 2)
            print(f" '{name}' encontrado em {pos} (score={score:.3f})")
            return pos
        time.sleep(POLL_INTERVAL)

    screen = capture_screen(hwnd)
    score, _ = find_template_score(screen, templates[name])
    raise TimeoutError(
        f"'{name}' não encontrado após {timeout:.0f}s "
        f"(melhor score={score:.3f}, threshold={CONFIDENCE[name]})"
    )
    
def wait_for_back(templates, hwnd):  # ← ADICIONE hwnd
    print("\n Aguardando fim da partida...")
    while not _stop:
        wait_check()
        screen = capture_screen(hwnd)  # ← ADICIONE hwnd
        back_score, back_loc = find_template_score(screen, templates["back"])

        if back_score >= CONFIDENCE["back"]:
            h, w = templates["back"].shape
            back_pos = (back_loc[0] + w // 2, back_loc[1] + h // 2)
            print(f"  Back detectado em {back_pos}")
            bg_click(hwnd, 205, 685, label="Back")  # ← MUDE para bg_click
            time.sleep(1.5)
            return

        bg_click(hwnd, 680, 342, label="avanço tela")  # ← MUDE para bg_click
        time.sleep(5)
        
def run_iteration(templates, iteration, hwnd):
    t_start = time.time()
    print(f"\n{'═'*50}")
    print(f"  Iteração #{iteration}  —  {time.strftime('%H:%M:%S')}")
    print(f"{'═'*50}")

    # 1. Clica 7x em (872, 327) - COORDENADAS RELATIVAS À JANELA
    print("\n[ETAPA 1] Navegando para Floor 2")
    time.sleep(1)
    for i in range(7):
        bg_click(hwnd, 872, 327, label=f"Floor2 {i+1}/7", relative=True)  # ← relative=True
        time.sleep(0.40)
    time.sleep(1.0)

    # 2. Replay
    print("\n[ETAPA 2] Procurando Replay...")
    replay_pos = wait_for_template(templates, "replay", timeout=15, hwnd=hwnd)
    bg_click(hwnd, *replay_pos, label="Replay", relative=True)  # ← relative=True

    # 3. Start
    delay = random.uniform(*DELAY_AFTER_REPLAY)
    print(f"\n[ETAPA 3] Aguardando {delay:.1f}s antes do Start...")
    time.sleep(delay)
    wait_check()
    start_pos = wait_for_template(templates, "start", timeout=20, hwnd=hwnd)
    bg_click(hwnd, *start_pos, label="Start", relative=True)  # ← relative=True

    # 4. Confirm
    print(f"\n[ETAPA 4] Aguardando 2s antes do Confirm...")
    time.sleep(2)
    wait_check()
    confirm_pos = wait_for_template(templates, "confirm", timeout=20, hwnd=hwnd)
    bg_click(hwnd, *confirm_pos, label="Confirm", relative=True)  # ← relative=True

    # 5. Espera pelo Back
    wait_for_back(templates, hwnd)

    elapsed = time.time() - t_start
    print(f"\n Iteração #{iteration} concluída em {elapsed/60:.1f} min")


def wait_for_back(templates, hwnd):
    print("\n Aguardando fim da partida...")
    while not _stop:
        wait_check()
        screen = capture_screen(hwnd)
        back_score, back_loc = find_template_score(screen, templates["back"])

        if back_score >= CONFIDENCE["back"]:
            h, w = templates["back"].shape
            back_pos = (back_loc[0] + w // 2, back_loc[1] + h // 2)
            print(f"  Back detectado em {back_pos}")
            bg_click(hwnd, 205, 685, label="Back", relative=True)  # ← relative=True
            time.sleep(1.5)
            return

        bg_click(hwnd, 680, 342, label="avanço tela", relative=True)  # ← relative=True
        time.sleep(5)
    
def update_report(iteration: int, start_time: float):
    global completed_runs

    elapsed = time.time() - start_time
    hours   = int(elapsed // 3600)
    minutes = int((elapsed % 3600) // 60)
    seconds = int(elapsed % 60)

    avg_min = (elapsed / iteration / 60) if iteration > 0 else 0

    radiance_coins = iteration * 30

    with counter_lock:
        completed_runs = iteration

# ─── Main ─────────────────────────────────────────────────────────────────────
def main():
    print("╔══════════════════════════════════════╗")
    print("║  F12 → Parar                         ║")
    print("╚══════════════════════════════════════╝\n")

    threading.Thread(target=_hotkey_listener, daemon=True).start()

    print("Procurando janela do jogo...")
    game_hwnd = find_game_window(game_window)
    if game_hwnd == 0:
        print("❌ Janela não encontrada! Verificar título da janela.")
        sys.exit(1)
    
    print(f"Janela encontrada (HWND: {game_hwnd})")

    templates = load_templates()

    print(f"\n Iniciando em 5 segundos\n")
    threading.Thread(target=show_counter, daemon=True).start()
    time.sleep(5)

    global start_time, completed_runs
    iteration  = 1
    start_time = time.time()
    completed_runs = 0

    while not _stop:
        try:
            run_iteration(templates, iteration, game_hwnd)
            update_report(iteration, start_time)
            iteration += 1
        except TimeoutError as e:
            print(f"\n Timeout: {e}\n   Reiniciando loop em 3s...")
            time.sleep(3)
        except RuntimeError as e:
            print(f"\n❌ {e}")
            sys.exit(1)

    update_report(iteration - 1, start_time)
    final_coins = (iteration - 1) * 30
    print(f"\n Bot finalizado. (Radiance Coins: {final_coins})")


if __name__ == "__main__":
    main()