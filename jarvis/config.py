"""Configuración central de JARVIS. Todo sale del archivo .env (ver .env.example)."""
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
WEB = RAIZ / "web"


def recargar_env():
    load_dotenv(RAIZ / ".env", override=True)


recargar_env()


def env(clave: str, defecto: str = "") -> str:
    v = os.getenv(clave)
    return v.strip() if v and v.strip() else defecto


def env_lista(clave: str) -> list[str]:
    return [x.strip() for x in env(clave).split(",") if x.strip()]


DATOS = Path(env("JARVIS_DATA", str(RAIZ / "data")))
DATOS.mkdir(parents=True, exist_ok=True)

HOST = env("JARVIS_HOST", "127.0.0.1")
PUERTO = int(env("JARVIS_PUERTO", "8765"))
ES_WINDOWS = sys.platform == "win32"
EN_DOCKER = Path("/.dockerenv").exists()


def nombre_asistente() -> str:
    return env("JARVIS_NOMBRE", "JARVIS")


def usuario() -> str:
    return env("USUARIO_NOMBRE", "")


def tratamiento() -> str:
    return env("USUARIO_TRATAMIENTO", "")


def voz() -> str:
    return env("VOZ", "es-CO-GonzaloNeural")


def voz_tono() -> str:
    return env("VOZ_TONO", "+0Hz")


def estrategia() -> str:
    return env("ESTRATEGIA", "equilibrio")
