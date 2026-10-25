"""«Avíseme al celular cuando…»: Maicol vigila algo del PC y, cuando pasa, le manda la notificación.

Tipos: que un programa se cierre o se abra, que termine una descarga, que el PC deje de trabajar duro (un render, una
compilación), que aparezca un archivo, o una condición de PowerShell para lo demás. Se revisan cada 20 s, sobreviven a
un reinicio de Maicol y vencen solas a las 24 h (o cuando se cumplen).
"""
import asyncio
import json
import logging
import os
import subprocess
import time
import uuid
from pathlib import Path

import psutil

from . import config
from .herramientas import COMANDO_DELICADO, P, herramienta

log = logging.getLogger("jarvis.vigilancias")
ARCHIVO = config.DATOS / "vigilancias.json"
AVISAR = None  # async fn(texto): lo conecta el servidor (celular, pantallas y Telegram)
VENCE = 24 * 3600
TIPOS = {
    "programa_se_cierra": "valor = nombre del programa (ej. 'steam', 'blender', 'chrome')",
    "programa_se_abre": "valor = nombre del programa",
    "descarga_termina": "valor = carpeta (vacío = Descargas): sin archivos a medio bajar y con algo nuevo",
    "pc_se_desocupa": "valor = % de CPU por debajo del cual se considera desocupado (por defecto 20)",
    "archivo_aparece": "valor = ruta del archivo o carpeta",
    "condicion": "valor = comando de PowerShell de solo lectura que imprime True cuando hay que avisar",
}
A_MEDIAS = (".crdownload", ".part", ".partial", ".download", ".tmp", ".opdownload")


def _todas() -> list[dict]:
    try:
        return json.loads(ARCHIVO.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _guardar(lista: list[dict]):
    ARCHIVO.write_text(json.dumps(lista, ensure_ascii=False, indent=1), encoding="utf-8")


def _procesos(nombre: str) -> int:
    n = nombre.lower().removesuffix(".exe")
    return sum(1 for p in psutil.process_iter(["name"]) if (p.info["name"] or "").lower().removesuffix(".exe") == n)


def _descargas(valor: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(valor))) if valor else Path.home() / "Downloads"


def _foto_descargas(carpeta: Path) -> dict:
    try:
        return {f.name: f.stat().st_size for f in carpeta.iterdir() if f.is_file()}
    except OSError:
        return {}


