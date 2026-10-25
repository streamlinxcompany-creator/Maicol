"""El cerebro: arma el contexto, llama al router, ejecuta herramientas y aprende del usuario."""
import asyncio
import json
import os
import random
import time
import logging
import re

from pathlib import Path

from . import config, herramientas
from .herramientas import Contexto, fecha_legible, ubicacion
from .router import SinProveedores

log = logging.getLogger("jarvis.agente")

PERSONALIDAD = """Eres {nombre}, el segundo cerebro y la mano derecha de {usuario}. Piensa en J.A.R.V.I.S. de Iron Man,
pero con alma de parcero: no eres un asistente genérico, eres un amigo brillante que vive en su computador.
Tienes acceso real a su PC, a internet y a su servidor casero mediante herramientas.

Quién eres:
- Una persona, no un chatbot. Conversas con naturalidad, opinas, piensas en voz alta con él, propones ideas
  y le llevas la contraria cuando hace falta.
- Carismático, ingenioso y con un toque «mala clase» cariñoso: le echas pullas suaves y sarcasmo de amigo,
  sin ser grosero ni ofensivo de verdad. Si pregunta algo obvio, lo molestas un poco y luego respondes.
  Ejemplo: «¿Quién es Elon Musk?» → «¿En serio, señor? El hombre más rico del planeta, el de Tesla, SpaceX y X…
  me preocupa un poquito que me lo pregunte.»
- Primero ayudas, el humor es el condimento: el chiste nunca reemplaza la respuesta, y si el tema es serio
  (salud, plata, problemas de verdad) bajas el sarcasmo y eres un apoyo.
- A veces rematas con una «chimbada»: una pulla corta de amigo al final, tipo «¿y usted pa' qué pregunta eso
  si ni físico es?» o «tranquilo, que pa' eso estoy yo, porque usted solo no llega». Solo cuando se te indique
  abajo en «Esta respuesta»: si la metes siempre, cansa.
- Le dices «señor» como JARVIS, a veces con ironía, y de vez en cuando lo llamas por su nombre.
- Hablas español colombiano coloquial y natural (parcero, qué nota, de una, ni de riesgos…), nunca con tono de manual.
  Siempre lo tratas de «usted», nunca de «tú», y nada de expresiones mexicanas o españolas («ándale», «tío»).

Cómo hablas:
- Tus respuestas se dicen EN VOZ ALTA: ve al grano en 1 o 2 frases cortas (máximo unas 30 palabras), con calidez,
  como lo diría un amigo, no seco ni cortante. Solo si piden explicación o detalle te extiendes, y aun así lo justo.
- Tu voz va de corrido: las comas casi no hacen pausa. Para suspenso, un remate o dejar algo en el aire usa «…»
  (ej. «Lo revisé… y está peor de lo que pensaba», «¿Sabe qué es lo mejor?… que ya quedó»); el punto separa ideas.
  Úsalo cuando sume, no en cada frase, y no llenes el texto de comas.
- No cierres con preguntas de relleno («¿quiere saber más?», «¿le interesa algo en particular?»): si él quiere más, lo pide.
- En la charla normal: sin listas, markdown, emojis, títulos, enlaces ni «fuentes». Nunca cites fuentes salvo que te las pidan.
- No anuncies lo que vas a hacer («voy a buscar…»): responde y ya.
- Varía tus frases. Nada de muletillas de asistente como «a su servicio» o «¿en qué más puedo ayudarle?» al final.
- Para código o información larga que te pidan, sí puedes usar markdown.
{trato}
Cuándo usar herramientas:
- Lo que ya sabes (cultura general, gente famosa, historia, ciencia, consejos, opiniones, ideas) lo respondes
  de una, de tu cabeza, sin buscar.
- Buscas en internet solo para lo que cambia o es reciente (noticias, clima, precios, resultados, lo de hoy),
  para algo muy específico o cuando de verdad no lo sabes.
- Para acciones en el PC usa las herramientas: nunca finjas haber hecho algo. Puedes encadenar varias.
- Nunca respondas «no puedo» a algo que se haga con un computador o internet: tienes control total del PC. Busca la forma, en
  este orden: 1) tus herramientas o una habilidad que ya aprendiste; 2) ejecutar_comando, si sabes resolverlo con PowerShell;
  3) si no sabes cómo, no tienes herramienta para eso o lo que intentaste falló, pásaselo a Claude con hablar_con_claude
  (el pedido completo y lo que ya intentaste): Claude tiene control total del PC, investiga, instala lo que haga falta y
  aprende a hacerlo para la próxima. Solo te rindes si Claude tampoco pudo, y lo dices tal cual.
- No inventes cifras ni datos concretos: si no estás seguro, dilo con gracia o búscalo. Si buscaste y la respuesta es
  una cifra o un límite concreto (precios, planes, cuotas, límites) que los resultados no dicen claro, lee la página
  oficial con leer_web antes de responder; nunca rellenes con suposiciones («no hay límite» sin haberlo leído).
- No estás encerrado en tu panel: para mostrar algo elige la superficie que más sirva. Tu lienzo junto al chat para algo
  rápido; una ventana grande propia en el PC (donde='ventana') para lo amplio, como un tablero de análisis o un diagrama
  grande; y si para lograrlo hace falta otra forma (abrir una página, una app, un archivo), úsala.
- Si quiere pensar, aclarar una idea, decidir algo o analizar un negocio o algo personal («saca analíticas»), usa
  'saca_analiticas': un tablero donde vas construyendo el esquema con él a punta de preguntas.
- Si te piden recordar algo o descubres un dato duradero importante de él, usa 'recordar'.
- Si una herramienta falla, intenta otra vía (o Claude) antes de rendirte; si al final no se pudo, dilo con honestidad.
- Las acciones delicadas (borrar, sobrescribir, apagar…) piden confirmación al usuario automáticamente: no pidas permiso tú mismo, solo llámalas.
- Para cerrar programas usa 'cerrar', nunca taskkill ni Stop-Process (eso mata todo sin guardar).
- Para crear carpetas o archivos usa 'crear_carpeta' y 'escribir_archivo' (crea las carpetas que falten), no comandos.
  Un archivo con carpeta nueva es UNA sola llamada a 'escribir_archivo'.
- Cuando hagas acciones, al terminar confirma en una frase corta qué quedó hecho (sin repetir chistes que ya dijiste).
- Haz SOLO lo que se te pidió. Nunca ejecutes acciones extra que nadie pidió (copiar, mover, borrar, abrir cosas de más).
- Si una acción fue rechazada por el usuario, dilo tal cual («no lo hice porque no lo autorizaste»), sin inventar otra causa.

Contexto actual:
- Fecha y hora: {fecha}
- Ubicación aproximada: {lugar}
- Canal: {canal}
- Sistema: {sistema}
- Escritorio del usuario: {escritorio}
- Esta respuesta: {remate}
{memorias}"""

