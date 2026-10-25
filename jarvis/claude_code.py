"""Claude Code como compañero de JARVIS para las tareas que lo superan (programar, revisar un proyecto, investigar a
fondo, diseñar algo complejo). No usa la API: ejecuta la línea de comandos de Claude Code con TU cuenta de Claude
(el plan Pro comparte su límite con el chat).

Instalar una vez (PowerShell):  irm https://claude.ai/install.ps1 | iex   → luego  claude  e inicia sesión.

- hablar_con_claude: la conversación de siempre con Claude, desde donde estés («dile a Claude que…»). Claude actúa en
  el PC (edita archivos, ejecuta comandos) y, si algo es irreversible, primero pregunta.
- preguntar_a_claude: una consulta aparte que solo lee (modo «plan»: no cambia nada).
Si Claude responde rápido, Maicol te dice la respuesta ahí mismo; si tarda, sigue en segundo plano y te avisa al terminar.
"""
import asyncio
import json
import logging
import os
import re
import shutil
import time
import uuid
from pathlib import Path

from . import config
from .herramientas import P, _sin_tildes, herramienta

log = logging.getLogger("jarvis.claude")
CARPETA = config.DATOS / "claude"
AVISAR = None  # async fn(texto): lo conecta el servidor al arrancar (todas las pantallas + Telegram)
DIFUNDIR = None  # async fn(evento): el panel de Claude de cada pantalla se actualiza en vivo
TAREAS: dict[str, asyncio.Task] = {}
PROCESOS: dict[str, asyncio.subprocess.Process] = {}
_SESION = {"ok": False, "hasta": 0.0}
LIMITE = 45 * 60  # una tarea no puede pasar de 45 min
ESPERA = 45  # segundos que Maicol espera la respuesta para decírtela en la misma conversación
INSTRUCCIONES = (
    "Eres Claude Code y trabajas en el PC con Windows del usuario. Tú NO eres Maicol ni JARVIS: Maicol es su asistente de voz "
    "y solo te reenvía lo que él dice. El usuario casi nunca está frente al PC (te habla desde el celular), así que haz tú el "
    "trabajo en el PC en vez de pedirle que lo haga; puedes moverte por cualquier carpeta de su usuario. Si algo debe quedar "
    "corriendo (un servidor, un programa), arráncalo desacoplado (p. ej. Start-Process) para que siga al terminar tu turno. "
    "Antes de algo irreversible (borrar, desinstalar, formatear, git push o reset, apagar el PC) no lo hagas: explica qué harías "
    "y pide que te lo confirme en su próximo mensaje. Si para lograrlo hace falta instalar algo o investigar cómo, hazlo. "
    "Si resolviste algo que el usuario probablemente vuelva a pedir y se puede repetir con un script, enséñaselo a Maicol: "
    f"guárdalo como habilidad en «{config.DATOS / 'habilidades'}» (un .ps1 o .py con nombre_en_minusculas_con_guiones_bajos), "
    "cuya PRIMERA línea sea un comentario «# qué hace, en una frase», que reciba sus datos como argumentos, que deje "
    "desacoplado lo que deba quedar corriendo y termine rápido; pruébala y dilo en tu respuesta. "
    "Responde en español, breve: se lo leerán en voz alta. "
    "Al final escribe una línea que empiece por «RESUMEN:» con 1-2 frases para decírselo en voz alta.")
ADMIN = (" Corres como administrador de Windows (Maicol arranca así con la tarea «Maicol Nucleo»): puedes usar bcdedit, "
         "diskpart, servicios, el registro de todo el equipo o instalar programas directamente, sin Start-Process -Verb RunAs "
         "(esa ventana de permiso nadie la puede aceptar desde el celular). Con más razón, lo irreversible primero se confirma.")
PROHIBIDOS = ["Bash(rm -rf:*)", "Bash(git push:*)", "Bash(git reset --hard:*)", "Bash(shutdown:*)", "Bash(format:*)"]


