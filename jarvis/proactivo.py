"""Maicol proactivo: habla sin que le pregunten, como un amigo que está pendiente, no como una alarma.

Cada minuto mira el PC (disco, RAM, CPU, batería, ventanas que no responden, cuánto llevas en lo mismo, la hora).
Cuando algo le llama la atención, no lo suelta de una: una IA rápida decide si de verdad a un amigo le importaría
y, si sí, arma una frase corta (o una pregunta). Reglas para no volverse cansón:
- como mucho un comentario cada 25 min (lo urgente sí puede antes) y unos pocos al día;
- nunca en modo juego, ni si estás en plena conversación con él, ni si no hay nadie frente al PC (salvo lo urgente);
- cada tema tiene su propio descanso, y aprende de ti: si lo ignoras, espera el doble; si le dices
  «no me avises eso» o «cállate», ese tema queda casi en silencio.
"""
import asyncio
import json
import logging
import random
import re
import time
from datetime import datetime

import psutil

from . import config

log = logging.getLogger("jarvis.proactivo")
ESTADO = config.DATOS / "proactivo.json"
ENTRE_COMENTARIOS = 25 * 60       # mínimo entre dos comentarios que nadie pidió
ENTRE_URGENTES = 5 * 60
MAXIMO_DIA = 8
DESCANSO_TEMA = 6 * 3600          # un mismo tema no vuelve antes de esto (se multiplica si lo ignoras)
CALLADO = re.compile(r"(?i)\b(c[aá]llate|no me (avises|digas|molestes|hables)|deja de (avisar|molestar|decirme)|no (me )?importa|"
                     r"ya (s[eé]|lo s[eé])|no jodas|silencio|para de|que fastidio|cans[oó]n)\b")


