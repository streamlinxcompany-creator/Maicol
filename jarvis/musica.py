"""Música en Spotify gratis (web en Brave) que aprende de lo que escuchas.

La API de Spotify exige Premium desde feb-2026, así que todo es local y gratis:
- Aprender: Windows informa título/artista/álbum de lo que suena (controles multimedia). Cada canción
  escuchada 30 s o más se guarda en la base de JARVIS.
- Reproducir: se busca la canción/artista/lista en open.spotify.com, se abre en una ventana propia de
  Brave (nunca en tus pestañas) y se pulsa «Reproducir» con la accesibilidad de Windows (UI Automation).
"""
import asyncio
import logging
import math
import random
import re
import sqlite3
import subprocess
import time

from . import aperturas, config
from .memoria import RUTA as RUTA_DB

log = logging.getLogger("jarvis.musica")
REPRODUCIENDO = 4
MINIMO_SEGUNDOS = 30


def _db():
    db = sqlite3.connect(RUTA_DB)
    db.execute("""CREATE TABLE IF NOT EXISTS musica(
        id INTEGER PRIMARY KEY, titulo TEXT, artista TEXT, album TEXT, fuente TEXT, segundos INTEGER, ts REAL)""")
    return db


# ======================= aprender =======================

async def _sonando() -> list[dict]:
    from winrt.windows.media.control import GlobalSystemMediaTransportControlsSessionManager as M

    out = []
    for s in (await M.request_async()).get_sessions():
        app = s.source_app_user_model_id
        if "127.0.0.1" in app or "localhost" in app:
            continue
        try:
            p = await s.try_get_media_properties_async()
        except Exception:  # noqa: BLE001
            continue
        out.append({"app": app, "estado": s.get_playback_info().playback_status, "titulo": p.title or "",
                    "artista": p.artist or "", "album": p.album_title or "", "sesion": s})
    return out


async def observador():
    """Cada 10 s mira qué suena; guarda las canciones escuchadas al menos 30 s."""
    if not config.ES_WINDOWS:
        return
    actual, acumulado, ultimo = None, 0.0, time.time()
    while True:
        await asyncio.sleep(10)
        ahora = time.time()
        try:
            sonando = [x for x in await _sonando() if x["estado"] == REPRODUCIENDO and x["artista"] and x["titulo"]]
        except Exception as e:  # noqa: BLE001
            log.debug("observador: %s", e)
            continue
        clave = (sonando[0]["titulo"], sonando[0]["artista"]) if sonando else None
        if clave != (actual and (actual["titulo"], actual["artista"])):
            _guardar(actual, acumulado)
            actual, acumulado = (sonando[0] if sonando else None), 0.0
        elif actual:
            acumulado += ahora - ultimo
        ultimo = ahora


def _guardar(pista, segundos):
    if not pista or segundos < MINIMO_SEGUNDOS:
        return
    with _db() as db:
        db.execute("INSERT INTO musica(titulo, artista, album, fuente, segundos, ts) VALUES(?,?,?,?,?,?)",
                   (pista["titulo"], pista["artista"], pista["album"], pista["app"], int(segundos), time.time()))
    log.info("aprendí: %s - %s", pista["artista"], pista["titulo"])


def gustos(dias: int = 120) -> dict:
    """Artistas y canciones favoritos, con más peso a lo reciente."""
    with _db() as db:
        filas = db.execute("SELECT titulo, artista, ts FROM musica WHERE ts > ?", (time.time() - dias * 86400,)).fetchall()
    artistas, canciones = {}, {}
    for titulo, artista, ts in filas:
        peso = math.exp(-(time.time() - ts) / (30 * 86400))  # lo de hace un mes vale ~1/3
        principal = re.split(r",|&| feat\.| ft\.", artista)[0].strip()
        artistas[principal] = artistas.get(principal, 0) + peso
        canciones[(titulo, principal)] = canciones.get((titulo, principal), 0) + peso
    return {"artistas": sorted(artistas.items(), key=lambda x: -x[1]), "canciones": sorted(canciones.items(), key=lambda x: -x[1]),
            "total": len(filas)}


def _elegir() -> tuple[str, str | None]:
    """(qué buscar, título exacto a pulsar o None). Mezcla favoritas y descubrimiento dentro de tus artistas."""
    g = gustos()
    if not g["artistas"]:
        return "", None
    top = g["artistas"][:8]
    artista = random.choices([a for a, _ in top], weights=[p for _, p in top])[0]
    suyas = [(t, p) for (t, a), p in g["canciones"] if a == artista]
    if suyas and random.random() < 0.55:
        titulo = random.choices([t for t, _ in suyas[:10]], weights=[p for _, p in suyas[:10]])[0]
        return f"{titulo} {artista}", titulo
    return artista, None  # página del artista: sus canciones populares, incluidas algunas que quizá no conoces