def ejecutable() -> str | None:
    """La línea de comandos instalada (la copia de la app de escritorio no sirve: no tiene la sesión iniciada)."""
    for c in (shutil.which("claude"), str(Path.home() / ".local" / "bin" / "claude.exe"), str(Path.home() / ".local" / "bin" / "claude")):
        if c and Path(c).is_file():
            return c
    return None


def comando() -> list[str]:
    """Cómo lanzarlo. La copia de npm es un .cmd y pasa por cmd.exe: un «&», «|» o comillas en el mensaje lo cortaban
    o lo convertían en otro comando. Por eso se llama a node directamente con el cli.js del paquete."""
    exe = ejecutable()
    if exe and exe.lower().endswith(".cmd"):
        cli = Path(exe).parent / "node_modules" / "@anthropic-ai" / "claude-code" / "cli.js"
        node = shutil.which("node")
        if cli.is_file() and node:
            return [node, str(cli)]
    return [exe]


def es_administrador() -> bool:
    if os.name != "nt":
        return hasattr(os, "geteuid") and os.geteuid() == 0
    import ctypes

    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


SIN_INSTALAR = ("Claude Code no está instalado en el PC. Instálalo una vez en PowerShell con "
                "«irm https://claude.ai/install.ps1 | iex», abre una terminal nueva, escribe «claude» e inicia sesión con tu cuenta.")
SIN_SESION = ("Claude Code no tiene la sesión iniciada en el PC, así que no le pasé nada. Ábrelo en el panel de Claude "
              "(botón «Iniciar sesión en el PC») o escribe «claude auth login» en una terminal del PC, una sola vez.")


async def sesion_iniciada() -> bool | None:
    """¿La línea de comandos tiene la sesión iniciada? (None = no se pudo saber). Un «sí» se recuerda 30 min."""
    if _SESION["ok"] and time.time() < _SESION["hasta"]:
        return True
    if not ejecutable():
        return False
    try:
        proc = await asyncio.create_subprocess_exec(*comando(), "auth", "status", stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL)
        salida, _ = await asyncio.wait_for(proc.communicate(), 30)
        ok = bool(json.loads(salida.decode("utf-8", errors="ignore")).get("loggedIn"))
    except (OSError, ValueError, asyncio.TimeoutError):
        return None
    _SESION.update(ok=ok, hasta=time.time() + 1800)
    return ok


async def listo_para_trabajar() -> str | None:
    """None si Claude puede recibir tareas; si no, el motivo para decírselo al usuario."""
    if not ejecutable():
        return SIN_INSTALAR
    if await sesion_iniciada() is False:
        return SIN_SESION
    return None


def abrir_inicio_sesion():
    """Abre en el PC una terminal con «claude auth login» (el navegador del PC termina el inicio de sesión)."""
    import subprocess

    exe = ejecutable()
    if not exe:
        raise RuntimeError(SIN_INSTALAR)
    _SESION.update(ok=False, hasta=0)
    subprocess.Popen(["cmd", "/c", "start", "Iniciar sesión en Claude", "cmd", "/k", exe, "auth", "login"],
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


def _carpeta(nombre: str | None) -> Path:
    """'jarvis', 'proyecto smurfit', una ruta… -> carpeta existente (por defecto el Escritorio)."""
    casa = Path.home()
    if not nombre:
        return casa / "Desktop"
    p = Path(os.path.expandvars(os.path.expanduser(nombre.strip('"'))))
    if p.is_absolute() and p.is_dir():  # una ruta relativa dependería de dónde corre JARVIS
        return p
    clave = _sin_tildes(nombre)
    palabras = [w for w in re.findall(r"\w+", clave) if w not in ("proyecto", "carpeta", "el", "la", "de", "del", "mi")]
    mejores = []
    for raiz in (casa / "Desktop", casa / "Documents", casa / "Desktop" / "proyectos"):
        if not raiz.is_dir():
            continue
        for actual, dirs, _ in os.walk(raiz):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in ("node_modules", ".venv", "__pycache__", "data")]
            if len(Path(actual).relative_to(raiz).parts) >= 4:
                dirs[:] = []
            for d in dirs:
                n = _sin_tildes(d)
                if palabras and all(w in n for w in palabras):
                    mejores.append((len(n), Path(actual) / d))
    if not mejores:
        raise ValueError(f"No encuentro la carpeta «{nombre}» en el Escritorio ni en Documentos.")
    return min(mejores)[1]