# ---------- lo que ve ----------
def ventana_activa() -> dict:
    """La app en primer plano, su título y hace cuánto no tocas el teclado o el ratón."""
    if not config.ES_WINDOWS:
        return {}
    import ctypes
    from ctypes import wintypes

    u = ctypes.windll.user32
    h = u.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(300)
    u.GetWindowTextW(h, buf, 300)
    pid = wintypes.DWORD()
    u.GetWindowThreadProcessId(h, ctypes.byref(pid))
    try:
        app = psutil.Process(pid.value).name().removesuffix(".exe")
    except (psutil.Error, ValueError):
        app = ""

    class LASTINPUTINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.UINT), ("dwTime", wintypes.DWORD)]

    li = LASTINPUTINFO(ctypes.sizeof(LASTINPUTINFO))
    u.GetLastInputInfo(ctypes.byref(li))
    quieto = (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000
    return {"app": app, "titulo": buf.value, "quieto": max(0.0, quieto)}


def _ventanas_colgadas() -> list[str]:
    if not config.ES_WINDOWS:
        return []
    import ctypes

    u, out = ctypes.windll.user32, []

    @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
    def cada(h, _):
        if u.IsWindowVisible(h) and u.IsHungAppWindow(h):
            b = ctypes.create_unicode_buffer(200)
            u.GetWindowTextW(h, b, 200)
            if b.value:
                out.append(b.value)
        return True

    u.EnumWindows(cada, None)
    return out


def _mas_pesado(campo: str) -> str:
    mejor = None
    for p in psutil.process_iter(["name", campo]):
        v = p.info.get(campo) or 0
        if p.info.get("name") not in ("System Idle Process", "System") and (not mejor or v > mejor[1]):
            mejor = (p.info["name"].removesuffix(".exe"), v)
    return mejor[0] if mejor else "?"


class Vigilante:
    def __init__(self):
        self.lecturas: dict[str, int] = {}   # cuántas lecturas seguidas lleva cada señal
        self.foco = {"app": None, "desde": time.time()}
        self.ultimo_dicho: dict | None = None
        self.estado = self._cargar()

    # ----- memoria de lo que ya dijo y de cómo le fue -----
    def _cargar(self) -> dict:
        try:
            return json.loads(ESTADO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"temas": {}, "ultimo": 0, "hoy": "", "dichos_hoy": 0}

    def _guardar(self):
        ESTADO.write_text(json.dumps(self.estado, ensure_ascii=False, indent=1), encoding="utf-8")

    def _tema(self, clave: str) -> dict:
        return self.estado["temas"].setdefault(clave, {"ultimo": 0, "factor": 1})

    # ----- señales: (clave, urgencia 1-3, qué notó) -----
    def observar(self) -> list[tuple[str, int, str]]:
        notas = []
        m = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=None)
        for k, alto in (("ram", m.percent >= 92), ("cpu", cpu >= 90)):
            self.lecturas[k] = self.lecturas.get(k, 0) + 1 if alto else 0
        if self.lecturas["ram"] >= 3:
            notas.append(("ram", 2, f"La RAM lleva varios minutos al {m.percent:.0f}%; lo que más ocupa es {_mas_pesado('memory_percent')}."))
        if self.lecturas["cpu"] >= 5:
            notas.append(("cpu", 1, f"El procesador lleva 5 minutos al {cpu:.0f}%; lo que más lo usa es {_mas_pesado('cpu_percent')}."))
        try:
            d = psutil.disk_usage("C:\\" if config.ES_WINDOWS else "/")
            if d.percent >= 92:
                notas.append(("disco", 3 if d.percent >= 97 else 2, f"El disco está al {d.percent:.0f}%, quedan {d.free / 2**30:.1f} GB libres."))
        except OSError:
            pass
        bat = psutil.sensors_battery() if hasattr(psutil, "sensors_battery") else None
        if bat and not bat.power_plugged and bat.percent <= 15:
            notas.append(("bateria", 3, f"La batería va en {bat.percent:.0f}% y el portátil no está conectado."))
        for titulo in _ventanas_colgadas():
            clave = f"colgada:{titulo[:40]}"
            self.lecturas[clave] = self.lecturas.get(clave, 0) + 1
            if self.lecturas[clave] >= 2:
                notas.append((clave, 2, f"La ventana «{titulo}» lleva más de un minuto sin responder."))
        v = ventana_activa()
        if v.get("app") and v["app"] != self.foco["app"]:
            self.foco = {"app": v["app"], "desde": time.time()}
        from .rutinas import RUTINAS

        if v.get("app") and v.get("quieto", 1e9) < 120:  # solo cuenta si de verdad la está usando
            RUTINAS.registrar(v["app"], v.get("titulo", ""))
        if v.get("quieto", 1e9) < 120:
            notas += RUTINAS.sugerencias()
        if v.get("quieto", 0) > 600:  # se fue del PC: el tiempo seguido vuelve a contar desde cero
            self.foco["desde"] = time.time()
        horas = (time.time() - self.foco["desde"]) / 3600
        if horas >= 2.5 and v.get("quieto", 0) < 120:
            notas.append((f"seguido:{self.foco['app']}", 1, f"Lleva {horas:.1f} horas seguidas en {self.foco['app']} sin pausa."))
        hora = datetime.now().hour
        if 1 <= hora < 5 and v.get("quieto", 1e9) < 120:
            notas.append(("trasnocho", 1, f"Son las {datetime.now():%H:%M} y sigue activo en el PC ({v.get('app') or 'algo'})."))
        return notas

    # ----- criterio: ¿vale la pena interrumpir? -----
    def puede(self, clave: str, urgencia: int, ocupado: bool, presente: bool) -> bool:
        ahora = time.time()
        hoy = datetime.now().strftime("%Y-%m-%d")
        if self.estado.get("hoy") != hoy:
            self.estado.update(hoy=hoy, dichos_hoy=0)
        from . import modos

        modo = (modos.activo() or {}).get("nombre")
        if urgencia < 3 and (modo in ("juego", "noche") or ocupado or not presente or self.estado["dichos_hoy"] >= MAXIMO_DIA):
            return False
        if ahora - self.estado.get("ultimo", 0) < (ENTRE_URGENTES if urgencia >= 3 else ENTRE_COMENTARIOS):
            return False
        tema = self._tema(clave)
        return ahora - tema["ultimo"] >= DESCANSO_TEMA * tema["factor"] / (2 if urgencia >= 3 else 1)

    async def decidir(self, router, nota: str, urgencia: int, contexto: str, obligado: bool = False) -> str | None:
        """Una IA rápida, con la personalidad de Maicol, decide si lo dice y cómo. None = mejor callarse.
        obligado: algo que siempre vale la pena (una app colgada, lo urgente): la IA solo decide cómo decirlo."""
        obligado = obligado or urgencia >= 3
        nombre, usuario = config.nombre_asistente(), config.usuario() or "el usuario"
        prompt = [{"role": "system", "content":
                   f"Eres {nombre}, el amigo y asistente de {usuario}, estilo JARVIS con alma de parcero colombiano (lo tratas de usted "
                   "y le dices «señor»). Notaste algo en su PC sin que te preguntara. Decide como lo haría un amigo de verdad: "
                   "hablas solo si le sirve saberlo AHORA o si hay algo útil que ofrecerle; si es menor, obvio o no cambia nada, te callas. "
                   "Si hablas: UNA frase corta y natural para decir en voz alta (máximo 25 palabras), puede ser una pregunta u ofrecer "
                   "ayuda concreta («¿se la cierro?», «¿le libero espacio?»), con calidez y si cabe una pulla suave; nada de tono de alarma "
                   "ni de manual. Ejemplos: una app colgada o el disco casi lleno → sí, y ofrécele arreglarlo; el PC trabajando duro "
                   "con lo mismo que él está usando (un video, un juego, una compilación) → te callas, es normal; muchas horas "
                   "seguidas o trasnochando → a veces, como amigo, sin regañar. Responde SOLO un JSON: {\"hablar\": true|false, \"frase\": \"...\"}"},
                  {"role": "user", "content": f"Lo que notaste: {nota}\nUrgencia (1 baja, 3 alta): {urgencia}\nContexto: {contexto}"
                   + ("\nEsto SÍ hay que decírselo: hablar=true, solo arma la frase." if obligado else "")}]
        try:
            crudo = await asyncio.wait_for(router.completar(prompt, "rapido"), 25)
            r = json.loads(re.search(r"\{.*\}", crudo, re.S).group(0))
        except Exception as e:  # noqa: BLE001 - sin IA a mano: lo importante se dice igual, lo demás se calla
            log.debug("proactivo sin criterio de IA: %s", e)
            return nota if obligado else None
        frase = str(r.get("frase") or "").strip()[:300]
        if obligado:
            return frase or nota
        return frase if r.get("hablar") and frase else None

    def dicho(self, clave: str, frase: str):
        ahora = time.time()
        self._tema(clave)["ultimo"] = ahora
        self.estado["ultimo"] = ahora
        self.estado["dichos_hoy"] = self.estado.get("dichos_hoy", 0) + 1
        self.ultimo_dicho = {"clave": clave, "cuando": ahora, "frase": frase, "respondido": False}
        self._guardar()

    # ----- aprende de cómo le respondes -----
    def respuesta_usuario(self, texto: str):
        d = self.ultimo_dicho
        if not d or d["respondido"] or time.time() - d["cuando"] > 300:
            return
        d["respondido"] = True
        tema = self._tema(d["clave"])
        if CALLADO.search(texto):
            tema["factor"] = min(64, tema["factor"] * 4)  # «no me avises eso»: casi en silencio
            log.info("proactivo: «%s» casi en silencio (x%d)", d["clave"], tema["factor"])
        else:
            tema["factor"] = max(1, tema["factor"] / 2)   # le sirvió: puede volver a avisar con normalidad
        self._guardar()

    def revisar_ignorado(self):
        d = self.ultimo_dicho
        if d and not d["respondido"] and time.time() - d["cuando"] > 300:
            d["respondido"] = True
            tema = self._tema(d["clave"])
            tema["factor"] = min(64, tema["factor"] * 2)  # lo ignoró: ese tema espera el doble
            self._guardar()


