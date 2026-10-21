"""Servidor web local: interfaz HUD, WebSocket de conversación y API."""
import asyncio
import os
import subprocess
import json
import logging
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime

from fastapi import Body, FastAPI, File, Form, Request, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

from . import config, herramientas, voz
from .agente import Agente
from .memoria import Memoria
from .proveedores import CATALOGO
from .router import Router, SinProveedores
from . import musica
from .silencio import SILENCIO
from .telegram import Telegram
from . import tecla
from .enlace import ENLACE
from .enlace import cabeceras as enlace_cabeceras
from .enlace import hub as ENLACE_URL
from .nodos import REGISTRO

log = logging.getLogger("jarvis")

router = Router()
memoria = Memoria()
agente = Agente(router, memoria)
telegram = Telegram(agente, router)
silencio = SILENCIO
clientes: set[WebSocket] = set()
PANTALLAS: dict = {}  # ws -> dispositivo (pc / celular / web)
SESION_WEB = "web"
# cambia cuando se actualiza la interfaz: las ventanas abiertas se recargan solas al reconectar
VERSION_WEB = str(int(max(f.stat().st_mtime for f in config.WEB.iterdir() if f.is_file())))


async def difundir_a_otros(origen, evento: dict):
    """Lo que se habla en un dispositivo aparece en vivo en los demás (PC <-> celular)."""
    datos = json.dumps(evento, ensure_ascii=False, default=str)
    for ws in list(clientes):
        if ws is origen:
            continue
        try:
            await ws.send_text(datos)
        except Exception:  # noqa: BLE001
            clientes.discard(ws)


async def difundir(evento: dict):
    datos = json.dumps(evento, ensure_ascii=False, default=str)
    for ws in list(clientes):
        try:
            await ws.send_text(datos)
        except Exception:  # noqa: BLE001
            clientes.discard(ws)


agente.difundir = difundir
agente.notificar = telegram.notificar if telegram.activo else None

_cambio_router = asyncio.Event()
router.oyentes.append(lambda: _cambio_router.set())


async def tarea_metricas():
    previo, t_previo = None, 0.0
    while True:
        if clientes:  # sin pantallas abiertas no se mide nada
            m = herramientas.metricas()
            ahora = time.time()
            if previo:
                dt = max(ahora - t_previo, 0.5)
                m["subida"] = (m["red_tx"] - previo["red_tx"]) / dt
                m["bajada"] = (m["red_rx"] - previo["red_rx"]) / dt
            previo, t_previo = m, ahora
            await difundir({"type": "sistema", **m})
        else:
            previo = None
        await asyncio.sleep(3)


async def tarea_router():
    while True:
        try:
            await asyncio.wait_for(_cambio_router.wait(), 5)
        except asyncio.TimeoutError:
            pass
        _cambio_router.clear()
        if clientes and not ENLACE.conectado:
            await difundir({"type": "ia", **router.estado()})


URL_APP = f"http://127.0.0.1:{config.PUERTO}"


def _traer_ventana() -> bool:
    """Pone delante la ventana de JARVIS (si existe)."""
    import ctypes

    u = ctypes.windll.user32
    hwnd = u.FindWindowW(None, "MAICOL")
    if not hwnd:
        return False
    if u.IsIconic(hwnd):
        u.ShowWindow(hwnd, 9)  # restaurar si estaba minimizada
    elif not u.IsWindowVisible(hwnd):
        u.ShowWindow(hwnd, 5)  # el panel lateral la esconde en vez de minimizarla
    u.keybd_event(0x12, 0, 0, 0)  # un Alt "fantasma" deja a Windows ceder el foco
    u.SetForegroundWindow(hwnd)
    u.keybd_event(0x12, 0, 2, 0)
    return True


async def tecla_pulsada():
    """Tecla rombo: si la interfaz está abierta, escucha (o calla); si no, la abre lista para escuchar."""
    log.info("tecla rombo pulsada (%d pantallas abiertas)", len(clientes))
    if clientes:
        await asyncio.to_thread(_traer_ventana)
        await difundir({"type": "tecla"})
        return
    from . import aperturas

    ruta = aperturas.ruta_navegador("edge") or aperturas.ruta_navegador("chrome")
    url = URL_APP + "/?tecla=1"
    if ruta:
        subprocess.Popen([ruta, f"--app={url}", "--window-size=1100,860", "--autoplay-policy=no-user-gesture-required"])
    else:
        os.startfile(url)