def _guardar(t: dict):
    CARPETA.mkdir(parents=True, exist_ok=True)
    (CARPETA / f"{t['id']}.json").write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")


def _todas() -> list[dict]:
    if not CARPETA.exists():
        return []
    out = []
    for f in CARPETA.glob("*.json"):
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return sorted(out, key=lambda t: t["creada"], reverse=True)


def _resumen(texto: str) -> str:
    m = re.search(r"RESUMEN:\s*(.+)", texto or "")
    if m:
        return m.group(1).strip()[:400]
    limpio = " ".join((texto or "").split())
    return limpio[:300] + ("…" if len(limpio) > 300 else "")


HERRAMIENTAS_LEGIBLES = {"Read": "Leyendo", "Edit": "Editando", "MultiEdit": "Editando", "Write": "Escribiendo", "Bash": "Ejecutando",
                         "Grep": "Buscando", "Glob": "Buscando archivos", "WebFetch": "Leyendo la web", "WebSearch": "Buscando en la web",
                         "TodoWrite": "Organizando los pasos", "Task": "Delegando una parte", "ExitPlanMode": "Proponiendo un plan"}


def _paso(bloque: dict) -> str | None:
    """Un evento de Claude en una línea corta para seguirlo desde el celular: «Editando servidor.py»."""
    if bloque.get("type") == "text":
        texto = " ".join((bloque.get("text") or "").split())
        return f"💬 {texto[:180]}" if texto else None
    if bloque.get("type") != "tool_use":
        return None
    nombre, e = bloque.get("name", ""), bloque.get("input") or {}
    que = e.get("file_path") or e.get("path") or e.get("pattern") or e.get("command") or e.get("url") or e.get("query") or e.get("description") or ""
    que = Path(que).name if (e.get("file_path") or e.get("path")) else " ".join(str(que).split())
    return f"🔧 {HERRAMIENTAS_LEGIBLES.get(nombre, nombre)} {que[:90]}".rstrip()


async def _avisar_cambio(t: dict):
    if DIFUNDIR:
        try:
            await DIFUNDIR({"type": "claude", "id": t["id"], "estado": t["estado"], "paso": (t.get("pasos") or [None])[-1]})
        except Exception:  # noqa: BLE001
            pass


