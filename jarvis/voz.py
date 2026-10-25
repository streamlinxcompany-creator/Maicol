"""Texto a voz con las voces neuronales gratuitas de Microsoft Edge (edge-tts)."""
import hashlib
import re
from collections import OrderedDict

import edge_tts

from . import config

_cache: OrderedDict[str, bytes] = OrderedDict()
_voces: list | None = None


def limpiar(texto: str) -> str:
    t = re.sub(r"```.*?```", " ", texto, flags=re.S)
    t = re.sub(r"`([^`]*)`", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)
    t = re.sub(r"https?://(?:www\.)?([^/\s]+)\S*", r"\1", t)
    t = numeros(t)
    t = re.sub(r"[*_#>|~]", "", t)
    # igual que pulirVoz en web/app.js: «;», «:», guiones y paréntesis como comas; sin espacios raros ni emojis
    t = re.sub(r"[   ​]", " ", t)
    t = re.sub(r"[\U0001F000-\U0001FAFF☀-➿]️?", "", t)
    t = re.sub(r"\s*[;:]\s+", ", ", t)
    t = re.sub(r"\s+[—–-]\s+", ", ", t)
    t = re.sub(r"\s*\(([^)]*)\)", r", \1,", t)
    t = re.sub(r"\.{3,}", "…", t)  # los puntos suspensivos se quedan: son la pausa de suspenso (ver fluir)
    t = re.sub(r"(\s*,\s*)+(?!\d)", ", ", t)  # «3,5» no se separa
    t = re.sub(r",\s*([.!?])", r"\1", t)
    t = re.sub(r"\s+", " ", t)
    return fluir(pronunciar(t.strip(" ,")))


# ---------- cómo suena: palabras que la voz lee mal y texto corrido (igual que en web/app.js) ----------
BASE = config.WEB / "pronunciacion.json"  # las de fábrica
PROPIAS = config.DATOS / "pronunciacion.json"  # las que el señor le enseña («DJ se dice diyei»)
_reglas: dict = {"fecha": None, "lista": []}


def diccionario() -> dict:
    """Las dos juntas (las propias mandan). También lo usa el panel (/api/pronunciacion): suena igual en todas partes."""
    import json

    datos = {}
    for ruta in (BASE, PROPIAS):
        try:
            datos.update(json.loads(ruta.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            continue
    return {k: v for k, v in datos.items() if v}  # vacío = quitada


def _fecha(ruta) -> float:
    try:
        return ruta.stat().st_mtime
    except OSError:
        return 0.0


def _reglas_pronunciacion() -> list[tuple[re.Pattern, str]]:
    """«DJ» -> «diyei». Las siglas en MAYÚSCULAS solo cambian escritas así; las demás, como vengan."""
    fecha = (_fecha(BASE), _fecha(PROPIAS))
    if _reglas["fecha"] != fecha:
        datos = diccionario()
        lista = []
        for palabra in sorted(datos, key=len, reverse=True):  # «YouTube Music» antes que «YouTube»
            sigla = palabra == palabra.upper() and any(c.isalpha() for c in palabra)
            lista.append((re.compile(rf"(?<!\w){re.escape(palabra)}(?!\w)", 0 if sigla else re.I), datos[palabra]))
        _reglas.update(fecha=fecha, lista=lista)
    return _reglas["lista"]


def pronunciar(t: str) -> str:
    for patron, dicho in _reglas_pronunciacion():
        t = patron.sub(dicho, t)
    return t.replace("%", " por ciento").replace(" & ", " y ")


# ---------- los números en palabras (igual que web/numeros.js) ----------
# «1.400» -> «mil cuatrocientos», «24 k» -> «veinticuatro mil», «$25.000» -> «veinticinco mil pesos», «11:00 am» ->
# «once de la mañana». Sin esto la voz lee «1.4 k» o «1.400» cifra por cifra. En pantalla quedan los números.
_UNIDADES = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce", "trece",
             "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte", "veintiuno", "veintidós",
             "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve"]
_DECENAS = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"]
_CENTENAS = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos", "setecientos",
             "ochocientos", "novecientos"]