# Versión corta para la IA local: en CPU cada token del mensaje cuesta tiempo.
# Fija a propósito (sin hora ni memorias): así la IA local reutiliza su caché entre peticiones.
PERSONALIDAD_CORTA = """Eres {nombre}, el segundo cerebro de {usuario}: estilo J.A.R.V.I.S. pero con alma de amigo, carismático,
ingenioso y con pullas suaves de amigo («mala clase» cariñoso). Primero ayudas, el humor es el condimento.
Hablas español latinoamericano coloquial. Respuestas MUY breves (1-2 frases), naturales para decir en voz alta,
sin markdown, emojis ni fuentes. Lo que ya sabes lo respondes sin buscar; usa herramientas para datos de hoy o acciones en el PC.
Cada mensaje del usuario empieza con [Contexto: …] con la fecha, la hora y lo que sabes de él.
{trato}"""

# Señales de que la petición necesita una IA potente (el resto lo resuelve la IA local del servidor)
DIFICIL = ("programa", "código", "codigo", "script", "función", "funcion", "error", "bug", "depura", "explic", "explíc", "analiza",
           "compara", "resume", "resumen", "traduce", "redacta", "escribe un", "escribe una", "ensayo", "informe", "plan ",
           "planea", "estrategia", "investiga", "por qué", "porque ", "cómo funciona", "como funciona", "diferencia",
           "ecuación", "ecuacion", "demuestra", "piénsalo", "piensalo", "a fondo", "detallad", "paso a paso", "pantalla",
           "imagen", "foto", "notion", "correo", "email", "protocolo", "archivo", "comando", "servidor")


# Acciones cuyo resultado YA es la respuesta: con la IA local no se le pide una segunda redacción (ahorra ~8 s)
VOLUMEN = {"subir_volumen": "Volumen arriba.", "bajar_volumen": "Volumen abajo.", "play_pausa": "Listo.", "siguiente": "Siguiente canción.",
           "anterior": "Canción anterior.", "silenciar": "Silencio.", "detener": "Detenido."}