async def _correr(t: dict):
    instrucciones = INSTRUCCIONES + (ADMIN if es_administrador() else "")
    # «hacer»: edita archivos y ejecuta comandos en esa carpeta (quien lo pide ya lo autorizó); «consultar»: solo lee
    args = [*comando(), "-p", t["pedido"], "--output-format", "stream-json", "--verbose", "--append-system-prompt", instrucciones,
            "--permission-mode", "acceptEdits" if t["modo"] == "hacer" else "plan"]
    if t["modo"] == "hacer":
        args += ["--allowedTools", "Bash", "--disallowedTools", *PROHIBIDOS, "--add-dir", str(Path.home())]
    if t.get("sesion"):
        args += ["--resume", t["sesion"]]
        if t.get("bifurcar"):  # un chat tuyo de la app: se sigue en una copia, sin pisar el chat que tienes abierto
            args += ["--fork-session"]
    t.update(estado="trabajando", inicio=time.time(), pasos=[])
    _guardar(t)
    await _avisar_cambio(t)
    r, proc = {}, None

    async def leer():
        ultimo_aviso = 0.0
        async for crudo in proc.stdout:
            try:
                ev = json.loads(crudo.decode("utf-8", errors="ignore"))
            except ValueError:
                continue
            if ev.get("type") == "result":
                r.update(ev)
            elif ev.get("type") == "assistant":
                nuevos = [p for p in map(_paso, (ev.get("message") or {}).get("content") or []) if p]
                if nuevos:
                    t["pasos"] = (t["pasos"] + nuevos)[-40:]
                    if time.time() - ultimo_aviso > 1.5:  # el panel se refresca sin inundar la red
                        ultimo_aviso = time.time()
                        _guardar(t)
                        await _avisar_cambio(t)
            if ev.get("session_id") and not t.get("sesion_nueva"):
                t["sesion_nueva"] = ev["session_id"]

    try:
        proc = await asyncio.create_subprocess_exec(*args, cwd=t["carpeta"], stdout=asyncio.subprocess.PIPE,
                                                    stderr=asyncio.subprocess.PIPE, stdin=asyncio.subprocess.DEVNULL,
                                                    limit=16 * 1024 * 1024)
        PROCESOS[t["id"]] = proc
        await asyncio.wait_for(asyncio.gather(leer(), proc.wait()), LIMITE)
        error = (await proc.stderr.read()).decode("utf-8", errors="ignore")
        if not r:
            r = {"is_error": True, "result": error[-800:] or "Claude terminó sin responder."}
        texto = r.get("result") or ""
        t.update(estado="error" if r.get("is_error") else "lista", respuesta=texto,
                 sesion=r.get("session_id") or t.get("sesion_nueva") or t.get("sesion"),
                 negados=[d.get("tool_name") for d in r.get("permission_denials") or []], fin=time.time())
        if "Not logged in" in texto or "/login" in texto:
            _SESION.update(ok=False, hasta=0)
            t["respuesta"] = SIN_SESION
    except asyncio.TimeoutError:
        proc.kill()
        t.update(estado="error", respuesta=f"Claude tardó más de {LIMITE // 60} min y detuve la tarea.", fin=time.time())
    except asyncio.CancelledError:
        if proc and proc.returncode is None:
            proc.kill()
        t.update(estado="detenida", respuesta="La detuviste antes de que terminara.", fin=time.time())
        _guardar(t)
        await _avisar_cambio(t)
        raise
    except Exception as e:  # noqa: BLE001
        t.update(estado="error", respuesta=f"No pude ejecutar Claude Code: {e}", fin=time.time())
    finally:
        PROCESOS.pop(t["id"], None)
        TAREAS.pop(t["id"], None)
    _guardar(t)
    await _avisar_cambio(t)
    if t.get("esperando"):  # Maicol sigue esperando la respuesta: él mismo te la dice
        return
    minutos = max(1, round((t["fin"] - t["inicio"]) / 60))
    if t["estado"] == "lista":
        aviso = f"🤖 Claude terminó «{t['titulo']}» ({minutos} min): {_resumen(t['respuesta'])}"
        if t.get("negados"):
            aviso += f" (No pudo usar: {', '.join(sorted(set(t['negados'])))}; pídeme repetir con permiso si hace falta.)"
    else:
        aviso = f"🤖 Claude no pudo con «{t['titulo']}»: {_resumen(t['respuesta'])}"
    if AVISAR:
        await AVISAR(aviso)


def _lanzar(pedido: str, carpeta: str | None, modo: str, sesion: str | None = None, titulo: str | None = None,
            bifurcar: bool = False) -> dict:
    if not ejecutable():
        raise RuntimeError(SIN_INSTALAR)
    t = {"id": uuid.uuid4().hex[:6], "titulo": titulo or " ".join(pedido.split())[:60], "pedido": pedido, "modo": modo,
         "carpeta": str(_carpeta(carpeta)), "sesion": sesion, "creada": time.time(), "estado": "en cola", "bifurcar": bifurcar}
    _guardar(t)
    TAREAS[t["id"]] = asyncio.create_task(_correr(t))
    return t


