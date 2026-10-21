"""Router multi-IA: rota entre proveedores gratuitos para que nunca te quedes sin tokens.

Idea clave: la unidad de rotación es la "ranura" (proveedor + modelo + llave).
En Gemini y Groq cada modelo tiene su propia cuota, así que 3 llaves x 6 modelos
son 18 bolsas de tokens independientes. Cuando una ranura responde 429, se enfría
el tiempo exacto que pide el proveedor y se pasa a la siguiente sin que lo notes.
"""
import asyncio
import json
import logging
import os
import random
import re
import string
import time
from dataclasses import dataclass, field

import httpx

from . import config
from .proveedores import CATALOGO

log = logging.getLogger("jarvis.router")

ESTADO = config.DATOS / "router_estado.json"
ETIQUETA = "herramienta"


class ErrorProveedor(Exception):
    def __init__(self, tipo: str, detalle: str = "", espera: float | None = None):
        super().__init__(f"{tipo}: {detalle[:300]}")
        self.tipo, self.detalle, self.espera = tipo, detalle, espera


class SinProveedores(Exception):
    pass


@dataclass
class Ranura:
    prov: dict
    modelo: str
    llave: str
    n_llave: int
    rango: float
    vision: bool = False
    tools: bool = True
    rapido: bool = False
    enfriar_hasta: float = 0.0
    motivo: str = ""
    fallos: int = 0
    latencia: float = 0.0
    peticiones: int = 0
    tokens: int = 0
    errores: int = 0
    dia: str = ""
    peticiones_dia: int = 0
    tokens_dia: int = 0
    recientes: list = field(default_factory=list)

    @property
    def id(self) -> str:
        return f"{self.prov['id']}:{self.modelo}#{self.n_llave}"

    def libre(self, ahora: float) -> bool:
        return ahora >= self.enfriar_hasta

    def contar(self, tokens: int):
        hoy = time.strftime("%Y-%m-%d")
        if self.dia != hoy:
            self.dia, self.peticiones_dia, self.tokens_dia = hoy, 0, 0
        self.peticiones += 1
        self.peticiones_dia += 1
        self.tokens += tokens
        self.tokens_dia += tokens


def _id_corto() -> str:
    # Mistral exige ids de 9 caracteres alfanuméricos; los generamos nosotros para todos.
    return "".join(random.choices(string.ascii_letters + string.digits, k=9))


def _espera_de(texto: str, cabeceras) -> float | None:
    if cabeceras is not None:
        ra = cabeceras.get("retry-after")
        if ra:
            try:
                return float(ra)
            except ValueError:
                pass
    t = texto.lower()
    m = re.search(r'retrydelay"?\s*:\s*"(\d+(?:\.\d+)?)s', t)
    if m:
        return float(m.group(1))
    m = re.search(r"retry after\s+(\d+(?:\.\d+)?)\s*s", t)
    if m:
        return max(float(m.group(1)), 30.0 if "per ip" in t else 0.0)
    m = re.search(r"(?:try again|retry) in\s+(?:(\d+)h)?(?:(\d+)m(?!s))?(?:(\d+(?:\.\d+)?)(ms|s))?", t)
    if m and any(m.groups()[:3]):
        h, mi, s, u = m.groups()
        seg = int(h or 0) * 3600 + int(mi or 0) * 60
        if s:
            seg += float(s) / (1000 if u == "ms" else 1)
        return seg
    return None


def clasificar(estado: int, texto: str, cabeceras=None) -> ErrorProveedor:
    t = texto.lower()
    espera = _espera_de(texto, cabeceras)
    if estado == 429 or any(w in t for w in ("rate limit", "rate_limit", "free limit", "free_limit", "limit reached", "quota", "resource_exhausted", "too many requests")):
        diario = any(w in t for w in ("per day", "daily", "perday", "rpd", "tpd", "per-day", "free-models-per-day", "monthly"))
        return ErrorProveedor("cuota_diaria" if diario else "limite", texto, espera)
    if estado in (401, 403) or any(w in t for w in ("invalid api key", "unauthorized", "valid api key", "api key not valid", "api_key_invalid", "invalid_api_key", "incorrect api key")):
        return ErrorProveedor("llave", texto)
    if estado in (400, 422) and any(w in t for w in ("tool", "function")):
        return ErrorProveedor("sin_tools", texto)
    if estado == 402 or "insufficient" in t or "credit" in t:
        return ErrorProveedor("creditos", texto)
    if estado == 413 or any(w in t for w in ("context length", "context_length", "too long", "maximum context", "too large")):
        return ErrorProveedor("contexto", texto)
    if estado == 404 or any(w in t for w in ("model_not_found", "does not exist", "decommissioned", "not found", "no endpoints", "deprecated")):
        return ErrorProveedor("modelo", texto)
    if estado >= 500:
        return ErrorProveedor("servidor", texto, espera)
    return ErrorProveedor("otro", f"HTTP {estado} {texto}", espera)


