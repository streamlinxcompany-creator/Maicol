"""Pruebas de las rutinas aprendidas y de los avisos al celular (sin mandar nada de verdad).
Ejecutar: .venv\\Scripts\\python -m tests.test_rutinas
"""
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from jarvis import avisos_push, rutinas


def main():
    rutinas.ARCHIVO = Path(tempfile.mkdtemp()) / "rutinas.json"
    r = rutinas.Rutinas()
    # un martes cualquiera a las 9:05; los 5 días de semana anteriores abrió Spotify entre 8:55 y 9:15
    hoy = datetime(2026, 10, 20, 9, 5)
    dia = hoy - timedelta(days=1)
    puestos = 0
    while puestos < 5:
        if dia.weekday() < 5:
            r.registrar("Spotify", ahora=(dia.replace(hour=8, minute=55) + timedelta(minutes=puestos * 5)).timestamp())
            r.registrar("excel", ahora=dia.replace(hour=15, minute=0).timestamp())
            puestos += 1
        dia -= timedelta(days=1)
    r.registrar("explorer", ahora=hoy.timestamp())  # el sistema no cuenta
    r.visto.clear()  # el vigilante «recién arrancado»: hoy no ha visto nada
    notas = r.sugerencias(hoy.timestamp())
    assert [n[0] for n in notas] == ["rutina:spotify"], notas
    assert "9:05" in notas[0][2]
    print("✓ aprende que suele abrir Spotify a eso de las 9 entre semana (y no ofrece Excel a esa hora)")

    assert not r.sugerencias(hoy.replace(hour=11).timestamp()), "fuera de la hora de costumbre no ofrece"
    assert not r.sugerencias((hoy + timedelta(days=5)).timestamp()), "el domingo no cuenta lo de entre semana"
    r.registrar("spotify", ahora=hoy.timestamp())
    assert not r.sugerencias(hoy.timestamp() + 60), "si hoy ya lo abrió, no lo ofrece"
    print("✓ solo a su hora, separando entre semana y fin de semana, y nunca si ya lo abrió")

    # avisos al celular: suscribir, mandar a todos y olvidar los que el celular canceló
    avisos_push.SUSCRIPCIONES = Path(tempfile.mkdtemp()) / "push.json"
    avisos_push.LLAVE = Path(tempfile.mkdtemp()) / "vapid.pem"
    assert len(avisos_push.clave_publica()) == 87
    avisos_push.suscribir({"endpoint": "https://push/a"}, "un celular Android")
    avisos_push.suscribir({"endpoint": "https://push/b"}, "un iPhone")
    avisos_push.suscribir({"endpoint": "https://push/a"}, "un celular Android")
    import pywebpush

    enviados = []

    class Respuesta:
        status_code = 410

    def falso(subscription_info, data, **kw):
        if subscription_info["endpoint"].endswith("b"):
            raise pywebpush.WebPushException("cancelada", response=Respuesta())
        enviados.append(data)

    pywebpush.webpush = falso
    assert avisos_push.enviar("Claude terminó", "Maicol") == 1 and "Claude terminó" in enviados[0]
    assert [s["dispositivo"] for s in avisos_push._todas()] == ["un celular Android"]
    print("✓ avisos al celular: sin duplicados y olvida los celulares que cancelaron")
    print("\nTodas las pruebas pasaron.")


if __name__ == "__main__":
    main()