# ---------- tus chats de Claude Code (los de la app de Claude en el PC) ----------
PROYECTOS = Path.home() / ".claude" / "projects"
_CHATS: dict[str, tuple[float, str | None, str | None]] = {}  # ruta -> (fecha, título, carpeta): los archivos pesan megas


def _leer_chat(f: Path) -> tuple[str | None, str | None]:
    """Título y carpeta del chat. La carpeta es la que da nombre a su archivo (Claude solo lo retoma desde ahí):
    un chat puede empezar en una carpeta temporal y moverse a su proyecto, o entrar a subcarpetas."""
    titulo, carpetas = None, []
    with f.open(encoding="utf-8", errors="ignore") as h:
        for linea in h:
            if '"custom-title"' in linea or '"cwd"' in linea:
                try:
                    d = json.loads(linea)
                except ValueError:
                    continue
                titulo = d.get("customTitle") or titulo
                if d.get("cwd") and d["cwd"] not in carpetas:
                    carpetas.append(d["cwd"])
    propia = next((c for c in carpetas if re.sub(r"[^A-Za-z0-9]", "-", c) == f.parent.name), None)
    return titulo, propia or (carpetas[-1] if carpetas else None)


def chats_tuyos(cuantos: int = 10) -> list[dict]:
    """Tus chats con título (los que abriste en la app de Claude), el más reciente primero."""
    out = []
    for f in PROYECTOS.glob("*/*.jsonl") if PROYECTOS.is_dir() else []:
        try:
            fecha = f.stat().st_mtime
            if _CHATS.get(str(f), (None,))[0] != fecha:
                _CHATS[str(f)] = (fecha, *_leer_chat(f))
        except OSError:
            continue
        _, titulo, carpeta = _CHATS[str(f)]
        if titulo and carpeta and Path(carpeta).is_dir():
            out.append({"id": f.stem, "titulo": titulo, "carpeta": carpeta, "cuando": fecha})
    return sorted(out, key=lambda c: c["cuando"], reverse=True)[:cuantos]


def _buscar_chat(nombre: str) -> dict | None:
    chats = chats_tuyos(30)
    if exacto := next((c for c in chats if c["id"] == nombre), None):
        return exacto
    palabras = [w for w in re.findall(r"\w+", _sin_tildes(nombre)) if w not in ("chat", "el", "la", "de", "del", "mi", "con", "sobre")]
    for c in chats:  # el más reciente que tenga todas las palabras en el título o en la carpeta
        donde = _sin_tildes(f"{c['titulo']} {Path(c['carpeta']).name}")
        if palabras and all(w in donde for w in palabras):
            return c
    return None


def _seguir_chat(chat: dict, mensaje: str, modo: str = "hacer") -> dict:
    return _lanzar(mensaje, chat["carpeta"], modo, sesion=chat["id"], titulo=f"💬 {chat['titulo']}", bifurcar=True)


def detener(ident: str) -> bool:
    tarea = TAREAS.get(ident)
    if not tarea:
        return False
    tarea.cancel()
    return True


def tareas(cuantas: int = 15) -> list[dict]:
    """Para el panel de Claude: las últimas conversaciones, la más reciente primero."""
    vivas = [{**t, "estado": "error", "respuesta": "Maicol se reinició mientras Claude trabajaba."}
             if t["estado"] in ("trabajando", "en cola") and t["id"] not in TAREAS else t for t in _todas()[:cuantas]]
    return vivas


