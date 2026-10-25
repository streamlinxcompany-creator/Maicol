"""Control remoto del PC desde un dispositivo emparejado: la pantalla en vivo y el ratón/teclado.

El celular pide un cuadro, lo muestra y recién ahí pide el siguiente: nunca se acumulan cuadros (en datos
móviles no se atrasa) y si la pantalla no cambia casi no se gasta red. Las coordenadas llegan normalizadas (0 a 1).
En modo touchpad el celular mueve el cursor en relativo («rel») y los clics sin x/y caen donde está el cursor.
"""
import ctypes
import hashlib
import io
from ctypes import wintypes

from PIL import Image, ImageDraw, ImageGrab

try:
    import pyautogui

    pyautogui.FAILSAFE = False  # tocar una esquina en el celular no debe cortar el control
    pyautogui.PAUSE = 0
except ImportError:  # deja arrancar a Maicol aunque falte la dependencia
    pyautogui = None

ANCHOS = {"normal": 1280, "hd": 1920}  # normal: se lee bien sin mandar megas por cuadro; hd: letra pequeña nítida


def disponible() -> bool:
    return pyautogui is not None


def cursor() -> tuple[float, float]:
    """Dónde está el cursor, normalizado (0 a 1): el celular lo sigue con el zoom."""
    x, y = pyautogui.position()
    ancho, alto = pyautogui.size()
    return x / max(1, ancho - 1), y / max(1, alto - 1)


def capturar(calidad: int = 55, nitidez: str = "normal") -> tuple[bytes, str]:
    """La pantalla principal en JPEG reducido, con el cursor dibujado (las capturas no lo traen)."""
    img = ImageGrab.grab()  # pantalla principal: mismas coordenadas que pyautogui
    ancho, alto = img.size
    escala = min(1.0, ANCHOS.get(nitidez, ANCHOS["normal"]) / ancho)
    if escala < 1:
        img = img.resize((round(ancho * escala), round(alto * escala)), Image.BILINEAR)
    x, y = pyautogui.position()
    cx, cy, r = x * escala, y * escala, 7
    d = ImageDraw.Draw(img)
    d.ellipse([cx - r - 2, cy - r - 2, cx + r + 2, cy + r + 2], fill=(0, 0, 0))
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 229, 255))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=max(25, min(85, int(calidad))))
    datos = buf.getvalue()
    return datos, hashlib.md5(datos).hexdigest()


# ---------- teclado ----------
TECLAS = {"enter": "enter", "borrar": "backspace", "esc": "esc", "tab": "tab", "espacio": "space",
          "arriba": "up", "abajo": "down", "izquierda": "left", "derecha": "right", "win": "win", "supr": "delete",
          "inicio": "home", "fin": "end"}
ATAJOS = {"copiar": ("ctrl", "c"), "pegar": ("ctrl", "v"), "cortar": ("ctrl", "x"), "deshacer": ("ctrl", "z"),
          "todo": ("ctrl", "a"), "cambiar_ventana": ("alt", "tab"), "cerrar_ventana": ("alt", "f4"), "escritorio": ("win", "d"),
          "minimizar": ("win", "down"), "maximizar": ("win", "up"), "buscar": ("win", "s"), "recorte": ("win", "shift", "s"),
          "tareas": ("ctrl", "shift", "esc"), "explorador": ("win", "e"), "pestana_nueva": ("ctrl", "t"),
          "cerrar_pestana": ("ctrl", "w"), "guardar": ("ctrl", "s"), "recargar": ("f5",), "zoom_mas": ("ctrl", "+"),
          "zoom_menos": ("ctrl", "-"), "volumen_mas": ("volumeup",), "volumen_menos": ("volumedown",), "silenciar": ("volumemute",),
          "pausa": ("playpause",)}


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ctypes.c_size_t)]


class _INPUT(ctypes.Structure):
    class _U(ctypes.Union):
        _fields_ = [("ki", _KEYBDINPUT), ("relleno", ctypes.c_byte * 32)]

    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _U)]


def escribir(texto: str):
    """Escribe cualquier texto (tildes, ñ, emojis) como si se tecleara."""
    utf16 = texto.encode("utf-16-le")
    eventos = []
    for i in range(0, len(utf16), 2):
        codigo = int.from_bytes(utf16[i:i + 2], "little")
        for flags in (0x0004, 0x0004 | 0x0002):  # KEYEVENTF_UNICODE, y su KEYEVENTF_KEYUP
            ev = _INPUT(type=1)
            ev.ki = _KEYBDINPUT(0, codigo, flags, 0, 0)
            eventos.append(ev)
    if eventos:
        ctypes.windll.user32.SendInput(len(eventos), (_INPUT * len(eventos))(*eventos), ctypes.sizeof(_INPUT))


# ---------- ratón y teclas ----------
def accion(m: dict):
    """Un gesto del celular convertido en ratón o teclado del PC."""
    t = m.get("t")
    if t == "texto":
        escribir(str(m.get("v", ""))[:500])
        return
    if t == "tecla":
        if m.get("v") in TECLAS:
            pyautogui.press(TECLAS[m["v"]])
        return
    if t == "atajo":
        if m.get("v") in ATAJOS:
            pyautogui.hotkey(*ATAJOS[m["v"]])
        return
    ancho, alto = pyautogui.size()
    if t == "rel":  # touchpad: dx/dy en fracciones de la pantalla del PC
        x, y = pyautogui.position()
        dx = max(-1.0, min(1.0, float(m.get("dx", 0)))) * ancho
        dy = max(-1.0, min(1.0, float(m.get("dy", 0)))) * alto
        pyautogui.moveTo(min(ancho - 1, max(0, round(x + dx))), min(alto - 1, max(0, round(y + dy))))
        return
    if "x" in m and "y" in m:
        x = round(min(1.0, max(0.0, float(m["x"]))) * (ancho - 1))
        y = round(min(1.0, max(0.0, float(m["y"]))) * (alto - 1))
    else:  # touchpad: donde esté el cursor
        x, y = pyautogui.position()
    boton = "right" if m.get("boton") == "derecho" else "left"
    if t == "mover":
        pyautogui.moveTo(x, y)
    elif t == "clic":
        pyautogui.click(x, y, button=boton)
    elif t == "doble":
        pyautogui.doubleClick(x, y)
    elif t == "bajar":
        pyautogui.mouseDown(x, y, button=boton)
    elif t == "subir":
        pyautogui.mouseUp(x, y, button=boton)
    elif t == "rueda":  # en Windows 120 = un «clic» de la rueda
        pyautogui.scroll(int(max(-2400, min(2400, float(m.get("cantidad", 0))))), x, y)