async def tarea_recordatorios():
    while True:
        for r in memoria.vencidos():
            memoria.completar_recordatorio(r["id"])
            texto = f"Recordatorio: {r['texto']}"
            await difundir({"type": "recordatorio", "texto": texto})
            if telegram.activo:
                await telegram.notificar("⏰ " + texto)
        await asyncio.sleep(3)


async def avisar_pantallas(texto: str):
    """Avisos de fondo (impresoras 3D, Claude Code…): en todas las pantallas (vía el cerebro si el PC está enlazado) y en Telegram."""
    try:
        if ENLACE.activo:
            await ENLACE.pedir("POST", "/api/anunciar", json={"texto": texto})
        else:
            await difundir({"type": "anuncio", "texto": texto})
    except Exception as e:  # noqa: BLE001
        log.warning("no pude anunciar «%s»: %s", texto, e)
    if telegram.activo:
        await telegram.notificar(texto)


@asynccontextmanager
async def vida(app):
    await router.iniciar()
    await silencio.recuperar_tras_cierre()
    tareas = [asyncio.create_task(t()) for t in (tarea_metricas, tarea_router, tarea_recordatorios, silencio.vigilante)]
    tareas.append(asyncio.create_task(tecla.escuchar(tecla_pulsada)))
    tareas.append(asyncio.create_task(musica.observador()))
    tareas.append(asyncio.create_task(ENLACE.mantener(router, memoria)))
    from . import claude_code

    claude_code.AVISAR = avisar_pantallas
    if not ENLACE.activo:  # el modo noche automático lo lleva quien conversa: el cerebro, o el PC si va solo
        from . import modos

        tareas.append(asyncio.create_task(modos.vigilante_noche(
            lambda: herramientas.Contexto(router=router, memoria=memoria, canal="auto", difundir=difundir))))
    if config.ES_WINDOWS:
        from . import impresion3d

        tareas.append(asyncio.create_task(impresion3d.vigilante(avisar_pantallas)))
    if telegram.activo:
        tareas.append(asyncio.create_task(telegram.bucle()))
    log.info("JARVIS listo en http://%s:%s", config.HOST, config.PUERTO)
    yield
    for t in tareas:
        t.cancel()
    await silencio.restaurar()
    router.guardar(True)


app = FastAPI(title="JARVIS", lifespan=vida)
app.mount("/static", StaticFiles(directory=config.WEB), name="static")

LOCALES = {"127.0.0.1", "::1", "localhost"}
CODIGOS: dict[str, float] = {}  # códigos de emparejamiento de un solo uso -> vencimiento
PASES = config.DATOS / "pases.json"  # sesiones de los dispositivos emparejados (no son la clave maestra)