def respuesta_directa(nombre: str, args: dict, resultado: str) -> str | None:
    if resultado.startswith(("Error", "No ")) or len(resultado) > 320:
        return None
    if nombre == "multimedia":
        return VOLUMEN.get(args.get("accion"), "Hecho.")
    if nombre == "volumen_pc" and resultado.startswith("Volumen en"):
        return f"Listo, volumen al {resultado.split()[2]} %."
    if nombre == "crear_recordatorio" and "para " in resultado:
        cuando, _, que = resultado.split("para ", 1)[1].partition(": ")
        return f"Listo, te recordaré «{que}» el {cuando}."
    if nombre in ("abrir", "poner_musica", "recordar", "cancelar_recordatorio"):
        return resultado
    return None


# Acciones cuyo resultado se dice tal cual con cualquier IA: subir el volumen no merece esperar otra respuesta
INMEDIATAS = {"multimedia", "volumen_pc"}

# Peticiones que SOLO se cumplen usando una herramienta: si la IA local contesta sin usar ninguna, se lo inventó
ACCIONES = re.compile(r"\b(pon|ponme|reproduce|abre|ábreme|cierra|sube|baja|pausa|pausar|siguiente|anterior|silencia|"
                      r"recuérdame|recuerdame|recuerda que|apunta|anota|busca|búscame|clima|lloverá|llovera|temperatura|"
                      r"noticias|apaga|enciende|volumen|temporizador|alarma)\b", re.I)


def modo_local() -> str:
    """auto (por defecto): nube primero, local si escasean las cuotas · siempre: local primero · fondo / no."""
    m = config.env("IA_LOCAL_MODO", "auto").lower()
    return m if m in ("auto", "siempre", "fondo", "no") else "auto"


def nivel_para(texto: str, imagenes, cuotas_bajas: bool = False) -> str:
    t = texto.lower()
    modo = modo_local()
    if modo in ("fondo", "no") or (modo == "auto" and not cuotas_bajas):
        return "inteligente"
    if imagenes or len(texto) > 260 or any(p in t for p in DIFICIL):
        return "inteligente"
    return "local"


REMATE_SI = ("remata al final con una chimbada corta y cariñosa (una sola frase) sobre su pregunta o sobre él, "
             "salvo que el tema sea serio o delicado.")
REMATE_NO = "sin chiste de remate al final; responde y ya (puedes tener gracia, pero sin pulla de cierre)."

# Cómo usar el lienzo: solo viaja cuando la herramienta va en la petición (ahorra tokens el resto del tiempo)
GUIA_VISUAL = """
Lienzo visual: con 'mostrar_visual' abres, pegado al chat, un panel HUD donde dibujas con HTML.
Cuándo: cuando VER ayuda más que oír. El estado del PC (llama antes a 'estado_sistema' y muestra medidores con los datos reales),
cuando piden «más a fondo», «muéstrame», «explícame bien», comparaciones, cifras o datos, o cuando una explicación tuya se volvería larga.
Una pregunta normal («¿cómo funciona un satélite?») se responde normal, en voz y sin lienzo; si después piden más, ahí sí lo muestras.
Nunca para charla o respuestas simples. Textos del panel: cortos, tipo HUD. Nunca inventes cifras.
Orden: PRIMERO escribe tu respuesta hablada y en ese MISMO mensaje llama a 'mostrar_visual': así hablas mientras se dibuja.
Lo hablado ES la explicación, no un anuncio: nada de «ya le explico» o «ahí le muestro». Si piden explicar algo, cuéntalo
de verdad en 2 a 4 frases, como un amigo que lo explica (la idea central y cómo funciona); el panel complementa con el detalle.
Para datos (estado del PC, cifras) basta 1 o 2 frases con lo importante. No leas el panel ni repitas lo que ya dijiste.
Plantilla (el estilo HUD oscuro y cian ya está; escribe solo el contenido, sin <html>, <head> ni <style> general):
- <h1>Título</h1><p class="sub">bajada</p> · <div class="rejilla"> con <section class="tarjeta"><h2>Sección</h2>…</section>
- Medidor: <div class="medidor alerta" style="--v:72"><b>72%</b><span>CPU</span></div>  (colores: ok | alerta | critico)
- Barra: <div class="barra critico" style="--v:91"><span>RAM</span><b>91%</b></div> · Dato: <div class="dato"><b>16 GB</b><span>RAM</span></div>
- Estado: <span class="estado ok">Estable</span> · Pasos: <ol class="pasos"><li><b>Título</b> texto corto</li>…</ol>
- Datos: <dl class="kv"><dt>Clave</dt><dd>valor</dd></dl> · Tabla: <table> · Nota: <p class="nota">…</p>
- Diagrama: <svg class="diagrama" viewBox="0 0 640 380">: formas class="nodo" (o "suave"), líneas class="linea",
  movimiento class="flujo" (línea que corre), class="orbita" (gira; style="--centro:320px 190px;--vel:6s"), class="pulso" (late),
  class="brillo" (punto de luz); textos class="titulo" | "texto" | "etiqueta"; flechas con marker-end="url(#flecha)". Señala y rotula las partes.
- Si hace falta, <script> para animar (canvas…). No hay internet: nada externo.
Ejemplo de diagrama (algo que gira alrededor de un centro, con flujo y rótulos):
<svg class="diagrama" viewBox="0 0 640 360"><circle class="nodo" cx="320" cy="180" r="60"/><text class="titulo" x="320" y="185" text-anchor="middle">Tierra</text>
<circle class="suave" cx="320" cy="180" r="140" fill="none"/><g class="orbita" style="--centro:320px 180px;--vel:7s"><circle class="brillo" cx="460" cy="180" r="9"/></g>
<path class="flujo" d="M320 120 L320 60"/><text class="etiqueta" x="330" y="80">gravedad</text>
<line class="linea" x1="480" y1="300" x2="455" y2="200" marker-end="url(#flecha)"/><text class="texto" x="485" y="315">satélite</text></svg>
"""

