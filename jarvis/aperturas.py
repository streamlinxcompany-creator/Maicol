"""Abrir cosas como lo haría una persona: primero la app del PC, si no existe la web.

Y recordar cómo se abrió cada cosa (por ejemplo «Spotify → web en Brave», «Notion → app»),
para que la próxima vez vaya directo. Los recuerdos viven en data/aperturas.json.
"""
import difflib
import json
import os
import re
import subprocess
import time
import unicodedata
import urllib.parse
from pathlib import Path

from . import config

RUTA = config.DATOS / "aperturas.json"
SIN_VENTANA = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _soy_admin() -> bool:
    try:
        import ctypes

        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


def iniciar(destino: str):
    """Como os.startfile, pero si el núcleo corre como administrador (scripts/instalar_admin.ps1) lo abre la pestaña
    lateral, que es usuario normal: así lo abierto no hereda más permisos de los necesarios y se pueden seguir
    arrastrando archivos a esas ventanas. (explorer.exe no sirve: desde administrador a veces abre «Documentos»
    en vez del enlace.) Sin la pestaña, un enlace va directo al navegador predeterminado."""
    if not _soy_admin():
        os.startfile(destino)
        return
    from . import superficies

    if superficies.abrir_como_usuario(destino):
        return
    navegador = ruta_navegador(navegador_predeterminado() or "edge") if re.match(r"^https?://", destino) else None
    if navegador:
        subprocess.Popen([navegador, destino], creationflags=SIN_VENTANA)
    else:
        os.startfile(destino)

# preferencias que el usuario ya dijo; se pueden cambiar diciendo «abre X en la app / en el navegador»
PRESETS = {
    "spotify": {"tipo": "web", "destino": "https://open.spotify.com", "navegador": "brave", "nombre": "Spotify"},
    "notion": {"tipo": "app", "destino": "notion.id", "nombre": "Notion"},
}

# programas de Windows que no aparecen con su nombre en español
SISTEMA = {"bloc de notas": "notepad", "notas": "notepad", "calculadora": "calc", "explorador": "explorer",
           "explorador de archivos": "explorer", "archivos": "explorer", "configuracion": "ms-settings:",
           "ajustes de windows": "ms-settings:", "terminal": "wt", "cmd": "cmd", "simbolo del sistema": "cmd",
           "powershell": "powershell", "paint": "mspaint", "administrador de tareas": "taskmgr"}

WEB = {"spotify": "https://open.spotify.com", "youtube": "https://www.youtube.com", "youtube music": "https://music.youtube.com",
       "gmail": "https://mail.google.com", "correo": "https://mail.google.com", "whatsapp": "https://web.whatsapp.com",
       "notion": "https://www.notion.so", "chatgpt": "https://chatgpt.com", "claude": "https://claude.ai",
       "github": "https://github.com", "netflix": "https://www.netflix.com", "drive": "https://drive.google.com",
       "google drive": "https://drive.google.com", "calendario": "https://calendar.google.com", "maps": "https://maps.google.com",
       "mapas": "https://maps.google.com", "google maps": "https://maps.google.com", "traductor": "https://translate.google.com",
       "outlook": "https://outlook.live.com", "instagram": "https://www.instagram.com", "facebook": "https://www.facebook.com",
       "twitter": "https://x.com", "x": "https://x.com", "tiktok": "https://www.tiktok.com", "twitch": "https://www.twitch.tv",
       "discord": "https://discord.com/app", "amazon": "https://www.amazon.com", "mercado libre": "https://www.mercadolibre.com.co",
       "linkedin": "https://www.linkedin.com", "reddit": "https://www.reddit.com", "wikipedia": "https://es.wikipedia.org",
       "google": "https://www.google.com", "classroom": "https://classroom.google.com", "teams": "https://teams.microsoft.com"}

