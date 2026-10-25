"""Herramientas reales que JARVIS puede usar. Todas gratuitas y sin llaves.

Las marcadas como `peligrosa` piden tu confirmación antes de ejecutarse.
"""
import ast
import asyncio
import base64
import difflib
import io
import json
import math
import os
import platform
import re
import socket
import subprocess
import time
import urllib.parse
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path

import httpx
import psutil

from . import config

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130 Safari/537.36"}
http = httpx.AsyncClient(timeout=20, follow_redirects=True, headers=UA)

HERRAMIENTAS: dict[str, dict] = {}


@dataclass
class Contexto:
    router: object
    memoria: object
    canal: str = "web"
    sesion: str = "web"
    difundir: object = None  # async fn(evento) -> manda a todas las pantallas
    notificar: object = None  # async fn(texto) -> manda al teléfono (Telegram)
    extra: dict = field(default_factory=dict)


def P(tipo, desc, enum=None, items=None):
    d = {"type": tipo, "description": desc}
    if enum:
        d["enum"] = enum
    if items:
        d["items"] = items
    return d


def herramienta(nombre, descripcion, params=None, requeridos=(), peligrosa=False, solo_pc=False, timeout=120):
    """timeout: segundos que el cerebro espera cuando la ejecuta el PC (laminar e imprimir tardan minutos)."""
    def deco(fn):
        HERRAMIENTAS[nombre] = {"fn": fn, "desc": descripcion, "params": params or {}, "req": list(requeridos),
                                "peligrosa": peligrosa, "solo_pc": solo_pc, "timeout": timeout}
        return fn
    return deco


NOTION_API = {"notion_buscar", "notion_leer", "notion_consultar", "notion_crear_nota"}


def disponibles() -> dict:
    sin_notion = not config.env("NOTION_TOKEN")  # sin llave, JARVIS lee Notion desde la app (notion_ver)
    return {k: v for k, v in HERRAMIENTAS.items()
            if not (v["solo_pc"] and not config.ES_WINDOWS) and not (sin_notion and k in NOTION_API)}


# Herramientas que el PC le presta al cerebro cuando funciona como nodo (además de todas las «solo PC»)
PARA_NODO = {"estado_sistema", "listar_archivos", "leer_archivo", "escribir_archivo", "ejecutar_comando",
             "mis_gustos_musicales", "como_abro"}


def para_nodo() -> list[dict]:
    """Lo que este equipo anuncia al cerebro cuando se conecta como nodo."""
    return [{"nombre": k, "desc": v["desc"], "params": v["params"], "req": v["req"], "peligrosa": v["peligrosa"], "timeout": v["timeout"]}
            for k, v in disponibles().items() if v["solo_pc"] or k in PARA_NODO]


def todas() -> dict:
    """Herramientas propias + las que prestan los nodos conectados (el PC)."""
    from .nodos import REGISTRO

    propias = disponibles()
    remotas = {k: {"desc": h["desc"], "params": h["params"], "req": h["req"], "peligrosa": h["peligrosa"], "solo_pc": False, "remota": h}
               for k, h in REGISTRO.remotas(set(propias)).items()}
    return {**propias, **remotas}


def _corto(texto: str, maximo: int) -> str:
    """Las descripciones viajan en CADA petición: se recortan para ahorrar tokens de la capa gratis."""
    texto = texto.strip()
    if len(texto) <= maximo:
        return texto
    corte = texto[:maximo]
    fin = max(corte.rfind(". "), corte.rfind(": "))
    return corte[: fin + 1] if fin > maximo // 2 else corte.rstrip() + "…"


# Mandar las 31 herramientas en cada petición cuesta ~2.400 tokens: se mandan solo las relevantes.
NUCLEO = {"fecha_hora", "buscar_web", "leer_web", "calcular", "recordar", "buscar_memoria", "crear_recordatorio", "abrir", "cerrar", "estado_ia",
          # siempre a mano para no rendirse nunca: un comando del PC, lo ya aprendido, y Claude para lo que no sepa hacer
          "ejecutar_comando", "usar_habilidad", "hablar_con_claude"}
GRUPOS = [
    ({"abrir_control_remoto", "cerrar_control_remoto"}, ("control remoto", "controlar el computador", "control del computador", "control del pc", "mouse remoto", "manejar el pc", "maneja el pc")),
    ({"clima"}, ("clima", "tiempo hace", "llov", "lluvia", "temperatura", "calor", "frío", "frio", "pronóstico", "pronostico", "sol ")),
    ({"leer_web", "noticias", "wikipedia"}, ("noticia", "página", "pagina", "web", "http", "www", "wikipedia", "quién es", "quien es", "qué es", "que es", "lee ", "artículo", "articulo", "historia de")),
    ({"multimedia", "volumen_pc"}, ("volumen", "música", "musica", "canción", "cancion", "pausa", "siguiente", "anterior", "sube", "baja", "silencia", "reproduce")),
    ({"ver_pantalla", "portapapeles"}, ("pantalla", "mira", "ves ", "ves?", "qué ves", "copia", "pega", "portapapeles", "esto")),
    ({"estado_sistema", "energia"}, ("pc", "computador", "ordenador", "cpu", "ram", "batería", "bateria", "sistema", "apaga", "reinicia", "bloquea", "suspende", "lento", "memoria del")),
    ({"listar_archivos", "leer_archivo", "escribir_archivo", "crear_carpeta", "ejecutar_comando"}, ("archivo", "carpeta", "bloc", "block", "nota", "txt", "escritorio", "documento", "comando", "powershell", "script", "instala", "crea un", "guarda en")),
    ({"olvidar", "listar_recordatorios", "cancelar_recordatorio"}, ("olvida", "recordatorio", "pendiente", "cancela", "borra")),
    ({"servidor_estado", "servidor_comando", "servidor_encender"}, ("servidor", "casaos", "server", "docker", "contenedor", "enciende")),
    ({"protocolos", "ejecutar_protocolo", "crear_protocolo"}, ("protocolo", "modo ", "macro", "rutina")),
    ({"notion_ver", "notion_buscar", "notion_leer", "notion_consultar", "notion_crear_nota"}, ("notion", "clase", "horario", "calendario", "apunte", "base de datos", "mis tareas", "mis notas", "nota en")),
    ({"poner_musica", "mis_gustos_musicales", "multimedia"}, ("música", "musica", "canción", "cancion", "spotify", "youtube", "pon algo", "ponme", "playlist", "lista de", "escuchar", "artista", "banda", "álbum", "album", "concentrarme", "relajarme", "gustos")),
    ({"hablar_con_claude", "preguntar_a_claude", "tareas_claude", "abrir_panel_claude", "chats_de_claude"}, ("claude", "cloud", "clod", "complej", "programa", "código", "codigo",
                                                                                           "script", "función", "funcion", "error en", "bug", "refactor", "revisa el proyecto", "investiga a fondo")),
    ({"activar_modo", "salir_modo", "modos", "crear_modo", "abrir_juego"}, ("modo", "jugar", "juego", "trabajar", "a trabajar", "noche", "steam", "partida")),
    ({"modelo_3d_abrir", "impresoras_3d", "impresion_3d_planear", "imprimir_3d", "estado_impresoras_3d", "controlar_impresion_3d"}, ("imprim", "impresora", "3d", "stl", "3mf", "bambu", "filamento", "ams", "lamina", "plato", "pieza", "relleno", "soporte", "pared", "pendiente", "pausa", "reanuda", "cancela", "cómo va", "como va", "progreso")),
    ({"mostrar_visual", "ocultar_visual", "estado_sistema"}, ("muéstr", "muestr", "enséñ", "ensén", "explícame", "explicame", "explica", "cómo funciona",
      "como funciona", "a fondo", "más a fondo", "mas a fondo", "diagrama", "gráfic", "grafic", "visual", "dibuj", "esquema", "lienzo",
      "cómo está el", "como esta el", "cómo va el", "como va el", "estado del", "rendimiento", "compar", "panel", "en pantalla")),
    ({"buscar_archivos", "enviar_archivo", "archivos_recibidos", "guardar_en_pc"}, ("archivo", "documento", "pdf", "foto", "imagen", "video",
      "tráeme", "traeme", "mándame", "mandame", "pásame", "pasame", "envíame", "enviame", "descarga", "guárdalo", "guardalo", "guarda", "compart")),
    ({"saca_analiticas", "tablero", "mostrar_tablero", "tableros", "terminar_analisis", "reorganizar_tablero", "borrar_analisis"},
     ("analític", "analitic", "analiz", "tablero", "esquema", "aclar", "pensar", "pensamiento", "lluvia de ideas", "mapa mental",
      "idea de negocio", "decidir", "decisión", "decision", "reabr", "retom", "proyecto", "organiza", "ordena", "enlist", "lista",
      "borra", "bórra", "olvida", "elimina", "historial")),
    ({"ensenar_pronunciacion"}, ("pronunci", "se dice", "dilo como", "dígalo como", "digalo como", "lo dices", "lo dice mal", "suena como")),
    ({"como_abro"}, ("cómo abres", "como abres", "dónde abres", "donde abres", "cómo abro", "como abro", "recuerdas abrir")),
    ({"enviar_al_telefono", "avisarme_cuando", "vigilancias"}, ("teléfono", "telefono", "celular", "telegram", "móvil", "movil",
      "mándame", "mandame", "envíame", "enviame", "notifica", "avís", "avis", "avise", "cuando termine", "cuando acabe", "cuando se",
      "cuando pase", "vigila", "pendiente de")),
]