# ---------- adaptación de mensajes ----------

def _texto_de(contenido) -> str:
    if isinstance(contenido, list):
        return " ".join(p.get("text", "") for p in contenido if p.get("type") == "text")
    return contenido or ""


def aplanar(mensajes: list, conservar_imagenes: bool) -> list:
    """Convierte llamadas a herramientas en texto, para modelos sin soporte nativo."""
    out = []
    for m in mensajes:
        rol = m["role"]
        if rol == "tool":
            out.append({"role": "user", "content": f"[Resultado de la herramienta]\n{m['content']}"})
        elif rol == "assistant" and m.get("tool_calls"):
            partes = [m.get("content") or ""]
            for c in m["tool_calls"]:
                try:
                    args = json.loads(c["function"]["arguments"] or "{}")
                except ValueError:
                    args = {}
                partes.append(f"<{ETIQUETA}>{json.dumps({'nombre': c['function']['name'], 'args': args}, ensure_ascii=False)}</{ETIQUETA}>")
            out.append({"role": "assistant", "content": "\n".join(p for p in partes if p)})
        elif isinstance(m.get("content"), list) and not conservar_imagenes:
            out.append({"role": rol, "content": _texto_de(m["content"])})
        else:
            out.append({"role": rol, "content": m.get("content") or ""})
    # algunos proveedores exigen alternancia estricta: fusionamos roles repetidos
    fusion = []
    for m in out:
        if fusion and fusion[-1]["role"] == m["role"] and m["role"] != "system" and isinstance(m["content"], str) and isinstance(fusion[-1]["content"], str):
            fusion[-1]["content"] += "\n\n" + m["content"]
        else:
            fusion.append(dict(m))
    return fusion


def firmas_para(proveedor: str, mensajes: list) -> list:
    """Gemini 3 exige la 'thought_signature' de cada llamada; el resto de proveedores no la acepta."""
    if not any(m.get("tool_calls") for m in mensajes):
        return mensajes
    out = []
    for m in mensajes:
        if m.get("tool_calls"):
            llamadas = []
            for c in m["tool_calls"]:
                c = {k: v for k, v in c.items() if k != "extra_content"}
                if proveedor == "gemini":
                    # si la llamada la hizo otro proveedor no hay firma: Google acepta este comodín documentado
                    extra = next((x.get("extra_content") for x in m["tool_calls"] if x.get("id") == c.get("id")), None)
                    c["extra_content"] = extra or {"google": {"thought_signature": "skip_thought_signature_validator"}}
                llamadas.append(c)
            m = {**m, "tool_calls": llamadas}
        out.append(m)
    return out


def instrucciones_protocolo(tools: list) -> str:
    lineas = [
        "\n\n## Herramientas",
        f"Para usar una herramienta responde ÚNICAMENTE con: <{ETIQUETA}>{{\"nombre\": \"...\", \"args\": {{...}}}}</{ETIQUETA}>",
        "Después recibirás el resultado y podrás responder. Herramientas disponibles:",
    ]
    for t in tools:
        f = t["function"]
        params = ", ".join(f"{k}: {v.get('description', v.get('type', ''))}" for k, v in f.get("parameters", {}).get("properties", {}).items())
        lineas.append(f"- {f['name']}({params}) — {f['description']}")
    return "\n".join(lineas)


def extraer_protocolo(texto: str) -> tuple[str, list]:
    llamadas = []
    patron = re.compile(rf"<{ETIQUETA}>(.*?)</{ETIQUETA}>", re.S)
    for bloque in patron.findall(texto):
        try:
            d = json.loads(bloque.strip())
            llamadas.append({"name": d.get("nombre") or d.get("name"), "args": json.dumps(d.get("args") or d.get("arguments") or {}, ensure_ascii=False)})
        except json.JSONDecodeError:
            continue
    return patron.sub("", texto).strip(), llamadas