NAVEGADORES = {
    "brave": ["{ProgramFiles}/BraveSoftware/Brave-Browser/Application/brave.exe", "{LOCALAPPDATA}/BraveSoftware/Brave-Browser/Application/brave.exe"],
    "chrome": ["{ProgramFiles}/Google/Chrome/Application/chrome.exe", "{LOCALAPPDATA}/Google/Chrome/Application/chrome.exe"],
    "edge": ["{ProgramFiles(x86)}/Microsoft/Edge/Application/msedge.exe", "{ProgramFiles}/Microsoft/Edge/Application/msedge.exe"],
    "firefox": ["{ProgramFiles}/Mozilla Firefox/firefox.exe"],
    "opera": ["{LOCALAPPDATA}/Programs/Opera/opera.exe"],
}
PROGID_NAVEGADOR = {"BraveHTML": "brave", "ChromeHTML": "chrome", "MSEdgeHTM": "edge", "FirefoxURL": "firefox", "OperaStable": "opera"}


def normalizar(texto: str) -> str:
    t = unicodedata.normalize("NFKD", texto.lower()).encode("ascii", "ignore").decode()
    t = re.sub(r"^(la |el |los |las )?(app |aplicacion |programa |pagina |pagina web |web )?(de |del )?", "", t.strip())
    return re.sub(r"\s+", " ", t).strip(" .")


# ---------- memoria de aperturas ----------

def _leer() -> dict:
    try:
        return json.loads(RUTA.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def recordar(clave: str, datos: dict):
    todo = _leer()
    previo = todo.get(clave, {})
    todo[clave] = {**datos, "veces": previo.get("veces", 0) + 1, "ultima": time.strftime("%Y-%m-%d %H:%M")}
    RUTA.write_text(json.dumps(todo, ensure_ascii=False, indent=2), encoding="utf-8")


def recuerdo(clave: str) -> dict | None:
    return _leer().get(clave) or PRESETS.get(clave)


def todos() -> dict:
    return {**PRESETS, **_leer()}


# ---------- apps instaladas ----------

_apps: dict = {"t": 0, "lista": {}}


def apps_instaladas() -> dict[str, str]:
    """Nombre normalizado -> AppID de todo lo que aparece en el menú Inicio (incluye apps de la Store)."""
    if time.time() - _apps["t"] < 600 and _apps["lista"]:
        return _apps["lista"]
    lista = {}
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                            "[Console]::OutputEncoding=[Text.Encoding]::UTF8; Get-StartApps | ConvertTo-Json -Compress"],
                           capture_output=True, timeout=20, creationflags=SIN_VENTANA)
        datos = json.loads(r.stdout.decode("utf-8", "replace") or "[]")
        for a in datos if isinstance(datos, list) else [datos]:
            app_id = a.get("AppID") or ""
            if app_id.startswith("http"):  # enlaces web disfrazados de app
                continue
            lista.setdefault(normalizar(a.get("Name", "")), app_id)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    for nombre, ruta in _accesos_directos().items():  # accesos directos del escritorio, por si acaso
        lista.setdefault(normalizar(nombre), str(ruta))
    _apps.update(t=time.time(), lista=lista)
    return lista


def _accesos_directos() -> dict[str, Path]:
    rutas = [Path.home() / "Desktop", Path(os.environ.get("PUBLIC", "")) / "Desktop"]
    out = {}
    for r in rutas:
        if r.exists():
            for f in list(r.glob("*.lnk")):
                out.setdefault(f.stem, f)
    return out


def buscar_app(clave: str) -> tuple[str, str] | None:
    """Devuelve (nombre, AppID) si hay una app instalada con ese nombre (exacto, contenido o muy parecido)."""
    apps = apps_instaladas()
    if clave in apps:
        return clave, apps[clave]
    contiene = [n for n in apps if re.search(rf"\b{re.escape(clave)}\b", n)]
    if contiene:
        # «notion» -> «notion», no «notion calendar»; y entre versiones, la más nueva («kicad 10.0» antes que «kicad 9.0»)
        version = lambda n: max((float(x) for x in re.findall(r"\d+(?:\.\d+)?", n)), default=0)  # noqa: E731
        n = min(contiene, key=lambda n: (len(re.sub(r"[\d.]+", "", n).strip()), -version(n)))
        return n, apps[n]
    cerca = difflib.get_close_matches(clave, apps.keys(), n=1, cutoff=0.8)
    return (cerca[0], apps[cerca[0]]) if cerca else None