# Órdenes inconfundibles que no se dejan a criterio de la IA (ver Agente.atajo): frase -> (herramienta, argumentos)
ATAJOS = [
    (re.compile(r"\b(saca|s[aá]came|saquemos|sacar|abre|[aá]breme|abramos|abrir|activa|activemos|pon|ponme|modo)\b.{0,12}"
                r"\banal[ií]tic|\bmodo\s+an[aá]lisis\b"
                # «analicemos», «analicemos algo porfa»: sin tema, a abrir en blanco (con tema lo entiende la IA)
                r"|^\W*(maicol\W+)?(analicemos|analizemos|pensemos)(\s+(algo|un\s+rato|porfa|porf|por\s+favor|pues|ya|juntos))*\W*$"),
     "saca_analiticas", {}),
]


def atajo(texto: str) -> tuple[str, dict] | None:
    t = (texto or "").lower()
    if len(t) > 80:  # una frase larga ya trae contenido: mejor que la IA la entienda completa
        return None
    return next(((nombre, dict(args)) for patron, nombre, args in ATAJOS if patron.search(t)), None)


def relevantes(contexto: str, usadas: set | None = None) -> set:
    t = f" {contexto.lower()} "
    elegidas = set(NUCLEO) | (usadas or set())
    for nombres, palabras in GRUPOS:
        if any(p in t for p in palabras):
            elegidas |= nombres
    from . import analisis

    if analisis.activo():  # en pleno análisis sus respuestas no traen palabras clave («porque ella…»): el tablero sigue a mano
        elegidas |= analisis.HERRAMIENTAS_TABLERO
    return elegidas


# La IA local (CPU) reutiliza lo ya procesado si el inicio de la petición es idéntico:
# por eso recibe SIEMPRE esta misma lista, en este mismo orden. Lo demás va a las IAs potentes.
LOCALES = ["fecha_hora", "clima", "buscar_web", "calcular", "recordar", "buscar_memoria", "crear_recordatorio",
           "listar_recordatorios", "abrir", "poner_musica", "multimedia", "estado_sistema", "noticias", "wikipedia", "estado_ia"]


def esquemas_locales() -> list:
    por_nombre = {e["function"]["name"]: e for e in esquemas()}
    return [por_nombre[n] for n in LOCALES if n in por_nombre]


def esquemas(contexto: str | None = None, usadas: set | None = None) -> list:
    filtro = relevantes(contexto, usadas) if contexto is not None else None
    out = []
    for k, v in todas().items():
        original = v["remota"]["original"] if v.get("remota") else k
        if filtro is not None and k not in filtro and original not in filtro:
            continue
        f = {"name": k, "description": _corto(v["desc"], 240)}
        if v["params"]:  # Gemini rechaza objetos sin propiedades: si no hay parámetros se omite
            props = {n: {**d, "description": _corto(d.get("description", ""), 60)} for n, d in v["params"].items()}
            f["parameters"] = {"type": "object", "properties": props, "required": v["req"]}
        out.append({"type": "function", "function": f})
    return out


def es_peligrosa(nombre) -> bool:
    return todas().get(nombre, {}).get("peligrosa", False)


# Lo que borra, sobrescribe, mata procesos, instala, descarga o toca el sistema: eso sí pide permiso.
# Lo demás (consultar, abrir, listar, ver) se hace solo.
COMANDO_DELICADO = re.compile(r"""(?ix)
    \b(del|erase|rd|rmdir|rm|remove-item|ri|format|diskpart|cipher|takeown|icacls|attrib|
       stop-process|spps|kill|taskkill|pkill|killall|shutdown|logoff|restart-computer|stop-computer|
       reg\s+(add|delete|import|copy)|set-itemproperty|new-itemproperty|remove-itemproperty|
       set-executionpolicy|bcdedit|sc(\.exe)?\s+(delete|stop|config|create)|stop-service|set-service|netsh|
       uninstall\S*|winget|choco|scoop|msiexec|pip\d?\s+(un)?install|npm\s+(i|install|uninstall|rm)|install-\w+|
       move-item|mv|move|rename-item|ren|rename|copy-item|cp|copy|xcopy|robocopy|
       set-content|clear-content|out-file|add-content|          # crear carpetas (new-item, mkdir) no borra nada: va sin permiso
       invoke-expression|iex|invoke-webrequest|iwr|curl|wget|start-bitstransfer|
       git\s+(reset|clean|push|checkout|rebase)|mkfs|dd|chmod|chown|sudo|apt(-get)?|dnf|yum|systemctl|
       docker\s+(rm|rmi|stop|kill|system|volume|compose\s+down)|truncate)\b
    | >>?\s*(?!\$?null\b|nul\b)\S        # redirigir la salida a un archivo lo sobrescribe
""")


def _comando_delicado(a) -> bool:
    return bool(COMANDO_DELICADO.search(str(a.get("comando", ""))))


def _sobrescribe(a) -> bool:
    try:
        return Path(os.path.expandvars(os.path.expanduser(str(a.get("ruta", ""))))).exists()
    except OSError:
        return True


PERMISO = {  # herramienta -> ¿esta llamada concreta necesita permiso?
    "ejecutar_comando": _comando_delicado,
    "servidor_comando": _comando_delicado,
    "escribir_archivo": _sobrescribe,                                              # crear uno nuevo no; pisar uno que existe sí
    "energia": lambda a: a.get("accion") in ("apagar", "reiniciar", "suspender"),  # bloquear o cancelar no
    "controlar_impresion_3d": lambda a: a.get("accion") == "cancelar",             # pausar o reanudar no
    "crear_protocolo": lambda a: False,
    "crear_modo": lambda a: False,
    "notion_crear_nota": lambda a: False,
    # imprimir_3d: siempre (gasta material)
}


def necesita_permiso(nombre, args) -> bool:
    """Las herramientas marcadas peligrosas solo piden permiso cuando la acción concreta es pesada o borra algo."""
    if not es_peligrosa(nombre):
        return False
    regla = PERMISO.get(nombre)
    return regla(args or {}) if regla else True


