import time
import cv2
import numpy as np
from pathlib import Path

try:
    import win32gui
    import win32ui
    import win32con
    import win32api
except ImportError:
    exit(1)

CONFIDENCE = 0.75

print("Você tem 5 segundos para clicar no jogo e deixá-lo em foco...")
for i in range(5, 0, -1):
    print(f"  {i}...")
    time.sleep(1)
print("Capturando tela agora!\n")


def capture_screen_win32():
    hdesktop = win32gui.GetDesktopWindow()
    width  = win32api.GetSystemMetrics(win32con.SM_CXVIRTUALSCREEN)
    height = win32api.GetSystemMetrics(win32con.SM_CYVIRTUALSCREEN)
    left   = win32api.GetSystemMetrics(win32con.SM_XVIRTUALSCREEN)
    top    = win32api.GetSystemMetrics(win32con.SM_YVIRTUALSCREEN)

    desktop_dc = win32gui.GetWindowDC(hdesktop)
    img_dc     = win32ui.CreateDCFromHandle(desktop_dc)
    mem_dc     = img_dc.CreateCompatibleDC()

    screenshot = win32ui.CreateBitmap()
    screenshot.CreateCompatibleBitmap(img_dc, width, height)
    mem_dc.SelectObject(screenshot)
    mem_dc.BitBlt((0, 0), (width, height), img_dc, (left, top), win32con.SRCCOPY)

    bmp_info = screenshot.GetInfo()
    bmp_data = screenshot.GetBitmapBits(True)

    img = np.frombuffer(bmp_data, dtype=np.uint8)
    img = img.reshape((bmp_info["bmHeight"], bmp_info["bmWidth"], 4))

    mem_dc.DeleteDC()
    img_dc.DeleteDC()
    win32gui.ReleaseDC(hdesktop, desktop_dc)
    win32gui.DeleteObject(screenshot.GetHandle())

    return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)


# Captura
screen_bgr  = capture_screen_win32()
screen_gray = cv2.cvtColor(screen_bgr, cv2.COLOR_BGR2GRAY)
print(f"Tela capturada: {screen_bgr.shape[1]}x{screen_bgr.shape[0]}")

cv2.imwrite("debug_raw_screen.png", screen_bgr)
print("Tela salva em: debug_raw_screen.png")
print("  → Abra este arquivo primeiro para confirmar que o jogo aparece!\n")

# Template
template_path = Path("floor2.png")
template      = cv2.imread(str(template_path), cv2.IMREAD_GRAYSCALE)
h, w          = template.shape
print(f"Template: {w}x{h}")

# Match
result = cv2.matchTemplate(screen_gray, template, cv2.TM_CCOEFF_NORMED)
_, max_val, _, max_loc = cv2.minMaxLoc(result)
locations = np.where(result >= CONFIDENCE)
matches   = list(zip(locations[1], locations[0]))

print(f"Matches >= {CONFIDENCE}: {len(matches)}")
print(f"Melhor match: score={max_val:.3f}  posição={max_loc}")

output = screen_bgr.copy()
for (x, y) in matches:
    cv2.rectangle(output, (x, y), (x + w, y + h), (0, 0, 255), 3)
    cv2.putText(output, f"{result[y,x]:.2f}", (x, y - 5),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)

cv2.rectangle(output, max_loc, (max_loc[0] + w, max_loc[1] + h), (0, 255, 0), 3)
cv2.imwrite("debug_screen.png", output)
print("\nResultado salvo em: debug_screen.png")