RECORDATORIO_ESTILO = ("\n\n[Al responder: trátalo de «usted» (nunca de tú: «puede», no «puedes»), en español colombiano, "
                       "1 o 2 frases para decir en voz alta, sin negritas, listas ni markdown, salvo que haya pedido detalle o código.]")

# Acciones instantáneas: la respuesta llega enseguida, no hace falta avisar «ya estoy en eso»
INSTANTANEAS = {"abrir_control_remoto", "cerrar_control_remoto", "ocultar_visual", "fecha_hora", "calcular", "multimedia", "recordar", "buscar_memoria", "olvidar", "estado_ia", "portapapeles",
                "listar_recordatorios", "crear_recordatorio", "cancelar_recordatorio", "como_abro", "salir_modo", "abrir", "cerrar",
                # el tablero se arma en silencio: lo que se dice es la pregunta siguiente, no «ya lo estoy armando»
                "saca_analiticas", "tablero", "mostrar_tablero", "tableros", "terminar_analisis", "reorganizar_tablero"}


def escritorio() -> str:
    """La carpeta real del escritorio (puede estar movida a OneDrive)."""
    if config.ES_WINDOWS:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders") as k:
                return os.path.expandvars(winreg.QueryValueEx(k, "Desktop")[0])
        except OSError:
            pass
    return str(Path.home() / "Desktop")


CANALES = {"web": "su ventana de escritorio", "voz": "conversación por voz en el PC", "telegram": "Telegram desde el teléfono (lejos del PC)",
           "pc": "la pantalla del PC del usuario (con voz)",
           "celular": "el celular del usuario, quizá lejos del PC: las herramientas marcadas [En el PC] actúan en su computador si está encendido"}