async def ejecutar(nombre: str, args: dict, ctx: Contexto) -> str:
    h = todas().get(nombre)
    if not h:
        return f"Error: la herramienta '{nombre}' no existe aquí."
    if h.get("remota"):
        from .nodos import REGISTRO

        return (await REGISTRO.ejecutar(h["remota"], {k: v for k, v in args.items() if k in h["params"]},
                                        timeout=h["remota"].get("timeout", 120)))[:9000]
    try:
        res = await h["fn"](ctx, **{k: v for k, v in args.items() if k in h["params"]})
    except TypeError as e:
        return f"Error en los argumentos: {e}"
    except Exception as e:  # noqa: BLE001
        return f"Error ejecutando {nombre}: {type(e).__name__}: {e}"
    if not isinstance(res, str):
        res = json.dumps(res, ensure_ascii=False, default=str)
    return res[:9000]


def _ps(script: str, timeout=60) -> str:
    """Corre PowerShell con salida en UTF-8."""
    pref = "[Console]::OutputEncoding=[Text.Encoding]::UTF8;$ProgressPreference='SilentlyContinue';"
    cod = base64.b64encode((pref + script).encode("utf-16-le")).decode()
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", cod],
                       capture_output=True, timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    salida = r.stdout.decode("utf-8", "replace").strip()
    err = r.stderr.decode("utf-8", "replace").strip()
    if err and r.returncode != 0:
        salida += ("\n" if salida else "") + "[error] " + err[:2000]
    return salida or f"(sin salida, código {r.returncode})"


# ======================= tiempo y ubicación =======================

_ubic = {}


async def ubicacion() -> dict:
    if _ubic:
        return _ubic
    ciudad = config.env("CIUDAD")
    if ciudad:
        g = await geocodificar(ciudad)
        if g:
            _ubic.update(g)
            return _ubic
    try:
        r = await http.get("http://ip-api.com/json/?lang=es&fields=city,regionName,country,lat,lon,timezone")
        d = r.json()
        _ubic.update({"ciudad": d.get("city"), "region": d.get("regionName"), "pais": d.get("country"), "lat": d.get("lat"), "lon": d.get("lon")})
    except (httpx.HTTPError, ValueError):
        pass
    return _ubic


async def geocodificar(nombre: str) -> dict | None:
    r = await http.get("https://geocoding-api.open-meteo.com/v1/search", params={"name": nombre, "count": 1, "language": "es"})
    res = (r.json().get("results") or [None])[0]
    if not res:
        return None
    return {"ciudad": res["name"], "region": res.get("admin1"), "pais": res.get("country"), "lat": res["latitude"], "lon": res["longitude"]}


DIAS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
MESES = ["enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre"]


def fecha_legible(dt: datetime | None = None) -> str:
    dt = dt or datetime.now()
    return f"{DIAS[dt.weekday()]} {dt.day} de {MESES[dt.month - 1]} de {dt.year}, {dt:%H:%M}"


@herramienta("fecha_hora", "Fecha y hora actuales, o cuánto falta para una fecha.",
             {"hasta": P("string", "Fecha ISO opcional (AAAA-MM-DD) para calcular cuánto falta")})
async def fecha_hora(ctx, hasta=None):
    ahora = datetime.now()
    txt = f"Ahora: {fecha_legible(ahora)}"
    if hasta:
        d = datetime.fromisoformat(hasta) - ahora
        txt += f". Faltan {d.days} días y {d.seconds // 3600} horas para {hasta}."
    return txt


CODIGOS_CLIMA = {0: "despejado", 1: "mayormente despejado", 2: "parcialmente nublado", 3: "nublado", 45: "niebla", 48: "niebla con escarcha",
                 51: "llovizna ligera", 53: "llovizna", 55: "llovizna intensa", 61: "lluvia ligera", 63: "lluvia", 65: "lluvia fuerte",
                 71: "nieve ligera", 73: "nieve", 75: "nieve fuerte", 80: "chubascos ligeros", 81: "chubascos", 82: "chubascos violentos",
                 95: "tormenta eléctrica", 96: "tormenta con granizo", 99: "tormenta fuerte con granizo"}


@herramienta("clima", "Clima actual y pronóstico de los próximos días (Open-Meteo).",
             {"ciudad": P("string", "Ciudad; si se omite se usa la ubicación del usuario"), "dias": P("integer", "Días de pronóstico (1-7)")})
async def clima(ctx, ciudad=None, dias=3):
    u = await geocodificar(ciudad) if ciudad else await ubicacion()
    if not u or u.get("lat") is None:
        return "No pude determinar la ubicación."
    r = await http.get("https://api.open-meteo.com/v1/forecast", params={
        "latitude": u["lat"], "longitude": u["lon"], "timezone": "auto", "forecast_days": max(1, min(int(dias or 3), 7)),
        "current": "temperature_2m,apparent_temperature,relative_humidity_2m,weather_code,wind_speed_10m,precipitation",
        "daily": "weather_code,temperature_2m_max,temperature_2m_min,precipitation_probability_max,uv_index_max,sunrise,sunset"})
    d = r.json()
    c = d["current"]
    lineas = [f"{u['ciudad']}, {u.get('pais', '')}: {c['temperature_2m']}°C (sensación {c['apparent_temperature']}°C), "
              f"{CODIGOS_CLIMA.get(c['weather_code'], 'variable')}, humedad {c['relative_humidity_2m']}%, viento {c['wind_speed_10m']} km/h."]
    dd = d["daily"]
    for i, f in enumerate(dd["time"]):
        lineas.append(f"{f}: {CODIGOS_CLIMA.get(dd['weather_code'][i], 'variable')}, {dd['temperature_2m_min'][i]}–{dd['temperature_2m_max'][i]}°C, "
                      f"lluvia {dd['precipitation_probability_max'][i]}%, UV {dd['uv_index_max'][i]}")
    return "\n".join(lineas)


# ======================= internet =======================

class _Texto(HTMLParser):
    SALTAR = {"script", "style", "noscript", "svg", "nav", "footer", "header", "form", "aside"}

    def __init__(self):
        super().__init__()
        self.partes, self.saltando, self.titulo, self._en_titulo = [], 0, "", False

    def handle_starttag(self, tag, attrs):
        if tag in self.SALTAR:
            self.saltando += 1
        if tag == "title":
            self._en_titulo = True
        if tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "tr", "div"):
            self.partes.append("\n")

    def handle_endtag(self, tag):
        if tag in self.SALTAR and self.saltando:
            self.saltando -= 1
        if tag == "title":
            self._en_titulo = False

    def handle_data(self, data):
        if self._en_titulo:
            self.titulo += data
        elif not self.saltando:
            self.partes.append(data)


def html_a_texto(html: str) -> tuple[str, str]:
    p = _Texto()
    p.feed(html)
    txt = re.sub(r"[ \t]+", " ", "".join(p.partes))
    txt = re.sub(r"\n\s*\n+", "\n", txt).strip()
    return p.titulo.strip(), txt


@herramienta("buscar_web", "Busca en internet (DuckDuckGo). Úsala para cualquier dato actual o que no sepas con certeza.",
             {"consulta": P("string", "Qué buscar"), "cantidad": P("integer", "Número de resultados (máx 10)")}, ["consulta"])
