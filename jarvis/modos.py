"""Modos: juego, trabajo, noche… Un modo es un estado: al entrar pone música y abre lo necesario, mientras está
activo cambia cómo responde JARVIS, y al salir deja el volumen como estaba.

- Juego: música para jugar y abre Steam o el juego que pidas (busca en tu biblioteca de Steam).
- Trabajo: música para concentrarte y pregunta en qué vas a trabajar (PCB, código, diseño 3D, robot VEX…)
  para abrir lo que corresponde.
- Noche: se activa sola al anochecer (si no hay otro modo) y se apaga en la mañana.
Los modos viven en data/modos.json: se pueden editar o crear por voz («crea un modo…»).
"""
import asyncio
import difflib
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta
from pathlib import Path

from . import config
from .herramientas import P, _sin_tildes, ejecutar, herramienta, http, ubicacion

log = logging.getLogger("jarvis.modos")
ARCHIVO = config.DATOS / "modos.json"
ACTIVO = config.DATOS / "modo_activo.json"

BASE = {
    "juego": {
        "descripcion": "Para jugar: música y Steam o el juego que pidas.",
        "musica": "música épica para jugar videojuegos",
        "abrir": ["Steam"],
        "estilo": "MODO JUEGO: responde en una sola frase corta, sin rodeos, y no lo interrumpas salvo algo urgente.",
    },
    "trabajo": {
        "descripcion": "Para trabajar: música para concentrarse y lo que necesites según el trabajo.",
        "musica": "música para concentrarme trabajando",
        "pregunta": "¿En qué vas a trabajar?",
        "tareas": {
            "pcb": {"nombre": "una PCB", "abrir": ["KiCad 10.0"], "palabras": ["pcb", "placa", "circuito", "kicad", "electronica", "esquematico"]},
            "codigo": {"nombre": "código", "abrir": ["Visual Studio Code", "GitHub Desktop"], "palabras": ["codigo", "programar", "programa", "python", "app", "software", "github", "jarvis"]},
            "diseno 3d": {"nombre": "diseño 3D", "abrir": ["Autodesk Fusion", "Bambu Studio"], "palabras": ["3d", "diseno", "fusion", "modelo", "pieza", "imprimir", "cad"]},
            "robot vex": {"nombre": "el robot VEX", "abrir": ["VEXcode IQ"], "palabras": ["vex", "robot", "vexcode"]},
            "arduino": {"nombre": "Arduino", "abrir": ["Arduino IDE"], "palabras": ["arduino", "esp32", "microcontrolador", "firmware"]},
        },
        "estilo": "MODO TRABAJO: sé concreto y técnico; ayuda con lo que esté haciendo y no lo distraigas con charla.",
    },
    "noche": {
        "descripcion": "Se activa sola al anochecer: volumen bajo y JARVIS tranquilo.",
        "volumen": 25,
        "auto": {"desde": "atardecer", "hasta": "06:00"},
        "estilo": "MODO NOCHE: habla tranquilo y breve; si es tarde, puedes sugerir descansar, sin insistir.",
    },
}


def _modos() -> dict:
    if not ARCHIVO.exists():
        _escribir(BASE)
    try:
        return json.loads(ARCHIVO.read_text(encoding="utf-8"))
    except ValueError:  # un modos.json dañado no debe romper cada respuesta del agente
        log.warning("modos.json dañado: uso los modos de fábrica")
        return dict(BASE)