# ======================= reproducir =======================

_urls: dict[str, str] = {}  # búsquedas ya resueltas: la segunda vez no se busca en internet


def _url_spotify(busqueda: str) -> str | None:
    clave = busqueda.lower().strip()
    if clave not in _urls:
        url = _buscar_url(busqueda)
        if url:
            _urls[clave] = url
    return _urls.get(clave)


def _buscar_url(busqueda: str) -> str | None:
    from ddgs import DDGS

    for q in (f"{busqueda} site:open.spotify.com", f"{busqueda} spotify"):
        try:
            res = list(DDGS().text(q, max_results=12))
        except Exception:  # noqa: BLE001
            continue
        for tipo in ("track", "artist", "playlist", "album"):
            for r in res:
                m = re.match(rf"https://open\.spotify\.com/(?:intl-[\w-]+/)?({tipo})/(\w+)", r.get("href", ""))
                if m:
                    return f"https://open.spotify.com/{m.group(1)}/{m.group(2)}"
    return None


def _ventanas_spotify():
    import uiautomation as auto

    # la ventana propia (modo app) se llama «Spotify – Web Player» o el título de la canción, y NO termina en «- Brave»
    return [w for w in auto.GetRootControl().GetChildren()
            if w.ClassName.startswith("Chrome_WidgetWin") and "Spotify" in w.Name and not w.Name.rstrip().endswith(("Brave", "Google Chrome", "Edge"))]


def _botones(ventana) -> list:
    encontrados = []

    def recorrer(c, prof=0):
        if prof > 45 or len(encontrados) > 60:
            return
        for h in c.GetChildren():
            if h.ControlTypeName == "ButtonControl" and h.Name and h.Name.lower().startswith(("reproducir", "play")):
                encontrados.append(h)
            recorrer(h, prof + 1)

    recorrer(ventana)
    return encontrados


def _abrir_y_pulsar(url: str, titulo: str | None) -> str:
    import uiautomation as auto

    with auto.UIAutomationInitializerInThread():
        for w in _ventanas_spotify():  # una sola ventana de JARVIS para Spotify
            try:
                w.GetWindowPattern().Close()
            except Exception:  # noqa: BLE001
                pass
        navegador = aperturas.ruta_navegador("brave") or aperturas.ruta_navegador("chrome") or aperturas.ruta_navegador("edge")
        if not navegador:
            return "No encontré Brave, Chrome ni Edge para abrir Spotify."
        subprocess.Popen([navegador, f"--app={url}", "--window-size=1100,760"])
        fin = time.time() + 20
        while time.time() < fin:
            time.sleep(1)
            ventanas = _ventanas_spotify()
            if not ventanas:
                continue
            botones = _botones(ventanas[0])
            if not botones:
                continue
            boton = None
            if titulo:
                t = titulo.lower()
                boton = next((b for b in botones if t in b.Name.lower()), None)
            boton = boton or max(botones, key=lambda b: b.BoundingRectangle.width())
            try:
                boton.GetInvokePattern().Invoke()
            except Exception:  # noqa: BLE001
                boton.Click(simulateMove=False)
            return "ok"
        return "Spotify cargó, pero no encontré el botón de reproducir (¿sesión de Spotify iniciada en Brave?)."


async def _que_suena(espera: float = 5) -> dict | None:
    fin = time.time() + espera
    while time.time() < fin:
        await asyncio.sleep(1)
        for x in await _sonando():
            if x["estado"] == REPRODUCIENDO and x["titulo"]:
                return x
    return None


def servicio() -> str:
    """Dónde poner música: «youtube» (YouTube Music en tu navegador de siempre) o «spotify» (web en Brave). MUSICA en .env."""
    return "youtube" if "youtube" in (config.env("MUSICA", "spotify") or "").lower() else "spotify"


_videos: dict[str, str] = {}  # búsquedas ya resueltas en YouTube


def _buscar_video(busqueda: str) -> str | None:
    """El id del primer video que da YouTube para esa búsqueda (sirve igual en music.youtube.com)."""
    clave = busqueda.lower().strip()
    if clave in _videos:
        return _videos[clave]
    import httpx

    try:
        r = httpx.get("https://www.youtube.com/results", params={"search_query": busqueda}, timeout=15, follow_redirects=True,
                      headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
                               "Chrome/130 Safari/537.36", "Accept-Language": "es-CO,es;q=0.9"})
        m = re.search(r'"videoId":"([\w-]{11})"', r.text)
    except httpx.HTTPError:
        m = None
    if m:
        _videos[clave] = m.group(1)
    return _videos.get(clave)