async def buscar_web(ctx, consulta, cantidad=6):
    cantidad = max(1, min(int(cantidad or 6), 10))
    try:
        from ddgs import DDGS

        res = await asyncio.to_thread(lambda: list(DDGS().text(consulta, region="es-es", max_results=cantidad)))
        if res:
            return "\n\n".join(f"{i + 1}. {r.get('title')}\n{r.get('href')}\n{r.get('body')}" for i, r in enumerate(res)) + SOLO_RESUMENES
    except Exception:  # noqa: BLE001
        pass
    r = await http.post("https://html.duckduckgo.com/html/", data={"q": consulta})
    bloques = re.findall(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?class="result__snippet"[^>]*>(.*?)</a>', r.text, re.S)
    limpiar = lambda s: re.sub(r"<.*?>", "", s).strip()  # noqa: E731
    out = []
    for i, (url, tit, snip) in enumerate(bloques[:cantidad]):
        if "uddg=" in url:
            url = urllib.parse.unquote(url.split("uddg=")[1].split("&")[0])
        out.append(f"{i + 1}. {limpiar(tit)}\n{url}\n{limpiar(snip)}")
    return "\n\n".join(out) + SOLO_RESUMENES if out else "Sin resultados."


# las IAs gratis responden con lo que «suena» en los resúmenes: si la pregunta es una cifra, que lean la fuente
SOLO_RESUMENES = ("\n\n(Esto son solo resúmenes. Si le preguntaron una cifra, un límite, un precio o un plan y aquí no aparece "
                  "exacto, abre la página oficial con leer_web antes de responder; no supongas «no hay límite».)")


@herramienta("leer_web", "Descarga una página web y devuelve su texto principal.",
             {"url": P("string", "Dirección completa"), "max_caracteres": P("integer", "Límite de texto (por defecto 6000)")}, ["url"])
async def leer_web(ctx, url, max_caracteres=6000):
    r = await http.get(url)
    tipo = r.headers.get("content-type", "")
    if "html" not in tipo and "text" not in tipo and "json" not in tipo:
        return f"El recurso es de tipo {tipo}, no es texto."
    titulo, txt = html_a_texto(r.text) if "html" in tipo else ("", r.text)
    return f"# {titulo}\n{txt[: int(max_caracteres or 6000)]}"


@herramienta("noticias", "Titulares de noticias recientes (Google News), generales o sobre un tema.",
             {"tema": P("string", "Tema opcional"), "cantidad": P("integer", "Cuántas (por defecto 8)")})
async def noticias(ctx, tema=None, cantidad=8):
    pais = config.env("PAIS", "CO")
    params = f"hl=es-419&gl={pais}&ceid={pais}:es-419"
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(tema)}&{params}" if tema else f"https://news.google.com/rss?{params}"
    r = await http.get(url)
    raiz = ET.fromstring(r.content)
    items = raiz.findall(".//item")[: int(cantidad or 8)]
    return "\n".join(f"- {i.findtext('title')} ({i.findtext('pubDate', '')[:16]})" for i in items) or "Sin noticias."


@herramienta("wikipedia", "Resumen de un tema en Wikipedia en español.", {"tema": P("string", "Tema a consultar")}, ["tema"])
async def wikipedia(ctx, tema):
    r = await http.get("https://es.wikipedia.org/w/api.php", params={"action": "opensearch", "search": tema, "limit": 1, "format": "json"})
    titulos = r.json()[1]
    if not titulos:
        return "No encontré ese tema en Wikipedia."
    s = await http.get(f"https://es.wikipedia.org/api/rest_v1/page/summary/{urllib.parse.quote(titulos[0])}")
    d = s.json()
    return f"{d.get('title')}: {d.get('extract')}\n{d.get('content_urls', {}).get('desktop', {}).get('page', '')}"


# ======================= cálculo =======================

_SEGURO = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
_SEGURO.update({"abs": abs, "round": round, "min": min, "max": max, "sum": sum})


def _evaluar(nodo):
    if isinstance(nodo, ast.Expression):
        return _evaluar(nodo.body)
    if isinstance(nodo, ast.Constant) and isinstance(nodo.value, (int, float)):
        return nodo.value
    if isinstance(nodo, ast.BinOp):
        a, b = _evaluar(nodo.left), _evaluar(nodo.right)
        ops = {ast.Add: lambda: a + b, ast.Sub: lambda: a - b, ast.Mult: lambda: a * b, ast.Div: lambda: a / b,
               ast.Pow: lambda: a ** b if abs(b) < 1000 else math.inf, ast.Mod: lambda: a % b, ast.FloorDiv: lambda: a // b}
        return ops[type(nodo.op)]()
    if isinstance(nodo, ast.UnaryOp):
        v = _evaluar(nodo.operand)
        return -v if isinstance(nodo.op, ast.USub) else v
    if isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Name) and nodo.func.id in _SEGURO:
        return _SEGURO[nodo.func.id](*[_evaluar(a) for a in nodo.args])
    if isinstance(nodo, ast.Name) and nodo.id in _SEGURO:
        return _SEGURO[nodo.id]
    if isinstance(nodo, (ast.List, ast.Tuple)):
        return [_evaluar(e) for e in nodo.elts]
    raise ValueError("expresión no permitida")


@herramienta("calcular", "Calcula una expresión matemática exacta (usa sintaxis Python: sqrt, sin, log, pi, **).",
             {"expresion": P("string", "Por ejemplo: sqrt(2)*15**2/7")}, ["expresion"])
async def calcular(ctx, expresion):
    return f"{expresion} = {_evaluar(ast.parse(expresion.replace('^', '**'), mode='eval'))}"


# ======================= memoria =======================

@herramienta("recordar", "Guarda un dato duradero sobre el usuario o algo que pidió recordar.",
             {"dato": P("string", "El dato, en tercera persona y autocontenido")}, ["dato"])
async def recordar(ctx, dato):
    i = ctx.memoria.recordar(dato)
    return f"Guardado en memoria (#{i})." if i else "Ya lo tenía registrado."


@herramienta("buscar_memoria", "Busca en la memoria a largo plazo lo que se sabe del usuario.", {"consulta": P("string", "Qué buscar")}, ["consulta"])
async def buscar_memoria(ctx, consulta):
    res = ctx.memoria.buscar(consulta) or ctx.memoria.hechos(15)
    return "\n".join(f"#{h['id']}: {h['texto']}" for h in res) or "Memoria vacía."


@herramienta("olvidar", "Borra un dato de la memoria por su número.", {"id": P("integer", "Número del dato")}, ["id"])
async def olvidar(ctx, id):  # noqa: A002
    return "Olvidado." if ctx.memoria.olvidar(int(id)) else "No existe ese dato."


# ======================= recordatorios =======================

@herramienta("crear_recordatorio", "Programa un recordatorio o temporizador. Avisa por voz en pantalla y al teléfono.",
             {"texto": P("string", "Qué recordar"), "en_minutos": P("number", "Dentro de cuántos minutos"),
              "fecha_hora": P("string", "Momento exacto ISO local (AAAA-MM-DDTHH:MM) si no se usa en_minutos")}, ["texto"])
async def crear_recordatorio(ctx, texto, en_minutos=None, fecha_hora=None):
    if fecha_hora:
        vence = datetime.fromisoformat(fecha_hora)
    else:
        vence = datetime.now() + timedelta(minutes=float(en_minutos or 5))
    i = ctx.memoria.crear_recordatorio(texto, vence.timestamp(), ctx.canal)
    return f"Recordatorio #{i} para {fecha_legible(vence)}: {texto}"


@herramienta("listar_recordatorios", "Lista los recordatorios pendientes.")
async def listar_recordatorios(ctx):
    rs = ctx.memoria.recordatorios()
    return "\n".join(f"#{r['id']} {fecha_legible(datetime.fromtimestamp(r['vence']))}: {r['texto']}" for r in rs) or "No hay recordatorios pendientes."


@herramienta("cancelar_recordatorio", "Cancela un recordatorio por su número.", {"id": P("integer", "Número")}, ["id"])
async def cancelar_recordatorio(ctx, id):  # noqa: A002
    return "Cancelado." if ctx.memoria.cancelar_recordatorio(int(id)) else "No encontré ese recordatorio."


# ======================= el PC =======================

def _bytes(n):
    for u in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {u}"
        n /= 1024
    return f"{n:.1f} PB"