def _menor_mil(n: int) -> str:
    if n == 100:
        return "cien"
    c, r = divmod(n, 100)
    s = _CENTENAS[c]
    if r:
        s += (" " if s else "") + (_UNIDADES[r] if r < 30 else _DECENAS[r // 10] + (f" y {_UNIDADES[r % 10]}" if r % 10 else ""))
    return s


def _corto(s: str) -> str:
    """«un»/«ún» delante de mil, millones o una cosa («veintiún pollos», «un millón»)."""
    return re.sub(r"uno$", "un", re.sub(r"veintiuno$", "veintiún", s))


def en_palabras(n: float, apocope: bool = False) -> str | None:
    if n < 0 or n >= 1e12:
        return None
    n = int(n)
    if n == 0:
        return "cero"
    millones, miles, resto = n // 1_000_000, n % 1_000_000 // 1000, n % 1000
    partes = []
    if millones:
        partes.append("un millón" if millones == 1 else _corto(en_palabras(millones)) + " millones")
    if miles:
        partes.append("mil" if miles == 1 else _corto(_menor_mil(miles)) + " mil")
    if resto:
        partes.append(_corto(_menor_mil(resto)) if apocope else _menor_mil(resto))
    return " ".join(partes)


_NUM = r"\d{1,3}(?:\.\d{3})+(?:,\d+)?|\d+(?:[.,]\d+)?"
_MILES = re.compile(r"\d{1,3}(?:\.\d{3})+")
_ESCALA = {"k": 1e3, "mil": 1e3, "m": 1e6, "mm": 1e6, "millon": 1e6, "millón": 1e6, "millones": 1e6}


def _valor(s: str) -> float:
    if re.fullmatch(r"\d{1,3}(\.\d{3})+(,\d+)?", s):
        return float(s.replace(".", "").replace(",", "."))
    return float(s.replace(",", "."))


def _leer(s: str, apocope: bool) -> str:
    if _MILES.fullmatch(s) or s.isdigit():
        return s if len(s.replace(".", "")) > 12 else en_palabras(_valor(s), apocope)  # un teléfono: como venga
    m = re.fullmatch(r"(\d+(?:\.\d{3})*)[.,](\d+)", s)
    if not m:
        return s
    entero, dec = m.group(1).replace(".", ""), m.group(2)
    ceros = len(dec) - len(dec.lstrip("0"))
    return f"{en_palabras(int(entero))} coma {'cero ' * ceros}{en_palabras(int(dec)) if dec.strip('0') else ''}".strip()


def _hora(h: str, mi: str | None) -> str:
    hora, minutos = int(h), int(mi or 0)
    return ("una" if hora == 1 else en_palabras(hora)) + (f" y {en_palabras(minutos)}" if minutos else "")


_CANTIDAD = re.compile(rf"(\$\s*)?({_NUM})(?:\s*(k|K|mil|MM|M|millones|millón|millon)(?![^\W_]))?"
                       r"(\s+(?:pesos|COP|cop|d[oó]lares|USD|usd)(?![^\W\d_]))?")
_NO_ES_COSA = re.compile(r"\s+(?:de|a|y|o|e|u|por|entre|al|más|menos|que)(?![^\W\d_])", re.I)


def numeros(t: str) -> str:
    def am_pm(m):
        hora = int(m.group(1))
        cuando = "de la mañana" if m.group(3).lower() == "a" else ("de la tarde" if hora == 12 or hora < 7 else "de la noche")
        return f"{_hora(m.group(1), m.group(2))} {cuando}"

    t = re.sub(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?(?![^\W\d_])", am_pm, t, flags=re.I)
    t = re.sub(r"\b(\d{1,2}):(\d{2})\b", lambda m: _hora(m.group(1), m.group(2)), t)
    t = re.sub(r"~\s*(?=\d)", "unos ", t)
    t = re.sub(r"(\d)\s*[x×]\s*(?=\d)", r"\1 por ", t)  # «20 x 63» -> «veinte por sesenta y tres»

    def cantidad(m):
        todo, peso, num, escala, moneda = m.group(0), m.group(1), m.group(2), m.group(3), m.group(4)
        antes = m.string[m.start() - 1] if m.start() else ""
        if antes and (antes.isalnum() or antes in ".,"):
            return todo  # parte de una palabra o de otro número («t22»)
        despues = m.string[m.end():]
        cosa = bool(re.match(r"\s+[^\W\d_]", despues)) and not _NO_ES_COSA.match(despues)
        factor = _ESCALA[escala.lower()] if escala else 1
        if factor > 1 and not (_MILES.fullmatch(num) or num.isdigit()):
            dicho = en_palabras(round(_valor(num) * factor), True)  # «1.4 k» = 1.400, «3,5 M» = 3.500.000
        elif factor > 1:
            v = _valor(num)
            if factor == 1e3:
                dicho = "mil" if v == 1 else f"{_leer(num, True)} mil"
            else:
                dicho = "un millón" if v == 1 else f"{_leer(num, True)} millones"
        else:
            dicho = _leer(num, cosa or bool(peso) or bool(moneda))
        if dicho is None or dicho == num:
            return todo
        pesos = " pesos" if peso and not moneda and not re.match(r"\s+pesos", despues, re.I) else ""
        return dicho + pesos + (moneda or "")

    t = _CANTIDAD.sub(cantidad, t)
    return t.replace(" millones pesos", " millones de pesos").replace(" millón pesos", " millón de pesos")


GIROS = r"pero|aunque|sino|eso sí|eso si|o sea|así que|asi que|mientras que"


def fluir(t: str) -> str:
    """Para que la voz siga derecho sin pausas ni cambios de tono a cada coma (en pantalla los signos sí van),
    pero con las pausas que suman: el punto entre frases (respirar), «…» (suspenso) y la coma antes de un giro
    («…, pero»). ¿? y ¡! no cambian el tono a mitad de texto. Los números no se tocan: «3,5» y «1.000» siguen enteros."""
    t = re.sub(r"[¿¡«»\"“”]", "", t)
    t = re.sub(r"(?<=\w)'(?=\s|$)", "", t)  # «pa'» -> «pa»
    t = re.sub(rf",\s+(?=(?:{GIROS})\b)", "\x00", t, flags=re.I)  # la coma del giro se aparta un momento
    t = re.sub(r"[,;:]+(?=\s|$)", "", t)
    t = re.sub(r"[.!?]+(?=\s+\S)", ".", t)  # entre frases: un punto (pausa corta, sin tono de pregunta)
    t = re.sub(r"(?<![.…])[.!?]+$", "", t)  # al final no hace falta
    t = t.replace("\x00", ", ")
    return re.sub(r"\s+", " ", t).strip()


async def sintetizar(texto: str, voz: str | None = None, velocidad: str = "+0%") -> bytes:
    texto = limpiar(texto)
    if not texto:
        return b""
    voz = voz or config.voz()
    tono = config.voz_tono()
    clave = hashlib.md5(f"{voz}|{velocidad}|{tono}|{texto}".encode()).hexdigest()
    if clave in _cache:
        _cache.move_to_end(clave)
        return _cache[clave]
    audio = bytearray()
    async for trozo in edge_tts.Communicate(texto, voz, rate=velocidad, pitch=tono).stream():
        if trozo["type"] == "audio":
            audio.extend(trozo["data"])
    datos = bytes(audio)
    _cache[clave] = datos
    while len(_cache) > 200:
        _cache.popitem(last=False)
    return datos


async def voces() -> list[dict]:
    global _voces
    if _voces is None:
        todas = await edge_tts.list_voices()
        _voces = sorted(({"id": v["ShortName"], "genero": v["Gender"], "region": v["Locale"]} for v in todas if v["Locale"].startswith("es-") or "Multilingual" in v["ShortName"]),
                        key=lambda v: v["id"])
    return _voces


from .herramientas import P, herramienta  # noqa: E402


@herramienta("ensenar_pronunciacion", "Guarda cómo debes pronunciar en voz alta una palabra, sigla o nombre («DJ se dice diyei», "
             "«pronuncia Feid como feid», «no digas así X»). Para quitar una, 'como' vacío.",
             {"palabra": P("string", "Como se escribe, ej. 'DJ'"), "como": P("string", "Como se dice, escrito como suena, ej. 'diyei'")},
             ["palabra"])
async def ensenar_pronunciacion(ctx, palabra, como=""):
    import json

    palabra = palabra.strip()
    if not palabra:
        return "¿Qué palabra?"
    try:
        propias = json.loads(PROPIAS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        propias = {}
    propias[palabra] = como.strip()  # vacío también tapa la de fábrica
    PROPIAS.write_text(json.dumps(propias, ensure_ascii=False, indent=2), encoding="utf-8")
    if ctx.difundir:
        await ctx.difundir({"type": "pronunciacion"})  # los paneles abiertos recargan el diccionario
    return f"Listo: «{palabra}» ahora se dice «{como.strip()}»." if como.strip() else f"Listo: «{palabra}» se lee normal."