async def _poner_youtube(busqueda: str, eleccion: str) -> str:
    """Abre la canción en el reproductor de YouTube Music (no en la búsqueda) en una pestaña de tu navegador y
    comprueba con los controles multimedia de Windows que de verdad suene; si quedó en pausa, le da reproducir."""
    video = await asyncio.to_thread(_buscar_video, busqueda)
    if not video:
        return f"No encontré «{busqueda}» en YouTube Music."

    async def del_navegador() -> list[dict]:
        try:
            return [x for x in await _sonando() if x["app"].lower().startswith(("msedge", "chrome", "brave", "firefox", "opera"))]
        except Exception:  # noqa: BLE001
            return []

    # lo que ya sonaba en el navegador se pausa: así no suenan dos cosas y no se confunde con la canción nueva
    viejas, siguen = set(), set()  # lo que había antes, y lo que sonaba y no se dejó pausar
    for x in await del_navegador():
        viejas.add(x["titulo"])
        if x["estado"] == REPRODUCIENDO:
            try:
                if not await x["sesion"].try_pause_async():
                    siguen.add(x["titulo"])
            except Exception:  # noqa: BLE001
                siguen.add(x["titulo"])
    await asyncio.to_thread(aperturas.abrir_web, f"https://music.youtube.com/watch?v={video}", None)
    fin, intento = time.time() + 20, 0
    while time.time() < fin:
        await asyncio.sleep(1.5)
        sesiones = await del_navegador()
        # lo viejo quedó en pausa: si algo suena ahora es la canción nueva (aunque sea la misma que ya sonaba)
        if sonando := next((x for x in sesiones if x["estado"] == REPRODUCIENDO and x["titulo"] and x["titulo"] not in siguen), None):
            return f"Sonando en YouTube Music ({eleccion}): {sonando['titulo']} de {sonando['artista']}."
        intento += 1
        if intento % 3 == 0:  # cargó pero el navegador no la arrancó sola: reproducir, solo a la nueva (no a una pestaña vieja)
            for x in [x for x in sesiones if x["titulo"] and x["titulo"] not in viejas]:
                try:
                    await x["sesion"].try_play_async()
                except Exception:  # noqa: BLE001
                    pass
    return (f"NO está sonando: abrí {busqueda} en YouTube Music ({eleccion}) pero no arrancó. Dígaselo tal cual al usuario (no "
            "diga que suena). Si pasa siempre, que permita la reproducción automática para music.youtube.com en su navegador.")


async def poner(peticion: str | None = None) -> str:
    if not config.ES_WINDOWS:
        return "La música solo funciona en el PC con Windows."
    if servicio() == "youtube":
        busqueda = (peticion or "").strip() or _elegir()[0] or "música en tendencia Colombia"
        return await _poner_youtube(busqueda, f"por tu pedido «{peticion}»" if peticion else "elegido según lo que sueles escuchar")
    titulo = None
    if peticion and peticion.strip():
        busqueda = peticion.strip()
    else:
        busqueda, titulo = _elegir()
        if not busqueda:
            # aún no conozco tus gustos: retomo donde lo dejaste
            for x in await _sonando():
                if x["app"].lower().startswith(("brave", "chrome", "msedge", "spotify")) and x["titulo"]:
                    await x["sesion"].try_play_async()
                    return (f"Aún estoy aprendiendo tus gustos, así que retomé lo último: {x['titulo']} de {x['artista']}. "
                            "Cuanto más escuches, mejor elegiré.")
            busqueda = "Top 50 Colombia"
    url = await asyncio.to_thread(_url_spotify, busqueda)
    if not url:
        return f"No encontré «{busqueda}» en Spotify."
    resultado = await asyncio.to_thread(_abrir_y_pulsar, url, titulo)
    if resultado != "ok":
        return resultado
    pista = await _que_suena(6)
    _encolar_si_jarvis_habla()
    eleccion = "elegido según lo que sueles escuchar" if not peticion else f"por tu pedido «{peticion}»"
    if pista:
        return f"Sonando en Spotify ({eleccion}): {pista['titulo']} de {pista['artista']}."
    return f"Abrí {busqueda} en Spotify ({eleccion}); debería empezar en un momento."


def _encolar_si_jarvis_habla():
    """Si JARVIS está hablando, la música espera a que termine (la reanuda el silenciador)."""
    from .silencio import SILENCIO

    if SILENCIO.activo and "Brave" not in SILENCIO.pausadas:
        SILENCIO.pausadas.append("Brave")
        asyncio.get_running_loop().create_task(SILENCIO.pausar_ahora("Brave"))


def resumen_gustos() -> str:
    g = gustos()
    if not g["total"]:
        return "Aún no tengo historial: escucha música en Spotify (Brave) y la iré aprendiendo sola."
    arts = ", ".join(f"{a}" for a, _ in g["artistas"][:6])
    cans = "; ".join(f"{t} ({a})" for (t, a), _ in g["canciones"][:6])
    return f"He registrado {g['total']} reproducciones. Tus artistas más escuchados: {arts}. Canciones: {cans}."
