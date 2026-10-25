"""Pruebas de «avíseme al celular cuando…» (sin mandar avisos de verdad).
Ejecutar: .venv\\Scripts\\python -m tests.test_vigilancias
"""
import asyncio
import tempfile
from pathlib import Path

from jarvis import avisos_push, vigilancias as vg
from jarvis import herramientas as h
from jarvis.herramientas import Contexto


def main():
    base = Path(tempfile.mkdtemp())
    vg.ARCHIVO = base / "vigilancias.json"
    avisos_push.SUSCRIPCIONES = base / "push.json"
    ctx = Contexto.__new__(Contexto)

    assert "no está abierto" in asyncio.run(vg.avisarme_cuando(ctx, "programa_se_cierra", "Se cerró", "programa_que_no_existe"))
    assert "solo puede leer" in asyncio.run(vg.avisarme_cuando(ctx, "condicion", "x", "Remove-Item C:\\algo"))
    print("✓ no vigila cosas sin sentido ni condiciones que cambian el PC")

    descargas = base / "Descargas"
    descargas.mkdir()
    (descargas / "viejo.pdf").write_text("x")
    r = asyncio.run(vg.avisarme_cuando(ctx, "descarga_termina", "Ya bajó, señor", str(descargas)))
    assert "quedé vigilando" in r and "Avisos en este celular" in r, r
    v = vg._todas()[0]
    assert not vg.cumplida(v), "nada nuevo todavía"
    (descargas / "juego.zip.crdownload").write_text("x")
    assert not vg.cumplida(v), "a medio bajar no cuenta"
    (descargas / "juego.zip.crdownload").rename(descargas / "juego.zip")
    assert vg.cumplida(v)
    print("✓ descarga: espera a que no quede nada a medio bajar y haya algo nuevo")

    avisos = []

    async def avisar(t):
        avisos.append(t)

    vg.AVISAR = avisar
    (base / "listo.txt").write_text("ok")
    asyncio.run(vg.avisarme_cuando(ctx, "archivo_aparece", "Apareció el archivo", str(base / "listo.txt")))

    async def una_vuelta():
        vg.asyncio.sleep = lambda s: original(0)
        tarea = asyncio.create_task(vg.vigilar())
        await original(0.5)
        tarea.cancel()

    original = asyncio.sleep
    asyncio.run(una_vuelta())
    vg.asyncio.sleep = original
    assert "Ya bajó, señor" in avisos and "Apareció el archivo" in avisos and not vg._todas(), avisos
    print("✓ avisa una sola vez cuando se cumple y la vigilancia se borra")

    for n in ("enviar_al_telefono", "avisarme_cuando"):
        assert n in h.relevantes("cuando pase algo en el pc mándeme una notificación al celular")
    print("✓ «mándeme una notificación cuando…» le da a Maicol las herramientas de avisar")
    print("\nTodas las pruebas pasaron.")


if __name__ == "__main__":
    main()