async def desde_panel(texto: str, tarea: str | None, hacer: bool, carpeta: str | None, chat: str | None = None) -> dict:
    """Mensaje escrito o dictado en el panel de Claude: sigue la conversación elegida, uno de tus chats, o empieza una nueva."""
    problema = await listo_para_trabajar()
    if problema:
        raise RuntimeError(problema)
    modo = "hacer" if hacer else "consultar"
    if chat and not tarea:
        encontrado = await asyncio.to_thread(_buscar_chat, chat)
        if not encontrado:
            raise RuntimeError("No encontré ese chat de Claude.")
        return _seguir_chat(encontrado, texto, modo)
    previa = next((t for t in _todas() if t["id"] == tarea), None) if tarea else None
    if previa:
        if previa["id"] in TAREAS:
            raise RuntimeError("Claude todavía está trabajando en esa; espera a que termine o detenla.")
        base = previa["titulo"].removesuffix(" (seguimiento)")
        return _lanzar(texto, previa["carpeta"], modo, sesion=previa.get("sesion"), titulo=f"{base} (seguimiento)")
    return _lanzar(texto, carpeta or str(config.RAIZ), modo)


async def _respuesta(t: dict) -> str:
    """Espera un rato a Claude: si contesta a tiempo, Maicol le pasa la respuesta al usuario en la misma conversación;
    si no, Claude sigue en segundo plano y avisa al terminar."""
    tarea = TAREAS.get(t["id"])
    if tarea:
        t["esperando"] = True
        listo, _ = await asyncio.wait({tarea}, timeout=ESPERA)
        if not listo:
            t["esperando"] = False
            return (f"Claude sigue trabajando en eso (#{t['id']}, en {t['carpeta']}). Mientras tanto le vas contando en voz alta lo "
                    "que hace y al terminar le avisas con el resultado. Díselo al usuario en una frase (que va para largo y le "
                    "irás contando), sin inventar lo que Claude está haciendo.")
    if t["estado"] == "lista":
        texto = (t.get("respuesta") or "").strip()
        nota = (f"\n(No le dejaron usar: {', '.join(sorted(set(t['negados'])))}.)" if t.get("negados") else "")
        return (f"Claude respondió (esto lo dijo Claude, no tú: cuéntaselo al usuario con tus palabras, breve, sin inventar nada):\n"
                f"{texto[:3000]}{nota}")
    return f"Claude no pudo: {_resumen(t.get('respuesta', ''))}"


def _conversacion_actual() -> dict | None:
    """La última conversación con Claude que se puede continuar."""
    return next((t for t in _todas() if t.get("sesion")), None)


@herramienta("hablar_con_claude", "Habla con Claude Code (IA experta que trabaja en el PC con la cuenta de Claude del usuario) en su "
             "conversación de siempre: «dile a Claude que…», «pregúntale a Claude…», «que Claude arranque/arregle/programe…». "
             "Claude actúa en el PC (edita archivos, ejecuta comandos, arranca programas o servidores) y recuerda lo hablado antes. "
             "Si el usuario nombra uno de sus chats de Claude («en el chat de Maicol», «en el chat del POS»), pásalo en 'chat' y Claude "
             "sigue ese chat con todo su contexto. Pásale el mensaje casi literal. Úsala para cualquier orden o mensaje para Claude.",
             {"mensaje": P("string", "Lo que el usuario quiere decirle a Claude, casi literal y con el contexto necesario"),
              "chat": P("string", "Nombre o tema de un chat suyo de Claude para continuarlo, ej. 'Maicol', 'POS WhatsApp' (opcional)"),
              "carpeta": P("string", "Solo si el usuario nombra una carpeta o proyecto, ej. 'smaky', 'jarvis' (opcional)"),
              "nueva": P("boolean", "true solo si el usuario pide empezar una conversación nueva con Claude")},
             ["mensaje"], solo_pc=True)