def _escribir(modos: dict):
    tmp = ARCHIVO.with_suffix(".tmp")  # escritura atómica: nunca queda un archivo a medias
    tmp.write_text(json.dumps(modos, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(ARCHIVO)


def activo() -> dict | None:
    try:
        return json.loads(ACTIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _guardar_activo(estado: dict | None):
    if estado is None:
        ACTIVO.unlink(missing_ok=True)
    else:
        ACTIVO.write_text(json.dumps(estado, ensure_ascii=False), encoding="utf-8")


def instruccion() -> str:
    """Lo que el agente debe saber del modo actual (se añade a sus instrucciones)."""
    a = activo()
    if not a:
        return ""
    m = _modos().get(a["nombre"], {})
    extra = f" Está trabajando en {a['tarea']}." if a.get("tarea") else ""
    return f"\n\n{m.get('estilo') or 'MODO ' + a['nombre'].upper()}{extra} (Modo «{a['nombre']}» activo desde las {a['desde_hora']}.)"


def _elegir(nombre: str, opciones) -> str | None:
    clave = re.sub(r"^modo\s+", "", _sin_tildes(nombre or "").strip())
    opciones = list(opciones)
    if not clave:
        return None
    if clave in opciones:
        return clave
    m = difflib.get_close_matches(clave, opciones, n=1, cutoff=0.5)
    return m[0] if m else next((o for o in opciones if re.search(rf"\b{re.escape(o)}\b", clave)), None)


def _tarea(modo: dict, texto: str) -> str | None:
    tareas = modo.get("tareas") or {}
    t = _sin_tildes(texto or "")
    if not t:
        return None
    for clave, d in tareas.items():  # palabras completas: «cad» no debe coincidir con «cada»
        if any(re.search(rf"\b{re.escape(p)}\b", t) for p in [clave, *d.get("palabras", [])]):
            return clave
    return _elegir(t, tareas)


async def _paso(nombre: str, args: dict, ctx) -> str:
    try:
        return await ejecutar(nombre, args, ctx)
    except Exception as e:  # noqa: BLE001 — un paso fallido (p. ej. el PC apagado) no impide los demás
        return f"{nombre}: {e}"


async def entrar(ctx, nombre: str, tarea: str | None = None, juego: str | None = None, auto: bool = False) -> str:
    modos = _modos()
    clave = _elegir(nombre, modos)
    if not clave:
        return f"No existe el modo «{nombre}». Modos: {', '.join(modos)}. Puedo crearlo con crear_modo."
    m = modos[clave]
    tarea_clave = _tarea(m, tarea) if m.get("tareas") else None
    if m.get("pregunta") and m.get("tareas") and not tarea_clave and not tarea:
        opciones = ", ".join(d.get("nombre", k) for k, d in m["tareas"].items())
        return (f"Antes de activar el modo {clave}, PREGUNTA al usuario: «{m['pregunta']}» (opciones: {opciones}, u otra cosa). "
                f"Con su respuesta llama otra vez a activar_modo con nombre='{clave}' y tarea=<lo que diga>.")
    anterior = activo()
    mismo = bool(anterior and anterior["nombre"] == clave)
    if anterior and not mismo:
        await salir(ctx, silencioso=True)
    hechos = []
    estado = {"nombre": clave, "desde": time.time(), "desde_hora": datetime.now().strftime("%H:%M"), "auto": auto,
              "tarea": (m["tareas"][tarea_clave].get("nombre", tarea_clave) if tarea_clave else tarea) or None}
    if mismo:  # repetir el modo activo no debe perder el volumen de antes ni la marca del modo noche automático
        estado.update({k: anterior[k] for k in ("volumen_antes", "auto", "noche_de", "desde", "desde_hora") if k in anterior})
    if "volumen" in m:
        r = await _paso("volumen_pc", {"nivel": str(m["volumen"])}, ctx)
        if not mismo:
            estado["volumen_antes"] = (re.search(r"antes (\d+)", r) or [None, None])[1]
        hechos.append(r)
    if m.get("musica"):
        hechos.append(await _paso("poner_musica", {"peticion": m["musica"]}, ctx))
    if juego:
        hechos.append(await _paso("abrir_juego", {"nombre": juego}, ctx))
    else:
        for app in m.get("abrir", []):
            hechos.append(await _paso("abrir", {"objetivo": app}, ctx))
    if tarea_clave:
        for app in m["tareas"][tarea_clave].get("abrir", []):
            hechos.append(await _paso("abrir", {"objetivo": app}, ctx))
    elif tarea:
        hechos.append(f"(No tengo apps guardadas para «{tarea}»; si me dices cuáles usas, las guardo con crear_modo.)")
    _guardar_activo(estado)
    if ctx.difundir:
        await ctx.difundir({"type": "modo", "nombre": clave, "tarea": estado["tarea"]})
    return f"Modo {clave} activado" + (f" para {estado['tarea']}" if estado["tarea"] else "") + ". " + " | ".join(h for h in hechos if h)


async def salir(ctx, silencioso=False) -> str:
    a = activo()
    if not a:
        return "No hay ningún modo activo."
    if a["nombre"] == "noche" and a.get("auto") and a.get("noche_de"):
        _estado_auto({"descartada": a["noche_de"]})  # si lo apagas a mano, esa noche no vuelve a encenderse
    hechos = []
    if a.get("volumen_antes"):
        hechos.append(await _paso("volumen_pc", {"nivel": a["volumen_antes"]}, ctx))
    _guardar_activo(None)
    if ctx.difundir and not silencioso:
        await ctx.difundir({"type": "modo", "nombre": None})
    minutos = int((time.time() - a["desde"]) // 60)
    return f"Salí del modo {a['nombre']} (estuvo {minutos} min). " + " | ".join(hechos)


@herramienta("activar_modo", "Activa un modo de JARVIS: juego (música + Steam o un juego), trabajo (música y apps según en qué "
             "trabaje: PCB, código, diseño 3D, robot VEX, Arduino…), noche u otros creados. Para «modo juego», «modo trabajo».",
             {"nombre": P("string", "Nombre del modo, ej. 'juego', 'trabajo', 'noche'"),
              "tarea": P("string", "En modo trabajo: en qué va a trabajar, ej. 'una PCB', 'código del robot'"),
              "juego": P("string", "En modo juego: el juego que pidió, ej. 'Battlefield 1' (si no, abre Steam)")}, ["nombre"])
async def activar_modo(ctx, nombre, tarea=None, juego=None):
    return await entrar(ctx, nombre, tarea, juego)


@herramienta("salir_modo", "Sale del modo activo (juego, trabajo, noche…) y deja el volumen como estaba.")
async def salir_modo(ctx):
    return await salir(ctx)


@herramienta("modos", "Lista los modos de JARVIS y cuál está activo.")
async def listar_modos(ctx):
    a = activo()
    return "\n".join(f"- {k}{' (ACTIVO)' if a and a['nombre'] == k else ''}: {v.get('descripcion', '')}" for k, v in _modos().items())


@herramienta("crear_modo", "Crea o modifica un modo. Campos: descripcion, musica (qué poner), abrir (apps), estilo (cómo debe "
             "responder JARVIS), pregunta y tareas (para modos que preguntan en qué vas a trabajar).",
             {"nombre": P("string", "Nombre corto del modo"),
              "datos": P("string", "JSON con los campos, ej. {\"musica\": \"lofi\", \"abrir\": [\"Notion\"], \"estilo\": \"…\"} "
                                   "o para agregar una tarea al modo trabajo: {\"tareas\": {\"web\": {\"abrir\": [\"Visual Studio Code\"]}}}")},
             ["nombre", "datos"], peligrosa=True)
async def crear_modo(ctx, nombre, datos):
    try:
        nuevos = json.loads(datos) if isinstance(datos, str) else dict(datos)
    except ValueError as e:
        return f"Los datos del modo no son JSON válido: {e}"
    if not isinstance(nuevos, dict):
        return "Los datos del modo deben ser un objeto JSON, ej. {\"musica\": \"lofi\"}."
    lista = lambda v: [v] if isinstance(v, str) else [str(x) for x in (v or [])]  # noqa: E731 — «Notion» -> ["Notion"]
    if "abrir" in nuevos:
        nuevos["abrir"] = lista(nuevos["abrir"])
    for d in (nuevos.get("tareas") or {}).values():
        if isinstance(d, dict):
            d["abrir"], d["palabras"] = lista(d.get("abrir")), lista(d.get("palabras"))
    if "volumen" in nuevos:
        nuevos["volumen"] = max(0, min(100, int(nuevos["volumen"])))
    modos = _modos()
    clave = _sin_tildes(nombre).strip()
    if not clave:
        return "El modo necesita un nombre."
    m = modos.setdefault(clave, {"descripcion": f"Modo {clave}"})
    if "tareas" in nuevos:
        m.setdefault("tareas", {}).update(nuevos.pop("tareas"))
    m.update(nuevos)
    _escribir(modos)
    return f"Modo «{clave}» guardado: {json.dumps(m, ensure_ascii=False)[:400]}"


# ───────────────────────── herramientas del PC ─────────────────────────
@herramienta("volumen_pc", "Pone el volumen del PC en un nivel exacto (0-100).", {"nivel": P("string", "0 a 100")}, ["nivel"], solo_pc=True)
async def volumen_pc(ctx, nivel):
    def poner():
        from pycaw.pycaw import AudioUtilities

        vol = AudioUtilities.GetSpeakers().EndpointVolume
        antes = round(vol.GetMasterVolumeLevelScalar() * 100)
        vol.SetMasterVolumeLevelScalar(max(0, min(100, int(float(nivel)))) / 100, None)
        return antes

    import comtypes

    def en_hilo():
        comtypes.CoInitialize()
        try:
            return poner()
        finally:
            comtypes.CoUninitialize()
    antes = await asyncio.to_thread(en_hilo)
    return f"Volumen en {int(float(nivel))} % (antes {antes})."


def _juegos_steam() -> dict[str, str]:
    """{nombre: appid} de los juegos instalados en todas las bibliotecas de Steam."""
    raiz = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam"
    bibliotecas = [raiz]
    try:
        vdf = (raiz / "steamapps" / "libraryfolders.vdf").read_text(encoding="utf-8", errors="ignore")
        bibliotecas += [Path(p.replace("\\\\", "\\")) for p in re.findall(r'"path"\s+"([^"]+)"', vdf)]
    except OSError:
        pass
    juegos = {}
    for b in bibliotecas:
        for acf in (b / "steamapps").glob("appmanifest_*.acf"):
            t = acf.read_text(encoding="utf-8", errors="ignore")
            n, i = re.search(r'"name"\s+"([^"]+)"', t), re.search(r'"appid"\s+"(\d+)"', t)
            if n and i and not re.search(r"redistributable|steamworks|proton|runtime", n.group(1), re.I):
                juegos[n.group(1)] = i.group(1)
    return juegos


@herramienta("abrir_juego", "Abre un juego del PC por su nombre (biblioteca de Steam; si no está ahí, lo busca como app).",
             {"nombre": P("string", "Nombre aproximado del juego, ej. 'battlefield', 'kerbal'")}, ["nombre"], solo_pc=True)
async def abrir_juego(ctx, nombre):
    juegos = await asyncio.to_thread(_juegos_steam)
    clave = _sin_tildes(nombre)
    por_clave = {_sin_tildes(k): k for k in juegos}
    hallado = next((v for k, v in por_clave.items() if clave in k), None) or \
        next(iter(difflib.get_close_matches(clave, por_clave, n=1, cutoff=0.45)), None)
    if hallado:
        hallado = por_clave.get(hallado, hallado)
        from .aperturas import iniciar

        iniciar(f"steam://rungameid/{juegos[hallado]}")  # el juego no hereda el administrador del núcleo
        return f"Abriendo {hallado} en Steam."
    return await ejecutar("abrir", {"objetivo": nombre}, ctx)


# ───────────────────────── modo noche automático ─────────────────────────
async def _atardecer() -> datetime:
    u = await ubicacion()
    try:
        r = await http.get("https://api.open-meteo.com/v1/forecast", params={"latitude": u["lat"], "longitude": u["lon"],
                                                                             "daily": "sunset", "timezone": "auto", "forecast_days": 1})
        return datetime.fromisoformat(r.json()["daily"]["sunset"][0])
    except Exception:  # noqa: BLE001 — sin internet o sin ubicación: una hora razonable
        return datetime.now().replace(hour=18, minute=30, second=0, microsecond=0)


async def _ventana_noche(m: dict) -> tuple[datetime, datetime]:
    ahora = datetime.now()
    auto = m.get("auto") or {}
    desde = await _atardecer() if auto.get("desde", "atardecer") == "atardecer" else \
        ahora.replace(hour=int(auto["desde"][:2]), minute=int(auto["desde"][3:5]), second=0, microsecond=0)
    hh, mm = (int(x) for x in auto.get("hasta", "06:00").split(":"))
    hasta = ahora.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if ahora < hasta:  # madrugada: la noche empezó ayer
        desde -= timedelta(days=1)
    else:
        hasta += timedelta(days=1)
    return desde.replace(tzinfo=None), hasta


async def vigilante_noche(crear_ctx):
    """En el cerebro (siempre encendido): activa el modo noche al anochecer si no hay otro modo y lo apaga en la mañana.
    Si el usuario sale del modo noche a mano, no se vuelve a activar esa noche."""
    while True:
        try:
            m = _modos().get("noche")
            if m and m.get("auto"):
                desde, hasta = await _ventana_noche(m)
                ahora = datetime.now()
                a = activo()
                noche_de = desde.strftime("%Y-%m-%d")
                if desde <= ahora < hasta:
                    if not a and _estado_auto().get("descartada") != noche_de:
                        await entrar(crear_ctx(), "noche", auto=True)
                        if est := activo():
                            _guardar_activo({**est, "noche_de": noche_de})
                elif a and a["nombre"] == "noche" and a.get("auto"):
                    await salir(crear_ctx())
        except Exception as e:  # noqa: BLE001
            log.warning("modo noche automático: %s", e)
        await asyncio.sleep(300)


def _estado_auto(nuevo: dict | None = None) -> dict:
    ruta = config.DATOS / "modo_noche.json"
    if nuevo is not None:
        ruta.write_text(json.dumps(nuevo), encoding="utf-8")
        return nuevo
    try:
        return json.loads(ruta.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
