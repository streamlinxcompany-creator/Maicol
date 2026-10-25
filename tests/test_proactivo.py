"""Pruebas de Maicol proactivo: cuándo habla, cuándo se calla y cómo aprende a no ser cansón (sin gastar IAs).
Ejecutar: .venv\\Scripts\\python -m tests.test_proactivo
"""
import asyncio
import tempfile
import time
from pathlib import Path

from jarvis import proactivo as p


class RouterFalso:
    def __init__(self, respuesta):
        self.respuesta = respuesta

    async def completar(self, mensajes, nivel):
        return self.respuesta


def main():
    from jarvis import modos

    p.ESTADO = Path(tempfile.mkdtemp()) / "proactivo.json"
    modos.activo = lambda: {"nombre": "noche"}
    v = p.Vigilante()
    assert not v.puede("disco", 2, False, True) and v.puede("bateria", 3, False, True), "de noche solo lo urgente"
    modos.activo = lambda: None
    assert v.puede("disco", 2, ocupado=False, presente=True)
    assert not v.puede("disco", 2, ocupado=True, presente=True), "en plena conversación no interrumpe"
    assert not v.puede("pausa", 1, ocupado=False, presente=False), "si no hay nadie, no habla al aire"
    assert v.puede("bateria", 3, ocupado=True, presente=False), "lo urgente sí"
    v.dicho("disco", "El disco va lleno, ¿le libero espacio?")
    assert not v.puede("ram", 2, False, True), "un comentario cada 25 min como mucho"
    v.estado["ultimo"] = time.time() - p.ENTRE_COMENTARIOS - 1
    assert v.puede("ram", 2, False, True) and not v.puede("disco", 2, False, True), "cada tema tiene su descanso"
    print("✓ habla poco: nunca en plena conversación, ni al aire, ni dos seguidos, ni el mismo tema otra vez")

    v.respuesta_usuario("no me avises eso, ya sé")
    assert v._tema("disco")["factor"] == 4, "«no me avises eso» lo calla mucho más tiempo"
    v.dicho("cpu", "El PC va a full, ¿qué tiene abierto?")
    v.ultimo_dicho["cuando"] -= 400
    v.revisar_ignorado()
    assert v._tema("cpu")["factor"] == 2, "si lo ignora, ese tema espera el doble"
    v.dicho("ram", "¿Le cierro Chrome que está comiendo RAM?")
    v._tema("ram")["factor"] = 4
    v.respuesta_usuario("sí, ciérrelo")
    assert v._tema("ram")["factor"] == 2, "si le sirvió, se vuelve a soltar"
    assert p.Vigilante()._tema("disco")["factor"] == 4, "lo aprendido queda guardado"
    print("✓ aprende: si lo callas o lo ignoras se modera; si le sirve, vuelve a avisar")

    assert asyncio.run(v.decidir(RouterFalso('{"hablar": false, "frase": ""}'), "CPU al 91%", 1, "")) is None
    assert asyncio.run(v.decidir(RouterFalso('ok {"hablar": true, "frase": "¿Le cierro eso?"}'), "x", 2, "")) == "¿Le cierro eso?"
    assert asyncio.run(v.decidir(RouterFalso("no es json"), "Batería al 9%", 3, "")) == "Batería al 9%", "lo urgente se dice aunque falle la IA"
    print("✓ la IA decide si vale la pena hablar; lo urgente no se pierde")

    w = p.ventana_activa()
    assert "app" in w and w["quieto"] >= 0
    assert isinstance(p.VIGILANTE.observar(), list)
    print(f"✓ ve el PC de verdad (en primer plano ahora: {w['app'] or '?'})")
    print("\nTodas las pruebas pasaron.")


if __name__ == "__main__":
    main()
