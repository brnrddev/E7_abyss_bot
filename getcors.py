from pynput import mouse

def on_click(x, y, button, pressed):
    if pressed:
        print(f"  Clique em: x={x}, y={y}   [{button}]")
with mouse.Listener(on_click=on_click) as listener:
    listener.join()