def metricas() -> dict:
    vm = psutil.virtual_memory()
    try:
        disco = psutil.disk_usage("C:\\" if config.ES_WINDOWS else "/").percent
    except OSError:
        disco = None
    bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
    red = psutil.net_io_counters()
    return {"cpu": psutil.cpu_percent(interval=None), "ram": vm.percent, "ram_usada": _bytes(vm.used), "ram_total": _bytes(vm.total),
            "disco": disco, "bateria": bat.percent if bat else None, "enchufado": bat.power_plugged if bat else None,
            "red_tx": red.bytes_sent, "red_rx": red.bytes_recv, "arranque": psutil.boot_time()}


@herramienta("mostrar_visual", "Abre el lienzo visual (panel HUD pegado al chat) y dibuja ahí con HTML usando la plantilla: "
             "estado del PC, cómo funciona algo, diagramas, pasos, comparaciones, datos.",
             {"titulo": P("string", "Título corto del panel"),
              "html": P("string", "Contenido HTML con las piezas de la plantilla (y SVG/script si hace falta)"),
              "donde": P("string", "'panel' (por defecto, junto al chat) o 'ventana' (ventana grande propia en el PC, para "
                         "algo amplio como un tablero de datos o un diagrama grande)", ["panel", "ventana"])}, ["titulo", "html"])
async def mostrar_visual(ctx, titulo, html, donde="panel"):
    if len(html) > 80000:
        return "El visual es demasiado grande; hazlo más simple."
    from . import superficies

    if await superficies.visual_al_lado(ctx, titulo, html):  # con las analíticas abiertas, sale al costado del tablero
        lugar = "en la pizarra que salió al lado del tablero de análisis"
    elif donde == "ventana" and config.ES_WINDOWS:
        from . import superficies

        superficies.abrir_ventana(f"/visual/{superficies.guardar_visual(titulo[:80], html)}", 1180, 820)
        lugar = "en una ventana grande en el PC"
    elif not ctx.difundir:
        return "Aquí no hay pantalla donde mostrarlo."
    else:
        await ctx.difundir({"type": "visual", "titulo": titulo[:80], "html": html})
        lugar = "en el lienzo"
    return (f"Mostrando «{titulo}» {lugar}. Si todavía no lo explicaste en voz, hazlo ahora de verdad: si era una "
            "explicación, 2 a 4 frases con la idea central y cómo funciona; si eran datos, 1 o 2 frases con lo importante. "
            "Nada de «ya le explico»: explícalo. No leas el panel ni repitas lo que ya dijiste.")


@herramienta("ocultar_visual", "Cierra el lienzo visual.")
async def ocultar_visual(ctx):
    if ctx.difundir:
        await ctx.difundir({"type": "visual", "cerrar": True})
    return "Lienzo cerrado."


@herramienta("abrir_control_remoto", "Abre en el celular un panel con la pantalla del PC en vivo para tocarla y controlar el mouse. Úsala cuando el usuario pida control remoto, mouse remoto o controlar el computador desde el celular.")
async def abrir_control_remoto(ctx):
    if not config.ES_WINDOWS:
        return "El control remoto solo está disponible cuando JARVIS corre en Windows."
    if not ctx.difundir:
        return "No hay una pantalla conectada para abrir el control remoto."
    await ctx.difundir({"type": "control_remoto", "abrir": True})
    return ("Listo: en el celular quedó la pantalla del PC en vivo. Tocar = clic, mantener presionado = clic derecho, "
            "arrastrar con un dedo = arrastrar, dos dedos = rueda, botón ⌨ = teclado. Dilo en una frase corta.")


@herramienta("cerrar_control_remoto", "Cierra el panel de control remoto del celular.")
async def cerrar_control_remoto(ctx):
    if ctx.difundir:
        await ctx.difundir({"type": "control_remoto", "abrir": False})
    return "Control remoto cerrado."


@herramienta("estado_sistema", "Estado del computador: CPU, RAM, disco, batería, temperatura y procesos que más consumen.")
async def estado_sistema(ctx):
    m = metricas()
    procs = []
    for p in psutil.process_iter(["name", "memory_info"]):
        try:
            procs.append((p.info["memory_info"].rss, p.info["name"]))
        except (psutil.Error, TypeError, AttributeError):
            pass
    top = ", ".join(f"{n} ({_bytes(r)})" for r, n in sorted(procs, reverse=True)[:6])
    horas = (time.time() - m["arranque"]) / 3600
    bat = f", batería {m['bateria']:.0f}% ({'cargando' if m['enchufado'] else 'descargando'})" if m["bateria"] is not None else ""
    return (f"{platform.node()} · {platform.system()} {platform.release()}. CPU {psutil.cpu_percent(interval=0.5)}% de {psutil.cpu_count()} hilos, "
            f"RAM {m['ram']}% ({m['ram_usada']} de {m['ram_total']}), disco {m['disco']}%{bat}. Encendido hace {horas:.1f} h. Más RAM: {top}")


@herramienta("abrir", "Abre un programa, archivo, carpeta o página web. Busca primero la app instalada en el PC y si no existe la abre en la web; "
             "recuerda cómo se abrió cada cosa. Si el usuario dice dónde abrirlo ('en la app', 'en el navegador', 'en Brave'), pásalo en donde/navegador y quedará guardado.",
             {"objetivo": P("string", "Ej: 'spotify', 'notion', 'https://...', 'C:/Users/...'"),
              "donde": P("string", "Solo si el usuario lo dijo: app o web", ["app", "web"]),
              "navegador": P("string", "Solo si el usuario lo dijo: brave, chrome, edge, firefox u opera")}, ["objetivo"], solo_pc=True)
async def abrir(ctx, objetivo, donde=None, navegador=None):
    from . import aperturas, musica

    if aperturas.normalizar(objetivo) == "spotify" and donde != "app" and not navegador and config.ES_WINDOWS:
        return await musica.poner()  # «abre Spotify» = pon algo que me guste

    return await asyncio.to_thread(aperturas.abrir, objetivo, donde, navegador)


@herramienta("poner_musica", "Pone música y la deja sonando (YouTube Music en su navegador o Spotify, según su preferencia). "
             "Úsala siempre para música, nunca 'abrir' con una búsqueda. Sin petición elige algo según lo que el usuario suele escuchar; "
             "con petición busca y reproduce eso (canción, artista, lista, género o ánimo: 'algo para concentrarme').",
             {"peticion": P("string", "Qué poner (opcional)")}, solo_pc=True)
async def poner_musica(ctx, peticion=None):
    from . import musica

    return await musica.poner(peticion)


@herramienta("mis_gustos_musicales", "Resume qué música escucha más el usuario (aprendido de lo que suena en el PC).")
async def mis_gustos_musicales(ctx):
    from . import musica

    return await asyncio.to_thread(musica.resumen_gustos)


@herramienta("como_abro", "Muestra cómo JARVIS recuerda abrir cada cosa (app del PC o web y en qué navegador).")
async def como_abro(ctx):
    from . import aperturas

    filas = [f"- {k}: {'app del PC' if v['tipo'] == 'app' else 'web en ' + aperturas.nombre_navegador(v.get('navegador'))}" for k, v in aperturas.todos().items()]
    return "\n".join(filas) or "Aún no recuerdo nada."


TECLAS = {"play_pausa": 0xB3, "siguiente": 0xB0, "anterior": 0xB1, "detener": 0xB2, "silenciar": 0xAD, "bajar_volumen": 0xAE, "subir_volumen": 0xAF}


@herramienta("multimedia", "Controla música/volumen del PC: play_pausa, siguiente, anterior, detener, silenciar, subir_volumen, bajar_volumen. "
             "Para dejar el volumen en un número exacto («a 20») usa volumen_pc.",
             {"accion": P("string", "Acción", list(TECLAS)), "veces": P("integer", "Repeticiones (para volumen, cada una ≈2%)")}, ["accion"], solo_pc=True)