VIGILANTE = Vigilante()


def contexto_actual() -> str:
    """Para las instrucciones de Maicol: en qué está el usuario ahora mismo (sin que se lo explique)."""
    try:
        v = ventana_activa()
    except Exception:  # noqa: BLE001
        return ""
    if not v.get("app"):
        return ""
    minutos = (time.time() - VIGILANTE.foco["desde"]) / 60 if VIGILANTE.foco["app"] == v["app"] else 0
    lleva = f", lleva {minutos:.0f} min ahí" if minutos >= 5 else ""
    return f"\nAhora mismo el usuario tiene en primer plano: {v['app']} («{v['titulo'][:120]}»){lleva}. Úsalo si ayuda a entender lo que pide."


async def vigilar(router, agente, decir, hay_pantalla_pc, avisar_lejos):
    """Bucle de fondo. Si usted está usando el PC, decir(frase) se lo dice ahí; si no está, solo lo urgente
    le llega al celular con avisar_lejos(frase), y lo demás espera a que vuelva."""
    await asyncio.sleep(90)  # que arranque tranquilo
    psutil.cpu_percent(interval=None)
    while True:
        try:
            VIGILANTE.revisar_ignorado()
            notas = await asyncio.to_thread(VIGILANTE.observar)
            v = await asyncio.to_thread(ventana_activa)
            presente = v.get("quieto", 1e9) < 300  # tocó teclado o ratón hace menos de 5 min
            ocupado = time.time() - getattr(agente, "ultimo_uso", 0) < 120  # en plena conversación no se interrumpe
            for clave, urgencia, nota in sorted(notas, key=lambda n: -n[1]):
                if not VIGILANTE.puede(clave, urgencia, ocupado, presente):
                    continue
                if presente and not hay_pantalla_pc():
                    continue  # está en el PC pero sin Maicol abierto: no hay dónde decirlo
                contexto = f"{datetime.now():%A %H:%M}; en primer plano: {v.get('app') or '?'} («{(v.get('titulo') or '')[:80]}»)"
                frase = await VIGILANTE.decidir(router, nota, urgencia, contexto, obligado=clave.startswith(("colgada:", "disco")))
                if not frase:
                    VIGILANTE._tema(clave)["ultimo"] = time.time() - DESCANSO_TEMA * 0.75  # lo pensó y no valía: vuelve a mirarlo luego
                    continue
                VIGILANTE.dicho(clave, frase)
                log.info("proactivo (%s): %s", clave, frase)
                await (decir if presente else avisar_lejos)(frase)
                break  # uno por vuelta, nunca una ráfaga
        except Exception as e:  # noqa: BLE001
            log.warning("vigilante proactivo: %s", e)
        await asyncio.sleep(60 + random.randint(0, 15))