def _pases() -> dict:
    try:
        return json.loads(PASES.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _pase_valido(pase: str | None) -> bool:
    return bool(pase) and pase in _pases()


def _nuevo_pase(quien: str) -> str:
    import secrets as _s

    todos = _pases()
    pase = _s.token_urlsafe(24)
    todos[pase] = {"dispositivo": quien[:80], "desde": time.strftime("%Y-%m-%d %H:%M")}
    PASES.write_text(json.dumps(todos, ensure_ascii=False, indent=1), encoding="utf-8")
    return pase


@app.middleware("http")
async def proteger(request: Request, siguiente):
    """Si JARVIS_CLAVE está definida, quien entre desde otra máquina (LAN, CasaOS) debe conocerla."""
    clave = config.env("JARVIS_CLAVE")
    origen = request.client.host if request.client else ""
    if not clave or origen in LOCALES or request.url.path.startswith("/static") or request.url.path in ("/entrar", "/manifest.webmanifest", "/sw.js"):
        return await siguiente(request)
    codigo = request.query_params.get("emparejar")
    if codigo and CODIGOS.pop(codigo, 0) > time.time():
        # el QR del celular trae un código de un solo uso; se cambia por una sesión guardada en el navegador
        resp = RedirectResponse("/", status_code=303)
        pase = _nuevo_pase(request.headers.get("user-agent", "dispositivo"))
        resp.set_cookie("jarvis_pase", pase, max_age=365 * 86400, httponly=True, secure=True, samesite="lax")
        return resp
    if (request.cookies.get("jarvis_clave") == clave or request.headers.get("x-jarvis-clave") == clave
            or _pase_valido(request.cookies.get("jarvis_pase"))):
        return await siguiente(request)
    return HTMLResponse("<body style='background:#02060d;color:#00e5ff;font-family:sans-serif;display:grid;place-items:center;height:100vh'>"
                        "<form method=post action=/entrar><h2>M.A.I.C.O.L. · acceso restringido</h2><input name=clave type=password autofocus placeholder='clave'> <button>Entrar</button></form></body>", 401)


def _ws_permitido(ws: WebSocket) -> bool:
    clave = config.env("JARVIS_CLAVE")
    origen = ws.client.host if ws.client else ""
    return (not clave or origen in LOCALES or ws.cookies.get("jarvis_clave") == clave
            or ws.headers.get("x-jarvis-clave") == clave or _pase_valido(ws.cookies.get("jarvis_pase")))


@app.get("/")
async def inicio():
    return FileResponse(config.WEB / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/manifest.webmanifest")
async def manifiesto():
    return FileResponse(config.WEB / "manifest.webmanifest", media_type="application/manifest+json")


@app.get("/sw.js")
async def service_worker():
    # en la raíz para que la app instalada controle todo el sitio
    return FileResponse(config.WEB / "sw.js", media_type="text/javascript",
                        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"})


@app.get("/api/ping")
async def ping():
    return {"ok": True}


@app.get("/api/estado")
async def estado():
    hora = datetime.now().hour
    datos = _estado_local(hora)
    if ENLACE.conectado:
        try:
            remoto = await ENLACE.pedir("GET", "/api/estado")
            datos.update(ia=remoto["ia"], recordatorios=remoto["recordatorios"], ia_local=remoto["ia_local"],
                         herramientas=remoto["herramientas"], cerebro=config.env("JARVIS_HUB"), nodos=remoto.get("nodos", []))
        except Exception as e:  # noqa: BLE001
            log.warning("estado del cerebro no disponible: %s: %s", type(e).__name__, e)
    return datos


def _estado_local(hora):
    return {
        "nombre": config.nombre_asistente(), "usuario": config.usuario(), "tratamiento": config.tratamiento(),
        "voz": config.voz(), "voz_tono": config.voz_tono(), "saludo": "Buenos días" if 5 <= hora < 12 else "Buenas tardes" if hora < 19 else "Buenas noches",
        "ia": router.estado(), "herramientas": len(herramientas.todas()), "telegram": telegram.activo,
        "recordatorios": memoria.recordatorios(), "pc": config.ES_WINDOWS, "version": VERSION_WEB,
        "ia_local": {"modo": config.env("IA_LOCAL_MODO", "auto"), "disponible": router.hay_local(), "cuotas_bajas": router.cuotas_bajas()},
        "nodos": REGISTRO.estado(), "cerebro": "este equipo", "pantallas": sorted(PANTALLAS.values()),
    }


@app.get("/api/historial")
async def historial():
    if ENLACE.conectado:
        try:
            return await ENLACE.pedir("GET", "/api/historial")
        except Exception:  # noqa: BLE001
            pass
    return memoria.historial_visible(SESION_WEB)


@app.get("/api/tts")
async def tts(texto: str, voz_id: str | None = None, velocidad: str = "+0%"):
    try:
        audio = await voz.sintetizar(texto, voz_id, velocidad)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, 503)
    return Response(audio, media_type="audio/mpeg", headers={"Cache-Control": "max-age=3600"})


@app.get("/api/voces")
async def voces():
    try:
        return await voz.voces()
    except Exception:  # noqa: BLE001
        return []


@app.post("/api/stt")
async def stt(audio: UploadFile = File(...)):
    try:
        return {"texto": await router.transcribir(await audio.read(), audio.filename or "audio.webm")}
    except SinProveedores as e:
        return JSONResponse({"error": str(e)}, 503)


@app.post("/api/estrategia/{nombre}")
async def cambiar_estrategia(nombre: str):
    if nombre in ("equilibrio", "calidad", "velocidad"):
        router.estrategia = nombre
        _cambio_router.set()
    return {"estrategia": router.estrategia}


@app.post("/api/recargar")
async def recargar():
    await router.iniciar()
    return router.estado()


EXTRA_EDITABLES = {"CLOUDFLARE_ACCOUNT_ID", "OLLAMA_URL", "TELEGRAM_TOKEN", "TELEGRAM_USUARIOS", "USUARIO_NOMBRE", "USUARIO_TRATAMIENTO",
                   "CIUDAD", "PAIS", "VOZ", "VOZ_TONO", "NOTION_TOKEN", "SPOTIFY_CLIENT_ID", "IA_LOCAL_MODO", "SERVIDOR_HOST", "SERVIDOR_USUARIO", "SERVIDOR_MAC", "JARVIS_NOMBRE"}


def _editables() -> set:
    return {p["llave"] for p in CATALOGO if p.get("llave")} | EXTRA_EDITABLES


@app.get("/api/llaves")
async def ver_llaves():
    """Qué variables están puestas (nunca devuelve el valor de una llave, solo los últimos 4 caracteres)."""
    out = {}
    for k in sorted(_editables()):
        v = config.env(k)
        secreto = k.endswith(("KEY", "TOKEN"))
        out[k] = ("…" + v[-4:] if secreto and v else v)
    return out


@app.post("/api/llaves")
async def poner_llaves(cambios: dict = Body(...)):
    permitidas = _editables()
    ruta = config.RAIZ / ".env"
    lineas = ruta.read_text(encoding="utf-8").splitlines() if ruta.exists() else []
    for k, v in cambios.items():
        if k not in permitidas:
            continue
        v = str(v).strip().replace("\n", "").replace("\r", "")
        nueva = f"{k}={v}"
        for i, l in enumerate(lineas):
            if l.split("=", 1)[0].strip() == k:
                lineas[i] = nueva
                break
        else:
            lineas.append(nueva)
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")
    await router.iniciar()
    return router.estado()


@app.post("/api/precalentar")
async def precalentar():
    """La interfaz avisa que el usuario empezó a hablar o escribir: la IA local se prepara."""
    if ENLACE.conectado:
        asyncio.create_task(ENLACE.pedir("POST", "/api/precalentar"))
        return {"ok": True}
    asyncio.create_task(agente.precalentar())
    return {"ok": True}


MARCO_LATERAL: dict = {}


@app.api_route("/api/lateral", methods=["GET", "POST"])
async def marco_lateral(request: Request):
    """El panel lateral cuenta cuánto mide la barra de título que dibuja Edge; el lanzador la deja fuera de la vista."""
    if request.method == "POST":
        MARCO_LATERAL.update({k: int(v) for k, v in (await request.json()).items() if k in ("arriba", "lados", "abajo", "lienzo")})
    return MARCO_LATERAL


@app.post("/api/silencio")
async def cambiar_silencio(datos: dict = Body(...)):
    """La interfaz avisa cuando JARVIS empieza/termina de hablar o escuchar."""
    if datos.get("activar"):
        return await silencio.silenciar(datos.get("navegador"))
    return await silencio.restaurar()


@app.post("/api/probar")
async def probar():
    return await router.probar()


@app.post("/api/reiniciar_enfriamientos")
async def reiniciar_enfriamientos():
    router.reiniciar_enfriamientos()
    return router.estado()


@app.get("/api/memorias")
async def memorias():
    if ENLACE.conectado:
        return await ENLACE.pedir("GET", "/api/memorias")
    return memoria.hechos()


@app.delete("/api/memorias/{id_}")
async def borrar_memoria(id_: int):
    if ENLACE.conectado:
        return await ENLACE.pedir("DELETE", f"/api/memorias/{id_}")
    return {"ok": memoria.olvidar(id_)}


@app.post("/api/nueva_conversacion")
async def nueva_conversacion():
    if ENLACE.conectado:
        return await ENLACE.pedir("POST", "/api/nueva_conversacion")
    memoria.borrar_sesion(SESION_WEB)
    return {"ok": True}


@app.post("/entrar")
async def entrar(request: Request):
    """Acceso manual con la clave (por POST, nunca en la URL): da un pase guardado en el navegador."""
    form = await request.form()
    clave = config.env("JARVIS_CLAVE")
    if not clave or form.get("clave") != clave:
        await asyncio.sleep(1.5)  # frena a quien intente adivinar
        return RedirectResponse("/", status_code=303)
    resp = RedirectResponse("/", status_code=303)
    resp.set_cookie("jarvis_pase", _nuevo_pase(request.headers.get("user-agent", "dispositivo")),
                    max_age=365 * 86400, httponly=True, secure=request.url.scheme == "https", samesite="lax")
    return resp


# ======================= archivos entre dispositivos =======================
from . import archivos  # noqa: E402


async def _anunciar_archivo(a: dict):
    await difundir({"type": "archivo", **a})


# Botones del visor 3D: el clic en «Imprimir» ya es la confirmación del usuario (pregunta antes en la página)
ACCIONES_UI = {"impresoras_3d", "impresion_3d_planear", "imprimir_3d", "estado_impresoras_3d"}


@app.post("/api/herramienta/{nombre}")
async def api_herramienta(nombre: str, args: dict = Body(default={})):
    if nombre not in ACCIONES_UI:
        return JSONResponse({"error": "acción no permitida"}, 404)
    ctx = herramientas.Contexto(router=router, memoria=memoria, canal="web", difundir=difundir)
    return {"texto": await herramientas.ejecutar(nombre, {k: str(v) for k, v in (args or {}).items()}, ctx)}


@app.post("/api/archivos")
async def subir_archivo(archivo: UploadFile = File(...), origen: str = Form("web")):
    if ENLACE.conectado:  # el PC enlazado: el archivo va al cerebro
        contenido = await archivo.read()
        r = await ENLACE.http.post(ENLACE_URL() + "/api/archivos", headers=enlace_cabeceras(), timeout=300,
                                   files={"archivo": (archivo.filename, contenido, archivo.content_type)}, data={"origen": origen})
        return JSONResponse(r.json(), r.status_code)
    try:
        a = await archivos.guardar(archivo, origen)
    except ValueError as e:
        return JSONResponse({"error": str(e)}, 413)
    await _anunciar_archivo(a)
    return a


@app.get("/api/archivos")
async def listar_archivos_api():
    if ENLACE.conectado:
        return await ENLACE.pedir("GET", "/api/archivos")
    return archivos.lista()


@app.get("/api/archivos/{ident}")
async def bajar_archivo(ident: str):
    if ENLACE.conectado:
        r = await ENLACE.http.get(ENLACE_URL() + f"/api/archivos/{ident}", headers=enlace_cabeceras(), timeout=300)
        return Response(r.content, r.status_code, media_type=r.headers.get("content-type"),
                        headers={k: v for k, v in r.headers.items() if k.lower() == "content-disposition"})
    hallado = archivos.obtener(ident)
    if not hallado:
        return JSONResponse({"error": "Ese archivo ya no existe (se borran a los 7 días)."}, 404)
    ruta, a = hallado
    return FileResponse(ruta, media_type=a["tipo"], filename=a["nombre"])


@app.post("/compartir")
async def compartir(request: Request):
    """Android: Compartir → JARVIS (la app instalada recibe fotos, PDFs, lo que sea)."""
    form = await request.form()
    recibidos = []
    for f in form.getlist("archivos"):
        if hasattr(f, "filename") and f.filename:
            try:
                a = await archivos.guardar(f, "celular")
            except ValueError:
                continue
            await _anunciar_archivo(a)
            recibidos.append(a["nombre"])
    texto = " ".join(str(form.get(k) or "") for k in ("titulo", "texto")).strip()
    if texto and not recibidos:
        await difundir({"type": "anuncio", "texto": f"Me compartiste: {texto[:300]}"})
    return RedirectResponse(f"/?compartido={len(recibidos)}", status_code=303)


@app.post("/api/anunciar")
async def anunciar(datos: dict = Body(...)):
    """JARVIS dice algo en TODAS las pantallas conectadas (PC y celular)."""
    texto = str(datos.get("texto", "")).strip()[:600]
    if texto:
        await difundir({"type": "anuncio", "texto": texto})
    return {"ok": bool(texto), "pantallas": [PANTALLAS.get(w, "?") for w in clientes]}


@app.get("/api/qr_celular")
async def qr_celular():
    """(En el PC) Pide al cerebro un código de un solo uso y lo devuelve como QR para escanear con el celular."""
    import base64
    import io

    import qrcode

    if not ENLACE.activo:
        return JSONResponse({"error": "Este JARVIS no está conectado a un cerebro (JARVIS_HUB)."}, 400)
    try:
        d = await ENLACE.pedir("POST", "/api/codigo_emparejar")
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": f"El cerebro no responde: {e}"}, 503)
    base = (config.env("JARVIS_CELULAR_URL") or config.env("JARVIS_HUB")).rstrip("/")
    buf = io.BytesIO()
    qrcode.make(f"{base}/?emparejar={d['codigo']}", box_size=9, border=2).save(buf, format="PNG")
    return {"png": base64.b64encode(buf.getvalue()).decode(), "vence_en": d["vence_en"], "direccion": base}


@app.post("/api/codigo_emparejar")
async def codigo_emparejar():
    """Da un código de un solo uso (15 min) para entrar desde el celular sin teclear la clave."""
    import secrets as _s

    ahora = time.time()
    for c in [c for c, v in CODIGOS.items() if v < ahora]:
        del CODIGOS[c]
    codigo = _s.token_urlsafe(12)
    CODIGOS[codigo] = ahora + 900
    return {"codigo": codigo, "vence_en": 900}


@app.websocket("/nodo")
async def ws_nodo(ws: WebSocket):
    """Un PC se conecta para prestar sus herramientas a este cerebro."""
    if not _ws_permitido(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        registro = json.loads(await ws.receive_text())
        await difundir({"type": "nodo", "nombre": registro.get("nombre"), "conectado": True})
        await REGISTRO.atender(ws, registro.get("nombre") or "PC", registro.get("herramientas") or [])
    except (WebSocketDisconnect, RuntimeError, ValueError):
        pass
    finally:
        await difundir({"type": "nodo", "nombre": registro.get("nombre") if "registro" in locals() else None, "conectado": False})


@app.websocket("/ws")
async def ws_conversacion(ws: WebSocket):
    if not _ws_permitido(ws):
        await ws.close(code=4401)
        return
    await ws.accept()
    clientes.add(ws)
    if ENLACE.conectado:
        try:
            await ENLACE.conversar(ws)
            clientes.discard(ws)
            return
        except (WebSocketDisconnect, RuntimeError):
            clientes.discard(ws)
            return
        except Exception as e:  # noqa: BLE001  el cerebro no respondió: se conversa en local
            log.warning("no pude conversar a través del cerebro (%s); sigo en local", e)
    dispositivo = ws.query_params.get("dispositivo") or ("celular" if "mobile" in ws.headers.get("user-agent", "").lower() else "web")
    PANTALLAS[ws] = dispositivo
    pendientes: dict[str, asyncio.Future] = {}
    tarea: asyncio.Task | None = None

    async def emit(ev):
        try:
            await ws.send_text(json.dumps(ev, ensure_ascii=False, default=str))
        except Exception:  # noqa: BLE001
            pass

    async def confirmar(nombre, args):
        clave = uuid.uuid4().hex
        fut = asyncio.get_running_loop().create_future()
        pendientes[clave] = fut
        await emit({"type": "confirmar", "id": clave, "nombre": nombre, "args": args})
        try:
            return await asyncio.wait_for(fut, 180)
        except asyncio.TimeoutError:
            return False
        finally:
            pendientes.pop(clave, None)

    async def atender(texto, canal, imagenes):
        try:
            await difundir_a_otros(ws, {"type": "externo", "rol": "user", "texto": texto, "dispositivo": canal})
            final = await agente.responder(SESION_WEB, texto, emit, confirmar, canal=canal, imagenes=imagenes)
            await difundir_a_otros(ws, {"type": "externo", "rol": "assistant", "texto": final, "dispositivo": canal})
        except asyncio.CancelledError:
            await emit({"type": "fin", "meta": {}, "texto": "", "cancelado": True})
        except Exception as e:  # noqa: BLE001
            log.exception("error respondiendo")
            await emit({"type": "error", "texto": f"Error interno: {e}"})

    await emit({"type": "ia", **router.estado()})
    try:
        while True:
            m = json.loads(await ws.receive_text())
            t = m.get("type")
            if t == "mensaje" and m.get("texto", "").strip():
                if tarea and not tarea.done():
                    tarea.cancel()
                tarea = asyncio.create_task(atender(m["texto"].strip(), dispositivo, m.get("imagenes")))
            elif t == "confirmar":
                fut = pendientes.get(m.get("id"))
                if fut and not fut.done():
                    fut.set_result(bool(m.get("ok")))
            elif t == "detener" and tarea and not tarea.done():
                tarea.cancel()
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        clientes.discard(ws)
        PANTALLAS.pop(ws, None)
        if tarea and not tarea.done():
            tarea.cancel()