async def multimedia(ctx, accion, veces=1):
    import ctypes

    vk = TECLAS[accion]
    for _ in range(max(1, min(int(veces or 1), 50))):
        ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
        ctypes.windll.user32.keybd_event(vk, 0, 2, 0)
    return f"Hecho: {accion} x{veces}"


@herramienta("ver_pantalla", "Toma una captura de la pantalla del PC y la analiza con una IA con visión. Úsala si el usuario dice 'mira', 'qué ves', 'ayúdame con esto'.",
             {"pregunta": P("string", "Qué quiere saber el usuario sobre la pantalla")}, ["pregunta"], solo_pc=True)
async def ver_pantalla(ctx, pregunta):
    from PIL import ImageGrab

    img = await asyncio.to_thread(ImageGrab.grab)
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=80)
    url = "data:image/jpeg;base64," + base64.b64encode(buf.getvalue()).decode()
    msgs = [{"role": "system", "content": "Eres los ojos de un asistente. Describe con precisión y en español lo relevante de la captura de pantalla para responder la pregunta. Transcribe textos, errores o código importantes."},
            {"role": "user", "content": [{"type": "text", "text": pregunta}, {"type": "image_url", "image_url": {"url": url}}]}]
    return "Lo que se ve en pantalla: " + await ctx.router.completar(msgs, nivel="inteligente", vision=True)


@herramienta("portapapeles", "Lee o escribe el portapapeles del PC.",
             {"accion": P("string", "leer o escribir", ["leer", "escribir"]), "texto": P("string", "Texto a copiar (si es escribir)")}, ["accion"], solo_pc=True)
async def portapapeles(ctx, accion, texto=""):
    if accion == "leer":
        return (await asyncio.to_thread(_ps, "Get-Clipboard -Raw"))[:6000]
    b64 = base64.b64encode(texto.encode()).decode()
    await asyncio.to_thread(_ps, f"Set-Clipboard -Value ([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}')))")
    return "Copiado al portapapeles."


@herramienta("ejecutar_comando", "Ejecuta un comando de PowerShell (o bash en Linux) y devuelve la salida. Para tareas avanzadas del sistema.",
             {"comando": P("string", "Comando a ejecutar"), "timeout": P("integer", "Segundos máximos (por defecto 60)")}, ["comando"], peligrosa=True)
async def ejecutar_comando(ctx, comando, timeout=60):
    t = max(5, min(int(timeout or 60), 600))
    if config.ES_WINDOWS:
        return await asyncio.to_thread(_ps, comando, t)
    r = await asyncio.to_thread(subprocess.run, ["bash", "-lc", comando], capture_output=True, text=True, timeout=t)
    return (r.stdout + ("\n[error] " + r.stderr if r.stderr else ""))[:8000] or f"(sin salida, código {r.returncode})"


@herramienta("listar_archivos", "Lista el contenido de una carpeta.", {"ruta": P("string", "Carpeta (por defecto el escritorio)")})
async def listar_archivos(ctx, ruta=None):
    p = Path(os.path.expandvars(os.path.expanduser(ruta or "~/Desktop")))
    if not p.exists():
        return "No existe esa ruta."
    filas = []
    for f in sorted(p.iterdir(), key=lambda x: (not x.is_dir(), x.name.lower()))[:200]:
        try:
            filas.append(f"{'[DIR] ' if f.is_dir() else ''}{f.name}" + ("" if f.is_dir() else f" ({_bytes(f.stat().st_size)})"))
        except OSError:
            pass
    return f"{p}:\n" + "\n".join(filas)


@herramienta("leer_archivo", "Lee un archivo de texto del PC.", {"ruta": P("string", "Ruta del archivo")}, ["ruta"])
async def leer_archivo(ctx, ruta):
    p = Path(os.path.expandvars(os.path.expanduser(ruta)))
    return p.read_text(encoding="utf-8", errors="replace")[:8000]


@herramienta("crear_carpeta", "Crea una carpeta (y las que falten en la ruta). Ej: escritorio/proyecto 1.",
             {"ruta": P("string", "Ruta completa de la carpeta")}, ["ruta"])
async def crear_carpeta(ctx, ruta):
    p = Path(os.path.expandvars(os.path.expanduser(ruta)))
    ya = p.is_dir()
    p.mkdir(parents=True, exist_ok=True)
    return f"{'Ya existía' if ya else 'Creada'} la carpeta {p}."


@herramienta("escribir_archivo", "Crea o sobrescribe un archivo de texto (.txt = bloc de notas) en el PC; crea solo las carpetas que falten.",
             {"ruta": P("string", "Ruta del archivo"), "contenido": P("string", "Contenido completo")}, ["ruta", "contenido"], peligrosa=True)
async def escribir_archivo(ctx, ruta, contenido):
    p = Path(os.path.expandvars(os.path.expanduser(ruta)))
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(contenido, encoding="utf-8")
    return f"Escrito {p} ({len(contenido)} caracteres)."


@herramienta("cerrar", "Cierra un programa como si le dieran a la X (pide guardar si hace falta). Úsala siempre para cerrar apps "
             "en vez de matar procesos con comandos. Nunca cierra a Maicol.",
             {"programa": P("string", "Nombre del programa o de la ventana, ej: 'edge', 'spotify', 'excel'")}, ["programa"], solo_pc=True)
async def cerrar(ctx, programa):
    return await asyncio.to_thread(_cerrar_ventanas, programa)


def _cerrar_ventanas(programa: str) -> str:
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    buscado = re.sub(r"[^a-z0-9]", "", programa.lower().replace("microsoft", ""))
    propias = {"maicol", "maicollateral"}
    cerradas, nombres = 0, set()

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def una(h, _):
        nonlocal cerradas
        if not u.IsWindowVisible(h) or u.GetWindow(h, 4) or not u.GetWindowTextLengthW(h):  # solo ventanas principales
            return True
        b = ctypes.create_unicode_buffer(300)
        u.GetWindowTextW(h, b, 300)
        titulo = re.sub(r"[^a-z0-9]", "", b.value.lower())
        if titulo in propias:
            return True
        pid = wintypes.DWORD()
        u.GetWindowThreadProcessId(h, ctypes.byref(pid))
        try:
            proc = psutil.Process(pid.value).name().lower().removesuffix(".exe")
        except psutil.Error:
            return True
        if proc in ("python", "pythonw", "explorer"):
            return True
        if buscado and (buscado in re.sub(r"[^a-z0-9]", "", proc) or buscado in titulo):
            u.PostMessageW(h, 0x0010, 0, 0)  # WM_CLOSE: igual que la X
            cerradas += 1
            nombres.add(proc)
        return True

    u.EnumWindows(una, 0)
    if not cerradas:
        return f"No encontré ninguna ventana abierta de «{programa}»."
    return f"Cerré {cerradas} ventana(s) de {', '.join(sorted(nombres))}."


@herramienta("energia", "Bloquear, suspender, apagar o reiniciar el PC (apagar/reiniciar esperan 60 s; 'cancelar' lo detiene).",
             {"accion": P("string", "Acción", ["bloquear", "suspender", "apagar", "reiniciar", "cancelar"])}, ["accion"], peligrosa=True, solo_pc=True)
async def energia(ctx, accion):
    cmds = {"bloquear": ["rundll32.exe", "user32.dll,LockWorkStation"], "suspender": ["rundll32.exe", "powrprof.dll,SetSuspendState", "0,1,0"],
            "apagar": ["shutdown", "/s", "/t", "60"], "reiniciar": ["shutdown", "/r", "/t", "60"], "cancelar": ["shutdown", "/a"]}
    subprocess.Popen(cmds[accion])
    return f"Acción '{accion}' enviada."


# ======================= servidor CasaOS =======================

