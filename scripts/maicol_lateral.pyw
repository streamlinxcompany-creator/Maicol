"""Maicol en el lateral de la pantalla (como el prototipo): una píldora de luz en el borde; al tocarla, el panel
de Maicol se desliza desde ese lado, y se vuelve a guardar cuando trabajas en otra cosa.

El panel es la interfaz web en modo lateral (?lateral=1) abierta como app de Edge, sin marco y con esquinas
redondeadas: así conserva la voz neuronal de Edge y el micrófono.
Clic: abrir/guardar · arrastrar: subir/bajar · clic derecho: fijar abierto, cambiar de lado, ventana grande, salir.
Se arranca con MAICOL.bat (o el acceso directo «Maicol IA» del escritorio).
"""
import ctypes
import json
import math
import os
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
from ctypes import wintypes
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
PREFS = RAIZ / "data" / "lateral.json"
REGISTRO = RAIZ / "data" / "lateral.log"
TAREA_ADMIN = "Maicol Nucleo"  # la crea scripts/instalar_admin.ps1: el núcleo como administrador, sin ventana de UAC
TITULO = "Maicol lateral"  # document.title del modo lateral en web/app.js
ACENTO = (0, 229, 255)
CLAVE = "#010203"  # color que Windows vuelve transparente en la pestaña (solo se ve la píldora)
ANCHO_TAB, ALTO_TAB = 34, 128
PILDORA_REPOSO, PILDORA_ENCIMA = 6, 28
ANCHO_PANEL, ALTO_PANEL = 400, 720
MARGEN = PILDORA_ENCIMA + 12  # el panel queda al lado de la píldora, sin taparla
RADIO = 28   # esquinas del panel

user32, gdi32 = ctypes.windll.user32, ctypes.windll.gdi32
# sin esto, HWND_TOPMOST (-1) y los estilos viajan como enteros de 32 bits y Windows los rechaza
user32.SetWindowPos.argtypes = [wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.GetParent.restype = wintypes.HWND
user32.GetForegroundWindow.restype = wintypes.HWND
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowRgn.argtypes = [wintypes.HWND, wintypes.HANDLE, wintypes.BOOL]
gdi32.CreateRoundRectRgn.restype = wintypes.HANDLE
try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)  # coordenadas en píxeles reales, iguales a las de Windows
except (AttributeError, OSError):
    user32.SetProcessDPIAware()

SW_HIDE, SW_SHOWNA, SW_RESTORE = 0, 8, 9
HWND_TOPMOST, HWND_NOTOPMOST = -1, -2
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_FRAMECHANGED, SWP_SHOWWINDOW = 0x1, 0x2, 0x10, 0x20, 0x40
GWL_STYLE, GWL_EXSTYLE = -16, -20
WS_CAPTION, WS_THICKFRAME, WS_SYSMENU, WS_MINIMIZEBOX, WS_MAXIMIZEBOX = 0xC00000, 0x40000, 0x80000, 0x20000, 0x10000
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = 0x80, 0x40000


def puerto() -> int:
    env = RAIZ / ".env"
    for linea in env.read_text(encoding="utf-8").splitlines() if env.exists() else []:
        if linea.startswith("JARVIS_PUERTO=") and linea.split("=", 1)[1].strip():
            return int(linea.split("=", 1)[1])
    return 8765


URL = f"http://127.0.0.1:{puerto()}"
T0 = time.time()


def anotar(texto: str):
    """Cuánto tarda cada paso al prender el PC (data/lateral.log), para saber qué lo frena."""
    try:
        with REGISTRO.open("a", encoding="utf-8") as f:
            f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} +{time.time() - T0:.0f}s {texto}\n")
    except OSError:
        pass


def hay_tarea_admin() -> bool:
    r = subprocess.run(["schtasks", "/query", "/tn", TAREA_ADMIN], capture_output=True, creationflags=0x08000000)
    return r.returncode == 0


def nucleo_vivo() -> bool:
    """Vivo = el puerto está tomado (aunque el núcleo esté ocupado o arrancando y tarde en contestar el ping)."""
    import socket

    try:
        urllib.request.urlopen(URL + "/api/ping", timeout=1.5)
        return True
    except OSError:
        pass
    try:
        with socket.create_connection(("127.0.0.1", puerto()), timeout=1):
            return True
    except OSError:
        return False


_ARRANQUE = {"desde": 0.0}


def arrancar_nucleo():
    # un solo arranque a la vez: el núcleo tarda en levantar y antes se lanzaban varios encima (todos menos uno fallaban)
    candado = _ARRANQUE.setdefault("candado", threading.Lock())
    with candado:
        if nucleo_vivo() or time.time() - _ARRANQUE["desde"] < 90:
            return
        _ARRANQUE["desde"] = time.time()
        if hay_tarea_admin():  # como administrador (y así también Claude Code, que lo lanza el núcleo)
            subprocess.Popen(["schtasks", "/run", "/tn", TAREA_ADMIN], creationflags=0x08000000)
            anotar("arranco el núcleo (administrador)")
        else:
            py = RAIZ / ".venv" / "Scripts" / "pythonw.exe"
            subprocess.Popen([str(py), "-m", "jarvis"], cwd=RAIZ, creationflags=0x08000000)  # sin consola
            anotar("arranco el núcleo")
    for _ in range(60):
        time.sleep(1)
        if nucleo_vivo():
            anotar("núcleo listo")
            return