def lanzar_app(app_id: str):
    if app_id == "notion.id":
        from . import notion  # Notion siempre con accesibilidad, para que JARVIS pueda leerlo

        if notion.abrir_app():
            return
    if os.path.exists(app_id):
        iniciar(app_id)
    else:
        iniciar(f"shell:AppsFolder\\{app_id}")


# ---------- navegadores ----------

def navegador_predeterminado() -> str | None:
    try:
        import winreg

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice") as k:
            progid = winreg.QueryValueEx(k, "ProgId")[0]
        return next((v for p, v in PROGID_NAVEGADOR.items() if progid.startswith(p)), None)
    except OSError:
        return None


def ruta_navegador(nombre: str) -> str | None:
    for plantilla in NAVEGADORES.get(nombre, []):
        ruta = re.sub(r"\{([^}]+)\}", lambda m: os.environ.get(m.group(1), ""), plantilla)
        if os.path.exists(ruta):
            return ruta
    return None


def abrir_web(url: str, navegador: str | None) -> str:
    ruta = ruta_navegador(navegador) if navegador else None
    if ruta:
        subprocess.Popen([ruta, url], creationflags=SIN_VENTANA)
        return navegador
    iniciar(url)
    return navegador_predeterminado() or "el navegador predeterminado"


def nombre_navegador(n: str | None) -> str:
    return {"brave": "Brave", "chrome": "Chrome", "edge": "Edge", "firefox": "Firefox", "opera": "Opera"}.get(n or "", n or "el navegador")


# ---------- la función principal ----------

def abrir(objetivo: str, donde: str | None = None, navegador: str | None = None) -> str:
    o = objetivo.strip()
    navegador = normalizar(navegador) if navegador else None
    if navegador and navegador not in NAVEGADORES:
        navegador = next((n for n in NAVEGADORES if n in navegador), None)

    # 1) rutas y direcciones explícitas
    if re.match(r"^https?://", o):
        usado = abrir_web(o, navegador)
        return f"Abrí {o} en {nombre_navegador(usado)}."
    if Path(os.path.expandvars(os.path.expanduser(o))).exists():
        iniciar(os.path.expandvars(os.path.expanduser(o)))
        return f"Abrí {o}."

    clave = normalizar(o)
    if clave in SISTEMA and donde != "web":
        destino = SISTEMA[clave]
        iniciar(destino)
        return f"Abrí {o}."

    previo = recuerdo(clave)
    pidio_algo = bool(donde or navegador)

    # 2) lo que se recuerda (si el usuario no pidió otra cosa)
    if previo and not pidio_algo:
        if previo["tipo"] == "app":
            lanzar_app(previo["destino"])
            recordar(clave, previo)
            return f"Abrí la app de {previo.get('nombre', o)}, como la última vez."
        usado = abrir_web(previo["destino"], previo.get("navegador"))
        recordar(clave, previo)
        return f"Abrí {previo.get('nombre', o)} en {nombre_navegador(usado)} (web), como la última vez."

    # 3) primero las apps del PC
    if donde != "web" and not navegador:
        app = buscar_app(clave)
        if app:
            nombre, app_id = app
            lanzar_app(app_id)
            recordar(clave, {"tipo": "app", "destino": app_id, "nombre": nombre.title()})
            return f"Abrí la app {nombre.title()} del PC. Lo recordaré para la próxima."
        if donde == "app":
            return f"No encontré ninguna app llamada «{o}» instalada en el PC."

    # 4) si no hay app, la web
    url = (previo or {}).get("destino") if (previo or {}).get("tipo") == "web" else None
    url = url or WEB.get(clave) or "https://duckduckgo.com/?q=" + urllib.parse.quote(f"! {o}")  # «!» = primer resultado
    usado = abrir_web(url, navegador or (previo or {}).get("navegador"))
    datos = {"tipo": "web", "destino": url, "navegador": navegador or (previo or {}).get("navegador") or navegador_predeterminado(), "nombre": o.title()}
    recordar(clave, datos)
    motivo = "" if pidio_algo else " porque no está instalada en el PC"
    return f"Abrí {o} en {nombre_navegador(usado)} (web){motivo}. Lo recordaré para la próxima."