async def hablar_con_claude(ctx, mensaje, carpeta=None, nueva=False, chat=None):
    if problema := await listo_para_trabajar():
        return problema
    if chat:
        encontrado = await asyncio.to_thread(_buscar_chat, str(chat))
        if not encontrado:
            nombres = ", ".join(f"«{c['titulo']}»" for c in await asyncio.to_thread(chats_tuyos, 8))
            return f"No encontré un chat de Claude llamado «{chat}». Los que tiene son: {nombres or 'ninguno'}. Pregúntale cuál."
        try:
            return await _respuesta(_seguir_chat(encontrado, mensaje))
        except Exception as e:  # noqa: BLE001
            return str(e)
    previa = None if nueva else _conversacion_actual()
    if previa and previa["id"] in TAREAS:
        return f"Claude todavía está con «{previa['titulo']}»; en cuanto termine te aviso y le paso lo siguiente."
    try:
        if previa and not carpeta:
            base = previa["titulo"].removesuffix(" (seguimiento)")
            t = _lanzar(mensaje, previa["carpeta"], "hacer", sesion=previa["sesion"], titulo=f"{base} (seguimiento)")
        else:  # otra carpeta = conversación nueva (Claude guarda sus conversaciones por carpeta)
            t = _lanzar(mensaje, carpeta, "hacer")
    except Exception as e:  # noqa: BLE001
        return str(e)
    return await _respuesta(t)


@herramienta("preguntar_a_claude", "Consulta aparte a Claude Code que solo lee y no cambia nada: revisar o explicar un proyecto o "
             "código, encontrar un error, planear algo difícil, investigar a fondo. Para órdenes o mensajes a Claude usa hablar_con_claude.",
             {"pedido": P("string", "La pregunta completa y con contexto, tal como se la explicarías a un experto"),
              "carpeta": P("string", "Carpeta o proyecto donde mirar, ej. 'jarvis', 'proyecto smurfit' (opcional)")},
             ["pedido"], solo_pc=True)
async def preguntar_a_claude(ctx, pedido, carpeta=None):
    if problema := await listo_para_trabajar():
        return problema
    try:
        t = _lanzar(pedido, carpeta, "consultar")
    except Exception as e:  # noqa: BLE001
        return str(e)
    return await _respuesta(t)


@herramienta("chats_de_claude", "Lista los chats que el usuario tiene con Claude Code (los de la app de Claude), por si pregunta "
             "cuáles tiene o hay que elegir uno para seguirlo con hablar_con_claude.", solo_pc=True)
async def chats_de_claude(ctx):
    chats = await asyncio.to_thread(chats_tuyos, 10)
    if not chats:
        return "No encontré chats de Claude con título en este PC."
    return "\n".join(f"- «{c['titulo']}» (carpeta {Path(c['carpeta']).name}, {time.strftime('%d/%m %H:%M', time.localtime(c['cuando']))})"
                     for c in chats)


@herramienta("abrir_panel_claude", "SOLO abre en la pantalla el panel de Claude Code (ver lo que hace Claude y sus respuestas); no le "
             "manda nada a Claude. Si además el usuario quiere decirle o preguntarle algo, llama también a hablar_con_claude.")
async def abrir_panel_claude(ctx):
    if ctx.difundir:
        await ctx.difundir({"type": "panel_claude"})
    return "Listo, abrí el panel de Claude en tu pantalla."


@herramienta("tareas_claude", "Muestra las tareas que JARVIS le pasó a Claude Code: cuáles siguen trabajando y la respuesta "
             "completa de las terminadas.", {"tarea": P("string", "id para ver una respuesta completa (opcional)")}, solo_pc=True)
async def tareas_claude(ctx, tarea=None):
    todas = _todas()
    if tarea:
        t = next((x for x in todas if x["id"] == tarea), None)
        return f"#{t['id']} «{t['titulo']}» ({t['estado']}):\n{t.get('respuesta') or '(sin respuesta aún)'}" if t else "No existe esa tarea."
    if not todas:
        return "Todavía no le he pasado tareas a Claude."
    lineas = []
    for t in todas[:8]:
        dur = f", {round(((t.get('fin') or time.time()) - t.get('inicio', t['creada'])) / 60)} min" if t.get("inicio") else ""
        lineas.append(f"- #{t['id']} «{t['titulo']}» — {t['estado']}{dur}" +
                      (f": {_resumen(t.get('respuesta', ''))}" if t["estado"] != "trabajando" else ""))
    return "\n".join(lineas)