def _ssh_base() -> list[str] | None:
    host, usuario = config.env("SERVIDOR_HOST"), config.env("SERVIDOR_USUARIO")
    if not host or not usuario:
        return None
    return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=6", "-o", "StrictHostKeyChecking=accept-new",
            "-p", config.env("SERVIDOR_PUERTO_SSH", "22"), f"{usuario}@{host}"]


@herramienta("servidor_estado", "Revisa el servidor casero CasaOS: si está encendido, latencia, y (con SSH) carga, RAM, disco y contenedores Docker.")
async def servidor_estado(ctx):
    host = config.env("SERVIDOR_HOST")
    if not host and config.EN_DOCKER:
        # este JARVIS ES el cerebro que vive en el servidor: se mide a sí mismo
        return "Este es el servidor donde vive JARVIS. " + await estado_sistema(ctx)
    if not host:
        return "No hay servidor configurado (SERVIDOR_HOST en .env)."
    t0 = time.time()
    try:
        with socket.create_connection((host, int(config.env("SERVIDOR_PUERTO_WEB", "80"))), timeout=3):
            pass
        vivo = f"En línea ({(time.time() - t0) * 1000:.0f} ms)."
    except OSError:
        return f"El servidor {host} no responde. Si tienes SERVIDOR_MAC configurada puedo encenderlo con Wake-on-LAN."
    base = _ssh_base()
    if not base:
        return vivo + " (Configura SERVIDOR_USUARIO y una llave SSH para ver más detalle.)"
    cmd = "uptime; free -h | head -2; df -h / | tail -1; docker ps --format '{{.Names}}: {{.Status}}' 2>/dev/null | head -30"
    r = await asyncio.to_thread(subprocess.run, base + [cmd], capture_output=True, text=True, timeout=25)
    return vivo + "\n" + (r.stdout or r.stderr)[:5000]


@herramienta("servidor_comando", "Ejecuta un comando por SSH en el servidor CasaOS.", {"comando": P("string", "Comando bash")}, ["comando"], peligrosa=True)
async def servidor_comando(ctx, comando):
    base = _ssh_base()
    if not base:
        return "Falta SERVIDOR_HOST / SERVIDOR_USUARIO en .env."
    r = await asyncio.to_thread(subprocess.run, base + [comando], capture_output=True, text=True, timeout=120)
    return (r.stdout + ("\n[error] " + r.stderr if r.stderr else ""))[:8000] or "(sin salida)"


@herramienta("servidor_encender", "Enciende el servidor casero con Wake-on-LAN.")
async def servidor_encender(ctx):
    mac = config.env("SERVIDOR_MAC").replace(":", "").replace("-", "")
    if len(mac) != 12:
        return "Configura SERVIDOR_MAC en .env (y activa Wake-on-LAN en la BIOS del servidor)."
    paquete = bytes.fromhex("FF" * 6 + mac * 16)
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(paquete, ("255.255.255.255", 9))
    return "Paquete mágico enviado. Debería arrancar en un minuto."


# ======================= protocolos (macros) =======================

PROTOCOLOS = config.DATOS / "protocolos.json"
PROTOCOLOS_BASE = {
    "trabajo": {"descripcion": "Abre las herramientas de trabajo", "pasos": [{"abrir": "visual studio code"}, {"abrir": "notion"}, {"abrir": "https://github.com"}]},
    "concentracion": {"descripcion": "Música para concentrarse y silencio de distracciones", "pasos": [{"abrir": "https://www.youtube.com/results?search_query=lofi+hip+hop+radio"}]},
    "fiesta": {"descripcion": "Volumen arriba y música", "pasos": [{"multimedia": "subir_volumen", "veces": 15}, {"abrir": "spotify"}]},
}


def _protocolos() -> dict:
    if not PROTOCOLOS.exists():
        PROTOCOLOS.write_text(json.dumps(PROTOCOLOS_BASE, ensure_ascii=False, indent=2), encoding="utf-8")
    return json.loads(PROTOCOLOS.read_text(encoding="utf-8"))


@herramienta("protocolos", "Lista los protocolos (macros) disponibles, como 'protocolo trabajo'.")
async def protocolos(ctx):
    return "\n".join(f"- {k}: {v['descripcion']} ({len(v['pasos'])} pasos)" for k, v in _protocolos().items())


@herramienta("ejecutar_protocolo", "Ejecuta un protocolo (macro) por su nombre.", {"nombre": P("string", "Nombre del protocolo")}, ["nombre"])
async def ejecutar_protocolo(ctx, nombre):
    todos = _protocolos()
    clave = difflib.get_close_matches(nombre.lower(), todos.keys(), n=1, cutoff=0.4)
    if not clave:
        return f"No existe el protocolo '{nombre}'. Disponibles: {', '.join(todos)}"
    hechos = []
    for paso in todos[clave[0]]["pasos"]:
        if "abrir" in paso:
            hechos.append(await ejecutar("abrir", {"objetivo": paso["abrir"]}, ctx))
        elif "multimedia" in paso:
            hechos.append(await ejecutar("multimedia", {"accion": paso["multimedia"], "veces": paso.get("veces", 1)}, ctx))
        elif "comando" in paso:
            hechos.append(await ejecutar_comando(ctx, paso["comando"]))
        elif "esperar" in paso:
            await asyncio.sleep(float(paso["esperar"]))
    return f"Protocolo {clave[0]} ejecutado: " + " | ".join(hechos)


@herramienta("crear_protocolo", "Crea o reemplaza un protocolo. Pasos: lista de objetos {abrir: 'x'} | {multimedia: 'accion', veces: n} | {comando: 'powershell'} | {esperar: segundos}.",
             {"nombre": P("string", "Nombre corto"), "descripcion": P("string", "Para qué sirve"),
              "pasos": P("string", "JSON con la lista de pasos, ej: [{\"abrir\": \"spotify\"}, {\"esperar\": 2}]")}, ["nombre", "descripcion", "pasos"], peligrosa=True)
