"""Dónde muestra Maicol las cosas. No está atado a su panel: elige la superficie que mejor sirva.

- panel: el lienzo de su panel (lateral o ventana grande) en todas las pantallas conectadas, también el celular.
- ventana: una ventana propia y grande en el PC (una app de Edge sin barras), para lo que necesita espacio.

Las ventanas las abre la pestaña lateral (scripts/maicol_lateral.pyw), que corre como usuario normal: el núcleo
puede ser administrador y lo que él abriera heredaría esos permisos. Si la pestaña no está corriendo, las abre el núcleo.
"""
import subprocess
import time
import urllib.parse
import uuid
from collections import Counter

from . import config

URL = f"http://127.0.0.1:{config.PUERTO}"
PEDIDOS: list[dict] = []  # ventanas pendientes que la pestaña lateral recoge en /api/ventanas
_LATERAL = {"visto": 0.0}
ABIERTOS: Counter = Counter()  # tableros abiertos en una ventana propia (id -> cuántas); no cuenta el que va dentro del panel
VISUALES: dict[str, dict] = {}  # visuales abiertos en ventana propia: id -> {titulo, html}
# la pizarra que sale al lado del tablero (web/visor.html): cuántas páginas conectadas, de qué trata lo que muestra
# y cuántas vueltas seguidas lleva la charla en otra cosa (a las 2 se guarda sola)
LADO = {"abiertos": 0, "claves": set(), "ajenas": 0}
VUELTAS_AJENAS = 2
_VACIAS = set(("para pero como este esta esto esos esas sobre entre desde hasta cuando donde porque tiene tienen puede pueden "
               "seria hacer queda mucho poco menos senor usted ustedes nuestro nuestra todo toda todos todas cada mismo misma "
               "algo bien ahora entonces tambien unos unas aqui alli listo bueno claro dale vale gracias quiero quisiera "
               "maicol pollo pollos negocio").split())