def _ps(comando: str) -> str:
    r = subprocess.run(["powershell", "-NoProfile", "-Command", comando], capture_output=True, text=True, timeout=30,
                       encoding="utf-8", errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return (r.stdout or "").strip()


def preparar(tipo: str, valor: str) -> tuple[dict, str | None]:
    """Estado inicial de la vigilancia y, si no tiene sentido, por qué."""
    if tipo == "programa_se_cierra":
        return {}, None if _procesos(valor) else f"«{valor}» no está abierto ahora mismo, así que no hay nada que esperar."
    if tipo == "descarga_termina":
        carpeta = _descargas(valor)
        return ({"antes": _foto_descargas(carpeta)}, None) if carpeta.is_dir() else ({}, f"No encuentro la carpeta {carpeta}.")
    if tipo == "condicion" and COMANDO_DELICADO.search(valor):
        return {}, "Esa condición cambia cosas en el PC; para vigilar solo puede leer."
    return {}, None


def cumplida(v: dict) -> bool:
    tipo, valor, estado = v["tipo"], v.get("valor") or "", v.setdefault("estado", {})
    if tipo == "programa_se_cierra":
        return _procesos(valor) == 0
    if tipo == "programa_se_abre":
        return _procesos(valor) > 0
    if tipo == "archivo_aparece":
        return Path(os.path.expandvars(os.path.expanduser(valor))).exists()
    if tipo == "descarga_termina":
        ahora = _foto_descargas(_descargas(valor))
        a_medias = any(n.lower().endswith(A_MEDIAS) for n in ahora)
        nuevo = any(n not in estado.get("antes", {}) and not n.lower().endswith(A_MEDIAS) for n in ahora)
        return nuevo and not a_medias
    if tipo == "pc_se_desocupa":
        limite = float(valor or 20)
        estado["bajas"] = estado.get("bajas", 0) + 1 if psutil.cpu_percent(interval=1) < limite else 0
        return estado["bajas"] >= 3  # un minuto seguido desocupado (no un bajón de un segundo)
    if tipo == "condicion":
        return _ps(valor).lower() in ("true", "1", "si", "sí", "yes")
    return False


@herramienta("avisarme_cuando", "Vigila algo del PC y le manda una notificación al celular cuando pase: «avíseme cuando termine "
             "la descarga», «cuando se cierre el juego», «cuando el render acabe», «si aparece tal archivo». Úsala siempre que pida "
             "que le avise de algo que va a pasar en el PC. Tipos: " + "; ".join(f"{k} ({d})" for k, d in TIPOS.items()),
             {"tipo": P("string", "Qué vigilar", list(TIPOS)), "valor": P("string", "Ver la descripción de cada tipo"),
              "mensaje": P("string", "Qué decirle cuando pase, corto, ej. 'Ya terminó la descarga, señor'")},
             ["tipo", "mensaje"], solo_pc=True)
async def avisarme_cuando(ctx, tipo, mensaje, valor=""):
    if tipo not in TIPOS:
        return f"No sé vigilar «{tipo}». Puedo: {', '.join(TIPOS)}."
    estado, problema = await asyncio.to_thread(preparar, tipo, str(valor or ""))
    if problema:
        return problema
    lista = _todas()
    v = {"id": uuid.uuid4().hex[:5], "tipo": tipo, "valor": str(valor or ""), "mensaje": mensaje[:200],
         "creada": time.time(), "estado": estado}
    _guardar(lista + [v])
    from . import avisos_push

    nota = "" if avisos_push.hay_suscritos() else (" Ojo: el celular aún no tiene los avisos activados (⚙ → «🔔 Avisos en este "
                                                     "celular»); mientras tanto se lo digo en las pantallas.")
    return f"Listo, quedé vigilando (#{v['id']}): cuando pase le aviso al celular.{nota}"


@herramienta("vigilancias", "Muestra o cancela lo que Maicol está vigilando para avisar al celular.",
             {"cancelar": P("string", "id de la vigilancia a cancelar, o 'todas' (opcional)")}, solo_pc=True)
async def vigilancias(ctx, cancelar=None):
    lista = _todas()
    if cancelar:
        quedan = [] if cancelar == "todas" else [v for v in lista if v["id"] != cancelar]
        _guardar(quedan)
        return f"Cancelé {len(lista) - len(quedan)} vigilancia(s)."
    if not lista:
        return "No estoy vigilando nada ahora."
    return "\n".join(f"- #{v['id']}: {v['tipo']} {v.get('valor') or ''} → «{v['mensaje']}» (desde {time.strftime('%H:%M', time.localtime(v['creada']))})"
                     for v in lista)


async def vigilar():
    """Bucle de fondo: revisa cada 20 s y avisa (una sola vez) lo que se cumplió."""
    while True:
        await asyncio.sleep(20)
        lista = _todas()
        if not lista:
            continue
        quedan, cambios = [], False
        for v in lista:
            try:
                if await asyncio.to_thread(cumplida, v):
                    log.info("vigilancia cumplida: %s %s", v["tipo"], v.get("valor"))
                    if AVISAR:
                        await AVISAR(v["mensaje"])
                    cambios = True
                    continue
            except Exception as e:  # noqa: BLE001 - una condición rota no tumba las demás
                log.warning("vigilancia %s: %s", v["id"], e)
            if time.time() - v["creada"] > VENCE:
                cambios = True
                continue
            quedan.append(v)
        if cambios or any(v.get("estado") for v in quedan):
            # mientras se revisaba pudieron crear o cancelar vigilancias: se respetan
            actual = _todas()
            ids_actual, ids_leidos = {x["id"] for x in actual}, {v["id"] for v in lista}
            _guardar([v for v in quedan if v["id"] in ids_actual] + [x for x in actual if x["id"] not in ids_leidos])