async def crear_protocolo(ctx, nombre, descripcion, pasos):
    if isinstance(pasos, str):
        pasos = json.loads(pasos)
    todos = _protocolos()
    todos[nombre.lower()] = {"descripcion": descripcion, "pasos": pasos}
    PROTOCOLOS.write_text(json.dumps(todos, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"Protocolo '{nombre}' guardado con {len(pasos)} pasos."


# ======================= meta =======================

@herramienta("estado_ia", "Muestra qué proveedores de IA gratis están disponibles, cuáles están en enfriamiento y el consumo de hoy.")
async def estado_ia(ctx):
    e = ctx.router.estado()
    lineas = [f"Estrategia: {e['estrategia']}. {e['libres']}/{e['total']} ranuras libres."]
    for p in e["proveedores"]:
        if not p["configurado"]:
            continue
        extra = f", próximo libre en {int(p['proximo'] // 60)} min ({p['motivo']})" if p["libres"] < p["ranuras"] else ""
        lineas.append(f"- {p['nombre']}: {p['libres']}/{p['ranuras']} libres, {p['peticiones_dia']} peticiones y ~{p['tokens_dia']} tokens hoy{extra}")
    faltan = [p["nombre"] for p in e["proveedores"] if not p["configurado"]]
    if faltan:
        lineas.append("Sin configurar: " + ", ".join(faltan))
    return "\n".join(lineas)


@herramienta("enviar_al_telefono", "Manda YA una notificación al celular del usuario (le llega aunque tenga Maicol cerrado). "
             "Para avisar más tarde, cuando pase algo en el PC, usa avisarme_cuando.", {"mensaje": P("string", "Texto del aviso")}, ["mensaje"])
async def enviar_al_telefono(ctx, mensaje):
    from . import avisos_push

    llegó = []
    if avisos_push.hay_suscritos() and await asyncio.to_thread(avisos_push.enviar, mensaje, "Maicol"):
        llegó.append("notificación")
    if ctx.notificar and await ctx.notificar(mensaje):
        llegó.append("Telegram")
    if llegó:
        return f"Enviado al celular ({' y '.join(llegó)})."
    return ("No le llegó: el celular todavía no tiene los avisos activados. Dígale que en el celular toque "
            "⚙ → «🔔 Avisos en este celular» una vez (en iPhone, con Maicol agregado a la pantalla de inicio).")


# ======================= archivos entre PC y celular =======================

def _carpetas_usuario() -> list[Path]:
    casa = Path.home()
    nombres = ["Desktop", "Escritorio", "Documents", "Documentos", "Downloads", "Descargas", "Pictures", "Imágenes", "Videos", "Music"]
    rutas = [casa / n for n in nombres] + [casa / "OneDrive" / n for n in nombres]
    vistas, out = set(), []
    for r in rutas:
        try:
            real = r.resolve()
        except OSError:
            continue
        if r.exists() and real not in vistas:
            vistas.add(real)
            out.append(r)
    return out


def _sin_tildes(t: str) -> str:
    import unicodedata

    return unicodedata.normalize("NFKD", t.lower()).encode("ascii", "ignore").decode()


@herramienta("buscar_archivos", "Busca archivos en el PC por nombre (escritorio, documentos, descargas, imágenes, videos, música). "
             "Úsala antes de enviar un archivo si no sabes la ruta exacta.",
             {"nombre": P("string", "Palabras del nombre, ej. 'factura enero' o 'pdf contrato'"),
              "carpeta": P("string", "Carpeta concreta donde buscar (opcional)")}, ["nombre"], solo_pc=True)
async def buscar_archivos(ctx, nombre, carpeta=None):
    palabras = [_sin_tildes(p) for p in re.findall(r"[\w.]+", nombre) if len(p) > 1]
    raices = [Path(os.path.expandvars(os.path.expanduser(carpeta)))] if carpeta else _carpetas_usuario()
    saltar = {".venv", "node_modules", "__pycache__", ".git", "AppData", "site-packages"}

    def buscar():
        hallados = []
        for raiz in raices:
            for actual, dirs, ficheros in os.walk(raiz):
                dirs[:] = [d for d in dirs if d not in saltar and not d.startswith(".")]
                if len(Path(actual).relative_to(raiz).parts) > 6:
                    dirs[:] = []
                for f in ficheros:
                    n = _sin_tildes(f)
                    if all(p in n for p in palabras):
                        ruta = Path(actual) / f
                        try:
                            st = ruta.stat()
                        except OSError:
                            continue
                        hallados.append((st.st_mtime, ruta, st.st_size))
                if len(hallados) > 200:
                    break
        return sorted(hallados, reverse=True)[:20]

    res = await asyncio.to_thread(buscar)
    if not res:
        return f"No encontré archivos con «{nombre}» en las carpetas del usuario."
    return "\n".join(f"- {r} ({_bytes(t)}, {datetime.fromtimestamp(m):%d/%m/%Y})" for m, r, t in res)


@herramienta("enviar_archivo", "Envía un archivo del PC a las pantallas del usuario (aparece un botón para descargarlo en el celular). "
             "Para 'tráeme / mándame / pásame el archivo X'.",
             {"ruta": P("string", "Ruta completa del archivo en el PC (búscala antes con buscar_archivos)")}, ["ruta"], solo_pc=True)
async def enviar_archivo(ctx, ruta):
    from . import archivos
    from .enlace import ENLACE, cabeceras, hub

    p = Path(os.path.expandvars(os.path.expanduser(ruta)))
    if not p.is_file():
        return f"No existe el archivo {p}."
    secretos = (p.name.lower() in (".env", "id_rsa", "id_ed25519", "id_ecdsa", "authorized_keys", "known_hosts")
                or p.suffix.lower() in (".pem", ".key", ".kdbx", ".pfx", ".p12") or ".ssh" in [x.lower() for x in p.parts])
    if secretos:
        return "Ese archivo contiene llaves o contraseñas: por seguridad no lo envío a ningún dispositivo."
    if p.stat().st_size > archivos.MAXIMO:
        return f"El archivo pesa {_bytes(p.stat().st_size)}; el máximo es {_bytes(archivos.MAXIMO)}."
    if ENLACE.activo:  # el PC enlazado lo sube al cerebro, que avisa a todas las pantallas
        with open(p, "rb") as f:
            r = await ENLACE.http.post(hub() + "/api/archivos", headers=cabeceras(), timeout=600,
                                       files={"archivo": (p.name, f)}, data={"origen": "PC"})
        if r.status_code != 200:
            return f"No pude subir el archivo: {r.text[:200]}"
        a = r.json()
    else:
        a = await asyncio.to_thread(archivos.guardar_ruta, p, "PC")
        if ctx.difundir:
            await ctx.difundir({"type": "archivo", **a})
    return f"Listo: «{a['nombre']}» ({_bytes(a['tamano'])}) ya está disponible para descargar en tus pantallas."


@herramienta("archivos_recibidos", "Lista los archivos compartidos recientemente entre tus dispositivos (subidos desde el celular o enviados desde el PC).")
async def archivos_recibidos(ctx):
    from . import archivos

    lista = archivos.lista()
    if not lista:
        try:
            from .enlace import ENLACE

            if ENLACE.conectado:
                lista = await ENLACE.pedir("GET", "/api/archivos")
        except Exception:  # noqa: BLE001
            pass
    if not lista:
        return "No hay archivos compartidos en los últimos 7 días."
    return "\n".join(f"- id={a['id']} · {a['nombre']} ({_bytes(a['tamano'])}, desde {a['origen']}, {a['cuando']})" for a in lista[:20])


@herramienta("guardar_en_pc", "Guarda en el PC un archivo compartido (por ejemplo una foto enviada desde el celular).",
             {"archivo": P("string", "id o nombre del archivo (de archivos_recibidos); vacío = el último recibido"),
              "carpeta": P("string", "Dónde guardarlo: Escritorio, Descargas, Documentos, Imágenes o una ruta (por defecto Descargas)")},
             solo_pc=True)
async def guardar_en_pc(ctx, archivo=None, carpeta="Descargas"):
    from .enlace import ENLACE, cabeceras, hub

    if not ENLACE.activo:
        return "Este PC no está enlazado al cerebro; los archivos del celular llegan a través del servidor."
    lista = await ENLACE.pedir("GET", "/api/archivos")
    if not lista:
        return "No hay archivos compartidos recientes."
    elegido = lista[0]
    if archivo:
        clave = _sin_tildes(archivo)
        elegido = next((a for a in lista if a["id"] == archivo), None) or next((a for a in lista if clave in _sin_tildes(a["nombre"])), None)
        if not elegido:
            return f"No encontré «{archivo}» entre los archivos recientes."
    casa = Path.home()
    alias = {"escritorio": "Desktop", "descargas": "Downloads", "documentos": "Documents", "imagenes": "Pictures", "imágenes": "Pictures", "fotos": "Pictures"}
    destino = casa / alias.get(_sin_tildes(carpeta or "descargas"), "") if _sin_tildes(carpeta or "descargas") in alias else Path(os.path.expandvars(os.path.expanduser(carpeta)))
    destino.mkdir(parents=True, exist_ok=True)
    final = destino / elegido["nombre"]
    n = 1
    while final.exists():  # nunca sobrescribe
        final = destino / f"{Path(elegido['nombre']).stem} ({n}){Path(elegido['nombre']).suffix}"
        n += 1
    r = await ENLACE.http.get(hub() + elegido["url"], headers=cabeceras(), timeout=600)
    if r.status_code != 200:
        return "No pude descargar el archivo del cerebro."
    final.write_bytes(r.content)
    return f"Guardé «{elegido['nombre']}» en {final}."


# herramientas que viven en su propio módulo (se registran al importarlas)
from . import analisis, claude_code, habilidades, impresion3d, modos, notion, vigilancias, voz  # noqa: E402,F401
