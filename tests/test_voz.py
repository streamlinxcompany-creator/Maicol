"""Pruebas de cómo suena Maicol: texto corrido sin signos, siglas bien dichas y palabras que le enseñan.
Ejecutar: .venv\\Scripts\\python -m tests.test_voz
"""
import asyncio
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

from jarvis import config, voz
from jarvis import herramientas as h
from jarvis.herramientas import Contexto


def main():
    voz.PROPIAS = Path(tempfile.mkdtemp()) / "pronunciacion.json"

    t = voz.limpiar("¿Listo, señor? Ya le pongo la canción. ¡Qué nota!")
    assert t == "Listo señor. Ya le pongo la canción. Qué nota", t
    print("✓ la voz sigue derecho: sin comas ni ¿? ¡!, con un punto para respirar entre frases")

    t = voz.limpiar("Lo revisé, señor... y está peor de lo que pensaba, pero tiene arreglo, eso sí, cuesta.")
    assert t == "Lo revisé señor… y está peor de lo que pensaba, pero tiene arreglo, eso sí cuesta", t
    print("✓ las pausas que suman se quedan: «…» para el suspenso y la coma antes de un giro («, pero»)")

    t = voz.limpiar("Son 3,5 millones, o sea 1.000 dólares… al 20%.")
    assert t == "Son tres millones quinientos mil, o sea mil dólares… al veinte por ciento", t
    print("✓ los números se dicen en palabras sin dañarse («3,5 millones», «1.000») y el % se dice")

    t = voz.limpiar("Le pongo un DJ en YouTube Music con AC/DC, no en el pc ni en la PC; ok?")
    assert "diyei" in t and "yutub miúsic" in t and "ei si di si" in t and "pecé" in t and "okey" in t, t
    assert "pc ni" in t, "las siglas solo cambian en MAYÚSCULAS (pc en minúscula se deja)"
    print("✓ siglas y marcas como suenan: DJ → diyei, YouTube Music → yutub miúsic, AC/DC → ei si di si")

    eventos = []

    async def difundir(ev):
        eventos.append(ev)

    ctx = Contexto(router=None, memoria=None, difundir=difundir)
    asyncio.run(voz.ensenar_pronunciacion(ctx, "Feid", "feid"))
    asyncio.run(voz.ensenar_pronunciacion(ctx, "Maicol", "máicol"))
    assert "máicol" in voz.limpiar("Soy Maicol y me gusta Feid") and eventos[-1] == {"type": "pronunciacion"}
    asyncio.run(voz.ensenar_pronunciacion(ctx, "DJ", ""))
    assert "DJ" in voz.limpiar("un DJ") and "DJ" not in voz.diccionario(), "vacío quita también la de fábrica"
    assert "ensenar_pronunciacion" in h.relevantes("DJ se dice diyei")
    print("✓ «DJ se dice diyei»: aprende, quita y avisa a los paneles para que suenen igual")

    assert h.atajo("maicol saca analíticas") == ("saca_analiticas", {})
    assert h.atajo("Saca las analiticas") == ("saca_analiticas", {})
    assert h.atajo("ponme una canción") is None
    print("✓ «saca analíticas» abre el tablero siempre, sin depender de que la IA se acuerde")

    casos = {
        "un costo entre 20 y 24 k": "un costo entre veinte y veinticuatro mil",
        "la caja (~1.4 k) y 17 k por pollo": "la caja (unos mil cuatrocientos) y diecisiete mil por pollo",
        "valen $800 a $1.400": "valen ochocientos pesos a mil cuatrocientos pesos",
        "sale a $25.000": "sale a veinticinco mil pesos",
        "capital de 3,5 M": "capital de tres millones quinientos mil",
        "de 11:00 am a 3:00 pm": "de once de la mañana a tres de la tarde",
        "1.260.000 pesos": "un millón doscientos sesenta mil pesos",
        "21 pollos, 1 pollo y 101 noches": "veintiún pollos, un pollo y ciento un noches",
        "llega a 63": "llega a sesenta y tres", "20 x 63": "veinte por sesenta y tres", "3,05": "tres coma cero cinco",
        "$2 millones": "dos millones de pesos", "la t22": "la t22", "mide 5 m": "mide cinco m", "1 k": "mil",
        "llame al 3001234567890": "llame al 3001234567890",
    }
    for dicho, esperado in casos.items():
        assert voz.numeros(dicho) == esperado, (dicho, voz.numeros(dicho))
    assert "mil cuatrocientos" in voz.limpiar("Cuesta 1.400.") and "cada uno" in voz.limpiar("$800 c/u")
    nodo = shutil.which("node")
    if nodo:  # el panel (web/numeros.js) tiene que decir exactamente lo mismo
        js = ("const {numeros}=require(process.argv[1]);const c=JSON.parse(process.argv[2]);"
              "console.log(JSON.stringify(Object.keys(c).map(numeros)))")
        salida = subprocess.run([nodo, "-e", js, str(config.WEB / "numeros.js"), json.dumps(casos)],
                                capture_output=True, text=True, encoding="utf-8", timeout=20)
        assert json.loads(salida.stdout) == list(casos.values()), salida.stdout + salida.stderr
    print("✓ números en palabras: «1.4 k» → mil cuatrocientos, «$25.000» → veinticinco mil pesos (igual en el panel)")
    print("\nTodas las pruebas pasaron.")


if __name__ == "__main__":
    main()