def _claves(texto: str) -> set[str]:
    """Las palabras que dicen de qué se habla (raíces de 5 letras, sin tildes ni palabras de relleno) y las cifras."""
    import re
    import unicodedata

    t = unicodedata.normalize("NFD", re.sub(r"<[^>]+>", " ", texto or "").lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn")
    palabras = {w[:5] for w in re.findall(r"[a-zñ]{4,}", t) if w not in _VACIAS}
    return palabras | {n.replace(".", "") for n in re.findall(r"\d[\d.]{1,}", t)}


def seguir_lado(dicho: str, respuesta: str, mostro_visual: bool) -> bool:
    """Después de cada vuelta: ¿la charla sigue en lo que muestra la pizarra del costado? Si lleva VUELTAS_AJENAS
    vueltas en otra cosa, True: es hora de guardarla. Si se vuelve al tema, la cuenta empieza de nuevo."""
    if LADO["abiertos"] <= 0 or mostro_visual:
        LADO["ajenas"] = 0
        return False
    comunes = LADO["claves"] & _claves(f"{dicho} {respuesta}")
    LADO["ajenas"] = 0 if len(comunes) >= 2 else LADO["ajenas"] + 1
    return LADO["ajenas"] >= VUELTAS_AJENAS


def tomar_pedidos() -> list[dict]:
    """La pestaña lateral pregunta cada instante: así se sabe que está viva y se lleva lo que haya que abrir."""
    _LATERAL["visto"] = time.time()
    out = PEDIDOS[:]
    PEDIDOS.clear()
    return out


def abrir_como_usuario(destino: str) -> bool:
    """Un enlace, archivo o app que debe abrirse como usuario normal: lo abre la pestaña lateral. False si no está."""
    if time.time() - _LATERAL["visto"] >= 5:
        return False
    PEDIDOS.append({"abrir": destino})
    return True


def abrir_ventana(ruta: str, ancho: int = 1280, alto: int = 820):
    url = URL + ruta
    if time.time() - _LATERAL["visto"] < 5:
        PEDIDOS.append({"url": url, "ancho": ancho, "alto": alto})
        return
    from . import aperturas

    navegador = aperturas.ruta_navegador("edge") or aperturas.ruta_navegador("chrome")
    if navegador:
        subprocess.Popen([navegador, f"--app={url}", f"--window-size={ancho},{alto}", "--autoplay-policy=no-user-gesture-required"])
    else:
        aperturas.iniciar(url)


def _elegir(ctx, donde: str) -> str:
    if donde in ("panel", "ventana"):
        return donde if config.ES_WINDOWS or donde == "panel" else "panel"
    # auto: en el PC, lo grande va en su propia ventana; desde el celular o Telegram, al panel (que también ve el celular)
    return "ventana" if config.ES_WINDOWS and ctx.canal not in ("celular", "telegram") else "panel"


async def mostrar_tablero(ctx, t: dict, donde: str = "auto") -> str:
    lugar = _elegir(ctx, donde)
    if ctx.difundir:
        await ctx.difundir({"type": "tablero", "tablero": t})
    if lugar == "ventana":
        if ABIERTOS[t["id"]]:  # ya abierta (quizá detrás de otras ventanas): se trae al frente
            PEDIDOS.append({"traer": f"{t['titulo']} · Maicol", "ancho": 1320, "alto": 860})
            return "en la ventana del tablero que ya estaba abierta (la traje al frente)"
        if sum(ABIERTOS.values()) > 0 and ctx.difundir:  # hay una ventana de tablero con otro proyecto: se usa la misma
            await ctx.difundir({"type": "tablero_cambiar", "id": t["id"]})
            PEDIDOS.append({"traer_tablero": True})
            return "en la ventana del tablero que ya estaba abierta (cambié el proyecto y la traje al frente)"
        abrir_ventana(f"/tablero?id={t['id']}", 1320, 860)
        return "en una ventana grande en el PC"
    if ctx.difundir:
        await ctx.difundir({"type": "tablero_mostrar", "id": t["id"], "titulo": t["titulo"]})
        return "en tu panel"
    return f"en {URL}/tablero?id={t['id']}"


def guardar_visual(titulo: str, html: str) -> str:
    ident = uuid.uuid4().hex[:10]
    VISUALES[ident] = {"titulo": titulo, "html": html, "creado": time.time()}
    while len(VISUALES) > 30:  # solo los últimos
        VISUALES.pop(next(iter(VISUALES)))
    return ident


def tablero_abierto() -> bool:
    """¿Hay una ventana del tablero de análisis abierta en este PC?"""
    return sum(ABIERTOS.values()) > 0


async def visual_al_lado(ctx, titulo: str, html: str) -> bool:
    """Con el tablero de análisis abierto en el PC, un visual de Maicol («explícame…») sale en una pizarra propia que
    se desliza desde el costado del tablero (la pestaña lateral la abre y la acomoda al lado, sin taparlo). Si ya
    está afuera, solo cambia lo que muestra. False si no hay tablero abierto o no está la pestaña lateral."""
    if not (config.ES_WINDOWS and tablero_abierto() and time.time() - _LATERAL["visto"] < 5):
        return False
    ident = guardar_visual(titulo[:80], html)
    LADO["claves"], LADO["ajenas"] = _claves(f"{titulo} {titulo} {html}"), 0
    if LADO["abiertos"] > 0 and ctx.difundir:
        await ctx.difundir({"type": "visual_lado", "id": ident, "titulo": titulo[:80]})
    else:
        PEDIDOS.append({"junto_tablero": URL + f"/pizarra?v={ident}&t={urllib.parse.quote(titulo[:80])}", "ancho": 580})
    return True


def pagina_visual(ident: str) -> str | None:
    """Un visual de mostrar_visual como página propia, con la misma plantilla HUD del lienzo."""
    v = VISUALES.get(ident)
    if not v:
        return None
    import html as h

    css = (config.WEB / "lienzo.css").read_text(encoding="utf-8")
    return ('<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            f"<title>{h.escape(v['titulo'])}</title><style>{css}</style></head><body>"
            '<svg width="0" height="0" style="position:absolute"><defs><marker id="flecha" viewBox="0 0 10 10" refX="9" refY="5" '
            'markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#00e5ff"/></marker></defs></svg>'
            f"<main class=\"lienzo-contenido\">{v['html']}</main></body></html>")