class FiltroPensamiento:
    """Quita los bloques <think>...</think> que algunos modelos mandan en el contenido."""

    def __init__(self):
        self.dentro = False
        self.buf = ""

    def __call__(self, trozo: str) -> str:
        self.buf += trozo
        salida = ""
        while self.buf:
            if self.dentro:
                i = self.buf.find("</think>")
                if i < 0:
                    self.buf = self.buf[-8:]
                    return salida
                self.buf = self.buf[i + 8:]
                self.dentro = False
            else:
                i = self.buf.find("<think>")
                if i < 0:
                    # retener un posible inicio de etiqueta cortado
                    corte = max((k for k in range(1, 7) if "<think>".startswith(self.buf[-k:])), default=0)
                    salida += self.buf[: len(self.buf) - corte]
                    self.buf = self.buf[len(self.buf) - corte:]
                    return salida
                salida += self.buf[:i]
                self.buf = self.buf[i + 7:]
                self.dentro = True
        return salida


# ---------- router ----------

class Router:
    def __init__(self):
        self.ranuras: list[Ranura] = []
        self.cliente = httpx.AsyncClient(timeout=httpx.Timeout(90, connect=10), follow_redirects=True)
        self.estrategia = config.estrategia()
        self.activa: str | None = None
        self.oyentes = []  # callbacks cuando cambia el estado
        self._guardado = 0.0
        self.proveedores_info: dict[str, dict] = {}

    # ----- arranque y descubrimiento -----
    def _base(self, prov) -> str | None:
        base = prov.get("base", "")
        for var in re.findall(r"\{(\w+)\}", base):
            valor = os.getenv(var) or prov.get("base_defecto", {}).get(var)
            if not valor:
                return None
            base = base.replace("{" + var + "}", valor.rstrip("/"))
        return base.rstrip("/")

    async def iniciar(self):
        config.recargar_env()
        self.estrategia = config.estrategia()
        nuevas: list[Ranura] = []
        self.proveedores_info = {}

        async def preparar(prov):
            llaves = [""] if prov.get("sin_llave") else config.env_lista(prov.get("llave", ""))
            base = self._base(prov)
            info = {"id": prov["id"], "nombre": prov["nombre"], "registro": prov.get("registro"),
                    "configurado": bool(llaves and base), "llave_env": prov.get("llave"), "sin_llave": prov.get("sin_llave", False), "nota": ""}
            self.proveedores_info[prov["id"]] = info
            if not llaves or not base:
                return []
            res = []
            for n, llave in enumerate(llaves):
                try:
                    modelos, nota = await self._descubrir(prov, base, llave)
                except Exception as e:  # noqa: BLE001
                    modelos, nota = [], f"sin conexión ({type(e).__name__})"
                if nota:
                    info["nota"] = nota
                for i, m in enumerate(modelos):
                    res.append(Ranura(prov=prov, modelo=m["id"], llave=llave, n_llave=n,
                                      rango=prov["prioridad"] * 10 + i, vision=m.get("vision", False),
                                      tools=m.get("tools", True), rapido=m.get("rapido", False)))
            if not res and prov.get("sin_llave"):
                info["configurado"] = False
            return res

        grupos = await asyncio.gather(*(preparar(p) for p in CATALOGO))
        for g in grupos:
            nuevas.extend(g)
        self.ranuras = nuevas
        self._cargar_estado()
        log.info("Router listo: %d ranuras en %d proveedores", len(nuevas), len({r.prov['id'] for r in nuevas}))
        self._avisar()

    async def _descubrir(self, prov, base, llave):
        cab = {"Authorization": f"Bearer {llave}"} if llave else {}
        preferidos = [dict(m) for m in prov["modelos"]]
        if prov.get("listar") is False:
            return preferidos, ""
        url = prov.get("lista_url") or f"{base}/models"
        timeout = 3 if prov["id"] == "ollama" else 12
        r = await self.cliente.get(url, headers=cab, timeout=timeout)
        if r.status_code in (401, 403) or (r.status_code == 400 and "api key" in r.text.lower()):
            return preferidos, "llave rechazada"
        if r.status_code != 200:
            return preferidos, ""
        try:
            datos = r.json()
        except ValueError:
            return preferidos, ""
        lista = datos.get("data", datos) if isinstance(datos, dict) else datos
        if not isinstance(lista, list):
            return preferidos, ""

        if prov["id"] == "openrouter":
            gratis = []
            for m in lista:
                p = m.get("pricing") or {}
                if str(p.get("prompt")) == "0" and str(p.get("completion")) == "0":
                    tamaño = max((float(x) for x in re.findall(r"(\d+(?:\.\d+)?)b", m["id"].lower())), default=0)
                    gratis.append({
                        "id": m["id"],
                        "tools": "tools" in (m.get("supported_parameters") or []),
                        "vision": "image" in ((m.get("architecture") or {}).get("input_modalities") or []),
                        "rapido": 0 < tamaño < 15,
                        "_orden": (not ("tools" in (m.get("supported_parameters") or [])), -tamaño),
                    })
            gratis.sort(key=lambda x: x["_orden"])
            return gratis[:10], ""

        if prov["id"] == "ollama":
            elegido = config.env("OLLAMA_MODELO")
            modelos = [m["id"] for m in lista if "embed" not in m["id"]]
            if elegido:
                modelos = [m for m in modelos if m == elegido or m.split(":")[0] + ":" + m.split(":")[-1] == elegido] or modelos
            return [{"id": m, "rapido": True} for m in modelos[:1 if elegido else 3]], ""

        ids = {str(m.get("id", "")).removeprefix("models/") for m in lista if isinstance(m, dict)}
        elegidos = [m for m in preferidos if m["id"] in ids]
        for patron in prov.get("patrones_extra", []):
            for i in sorted(ids, reverse=True):
                if re.match(patron, i) and i not in {m["id"] for m in elegidos}:
                    elegidos.insert(0, {"id": i, "vision": prov.get("vision_extra", False),
                                        "rapido": any(re.match(p, i) for p in prov.get("rapido_extra", []))})
        if not elegidos and ids:
            # ninguno de los preferidos existe: elegimos los que parezcan modelos de chat
            malos = ("embed", "whisper", "tts", "guard", "image", "audio", "moderation", "rerank", "vision-only", "orpheus", "playai")
            chat = [i for i in ids if not any(b in i.lower() for b in malos)]
            chat.sort(key=lambda i: -max((float(x) for x in re.findall(r"(\d+(?:\.\d+)?)b", i.lower())), default=1))
            elegidos = [{"id": i} for i in chat[:4]]
        return elegidos, ""

    # ----- estado persistente -----
    def _cargar_estado(self):
        try:
            datos = json.loads(ESTADO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        for r in self.ranuras:
            d = datos.get(r.id)
            if not d:
                continue
            for k in ("enfriar_hasta", "motivo", "latencia", "peticiones", "tokens", "errores", "dia", "peticiones_dia", "tokens_dia", "tools"):
                if k in d:
                    setattr(r, k, d[k])

    def guardar(self, forzar=False):
        if not forzar and time.time() - self._guardado < 5:
            return
        self._guardado = time.time()
        datos = {r.id: {k: getattr(r, k) for k in ("enfriar_hasta", "motivo", "latencia", "peticiones", "tokens", "errores", "dia", "peticiones_dia", "tokens_dia", "tools")} for r in self.ranuras}
        try:
            ESTADO.write_text(json.dumps(datos), encoding="utf-8")
        except OSError:
            pass

    def _avisar(self):
        for f in self.oyentes:
            try:
                f()
            except Exception:  # noqa: BLE001
                pass

    def cuotas_bajas(self, umbral: float = 0.3) -> bool:
        """True si quedan libres menos del 30 % de los modelos en la nube (sin contar local ni el de emergencia)."""
        ahora = time.time()
        nube = [r for r in self.ranuras if r.prov["id"] not in ("ollama", "pollinations")]
        if not nube:
            return True
        return sum(r.libre(ahora) for r in nube) / len(nube) < umbral

    def hay_local(self) -> bool:
        ahora = time.time()
        return any(r.prov["id"] == "ollama" and r.libre(ahora) for r in self.ranuras)

    # ----- selección -----
    def elegir(self, nivel: str, vision: bool, con_tools: bool, excluir: set) -> Ranura | None:
        ahora = time.time()
        cands = [r for r in self.ranuras if r.id not in excluir and r.libre(ahora) and (r.vision or not vision)]
        if nivel == "local":  # solo la IA del servidor; si no está, quien llama escala a las potentes
            cands = [r for r in cands if r.prov["id"] == "ollama"]
        if not cands:
            return None

        def puntaje(r: Ranura) -> float:
            base = r.rango
            if nivel == "rapido":
                base = base * 0.3 + (0 if r.rapido else 40)
            elif r.rapido:
                base += 25  # inventan más: solo para la charla principal si no queda nada mejor
            if con_tools and not r.tools:
                base += 12
            r.recientes = [t for t in r.recientes if ahora - t < 60]
            if self.estrategia == "calidad":
                return base + random.random() * 0.1
            if self.estrategia == "velocidad":
                # los «rápidos» ganan por latencia pero responden peor: en la charla solo si no queda otro
                return (r.latencia or 2.5) * 10 + base * 0.2 + len(r.recientes) + (25 if r.rapido and nivel != "rapido" else 0)
            # equilibrio: reparte la carga para que ninguna cuota se agote antes de tiempo
            return base + len(r.recientes) * 4 + r.fallos * 6 + random.random() * 2

        return min(cands, key=puntaje)

    def _penalizar(self, r: Ranura, e: ErrorProveedor):
        r.errores += 1
        r.fallos += 1
        ahora = time.time()
        escala = [20, 60, 180, 600, 1800]
        duracion, motivo = 0.0, e.tipo
        if e.tipo == "limite":
            duracion, motivo = e.espera or escala[min(r.fallos - 1, 4)], "límite por minuto"
        elif e.tipo == "cuota_diaria":
            duracion, motivo = e.espera or [3600, 3 * 3600, 6 * 3600][min(r.fallos - 1, 2)], "cuota diaria agotada"
        elif e.tipo == "llave":
            duracion, motivo = 12 * 3600, "llave inválida"
        elif e.tipo == "creditos":
            duracion, motivo = 24 * 3600, "sin créditos gratis"
        elif e.tipo == "modelo":
            duracion, motivo = 24 * 3600, "modelo retirado"
        elif e.tipo == "sin_tools":
            r.tools = False
            r.fallos -= 1
            motivo = ""
        elif e.tipo == "contexto":
            r.fallos -= 1
            motivo = ""
        else:
            duracion, motivo = e.espera or escala[min(r.fallos - 1, 4)], {"servidor": "servidor caído", "timeout": "sin respuesta", "red": "error de red", "vacio": "respuesta vacía"}.get(e.tipo, "error")
        if duracion:
            hasta = ahora + min(duracion, 24 * 3600)
            afectadas = [r]
            if e.tipo == "vacio" and "respuesta no válida" in e.detalle:
                # no es un modelo: todo el servicio responde algo que no es una IA
                hasta = ahora + min(1800 * r.fallos, 6 * 3600)
                motivo = "servicio caído"
            if (e.tipo in ("cuota_diaria", "llave", "creditos") and r.prov.get("cuota_por_llave")) or e.tipo == "llave" or motivo == "servicio caído":
                afectadas = [x for x in self.ranuras if x.prov is r.prov and x.llave == r.llave]
            for x in afectadas:
                x.enfriar_hasta, x.motivo = max(x.enfriar_hasta, hasta), motivo
        log.warning("Ranura %s -> %s (%s) %.0fs", r.id, e.tipo, e.detalle[:120].replace("\n", " "), duracion)
        self.guardar(True)
        self._avisar()

    # ----- llamadas -----
    async def stream(self, mensajes: list, tools: list | None = None, nivel: str = "inteligente", vision: bool = False, max_intentos: int = 10):
        """Generador de eventos: proveedor, delta, pensando, reset, rotacion, fin."""
        probadas: set = set()
        ultimo: ErrorProveedor | None = None
        emitio = False
        for _ in range(max_intentos):
            r = self.elegir(nivel, vision, bool(tools), probadas)
            if r is None:
                break
            probadas.add(r.id)
            if emitio:
                yield {"type": "reset"}
                emitio = False
            try:
                async for ev in self._stream_ranura(r, mensajes, tools, vision):
                    if ev["type"] == "delta":
                        emitio = True
                    yield ev
                return
            except ErrorProveedor as e:
                ultimo = e
                self._penalizar(r, e)
                if e.tipo == "sin_tools" and tools:
                    probadas.discard(r.id)  # se reintenta ya mismo con el protocolo de texto
                    continue
                yield {"type": "rotacion", "desde": r.id, "proveedor": r.prov["nombre"], "motivo": r.motivo or e.tipo}
        raise SinProveedores(self.resumen_agotado(ultimo))

    def resumen_agotado(self, ultimo=None) -> str:
        if not self.ranuras:
            return "No tengo ningún proveedor de IA configurado. Agrega al menos una llave gratuita en el archivo .env."
        ahora = time.time()
        prox = min((r.enfriar_hasta for r in self.ranuras), default=ahora)
        espera = max(0, prox - ahora)
        return f"Todos mis proveedores están en enfriamiento. El primero vuelve en {int(espera // 60)} min {int(espera % 60)} s." + (f" (último error: {ultimo.tipo})" if ultimo else "")

    async def _stream_ranura(self, r: Ranura, mensajes, tools, vision):
        prov = r.prov
        nativo = bool(tools) and r.tools
        msgs = mensajes if nativo else aplanar(mensajes, vision)
        if nativo:
            msgs = firmas_para(prov["id"], msgs)
        if tools and not nativo:
            msgs = [dict(m) for m in msgs]
            msgs[0]["content"] = _texto_de(msgs[0]["content"]) + instrucciones_protocolo(tools)
        cuerpo = {"model": r.modelo, "messages": msgs, "stream": True, **prov.get("cuerpo_extra", {})}
        if nativo:
            # Gemini rechaza objetos sin propiedades; los servidores vLLM exigen "parameters" siempre
            cuerpo["tools"] = tools if prov["id"] == "gemini" else [
                t if "parameters" in t["function"] else {"type": "function", "function": {**t["function"], "parameters": {"type": "object", "properties": {}}}}
                for t in tools]
        url = prov.get("chat_url") or f"{self._base(prov)}/chat/completions"
        cab = {"Content-Type": "application/json", **prov.get("cabeceras", {})}
        if r.llave:
            cab["Authorization"] = f"Bearer {r.llave}"

        t0 = time.time()
        r.recientes.append(t0)
        texto, acumulado, usage = "", {}, None
        por_indice: dict = {}  # índice que manda el proveedor -> llamada acumulada
        filtro = FiltroPensamiento()
        decidido = nativo or not tools  # en modo protocolo esperamos a saber si es llamada
        retenido = ""
        pensando_avisado = False
        primer_token = None
        try:
            espera_lectura = 45 if prov["id"] == "ollama" else 60  # si la local no arranca en 45 s, se escala a una potente
            async with self.cliente.stream("POST", url, json=cuerpo, headers=cab, timeout=httpx.Timeout(240, connect=10, read=espera_lectura)) as resp:
                if resp.status_code != 200:
                    cuerpo_err = (await resp.aread()).decode("utf-8", "replace")
                    raise clasificar(resp.status_code, cuerpo_err, resp.headers)
                self.activa = r.id
                yield {"type": "proveedor", "ranura": r.id, "proveedor": prov["nombre"], "id_proveedor": prov["id"], "modelo": r.modelo}
                self._avisar()
                tipo = resp.headers.get("content-type", "")
                if "event-stream" not in tipo:
                    crudo = (await resp.aread()).decode("utf-8", "replace")
                    lineas = None
                    try:
                        datos = json.loads(crudo)
                    except ValueError:
                        datos = None
                    if isinstance(datos, dict):
                        if "error" in datos:
                            err = datos["error"] if isinstance(datos["error"], dict) else {"message": str(datos["error"])}
                            raise clasificar(int(err["code"]) if str(err.get("code", "")).isdigit() else 500, json.dumps(err))
                        trozos = [{"choices": [{"delta": c.get("message", {})} for c in datos.get("choices", [])], "usage": datos.get("usage")}]
                    elif "data:" in crudo:
                        # streaming real pero con content-type equivocado
                        trozos = [json.loads(l[5:].strip()) for l in crudo.splitlines()
                                  if l.startswith("data:") and l[5:].strip() not in ("", "[DONE]") and l[5:].strip().startswith("{")]
                    else:
                        raise ErrorProveedor("vacio", f"respuesta no válida ({tipo or 'sin tipo'}): {crudo[:120]}")
                else:
                    trozos = None
                    lineas = resp.aiter_lines()

                async def fuente():
                    if trozos is not None:
                        for t in trozos:
                            yield t
                        return
                    async for linea in lineas:
                        linea = linea.strip()
                        if not linea.startswith("data:"):
                            continue
                        dato = linea[5:].strip()
                        if dato == "[DONE]":
                            return
                        try:
                            yield json.loads(dato)
                        except ValueError:
                            continue

                async for trozo in fuente():
                    if trozo.get("error"):
                        err = trozo["error"]
                        codigo = err.get("code") if isinstance(err, dict) else None
                        raise clasificar(int(codigo) if str(codigo).isdigit() else 500, json.dumps(err))
                    if trozo.get("usage"):
                        usage = trozo["usage"]
                    for i, ch in enumerate(trozo.get("choices") or []):
                        d = ch.get("delta") or ch.get("message") or {}
                        if (d.get("reasoning_content") or d.get("reasoning")) and not pensando_avisado:
                            pensando_avisado = True
                            yield {"type": "pensando"}
                        c = d.get("content")
                        if c:
                            limpio = filtro(c)
                            if limpio:
                                if primer_token is None:
                                    primer_token = time.time()
                                texto += limpio
                                if decidido:
                                    yield {"type": "delta", "text": limpio}
                                else:
                                    retenido += limpio
                                    s = retenido.lstrip()
                                    marca = f"<{ETIQUETA}"
                                    if s.startswith(marca):
                                        pass  # es una llamada: no se muestra
                                    elif len(s) < len(marca) and marca.startswith(s):
                                        pass
                                    else:
                                        decidido = True
                                        yield {"type": "delta", "text": retenido}
                                        retenido = ""
                        for j, tc in enumerate(d.get("tool_calls") or []):
                            idx = tc.get("index", j)
                            f = tc.get("function") or {}
                            nombre, tid = f.get("name"), tc.get("id")
                            acc = acumulado.get(por_indice.get(idx))
                            # Gemini manda llamadas paralelas con el mismo índice: un id distinto
                            # o un nombre nuevo sobre una llamada ya nombrada es OTRA llamada
                            if (acc is None or (tid and acc["id"] and tid != acc["id"])
                                    or (nombre and acc["name"] and not (nombre == acc["name"] and not acc["args"]))):
                                por_indice[idx] = len(acumulado)
                                acc = acumulado[por_indice[idx]] = {"name": "", "args": "", "id": tid or ""}
                            if nombre:
                                acc["name"] = nombre
                            if tid and not acc["id"]:
                                acc["id"] = tid
                            if tc.get("extra_content"):  # Gemini 3: firma de pensamiento que hay que devolver
                                acc["extra"] = tc["extra_content"]
                            a = f.get("arguments")
                            if a:
                                acc["args"] += a if isinstance(a, str) else json.dumps(a)
        except httpx.TimeoutException as e:
            raise ErrorProveedor("timeout", str(e)) from e
        except httpx.HTTPError as e:
            raise ErrorProveedor("red", str(e)) from e
        finally:
            if self.activa == r.id:
                self.activa = None

        llamadas = [{"name": v["name"], "args": v["args"] or "{}", **({"extra": v["extra"]} if v.get("extra") else {})}
                    for _, v in sorted(acumulado.items()) if v["name"]]
        if tools and not nativo:
            limpio, extra = extraer_protocolo(texto)
            if extra:
                texto, llamadas = limpio, llamadas + extra
        if not texto.strip() and not llamadas:
            raise ErrorProveedor("vacio", "el modelo no devolvió nada")

        total = time.time() - t0
        lat = (primer_token or time.time()) - t0
        r.latencia = lat if not r.latencia else r.latencia * 0.7 + lat * 0.3
        r.fallos = 0
        r.motivo = ""
        tokens = (usage or {}).get("total_tokens") or (sum(len(_texto_de(m.get("content"))) for m in msgs) + len(texto)) // 4
        r.contar(int(tokens))
        self.guardar()
        self._avisar()
        for ll in llamadas:
            ll["id"] = _id_corto()
            # algunos modelos envuelven la llamada en nuestro formato de protocolo: lo desenvolvemos
            try:
                a = json.loads(ll["args"]) if isinstance(ll["args"], str) else ll["args"]
            except ValueError:
                a = None
            if isinstance(a, dict) and isinstance(a.get("args"), dict) and (a.get("nombre") or a.get("name")):
                ll["name"], ll["args"] = a.get("nombre") or a.get("name"), json.dumps(a["args"], ensure_ascii=False)
        yield {"type": "fin", "texto": texto, "llamadas": llamadas, "ranura": r.id, "proveedor": prov["nombre"],
               "modelo": r.modelo, "segundos": round(total, 2), "tokens": int(tokens)}

    async def completar(self, mensajes: list, nivel: str = "rapido", vision: bool = False, herramientas_fijas: list | None = None) -> str:
        texto = ""
        async for ev in self.stream(mensajes, herramientas_fijas, nivel, vision):
            if ev["type"] == "reset":
                texto = ""
            elif ev["type"] == "delta":
                texto += ev["text"]
        return texto.strip()

    async def probar(self) -> list[dict]:
        """Hace una llamada real y mínima a cada proveedor configurado (por cada llave) y dice si responde."""
        mensajes = [{"role": "system", "content": "Responde solo con la palabra: listo"}, {"role": "user", "content": "¿Estás en línea?"}]
        grupos: dict[tuple, list[Ranura]] = {}
        for r in self.ranuras:
            grupos.setdefault((r.prov["id"], r.n_llave), []).append(r)

        async def una(clave, ranuras):
            prov = ranuras[0].prov
            res = {"id": prov["id"], "nombre": prov["nombre"], "llave": clave[1] + 1, "modelos": len(ranuras), "ok": False}
            for r in sorted(ranuras, key=lambda x: x.rango)[:3]:  # si un modelo fue retirado, prueba el siguiente
                try:
                    async for ev in self._stream_ranura(r, mensajes, None, False):
                        if ev["type"] == "fin":
                            res.update(ok=True, modelo=r.modelo, segundos=ev["segundos"], respuesta=ev["texto"][:60])
                    r.enfriar_hasta, r.motivo = 0, ""
                    return res
                except ErrorProveedor as e:
                    self._penalizar(r, e)
                    res.update(modelo=r.modelo, error=r.motivo or e.tipo, detalle=e.detalle[:160])
                    if e.tipo in ("llave", "creditos", "cuota_diaria"):  # problema de la cuenta: otro modelo no ayuda
                        return res
                except Exception as e:  # noqa: BLE001  (una prueba nunca debe tumbar las demás)
                    res.update(modelo=r.modelo, error="error interno", detalle=f"{type(e).__name__}: {e}"[:160])
                    return res
            return res

        resultados = await asyncio.gather(*(una(k, v) for k, v in grupos.items()))
        self.guardar(True)
        self._avisar()
        return sorted(resultados, key=lambda x: (not x["ok"], x["nombre"]))

    async def transcribir(self, audio: bytes, nombre: str = "audio.webm") -> str:
        """Voz a texto con Whisper gratis (Groq), rotando llaves."""
        for prov in CATALOGO:
            if not prov.get("stt"):
                continue
            for llave in config.env_lista(prov["llave"]):
                try:
                    r = await self.cliente.post(f"{prov['base']}/audio/transcriptions", headers={"Authorization": f"Bearer {llave}"},
                                                data={"model": prov["stt"], "language": "es", "response_format": "json"},
                                                files={"file": (nombre, audio)}, timeout=60)
                    if r.status_code == 200:
                        return r.json().get("text", "").strip()
                    log.warning("STT %s: %s %s", prov["id"], r.status_code, r.text[:200])
                except httpx.HTTPError as e:
                    log.warning("STT %s: %s", prov["id"], e)
        raise SinProveedores("No hay servicio de transcripción disponible (agrega GROQ_API_KEY).")

    # ----- estado para la interfaz -----
    def estado(self) -> dict:
        ahora = time.time()
        provs = {}
        for pid, info in self.proveedores_info.items():
            provs[pid] = {**info, "ranuras": 0, "libres": 0, "peticiones_dia": 0, "tokens_dia": 0, "proximo": 0, "motivo": "", "activo": False, "modelos": []}
        hoy = time.strftime("%Y-%m-%d")
        for r in self.ranuras:
            p = provs[r.prov["id"]]
            p["ranuras"] += 1
            libre = r.libre(ahora)
            p["libres"] += libre
            if r.dia == hoy:
                p["peticiones_dia"] += r.peticiones_dia
                p["tokens_dia"] += r.tokens_dia
            if not libre:
                falta = r.enfriar_hasta - ahora
                p["proximo"] = falta if not p["proximo"] else min(p["proximo"], falta)
                p["motivo"] = r.motivo
            if r.id == self.activa:
                p["activo"] = True
            p["modelos"].append({"id": r.modelo, "libre": libre, "motivo": r.motivo if not libre else "", "falta": max(0, int(r.enfriar_hasta - ahora)),
                                 "latencia": round(r.latencia, 2), "hoy": r.peticiones_dia if r.dia == hoy else 0, "tools": r.tools, "vision": r.vision})
        orden = [p["id"] for p in CATALOGO]
        return {
            "estrategia": self.estrategia,
            "activa": self.activa,
            "total": len(self.ranuras),
            "libres": sum(r.libre(ahora) for r in self.ranuras),
            "proveedores": [provs[i] for i in orden if i in provs],
        }

    def reiniciar_enfriamientos(self):
        for r in self.ranuras:
            r.enfriar_hasta, r.motivo, r.fallos = 0, "", 0
        self.guardar(True)
        self._avisar()
