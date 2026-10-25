"""Avisos al celular aunque Maicol esté cerrado (notificaciones push de la app web).

El celular se suscribe una vez (⚙ → 🔔 Avisos en este celular) y desde ahí el PC le puede mandar notificaciones:
lo urgente que nota estando usted lejos del PC, cuando Claude termina, los recordatorios. Las llaves (VAPID) se crean
solas la primera vez y se guardan en data/. En iPhone hace falta tener Maicol agregado a la pantalla de inicio.
"""
import base64
import json
import logging
import time

from . import config

log = logging.getLogger("jarvis.push")
LLAVE = config.DATOS / "vapid_privada.pem"
SUSCRIPCIONES = config.DATOS / "push.json"


def _vapid():
    from py_vapid import Vapid

    if not LLAVE.exists():
        v = Vapid()
        v.generate_keys()
        v.save_key(str(LLAVE))
    return Vapid.from_file(str(LLAVE))


def clave_publica() -> str:
    from cryptography.hazmat.primitives import serialization

    crudo = _vapid().public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return base64.urlsafe_b64encode(crudo).decode().rstrip("=")


def _todas() -> list[dict]:
    try:
        return json.loads(SUSCRIPCIONES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _guardar(subs: list[dict]):
    SUSCRIPCIONES.write_text(json.dumps(subs, ensure_ascii=False, indent=1), encoding="utf-8")


def suscribir(sub: dict, dispositivo: str) -> int:
    if not sub.get("endpoint"):
        raise ValueError("Suscripción inválida")
    subs = [s for s in _todas() if s["sub"].get("endpoint") != sub["endpoint"]]
    subs.append({"sub": sub, "dispositivo": dispositivo[:80], "desde": time.strftime("%Y-%m-%d %H:%M")})
    _guardar(subs)
    return len(subs)


def hay_suscritos() -> bool:
    return bool(_todas())


def enviar(texto: str, titulo: str = "Maicol", url: str = "/", etiqueta: str | None = None) -> int:
    """Manda la notificación a todos los celulares suscritos (bloqueante: llamar en un hilo). Devuelve cuántos la recibieron."""
    subs = _todas()
    if not subs:
        return 0
    from pywebpush import WebPushException, webpush

    datos = json.dumps({"titulo": titulo, "texto": texto[:300], "url": url, "etiqueta": etiqueta or titulo}, ensure_ascii=False)
    # el «sub» identifica al remitente ante Google/Apple: la dirección del propio Maicol
    remitente = config.env("JARVIS_CELULAR_URL") or "https://maicol.local"
    vivas, enviadas = [], 0
    for s in subs:
        try:
            webpush(subscription_info=s["sub"], data=datos, vapid_private_key=str(LLAVE),
                    vapid_claims={"sub": remitente}, ttl=3600, timeout=10)
            enviadas += 1
            vivas.append(s)
        except WebPushException as e:
            codigo = getattr(e.response, "status_code", None)
            if codigo not in (404, 410):  # 404/410: el celular canceló la suscripción; se olvida
                vivas.append(s)
            log.warning("push a %s: %s", s.get("dispositivo"), e)
        except Exception as e:  # noqa: BLE001
            vivas.append(s)
            log.warning("push a %s: %s", s.get("dispositivo"), e)
    if len(vivas) != len(subs):
        _guardar(vivas)
    return enviadas