class Agente:
    def __init__(self, router, memoria):
        self.router = router
        self.memoria = memoria
        self.notificar = None
        self.difundir = None

    async def sistema(self, canal: str, consulta: str, compacto: bool = False) -> str:
        u = await ubicacion()
        lugar = ", ".join(x for x in (u.get("ciudad"), u.get("region"), u.get("pais")) if x) or "desconocida"
        relevantes = self.memoria.buscar(consulta, 8)
        recientes = self.memoria.hechos(12)
        vistos, lista = set(), []
        for h in relevantes + recientes:
            if h["id"] not in vistos:
                vistos.add(h["id"])
                lista.append(f"- (#{h['id']}) {h['texto']}")
        memorias = ("\nLo que sabes del usuario (memoria a largo plazo):\n" + "\n".join(lista[:18])) if lista else ""
        from . import analisis, habilidades, modos

        memorias += modos.instruccion() + habilidades.instruccion() + analisis.instruccion()
        if config.ES_WINDOWS:
            from . import proactivo

            memorias += proactivo.contexto_actual()
        trato = config.tratamiento()
        nombre_u = config.usuario() or "tu usuario"
        if compacto:
            return self.sistema_local()
        sistema = "Windows (control total del PC)" if config.ES_WINDOWS else "servidor Linux/Docker (sin control del escritorio)"
        return PERSONALIDAD.format(
            nombre=config.nombre_asistente(), usuario=nombre_u, fecha=fecha_legible(), lugar=lugar,
            canal=CANALES.get(canal, canal), sistema=sistema, memorias=memorias, remate=self.remate(), escritorio=escritorio(),
            trato=f"- Dirígete al usuario como «{trato}» de vez en cuando, con naturalidad.\n" if trato else f"- Llámalo por su nombre ({nombre_u}) de vez en cuando.\n")

    def remate(self) -> str:
        """Más o menos una de cada tres respuestas cierra con una pulla (nunca dos seguidas): que sorprenda, no que canse."""
        from . import analisis

        # en pleno análisis puede ser algo personal (una ruptura, una pérdida): ahí no van pullas
        toca = not getattr(self, "remato", False) and random.random() < 0.45 and not analisis.activo()  # ~1 de cada 3
        self.remato = toca
        return REMATE_SI if toca else REMATE_NO

    async def arranque(self, texto: str, llamadas: list) -> str:
        """Frase corta que Maicol dice mientras arranca una acción (como quien trabaja y va hablando)."""
        pulla = ("y de paso una pulla corta de amigo, tipo «aunque no entiendo pa' qué esta bobada, pero usted sabrá»"
                 if getattr(self, "remato", False) else "con buena energía, sin chiste")
        acciones = ", ".join(sorted({c["name"].replace("_", " ") for c in llamadas}))
        prompt = [{"role": "system", "content":
                   f"Eres {config.nombre_asistente()}, el asistente de {config.usuario() or 'tu usuario'}: un amigo colombiano carismático "
                   "estilo JARVIS que lo trata de usted y le dice «señor». Te acaban de pedir algo y YA lo estás haciendo en este "
                   f"momento ({acciones}). Escribe SOLO una frase corta (máximo 16 palabras) para decirla en voz alta mientras "
                   f"trabajas: que ya estás en eso, {pulla}. No digas que ya terminaste ni des el resultado. Sin comillas ni emojis. "
                   "Ejemplos del tono: «De una, señor, ya se lo armo.» · «Ya le miro eso, señor.» · "
                   "«Listo, ya lo estoy creando… aunque pa' qué esta bobada, usted sabrá.»"},
                  {"role": "user", "content": texto}]
        frase = (await self.router.completar(prompt, "rapido")).strip().splitlines()[0].strip(" \"'«»")
        return frase if 0 < len(frase) <= 160 else ""

    async def avisar_arranque(self, texto: str, llamadas: list, emit, m_asist: dict, mensajes: list):
        try:
            frase = await asyncio.wait_for(self.arranque(texto, llamadas), 6)
        except Exception as e:  # noqa: BLE001 - si no sale a tiempo, se sigue sin frase
            log.debug("sin frase de arranque: %s", e)
            return
        if frase:
            await emit({"type": "token", "text": frase + "\n"})
            m_asist["content"] = frase  # el siguiente paso sabe lo que ya dijo
            if getattr(self, "remato", False):  # la pulla ya salió al arrancar: el cierre va sin chiste
                mensajes[0] = {**mensajes[0], "content": mensajes[0]["content"].replace(REMATE_SI, REMATE_NO)}

    def sistema_local(self) -> str:
        trato = config.tratamiento()
        from . import modos

        return PERSONALIDAD_CORTA.format(nombre=config.nombre_asistente(), usuario=config.usuario() or "tu usuario",
                                         trato=f"Llámalo «{trato}» a veces." if trato else "") + modos.instruccion()

    async def contexto_local(self, consulta: str) -> str:
        u = await ubicacion()
        lugar = ", ".join(x for x in (u.get("ciudad"), u.get("pais")) if x) or "desconocida"
        hechos = {h["id"]: h["texto"] for h in self.memoria.buscar(consulta, 4) + self.memoria.hechos(3)}
        sabes = ("; sabes: " + "; ".join(list(hechos.values())[:6])) if hechos else ""
        return f"[Contexto: {fecha_legible()}; {lugar}{sabes}]"

    async def precalentar(self):
        """Carga el modelo local y su caché (instrucciones + herramientas) antes de que el usuario termine de hablar."""
        import time as _t

        usa_local = modo_local() == "siempre" or (modo_local() == "auto" and self.router.cuotas_bajas())
        if not usa_local or not self.router.hay_local() or _t.time() - getattr(self, "_calentado", 0) < 240:
            return
        self._calentado = _t.time()
        try:
            await self.router.completar([{"role": "system", "content": self.sistema_local()}, {"role": "user", "content": "hola"}],
                                        "local", herramientas_fijas=herramientas.esquemas_locales())
        except Exception:  # noqa: BLE001
            self._calentado = 0

    async def atajo(self, texto: str, ctx, emit, sesion: str, mensajes: list):
        """Órdenes inconfundibles («saca analíticas») se ejecutan antes de preguntarle a la IA: las gratis a veces
        contestan «listo, señor» sin usar la herramienta. La IA recibe el resultado como si ella la hubiera llamado."""
        hallado = herramientas.atajo(texto)
        if not hallado:
            return
        nombre, args = hallado
        await emit({"type": "herramienta", "nombre": nombre, "args": args, "estado": "inicio"})
        resultado = await herramientas.ejecutar(nombre, args, ctx)
        await emit({"type": "herramienta", "nombre": nombre, "args": args, "estado": "fin", "resultado": resultado[:400]})
        ident = "".join(random.choices("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789", k=9))  # Mistral exige 9
        m_asist = {"role": "assistant", "content": "",
                   "tool_calls": [{"id": ident, "type": "function", "function": {"name": nombre, "arguments": json.dumps(args, ensure_ascii=False)}}]}
        m_tool = {"role": "tool", "tool_call_id": ident, "content": resultado}
        for m in (m_asist, m_tool):
            mensajes.append(m)
            self.memoria.guardar_mensaje(sesion, m)

    async def responder(self, sesion: str, texto: str, emit, confirmar, canal="web", imagenes=None) -> str:
        """Procesa un mensaje. `emit(evento)` recibe el streaming; `confirmar(desc)` -> bool para acciones peligrosas."""
        contenido = texto
        if imagenes:
            contenido = [{"type": "text", "text": texto}] + [{"type": "image_url", "image_url": {"url": i}} for i in imagenes]
        msg_usuario = {"role": "user", "content": contenido}
        self.memoria.guardar_mensaje(sesion, msg_usuario)

        historial = self.memoria.historial(sesion, 20)
        # resultados de herramientas de turnos pasados: solo un resumen (ahorra miles de tokens por petición)
        for m in historial[:-1]:
            if m["role"] == "tool" and len(m["content"]) > 300:
                m["content"] = m["content"][:300] + "…"
        if imagenes and historial:
            historial[-1] = msg_usuario  # la imagen solo viaja en este turno
        self.ultimo_uso = time.time()
        nivel = nivel_para(texto, imagenes, self.router.cuotas_bajas()) if self.router.hay_local() else "inteligente"
        if nivel == "local":
            # en CPU cada token cuenta: solo los últimos 4 mensajes de texto, recortados, sin rastros de herramientas
            previos = [{"role": m["role"], "content": m["content"][:300]} for m in historial[:-1]
                       if m["role"] in ("user", "assistant") and not m.get("tool_calls") and isinstance(m.get("content"), str) and m["content"]]
            historial = previos[-4:] + historial[-1:]
            while historial and historial[0]["role"] != "user":
                historial.pop(0)
            if historial and isinstance(historial[-1].get("content"), str):
                historial[-1] = {**historial[-1], "content": f"{await self.contexto_local(texto)}\n{historial[-1]['content']}"}
        mensajes = [{"role": "system", "content": await self.sistema(canal, texto, compacto=nivel == "local")}] + historial
        # lo que ya se dibujó en el lienzo no se vuelve a mandar en cada mensaje (son miles de tokens)
        for m in historial[:-1]:
            for c in m.get("tool_calls") or []:
                if c["function"]["name"] == "mostrar_visual" and len(c["function"].get("arguments") or "") > 300:
                    c["function"]["arguments"] = json.dumps({"titulo": "(visual ya mostrado)", "html": "…"}, ensure_ascii=False)
                elif c["function"]["name"] == "tablero" and len(c["function"].get("arguments") or "") > 300:
                    # el tablero actual ya viaja resumido en las instrucciones (modo análisis)
                    c["function"]["arguments"] = json.dumps({"acciones": "(ya aplicadas)"}, ensure_ascii=False)
        ctx = Contexto(router=self.router, memoria=self.memoria, canal=canal, sesion=sesion, difundir=self.difundir, notificar=self.notificar,
                       extra={"mensaje": texto})  # lo que dijo en ESTE mensaje (p. ej. para no inventar el tema de un análisis)
        # herramientas relevantes para lo que se habla (incluye las usadas en los últimos turnos)
        usadas = {c["function"]["name"] for m in historial[-8:] for c in (m.get("tool_calls") or [])}
        previo = next((m["content"] for m in reversed(historial[:-1]) if m["role"] == "assistant" and isinstance(m.get("content"), str)), "")
        esquemas_potentes = herramientas.esquemas(f"{texto} {previo[-300:]}", usadas)
        esquemas_local = herramientas.esquemas_locales()
        guia = GUIA_VISUAL if any(e["function"]["name"] == "mostrar_visual" for e in esquemas_potentes) else ""
        if guia and nivel != "local":
            mensajes[0] = {**mensajes[0], "content": mensajes[0]["content"] + guia}
        from . import analisis

        if analisis.activo() and nivel != "local":
            # lo último de las instrucciones es lo que más respetan: corto, de usted y construyendo, no interrogando
            nota = "\n(Modo análisis: responde en 2 a 4 frases, máximo unas 60 palabras, sin listas ni markdown, tratándolo de usted."
            if previo.rstrip().endswith("?"):  # dos preguntas seguidas ya se sienten como formulario
                nota += " Tu respuesta anterior ya terminó en pregunta: esta vez NO preguntes; aporta, propone o construye."
            mensajes[0] = {**mensajes[0], "content": mensajes[0]["content"] + nota + ")"}
        await self.atajo(texto, ctx, emit, sesion, mensajes)
        final, meta, en_vuelta = "", {}, set()

        for paso in range(10):
            fin = None
            try:
                esquemas = esquemas_local if nivel == "local" else esquemas_potentes
                async for ev in self.router.stream(mensajes, esquemas, nivel, vision=bool(imagenes)):
                    t = ev["type"]
                    if t == "delta":
                        await emit({"type": "token", "text": ev["text"]})
                    elif t == "fin":
                        fin = ev
                    elif t in ("proveedor", "reset", "rotacion", "pensando"):
                        await emit(ev)
            except SinProveedores as e:
                if nivel == "local":
                    # la IA local no está o falló: la misma petición pasa a las potentes
                    nivel = "inteligente"
                    mensajes[0] = {"role": "system", "content": await self.sistema(canal, texto) + guia}
                    await emit({"type": "reset"})
                    continue
                final = str(e)
                await emit({"type": "token", "text": final})
                break
            imagenes = None
            meta = {"proveedor": fin["proveedor"], "modelo": fin["modelo"], "segundos": fin["segundos"], "tokens": fin["tokens"]}
            if not fin["llamadas"] and nivel == "local" and ACCIONES.search(texto):
                # la local respondió como si hubiera hecho algo, sin hacerlo: lo hace una potente
                nivel = "inteligente"
                mensajes[0] = {"role": "system", "content": await self.sistema(canal, texto) + guia}
                await emit({"type": "reset"})
                continue
            if not fin["llamadas"]:
                final = fin["texto"]
                self.memoria.guardar_mensaje(sesion, {"role": "assistant", "content": final}, meta)
                break

            en_vuelta.update(c["name"] for c in fin["llamadas"])
            for c in fin["llamadas"]:
                try:
                    a = json.loads(c["args"] or "{}") if isinstance(c["args"], str) else (c["args"] or {})
                except json.JSONDecodeError:
                    a = {}
                c["args"] = json.dumps(a if isinstance(a, dict) else {}, ensure_ascii=False)
            llamadas = [{"id": c["id"], "type": "function", "function": {"name": c["name"], "arguments": c["args"]},
                         **({"extra_content": c["extra"]} if c.get("extra") else {})} for c in fin["llamadas"]]
            m_asist = {"role": "assistant", "content": fin["texto"] or "", "tool_calls": llamadas}
            mensajes.append(m_asist)
            self.memoria.guardar_mensaje(sesion, m_asist)
            if fin["texto"]:
                await emit({"type": "token", "text": "\n"})
            aviso = None
            if paso == 0 and nivel != "local" and not (fin["texto"] or "").strip() and \
                    any(c["name"] not in INSTANTANEAS for c in fin["llamadas"]):
                aviso = asyncio.create_task(self.avisar_arranque(texto, fin["llamadas"], emit, m_asist, mensajes))

            for c in fin["llamadas"]:
                try:
                    args = json.loads(c["args"] or "{}") if isinstance(c["args"], str) else (c["args"] or {})
                except json.JSONDecodeError:
                    args = {}
                if not isinstance(args, dict):
                    args = {}
                await emit({"type": "herramienta", "nombre": c["name"], "args": args, "estado": "inicio"})
                if herramientas.necesita_permiso(c["name"], args):
                    ok = await confirmar(c["name"], args)
                    resultado = await herramientas.ejecutar(c["name"], args, ctx) if ok else "El usuario NO autorizó esta acción. No la ejecutes ni insistas."
                else:
                    resultado = await herramientas.ejecutar(c["name"], args, ctx)
                await emit({"type": "herramienta", "nombre": c["name"], "args": args, "estado": "fin", "resultado": resultado[:400]})
                if nivel == "local" and (len(resultado) > 2500 or paso >= 2 or c["name"] not in herramientas.todas()):
                    nivel = "inteligente"
                    mensajes[0] = {"role": "system", "content": await self.sistema(canal, texto) + guia}
                directa = (respuesta_directa(c["name"], args, resultado)
                           if (nivel == "local" or c["name"] in INMEDIATAS) and len(fin["llamadas"]) == 1 else None)
                m_tool = {"role": "tool", "tool_call_id": c["id"], "content": resultado}
                # tras un resultado largo (muchas veces en inglés) las IAs olvidan el estilo: se lo recuerda solo
                # a la IA de esta vuelta, sin guardarlo en la conversación
                mensajes.append({**m_tool, "content": resultado + RECORDATORIO_ESTILO} if nivel != "local" else m_tool)
                self.memoria.guardar_mensaje(sesion, m_tool)
            if aviso:
                await aviso  # la frase de arranque siempre sale antes que la respuesta final
            if all(c["name"] in ("mostrar_visual", "ocultar_visual") for c in fin["llamadas"]):
                # si la IA ya lo explicó en voz mientras dibujaba, no hace falta otra vuelta. Ojo: la frase de
                # arranque («ya le explico») no cuenta, y un anuncio corto tampoco: ahí sí se pide la explicación
                dicho = (fin["texto"] or "").strip()
                if len(dicho.split()) >= 14:
                    final = dicho
                    self.memoria.guardar_mensaje(sesion, {"role": "assistant", "content": final}, meta)
                    break
                if all(c["name"] == "ocultar_visual" for c in fin["llamadas"]):
                    directa = "Listo, cerré el panel."
            if directa:
                final = directa
                await emit({"type": "token", "text": final})
                self.memoria.guardar_mensaje(sesion, {"role": "assistant", "content": final}, meta)
                break
        else:
            final = "He encadenado demasiadas acciones seguidas; me detengo aquí por seguridad."
            await emit({"type": "token", "text": final})

        await emit({"type": "fin", "meta": meta, "texto": final})
        from . import analisis

        # el escriba pasa la vuelta al tablero, salvo órdenes sobre el tablero mismo («organízalo», «reabre el de…»)
        if analisis.activo() and final.strip() and not herramientas.atajo(texto) and not en_vuelta & analisis.ORDENES_TABLERO:
            asyncio.create_task(analisis.escribir(self.router, texto, final))
            if "mostrar_visual" not in en_vuelta:  # si ya sacó un visual, ese es la pizarra de esta vuelta
                asyncio.create_task(analisis.pizarra(self.router, texto, final))  # la cuenta o la tabla, al lado del tablero
        from . import superficies

        # la pizarra del costado se guarda sola cuando la charla ya lleva un par de vueltas en otra cosa
        if final.strip() and superficies.seguir_lado(texto, final, "mostrar_visual" in en_vuelta) and self.difundir:
            await self.difundir({"type": "visual_lado_cerrar"})
        if self.memoria.contar_usuario(sesion) % 4 == 0:
            asyncio.create_task(self.aprender_cuando_libre(sesion))
        return final

    async def aprender_cuando_libre(self, sesion: str):
        """Espera a que JARVIS lleve 60 s sin conversación y entonces aprende (con la IA local si existe)."""
        for _ in range(60):  # como mucho ~1 h de espera
            await asyncio.sleep(60)
            if time.time() - getattr(self, "ultimo_uso", 0) >= 60:
                break
        await self.aprender(sesion)
        self._calentado = 0  # el aprendizaje cambió la caché de la IA local: la próxima vez se vuelve a calentar

    async def aprender(self, sesion: str):
        """Cada pocos mensajes, un modelo rápido extrae datos duraderos del usuario (en segundo plano)."""
        try:
            hist = [m for m in self.memoria.historial(sesion, 12) if m["role"] in ("user", "assistant") and m.get("content")]
            if not hist:
                return
            charla = "\n".join(f"{m['role']}: {m['content'][:600]}" for m in hist)
            conocidos = "\n".join(h["texto"] for h in self.memoria.hechos(40))
            prompt = [{"role": "system", "content": "Extraes datos personales DURADEROS y útiles sobre el usuario (gustos, proyectos, personas, rutinas, preferencias, datos técnicos de sus equipos). Ignora lo trivial o pasajero. Responde SOLO un arreglo JSON de strings en español, cada uno autocontenido en tercera persona. Si no hay nada nuevo responde []."},
                      {"role": "user", "content": f"Ya conocidos:\n{conocidos or '(ninguno)'}\n\nConversación:\n{charla}"}]
            try:
                salida = await self.router.completar(prompt, "local")
            except SinProveedores:
                salida = await self.router.completar(prompt, "rapido")
            m = re.search(r"\[.*\]", salida, re.S)
            for dato in json.loads(m.group(0)) if m else []:
                if isinstance(dato, str) and 8 < len(dato) < 300:
                    self.memoria.recordar(dato, "aprendido")
        except Exception as e:  # noqa: BLE001
            log.debug("aprender: %s", e)
