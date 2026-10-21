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
    t = re.sub(r"[*_#>|~]", "", t)
    t = re.sub(r"\s+", " ", t)
    return t.strip()


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