def ruta_edge() -> str | None:
    for base in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles"), os.environ.get("LOCALAPPDATA")):
        if base and (Path(base) / "Microsoft/Edge/Application/msedge.exe").exists():
            return str(Path(base) / "Microsoft/Edge/Application/msedge.exe")
    return None


def buscar_panel() -> int:
    """La ventana del panel (app de Edge con el título del modo lateral), aunque esté escondida.
    Si quedaron varias (p. ej. tras reiniciar Edge), se queda con una y cierra las demás."""
    encontrada = []

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def una(hwnd, _):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, buf, 256)
        clase = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, clase, 64)
        if buf.value == TITULO and clase.value.startswith("Chrome_WidgetWin"):
            encontrada.append(hwnd)
        return True

    user32.EnumWindows(una, 0)
    for sobra in encontrada[1:]:
        user32.PostMessageW(sobra, 0x0010, 0, 0)  # WM_CLOSE
    return encontrada[0] if encontrada else 0


def parecidos(a: dict | None, b: dict | None) -> bool:
    """¿Dos medidas del marco de Edge son la misma? Hasta 2 px de diferencia es solo redondeo de la página."""
    if not a or not b:
        return a == b
    return all(abs(a[k] - b[k]) <= 2 for k in ("arriba", "lados", "abajo"))


def titulo_de(hwnd: int) -> str:
    buf = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def ventanas_chrome() -> set[int]:
    """Las ventanas visibles de Edge/Chrome que hay ahora (para reconocer cuál es la recién abierta)."""
    vistas = set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def una(hwnd, _):
        clase = ctypes.create_unicode_buffer(64)
        user32.GetClassNameW(hwnd, clase, 64)
        if clase.value.startswith("Chrome_WidgetWin") and user32.IsWindowVisible(hwnd):
            vistas.add(hwnd)
        return True

    user32.EnumWindows(una, 0)
    return vistas


def area_trabajo() -> tuple[int, int, int, int]:
    r = wintypes.RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)  # SPI_GETWORKAREA: pantalla sin la barra de tareas
    return r.left, r.top, r.right, r.bottom


def color(f: float) -> str:
    """El acento con brillo f (0 = apagado, 1 = pleno)."""
    f = max(0.0, min(1.0, f))
    return "#%02x%02x%02x" % tuple(int(8 + (c - 8) * f) for c in ACENTO)


def suave(t: float) -> float:
    return 1 - (1 - t) ** 3  # ease-out cúbico


