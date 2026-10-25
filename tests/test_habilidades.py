"""Pruebas de las habilidades aprendidas (scripts que Claude deja y Maicol repite solo).
Ejecutar: .venv\\Scripts\\python -m tests.test_habilidades
"""
import asyncio
import tempfile
from pathlib import Path

from jarvis import habilidades as hb
from jarvis import herramientas as h


def main():
    hb.CARPETA = Path(tempfile.mkdtemp())
    (hb.CARPETA / "saludar.ps1").write_text('# Saluda a quien le digan\nWrite-Output "hola $($args[0])"', encoding="utf-8")
    (hb.CARPETA / "limpiar.ps1").write_text("# Borra temporales\nRemove-Item $env:TEMP\\x -Recurse", encoding="utf-8")
    (hb.CARPETA / "sumar.py").write_text("# Suma dos números\nimport sys\nprint(int(sys.argv[1]) + int(sys.argv[2]))", encoding="utf-8")
    (hb.CARPETA / "notas.txt").write_text("no es una habilidad", encoding="utf-8")

    assert set(hb.todas()) == {"saludar", "limpiar", "sumar"}
    assert "- saludar: Saluda a quien le digan" in hb.instruccion()
    print("✓ Maicol ve sus habilidades (nombre y qué hace) en sus instrucciones")
    assert "hola Juan" in asyncio.run(hb.usar_habilidad(None, "saludar", ["Juan"]))
    assert "5" in asyncio.run(hb.usar_habilidad(None, "sumar", ["2", "3"]))
    assert "No tengo una habilidad" in asyncio.run(hb.usar_habilidad(None, "volar"))
    print("✓ ejecuta habilidades de PowerShell y Python con sus argumentos")
    assert not h.necesita_permiso("usar_habilidad", {"nombre": "saludar"})
    assert h.necesita_permiso("usar_habilidad", {"nombre": "limpiar"})
    print("✓ solo pide permiso si la habilidad borra, mata procesos o instala")
    for n in ("hablar_con_claude", "ejecutar_comando", "usar_habilidad"):
        assert n in h.relevantes("prende el sistema de pruebas"), f"{n} debe estar siempre a mano"
    print("✓ Claude, los comandos y las habilidades están siempre a mano (no solo si dices «Claude»)")
    print("\nTodas las pruebas pasaron.")


if __name__ == "__main__":
    main()
