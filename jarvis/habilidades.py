"""Habilidades aprendidas: lo que Claude Code resolvió una vez queda como un script que Maicol repite solo.

Cada habilidad es un archivo en data/habilidades/ (.ps1 o .py). La primera línea es un comentario con lo que hace:
    # Prende el sistema smaky pruebas (servidor y WhatsApp)
Recibe sus parámetros como argumentos ($args en PowerShell, sys.argv en Python). Maicol las ve en sus instrucciones
y las usa con usar_habilidad; si una falla, se lo pasa a Claude para que la arregle.
"""
import asyncio
import re
import subprocess
import sys

from . import config
from .herramientas import COMANDO_DELICADO, P, PERMISO, herramienta

CARPETA = config.DATOS / "habilidades"
TIPOS = {".ps1", ".py"}


def todas() -> dict[str, dict]:
    """nombre -> {ruta, desc}"""
    out = {}
    for f in sorted(CARPETA.glob("*")) if CARPETA.is_dir() else []:
        if f.suffix.lower() not in TIPOS:
            continue
        try:
            primera = f.read_text(encoding="utf-8", errors="ignore").lstrip("﻿").splitlines()[0]
        except (OSError, IndexError):
            primera = ""
        out[f.stem] = {"ruta": f, "desc": re.sub(r"^\s*#\s*", "", primera).strip()[:200] or f.stem}
    return out


def instruccion() -> str:
    """Para las instrucciones de Maicol: lo que ya sabe hacer solo."""
    hab = todas()
    if not hab:
        return ""
    return ("\nHabilidades que ya aprendiste (úsalas con usar_habilidad antes que pedírselo a Claude):\n"
            + "\n".join(f"- {n}: {h['desc']}" for n, h in list(hab.items())[:40]))


def _delicada(a) -> bool:
    """Pide permiso solo si el script hace algo delicado (borrar, matar procesos, instalar…)."""
    h = todas().get(str(a.get("nombre", "")))
    if not h:
        return False
    return bool(COMANDO_DELICADO.search(h["ruta"].read_text(encoding="utf-8", errors="ignore")))


PERMISO["usar_habilidad"] = _delicada


def _correr(ruta, argumentos: list[str], segundos: int) -> str:
    if ruta.suffix.lower() == ".py":
        cmd = [sys.executable, str(ruta), *argumentos]
    else:
        cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ruta), *argumentos]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=segundos,
                       cwd=str(ruta.parent), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    salida = (r.stdout or "") + (f"\n[error] {r.stderr}" if r.stderr.strip() else "")
    estado = "terminó bien" if r.returncode == 0 else f"FALLÓ (código {r.returncode})"
    return f"La habilidad {estado}.\n{salida.strip()[:6000]}"


@herramienta("usar_habilidad", "Ejecuta una habilidad que ya aprendiste (están en tus instrucciones). Si falla, pásale el error a "
             "Claude con hablar_con_claude para que la arregle.",
             {"nombre": P("string", "Nombre exacto de la habilidad"),
              "argumentos": P("array", "Parámetros, si la habilidad los necesita", items={"type": "string"})},
             ["nombre"], peligrosa=True, solo_pc=True, timeout=600)
async def usar_habilidad(ctx, nombre, argumentos=None):
    h = todas().get(str(nombre))
    if not h:
        return f"No tengo una habilidad llamada «{nombre}». Las que sé: {', '.join(todas()) or 'ninguna todavía'}."
    if isinstance(argumentos, str):
        argumentos = [argumentos]
    try:
        return await asyncio.to_thread(_correr, h["ruta"], [str(a) for a in argumentos or []], 300)
    except subprocess.TimeoutExpired:
        return "La habilidad tardó más de 5 minutos y la detuve."
    except OSError as e:
        return f"No pude ejecutar la habilidad: {e}"
