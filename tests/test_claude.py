"""Pruebas de la conexión con Claude Code usando una línea de comandos simulada (no gasta tu plan).
Ejecutar: .venv\\Scripts\\python -m tests.test_claude
"""
import asyncio
import json
import tempfile
from pathlib import Path

from jarvis import claude_code as c
from jarvis.herramientas import Contexto


def main():
    c.CARPETA = Path(tempfile.mkdtemp())
    c.ejecutable = lambda: "claude"
    llamadas, avisos = [], []
    demora = {"s": 0}

    async def con_sesion():
        return True

    class Salida:  # stream-json: una línea por evento
        def __init__(self):
            fin = {"type": "result", "is_error": False, "session_id": "ses-1", "permission_denials": [],
                   "result": "Listo.\nRESUMEN: Encontré dos errores y te dejé el plan."}
            paso = {"type": "assistant", "session_id": "ses-1",
                    "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "C:/x/router.py"}}]}}
            self.lineas = [json.dumps(paso).encode() + b"\n", json.dumps(fin).encode() + b"\n"]

        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(demora["s"])
            if not self.lineas:
                raise StopAsyncIteration
            return self.lineas.pop(0)

    class Proc:
        returncode = 0

        def __init__(self):
            self.stdout = Salida()
            self.stderr = asyncio.StreamReader()
            self.stderr.feed_eof()

        async def wait(self):
            return 0

    async def lanzar(*args, **kw):
        llamadas.append((args, kw["cwd"]))
        return Proc()

    async def avisar(texto):
        avisos.append(texto)

    c.asyncio.create_subprocess_exec, c.AVISAR, c.sesion_iniciada = lanzar, avisar, con_sesion
    ctx = Contexto.__new__(Contexto)

    async def flujo():
        r = await c.preguntar_a_claude(ctx, "revisa el router", str(Path.home()))
        args = llamadas[-1][0]
        assert args[args.index("--permission-mode") + 1] == "plan", "preguntar debe ser de solo lectura"
        assert "dos errores" in r and not avisos, "si responde a tiempo, Maicol lo dice y no hay aviso aparte"
        assert c._todas()[0]["pasos"] == ["🔧 Leyendo router.py"]
        r = await c.hablar_con_claude(ctx, "arréglalo")
        args = llamadas[-1][0]
        assert args[args.index("--resume") + 1] == "ses-1", "hablar sigue la conversación de siempre"
        assert args[args.index("--permission-mode") + 1] == "acceptEdits" and "Bash" in args
        assert "Claude respondió" in r
        r = await c.hablar_con_claude(ctx, "empecemos de cero", nueva=True)
        assert "--resume" not in llamadas[-1][0], "nueva = conversación nueva"
        # tus chats de la app: se encuentran por título y se siguen en una copia (--fork-session) en su carpeta
        c.PROYECTOS = Path(tempfile.mkdtemp())
        (c.PROYECTOS / "proy").mkdir()
        lineas = [{"type": "user", "cwd": str(Path.home())}, {"type": "custom-title", "customTitle": "Confirmación de Maicol"}]
        (c.PROYECTOS / "proy" / "abc-123.jsonl").write_text("\n".join(map(json.dumps, lineas)), encoding="utf-8")
        assert [x["titulo"] for x in c.chats_tuyos()] == ["Confirmación de Maicol"]
        r = await c.hablar_con_claude(ctx, "agrega un botón", chat="el chat de maicol")
        args = llamadas[-1][0]
        assert args[args.index("--resume") + 1] == "abc-123" and "--fork-session" in args and llamadas[-1][1] == str(Path.home())
        assert "Confirmación de Maicol" in await c.hablar_con_claude(ctx, "x", chat="no existe")
        c.ESPERA, demora["s"] = 0.05, 0.2
        r = await c.hablar_con_claude(ctx, "algo largo")
        assert "sigue trabajando" in r
        await asyncio.gather(*c.TAREAS.values())
        assert "dos errores" in avisos[-1], "si tarda, avisa al terminar"

    asyncio.run(flujo())
    print("✓ preguntar solo lee; hablar sigue la conversación y actúa; respuesta rápida en la misma charla, lenta con aviso")
    assert c._resumen("bla bla\nRESUMEN: corto y claro.") == "corto y claro."
    print("✓ resumen para leer en voz alta")
    c.ejecutable = lambda: None
    assert "no está instalado" in asyncio.run(c.hablar_con_claude(ctx, "hola"))
    print("✓ sin Claude Code instalado explica cómo instalarlo")
    print("\nTodas las pruebas pasaron.")


if __name__ == "__main__":
    main()