class Lateral:
    def __init__(self):
        self.prefs = {"lado": "derecha", "fijo": False, "y": None}
        try:
            self.prefs.update(json.loads(PREFS.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
        self.abierto = False
        self.hwnd = 0
        self.fuera_desde = None
        self.mostrado = 0.0
        self.arrastre = None
        self.ancho_lienzo = 0  # ancho extra (px) mientras Maicol muestra algo en el lienzo
        self.reintento = time.time()
        self.preparando = False  # el hilo de fondo está abriendo el panel (Edge)
        self.mostrar_pendiente = False  # tocaron la pestaña antes de que el panel existiera: sale en cuanto esté
        self.estado = {}  # lo último que contó la página (/api/lateral); lo trae el hilo de fondo
        self.propias = {}  # ventanas que Maicol pidió (tablero…), sin marco como el panel: hwnd -> (x, y, w, h)
        self.lado, self.lado_antes = 0, None  # la pizarra que sale al costado del tablero y dónde estaba el tablero
        self.tab_y = 0
        self.encima = False
        self.ancho_pildora = float(PILDORA_REPOSO)
        self.t0 = time.time()

        self.raiz = tk.Tk()
        self.raiz.overrideredirect(True)
        self.raiz.attributes("-topmost", True)
        self.raiz.configure(bg=CLAVE)
        self.raiz.attributes("-transparentcolor", CLAVE)
        self.lienzo = tk.Canvas(self.raiz, width=ANCHO_TAB, height=ALTO_TAB, bg=CLAVE, highlightthickness=0, cursor="hand2")
        self.lienzo.pack()
        self.lienzo.bind("<Enter>", lambda e: self.poner_encima(True))
        self.lienzo.bind("<Leave>", lambda e: self.poner_encima(False))
        self.lienzo.bind("<ButtonPress-1>", self.presionar)
        self.lienzo.bind("<B1-Motion>", self.mover)
        self.lienzo.bind("<ButtonRelease-1>", self.soltar)
        self.lienzo.bind("<Button-3>", self.menu)
        self.colocar_tab()
        self.animar_tab()
        self.raiz.after(400, self.vigilar)

    # ---------- la píldora del borde ----------
    def poner_encima(self, si: bool):
        self.encima = si

    def animar_tab(self):
        """Respira despacio en reposo; al pasar el ratón se ensancha y muestra el orbe."""
        objetivo = PILDORA_ENCIMA if (self.encima or self.abierto) else PILDORA_REPOSO
        self.ancho_pildora += (objetivo - self.ancho_pildora) * 0.28
        t = time.time() - self.t0
        respiro = 0.55 + 0.25 * math.sin(t * 1.6)
        self.dibujar(1.0 if (self.encima or self.abierto) else respiro)
        self.raiz.after(16 if abs(objetivo - self.ancho_pildora) > 0.3 else 60, self.animar_tab)

    def dibujar(self, brillo: float):
        c = self.lienzo
        c.delete("all")
        w = max(PILDORA_REPOSO, int(round(self.ancho_pildora)))
        der = self.prefs["lado"] == "derecha"
        x0, x1 = (ANCHO_TAB - w, ANCHO_TAB + w) if der else (-w, w)  # media píldora pegada al borde
        y0, y1 = 4, ALTO_TAB - 4
        r = w
        fondo = "#071a26"
        # halo (dos capas más tenues alrededor)
        for k, f in ((3, 0.18), (1.5, 0.38)):
            self.pildora(x0 - k, y0 - k, x1 + k, y1 + k, r + k, color(brillo * f))
        self.pildora(x0, y0, x1, y1, r, color(brillo * 0.95))
        # angosta es una línea de luz; ancha, una cápsula oscura con borde de luz
        self.pildora(x0 + 1.5, y0 + 1.5, x1 - 1.5, y1 - 1.5, r - 1.5, fondo if w >= 12 else color(brillo * 0.55))
        if w >= 14:  # ya cabe el orbe
            cx = (ANCHO_TAB - w / 2) if der else w / 2
            cy = ALTO_TAB / 2
            op = min(1.0, (w - 14) / (PILDORA_ENCIMA - 14))
            rr = 9
            c.create_oval(cx - rr, cy - rr, cx + rr, cy + rr, outline=color(op * 0.7), width=1.5)
            c.create_oval(cx - 5, cy - 5, cx + 5, cy + 5, fill=color(op * 0.55), outline="")
            c.create_oval(cx - 2.5, cy - 2.5, cx + 2.5, cy + 2.5, fill=color(op), outline="")
            # flecha discreta: hacia dónde va el panel
            fl = "‹" if (der != self.abierto) else "›"
            c.create_text(cx, cy - 34, text=fl, fill=color(op * 0.6), font=("Segoe UI", 11, "bold"))
            c.create_text(cx, cy + 34, text=fl, fill=color(op * 0.6), font=("Segoe UI", 11, "bold"))

    def pildora(self, x0, y0, x1, y1, r, relleno):
        c = self.lienzo
        r = min(r, (x1 - x0) / 2, (y1 - y0) / 2)
        c.create_oval(x0, y0, x0 + 2 * r, y0 + 2 * r, fill=relleno, outline="")
        c.create_oval(x0, y1 - 2 * r, x0 + 2 * r, y1, fill=relleno, outline="")
        c.create_oval(x1 - 2 * r, y0, x1, y0 + 2 * r, fill=relleno, outline="")
        c.create_oval(x1 - 2 * r, y1 - 2 * r, x1, y1, fill=relleno, outline="")
        c.create_rectangle(x0 + r, y0, x1 - r, y1, fill=relleno, outline="")
        c.create_rectangle(x0, y0 + r, x1, y1 - r, fill=relleno, outline="")

    def colocar_tab(self):
        izq, arriba, der, abajo = area_trabajo()
        y = self.prefs["y"] if self.prefs["y"] is not None else (arriba + abajo - ALTO_TAB) // 2
        y = max(arriba, min(abajo - ALTO_TAB, y))
        x = der - ANCHO_TAB if self.prefs["lado"] == "derecha" else izq
        self.raiz.geometry(f"{ANCHO_TAB}x{ALTO_TAB}+{x}+{y}")
        self.tab_y = y  # el hilo de fondo la usa para ubicar el panel sin tocar Tk

    def presionar(self, e):
        self.arrastre = (e.y_root, self.raiz.winfo_y(), False)

    def mover(self, e):
        if not self.arrastre:
            return
        y0, tab_y, _ = self.arrastre
        if abs(e.y_root - y0) > 4:
            self.arrastre = (y0, tab_y, True)
            self.prefs["y"] = tab_y + e.y_root - y0
            self.colocar_tab()
            if self.abierto:
                self.mover_panel_a(*self.rect_panel())

    def soltar(self, e):
        movido = self.arrastre and self.arrastre[2]
        self.arrastre = None
        if movido:
            self.guardar()
        else:
            self.alternar()

    def menu(self, e):
        m = tk.Menu(self.raiz, tearoff=0, bg="#0b1520", fg="#d8f6ff", activebackground="#0f6d73", activeforeground="white",
                    bd=0, font=("Segoe UI", 10))
        m.add_command(label=("✓  " if self.prefs["fijo"] else "     ") + "Fijar abierto", command=self.alternar_fijo)
        m.add_command(label="     Pasar al lado " + ("izquierdo" if self.prefs["lado"] == "derecha" else "derecho"), command=self.cambiar_lado)
        m.add_command(label="     Abrir la ventana grande", command=self.ventana_grande)
        m.add_separator()
        m.add_command(label="     Salir del lateral", command=self.salir)
        m.tk_popup(e.x_root, e.y_root)

    def alternar_fijo(self):
        self.prefs["fijo"] = not self.prefs["fijo"]
        self.guardar()

    def cambiar_lado(self):
        abierto = self.abierto
        if abierto:
            self.esconder()
        self.prefs["lado"] = "izquierda" if self.prefs["lado"] == "derecha" else "derecha"
        self.guardar()
        self.colocar_tab()
        if self.hwnd and user32.IsWindow(self.hwnd):
            user32.PostMessageW(self.hwnd, 0x0010, 0, 0)  # WM_CLOSE: se vuelve a abrir con el filo de luz del otro lado
            self.hwnd = 0
        if abierto:
            self.raiz.after(400, self.mostrar)

    def guardar(self):
        try:
            PREFS.parent.mkdir(parents=True, exist_ok=True)
            PREFS.write_text(json.dumps(self.prefs), encoding="utf-8")
        except OSError:
            pass

    # ---------- el panel ----------
    def rect_panel(self) -> tuple[int, int, int, int]:
        izq, arriba, der, abajo = area_trabajo()
        alto = min(ALTO_PANEL, abajo - arriba - 2 * MARGEN)
        if threading.current_thread() is threading.main_thread():  # Tk solo se toca desde su hilo
            self.tab_y = self.raiz.winfo_y()
        centro_tab = self.tab_y + ALTO_TAB // 2
        y = max(arriba + MARGEN, min(abajo - MARGEN - alto, centro_tab - alto // 2))
        # con el lienzo abierto la ventana crece hacia el centro de la pantalla
        ancho = min(ANCHO_PANEL + self.ancho_lienzo, der - izq - 2 * MARGEN)
        x = der - MARGEN - ancho if self.prefs["lado"] == "derecha" else izq + MARGEN
        return x, y, ancho, alto

    def x_guardado(self, w: int) -> int:
        izq, _, der, _ = area_trabajo()
        return der + 4 if self.prefs["lado"] == "derecha" else izq - w - 4  # justo fuera de la pantalla

    def preparar_ventana(self, hwnd: int, w: int, h: int):
        """Sin marco ni botón en la barra de tareas, con esquinas redondeadas (Edge a veces devuelve el marco)."""
        est = user32.GetWindowLongPtrW(hwnd, GWL_STYLE)
        nuevo = est & ~(WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
        ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        ex_nuevo = (ex | WS_EX_TOOLWINDOW) & ~WS_EX_APPWINDOW
        if nuevo != est or ex_nuevo != ex:
            user32.SetWindowLongPtrW(hwnd, GWL_STYLE, nuevo)
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex_nuevo)
            user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED | 0x4)
        self.recortar(w, h)  # si la página aún no contó su marco, vigilar() lo vuelve a recortar cuando llegue

    def recortar(self, w: int, h: int):
        m = getattr(self, "_marco", {"arriba": 0, "lados": 0, "abajo": 0})
        self._marco_aplicado = m
        user32.SetWindowRgn(self.hwnd, gdi32.CreateRoundRectRgn(m["lados"], m["arriba"], m["lados"] + w + 1, m["arriba"] + h + 1, RADIO, RADIO), True)

    def preparar_panel(self):
        """Solo desde el hilo de fondo: abrir Edge puede tardar mucho al prender el PC."""
        if self.preparando:
            return
        self.preparando = True
        try:
            self.asegurar_panel()
        finally:
            self.preparando = False

    def asegurar_panel(self) -> int:
        self.hwnd = self.hwnd if self.hwnd and user32.IsWindow(self.hwnd) else buscar_panel()
        if self.hwnd:
            return self.hwnd
        edge = ruta_edge()
        if not edge:
            import webbrowser

            webbrowser.open(URL)
            return 0
        arrancar_nucleo()
        anotar("abro el panel en Edge")
        x, y, w, h = self.rect_panel()
        # perfil propio: el panel es otro Edge, aparte del navegador de siempre (abrir, cerrar o reiniciar
        # Edge no lo toca, y Edge no hereda las opciones del panel)
        perfil = RAIZ / "data" / "edge_lateral"
        subprocess.Popen([edge, f"--user-data-dir={perfil}", "--no-first-run", "--no-default-browser-check",
                          f"--app={URL}/?lateral=1&lado={self.prefs['lado']}", f"--window-size={w},{h}",
                          f"--window-position={self.x_guardado(w)},{y}", "--autoplay-policy=no-user-gesture-required"])
        for _ in range(80):
            time.sleep(0.25)
            self.hwnd = buscar_panel()
            if self.hwnd:
                user32.ShowWindow(self.hwnd, SW_HIDE)  # que no aparezca de golpe: entra con el desliz
                time.sleep(0.6)  # la interfaz termina de arrancar mientras tanto
                anotar("panel listo")
                break
        else:
            anotar("el panel no apareció en 20 s; reintento en 10 s")
        return self.hwnd

    def marco(self) -> dict:
        """Lo que mide la barra de título que Edge dibuja dentro de la ventana (lo cuenta la propia página).
        Solo desde el hilo de fondo: si el núcleo está ocupado, la consulta puede tardar."""
        try:
            m = json.loads(urllib.request.urlopen(URL + "/api/lateral", timeout=1).read())
            self.estado = m
            if m.get("arriba") is not None:
                self._marco = m
        except (OSError, ValueError):
            pass
        return getattr(self, "_marco", {"arriba": 0, "lados": 0, "abajo": 0})

    def mover_panel_a(self, x, y, w, h, insertar=HWND_TOPMOST, extra=0):
        # la ventana real es más grande: la barra de título queda por encima, fuera de la región visible
        m = getattr(self, "_marco", {"arriba": 0, "lados": 0, "abajo": 0})
        user32.SetWindowPos(self.hwnd, insertar, int(x) - m["lados"], int(y) - m["arriba"],
                            int(w) + 2 * m["lados"], int(h) + m["arriba"] + m["abajo"], SWP_NOACTIVATE | extra)

    def cambiar_ancho(self, nuevo: int):
        """El lienzo se abrió o se cerró: la ventana se ensancha (o encoge) con una animación."""
        x0, y, w0, h = self.rect_panel()
        self.ancho_lienzo = nuevo
        x1, _, w1, _ = self.rect_panel()
        if not self.abierto:
            return
        t0 = time.perf_counter()
        while True:
            t = min(1.0, (time.perf_counter() - t0) / 0.3)
            k = suave(t)
            w = int(w0 + (w1 - w0) * k)
            self.mover_panel_a(x0 + (x1 - x0) * k, y, w, h)
            self.recortar(w, h)
            if t >= 1:
                break
            time.sleep(0.01)

    def deslizar(self, desde: int, hasta: int, y: int, w: int, h: int, dur: float):
        t0 = time.perf_counter()
        while True:
            t = min(1.0, (time.perf_counter() - t0) / dur)
            self.mover_panel_a(desde + (hasta - desde) * suave(t), y, w, h)
            if t >= 1:
                break
            time.sleep(0.008)

    def mostrar(self):
        hwnd = self.hwnd if self.hwnd and user32.IsWindow(self.hwnd) else buscar_panel()
        if not hwnd:  # el hilo de fondo lo abre y vigilar() lo muestra en cuanto exista; la pestaña no se congela
            self.mostrar_pendiente = True
            if not self.preparando:
                threading.Thread(target=self.preparar_panel, daemon=True).start()
            return
        self.hwnd = hwnd
        self.mostrar_pendiente = False
        x, y, w, h = self.rect_panel()
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, SW_RESTORE)
        self.preparar_ventana(hwnd, w, h)
        inicio = self.x_guardado(w)
        self.mover_panel_a(inicio, y, w, h, extra=SWP_SHOWWINDOW)
        user32.ShowWindow(hwnd, SW_SHOWNA)
        self.abierto = True
        self.deslizar(inicio, x, y, w, h, 0.26)
        user32.keybd_event(0x12, 0, 0, 0)  # un Alt «fantasma» deja a Windows ceder el foco
        user32.SetForegroundWindow(hwnd)
        user32.keybd_event(0x12, 0, 2, 0)
        self.fuera_desde = None
        self.mostrado = time.time()

    def esconder(self):
        if self.hwnd and user32.IsWindow(self.hwnd) and user32.IsWindowVisible(self.hwnd):
            x, y, w, h = self.rect_panel()
            self.deslizar(x, self.x_guardado(w), y, w, h, 0.2)
            user32.ShowWindow(self.hwnd, SW_HIDE)  # sigue vivo: Maicol puede terminar de hablar
        self.abierto = False

    def alternar(self):
        self.esconder() if self.abierto else self.mostrar()

    def ventana_grande(self):
        if self.abierto:
            self.esconder()
        bat = RAIZ / "JARVIS.bat"
        subprocess.Popen(["cmd", "/c", str(bat)], cwd=RAIZ, creationflags=0x08000000)

    def vigilar(self):
        """Se guarda solo cuando trabajas en otra ventana (como el prototipo), salvo que esté fijado."""
        try:
            if self.mostrar_pendiente and self.hwnd and user32.IsWindow(self.hwnd):
                self.mostrar()
            # la página contó su marco después de mostrarse: se recorta otra vez para esconder la barra de título
            # solo si de verdad cambió: la página redondea distinto cada vez que se reacomoda (34, 35, 36 px) y
            # reaccionar a eso la hacía temblar arriba y abajo sin parar
            if self.abierto and not parecidos(getattr(self, "_marco", None), getattr(self, "_marco_aplicado", None)):
                x, y, w, h = self.rect_panel()
                self.mover_panel_a(x, y, w, h)
                self.recortar(w, h)
            # ¿Maicol abrió o cerró el lienzo? (la página lo avisa al núcleo)
            pedido = int(self.estado.get("lienzo", 0) or 0)
            if pedido != self.ancho_lienzo:
                abrir = pedido > 0 and not self.abierto and self.hwnd and user32.IsWindow(self.hwnd)
                self.cambiar_ancho(pedido)
                if abrir:
                    self.mostrar()  # quiere enseñar algo: el panel sale solo
            if self.abierto:
                if not (self.hwnd and user32.IsWindow(self.hwnd)) or not user32.IsWindowVisible(self.hwnd):
                    self.abierto = False  # lo cerraron (Alt+F4)
                elif not self.prefs["fijo"] and time.time() - self.mostrado > 1.5:  # al abrir, Edge a veces pasa el foco a otra ventana suya un instante
                    activa = user32.GetForegroundWindow()
                    propia = activa in (self.hwnd, self.raiz.winfo_id(), user32.GetParent(self.raiz.winfo_id()))
                    if propia or not activa:
                        self.fuera_desde = None
                    elif self.fuera_desde is None:
                        self.fuera_desde = time.time()
                    elif time.time() - self.fuera_desde > 0.6:
                        self.esconder()
            self.raiz.attributes("-topmost", True)
        finally:
            self.raiz.after(250, self.vigilar)

    def abrir_pedidas(self):
        """Ventanas que Maicol pidió (un tablero de análisis, un visual grande). Se abren desde aquí y no desde el
        núcleo porque el núcleo puede ser administrador, y la ventana heredaría esos permisos."""
        try:
            pedidos = json.loads(urllib.request.urlopen(URL + "/api/ventanas", timeout=1).read())
        except (OSError, ValueError):
            return
        edge = ruta_edge()
        izq, arriba, der, abajo = area_trabajo()
        for p in pedidos:
            if p.get("abrir"):  # un enlace, archivo o app que el núcleo (administrador) quiere abrir como usuario normal
                try:
                    os.startfile(p["abrir"])
                    anotar(f"abro como usuario: {p['abrir'][:120]}")
                except OSError as e:
                    anotar(f"no pude abrir {p['abrir'][:120]}: {e}")
                continue
            if not edge:
                continue
            w, h = min(int(p.get("ancho", 1320)), der - izq - 40), min(int(p.get("alto", 860)), abajo - arriba - 40)
            x, y = izq + (der - izq - w) // 2, arriba + (abajo - arriba - h) // 2
            desde = self.donde_esta_maicol()
            if p.get("junto_tablero"):  # Maicol explica con un visual: la pizarra sale del costado del tablero
                tab = self.ventana_tablero()
                if tab and edge:
                    antes = ventanas_chrome()
                    subprocess.Popen([edge, f"--user-data-dir={RAIZ / 'data' / 'edge_lateral'}", "--no-first-run",
                                      "--no-default-browser-check", f"--app={p['junto_tablero']}"])
                    anotar("saco la pizarra al lado del tablero")
                    threading.Thread(target=self.sacar_al_lado, args=(antes, tab, int(p.get("ancho", 580))), daemon=True).start()
                    continue
                p["url"] = p["junto_tablero"]  # sin el tablero a la vista: en una ventana normal
            if p.get("traer_tablero"):  # la ventana del tablero cambió de proyecto: al frente, donde estaba
                v = self.ventana_tablero()
                if v:
                    self.al_frente(v, *self.propias[v])
                    anotar("ventana del tablero al frente (otro proyecto)")
                continue
            if p.get("traer"):  # ya existe: solo se trae al frente, centrada (sin crecer desde el panel: ya está ahí)
                ya = next((v for v in ventanas_chrome() if titulo_de(v) == p["traer"]), 0)
                if ya:
                    self.al_frente(ya, x, y, w, h)
                    anotar(f"ventana al frente: {p['traer']}")
                continue
            antes = ventanas_chrome()
            subprocess.Popen([edge, f"--user-data-dir={RAIZ / 'data' / 'edge_lateral'}", "--no-first-run", "--no-default-browser-check",
                              f"--app={p['url']}", f"--window-size={w},{h}", f"--window-position={x},{y}",
                              "--autoplay-policy=no-user-gesture-required"])
            anotar(f"abro una ventana de Maicol: {p['url']}")
            threading.Thread(target=self.traer_ventana, args=(antes, x, y, w, h, desde), daemon=True).start()

    def ventana_tablero(self) -> int:
        """La ventana del tablero abierta. Si la pestaña se reinició y no la conoce, la reconoce por su título
        («… · Maicol») y recupera dónde está (la parte visible, sin la barra de Edge que queda fuera)."""
        vivas = [v for v in self.propias if user32.IsWindow(v) and v != self.lado]
        if vivas:
            return vivas[-1]
        v = next((v for v in ventanas_chrome() if titulo_de(v).endswith("· Maicol") and v != self.hwnd), 0)
        if v:
            r, m = wintypes.RECT(), getattr(self, "_marco", {"arriba": 0, "lados": 0, "abajo": 0})
            user32.GetWindowRect(v, ctypes.byref(r))
            self.propias[v] = (r.left + m["lados"], r.top + m["arriba"], r.right - r.left - 2 * m["lados"],
                               r.bottom - r.top - m["arriba"] - m["abajo"])
        return v

    def donde_esta_maicol(self) -> tuple:
        """De dónde «sale» una ventana suya: el panel si está abierto, si no la píldora del borde."""
        if self.abierto and self.hwnd and user32.IsWindowVisible(self.hwnd):
            return self.rect_panel(), True
        izq, _, der, _ = area_trabajo()
        x = der - ANCHO_TAB if self.prefs["lado"] == "derecha" else izq
        return (x, self.tab_y, ANCHO_TAB, ALTO_TAB), False

    def traer_ventana(self, antes: set, x: int, y: int, w: int, h: int, desde: tuple | None = None):
        """Edge ignora --window-size/--window-position cuando su proceso ya está abierto (el del panel) y la ventana
        nueva hereda el lugar del panel escondido: fuera de la pantalla, a la derecha. Se busca y se pone al frente."""
        for _ in range(50):
            time.sleep(0.2)
            nuevas = [v for v in ventanas_chrome() - antes if v != self.hwnd and titulo_de(v) not in ("", TITULO)]
            if nuevas:
                self.al_frente(nuevas[0], x, y, w, h, desde)
                anotar(f"ventana al frente: {titulo_de(nuevas[0])}")
                return
        anotar("la ventana pedida no apareció en 10 s")

    def al_frente(self, v: int, x: int, y: int, w: int, h: int, desde: tuple | None = None):
        user32.ShowWindow(v, SW_RESTORE)
        if desde:
            self.transformar(v, desde[0], (x, y, w, h), sobre_panel=desde[1])
        else:
            self.propias[v] = (x, y, w, h)
            self.sin_marco(v)
            # encima de todo un instante y luego normal: queda arriba aunque Windows no le ceda el foco
            user32.SetWindowPos(v, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
            user32.SetWindowPos(v, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
        user32.keybd_event(0x12, 0, 0, 0)  # un Alt «fantasma» deja a Windows ceder el foco
        user32.SetForegroundWindow(v)
        user32.keybd_event(0x12, 0, 2, 0)

    def transformar(self, v: int, desde: tuple, hasta: tuple, sobre_panel: bool):
        """La transición «Maicol se vuelve el tablero»: la ventana nace encima de Maicol (su panel o la píldora), el
        panel desaparece debajo, y la ventana crece hasta su lugar. Al cerrarla, Maicol vuelve a su panel."""
        t0, primero = time.perf_counter(), True
        while True:
            t = min(1.0, (time.perf_counter() - t0) / 0.45)
            k = suave(t)
            self.propias[v] = tuple(int(a + (b - a) * k) for a, b in zip(desde, hasta))
            self.sin_marco(v)
            if primero:
                primero = False
                # encima de todo un instante y luego normal: queda arriba aunque Windows no le ceda el foco
                user32.SetWindowPos(v, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
                user32.SetWindowPos(v, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE)
                if sobre_panel and self.hwnd and user32.IsWindow(self.hwnd):
                    user32.ShowWindow(self.hwnd, SW_HIDE)  # ya lo tapa la ventana nueva: Maicol «se mudó» a ella
                    self.abierto = False
                    self.volver_de = v
            if t >= 1:
                break
            time.sleep(0.008)

    def sacar_al_lado(self, antes: set, tab: int, ancho: int):
        """La pizarra sale de detrás del tablero hacia su costado. Si a ese lado no cabe, el tablero se corre lo justo
        (y si ni así, se angosta un poco): los dos se mueven a la vez, como una sola pieza."""
        lado = 0
        for _ in range(50):
            time.sleep(0.2)
            nuevas = [v for v in ventanas_chrome() - antes if v not in (self.hwnd, tab) and titulo_de(v) not in ("", TITULO)]
            if nuevas:
                lado = nuevas[0]
                break
        if not lado or tab not in self.propias:
            anotar("la pizarra no apareció en 10 s")
            return
        izq, _, der, _ = area_trabajo()
        bx, by, bw, bh = self.propias[tab]
        margen, hueco = 16, 14
        libre = der - izq - 2 * margen
        sw = min(ancho, max(380, libre - bw - hueco))
        nbw = bw if bw + hueco + sw <= libre else max(820, libre - hueco - sw)
        sw = min(sw, libre - hueco - nbw)
        nbx = max(izq + margen, min(bx, der - margen - (nbw + hueco + sw)))  # si cabe, el tablero no se mueve
        self.lado, self.lado_antes = lado, (bx, by, bw, bh)
        user32.ShowWindow(lado, SW_RESTORE)
        self.animar_juntos({tab: ((bx, by, bw, bh), (nbx, by, nbw, bh)),
                            lado: ((bx + bw - 70, by + 40, 70, bh - 80), (nbx + nbw + hueco, by, sw, bh))}, 0.6, debajo_de=tab)
        anotar(f"pizarra al lado del tablero: {titulo_de(lado)}")

    def animar_juntos(self, movimientos: dict, dur: float, debajo_de: int = 0):
        """Mueve varias ventanas propias a la vez, de su rectángulo inicial al final (con la curva suave de siempre).
        Con debajo_de, las demás quedan detrás de esa: la pizarra «sale de debajo» del tablero."""
        t0, primero = time.perf_counter(), True
        while True:
            t = min(1.0, (time.perf_counter() - t0) / dur)
            k = suave(t)
            for v, (desde, hasta) in movimientos.items():
                if user32.IsWindow(v):
                    self.propias[v] = tuple(int(a + (b - a) * k) for a, b in zip(desde, hasta))
                    self.sin_marco(v)
            if primero and debajo_de:
                primero = False
                for v in movimientos:
                    if v != debajo_de:
                        user32.SetWindowPos(v, debajo_de, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_SHOWWINDOW)
            if t >= 1:
                return
            time.sleep(0.008)

    def guardar_lado(self):
        """Se cerró la pizarra: el tablero vuelve a donde estaba antes de hacerle sitio."""
        tab, antes = self.ventana_tablero(), self.lado_antes
        self.lado_antes = None
        if tab and antes and tab in self.propias:
            self.animar_juntos({tab: (self.propias[tab], antes)}, 0.45)

    def sin_marco(self, v: int):
        """Igual que el panel: sin marco ni ✕ y con esquinas redondeadas (la página trae su propio botón de cerrar).
        La barra de título que Edge dibuja por dentro queda arriba, fuera de la región visible."""
        x, y, w, h = self.propias[v]
        est = user32.GetWindowLongPtrW(v, GWL_STYLE)
        nuevo = est & ~(WS_CAPTION | WS_THICKFRAME | WS_SYSMENU | WS_MINIMIZEBOX | WS_MAXIMIZEBOX)
        if nuevo != est:
            user32.SetWindowLongPtrW(v, GWL_STYLE, nuevo)
        m = getattr(self, "_marco", {"arriba": 0, "lados": 0, "abajo": 0})
        user32.SetWindowPos(v, 0, x - m["lados"], y - m["arriba"], w + 2 * m["lados"], h + m["arriba"] + m["abajo"],
                            SWP_FRAMECHANGED | SWP_SHOWWINDOW | SWP_NOACTIVATE | 0x4)  # 0x4 = SWP_NOZORDER: no la sube
        user32.SetWindowRgn(v, gdi32.CreateRoundRectRgn(m["lados"], m["arriba"], m["lados"] + w + 1, m["arriba"] + h + 1, RADIO, RADIO), True)
        self.marco_propias = dict(m)

    def cuidar_propias(self):
        """Edge a veces devuelve el marco (al activar la ventana, por ejemplo): se le vuelve a quitar."""
        m = getattr(self, "_marco", {"arriba": 0, "lados": 0, "abajo": 0})
        if not self.propias and hasattr(self, "_marco") and time.time() - getattr(self, "_buscada", 0) > 3:
            self._buscada = time.time()  # la pestaña se reinició con un tablero abierto: lo reconoce y lo sigue cuidando
            if v := self.ventana_tablero():
                self.sin_marco(v)  # su recorte (que esconde la barra de Edge) se perdió con el reinicio
        for v in list(self.propias):
            if not user32.IsWindow(v):
                self.propias.pop(v, None)
                if v == self.lado:  # cerró la pizarra: el tablero vuelve a su lugar
                    self.lado = 0
                    threading.Thread(target=self.guardar_lado, daemon=True).start()
                elif self.lado and user32.IsWindow(self.lado) and not self.ventana_tablero():
                    user32.PostMessageW(self.lado, 0x10, 0, 0)  # cerró el tablero: su pizarra se va con él
                if getattr(self, "volver_de", None) == v:  # cerró el tablero: Maicol vuelve a su panel
                    self.volver_de = None
                    self.mostrar_pendiente = True
            elif user32.GetWindowLongPtrW(v, GWL_STYLE) & WS_CAPTION or not parecidos(m, getattr(self, "marco_propias", None)):
                self.sin_marco(v)

    def fondo(self):
        """Todo lo que espera va aquí y no en el hilo de la pestaña. Antes, al prender el PC, la pestaña quedaba
        congelada minutos: esperaba al núcleo (hasta 60 s), a Edge (hasta 20 s) y a cada consulta HTTP."""
        anotar("pestaña iniciada")
        arrancar_nucleo()  # al iniciar Windows nadie toca la pestaña
        while True:
            try:
                self.marco()
                self.abrir_pedidas()
                self.cuidar_propias()
                # si el panel murió (cerraron Edge, se reinició…), se vuelve a crear escondido: así Maicol
                # siempre tiene dónde mostrar el lienzo aunque no hayas tocado la pestaña
                if time.time() - self.reintento > 10:
                    self.reintento = time.time()
                    if not nucleo_vivo():
                        arrancar_nucleo()  # se cayó o lo detuvieron: se vuelve a levantar solo (el iPhone depende de él)
                    elif not (self.hwnd and user32.IsWindow(self.hwnd)):
                        self.preparar_panel()
            except Exception as e:  # noqa: BLE001 — este hilo no puede morir
                anotar(f"error en segundo plano: {e}")
            time.sleep(0.25)

    def salir(self):
        if self.hwnd and user32.IsWindow(self.hwnd):
            user32.PostMessageW(self.hwnd, 0x0010, 0, 0)  # WM_CLOSE: que no quede una ventana invisible
        self.raiz.destroy()

    def correr(self, abrir: bool):
        threading.Thread(target=self.fondo, daemon=True).start()
        if abrir:
            self.raiz.after(300, self.mostrar)
        self.raiz.mainloop()


if __name__ == "__main__":
    # una sola pestaña aunque abran el acceso directo dos veces
    ctypes.windll.kernel32.CreateMutexW(None, False, "Maicol.Lateral")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        sys.exit(0)
    Lateral().correr(abrir="--cerrado" not in sys.argv)
