"""«Maicol, saca analíticas»: un tablero para pensar en voz alta (la idea de LienzzonzoNZO, dentro de Maicol).

El señor cuenta lo que quiere aclarar (un negocio, una decisión, «¿por qué me dejó mi ex?») y Maicol la construye
con él como un socio: hace cuentas, propone, advierte riesgos y pregunta solo lo que destraba. Un escriba automático
(escribir) pasa al tablero, después de cada vuelta, lo que él dijo y lo que Maicol aportó: no depende de que la IA
se acuerde de anotar. El tablero se guarda (data/tableros/) y se retoma.

Maicol decide dónde mostrarlo (superficies.py): en su panel, en una ventana grande propia o en el celular.
Todas las pantallas lo ven cambiar en vivo y el señor también puede mover, editar o borrar tarjetas a mano.
"""
import asyncio
import difflib
import json
import logging
import math
import re
import time
import uuid

from . import config, superficies
from .herramientas import P, _sin_tildes, herramienta

log = logging.getLogger("jarvis.analisis")
CARPETA = config.DATOS / "tableros"
ACTIVO = config.DATOS / "analisis_activo.json"
VIGENCIA = 3 * 3600  # una sesión de análisis sigue «abierta» 3 h después del último cambio
DIFUNDIR = None  # async fn(evento): lo conecta el servidor al arrancar

ANCHO, ALTO, HUECO = 286, 170, 34  # tarjeta (px del tablero) y espacio mínimo entre tarjetas
TIPOS = {"tema", "problema", "idea", "pregunta", "respuesta", "emocion", "evidencia", "hallazgo", "requisito", "riesgo",
         "opcion", "dato", "accion", "conclusion", "seccion", "lista"}
ALIAS = {"raiz": "tema", "central": "tema", "problem": "problema", "question": "pregunta", "emoción": "emocion",
         "sentimiento": "emocion", "hecho": "evidencia", "insight": "hallazgo", "patron": "hallazgo", "patrón": "hallazgo",
         "solucion": "opcion", "solución": "opcion", "alternativa": "opcion", "metrica": "dato", "métrica": "dato",
         "paso": "accion", "acción": "accion", "siguiente paso": "accion", "conclusión": "conclusion", "claridad": "conclusion",
         "grupo": "seccion", "sección": "seccion", "parte": "seccion", "area": "seccion", "checklist": "lista",
         "lista de chequeo": "lista", "pendientes": "lista", "tareas": "lista"}
HERRAMIENTAS_TABLERO = {"saca_analiticas", "tablero", "mostrar_tablero", "tableros", "terminar_analisis", "reorganizar_tablero",
                        "borrar_analisis"}
# vueltas que son órdenes sobre el tablero (abrirlo, ordenarlo): el escriba no las anota como tarjetas
ORDENES_TABLERO = HERRAMIENTAS_TABLERO - {"tablero"}


# ───────────────────────── guardar y leer ─────────────────────────
def _ruta(ident: str):
    return CARPETA / f"{re.sub(r'[^a-z0-9]', '', ident.lower())}.json"


def leer(ident: str) -> dict | None:
    try:
        return json.loads(_ruta(ident).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def guardar(t: dict):
    CARPETA.mkdir(parents=True, exist_ok=True)
    t["actualizado"] = time.time()
    _ruta(t["id"]).write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")


def todos() -> list[dict]:
    out = []
    for f in CARPETA.glob("*.json") if CARPETA.is_dir() else []:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except ValueError:
            continue
    return sorted(out, key=lambda t: t.get("actualizado", 0), reverse=True)


def crear(titulo: str, tema: str = "") -> dict:
    t = {"id": uuid.uuid4().hex[:8], "titulo": titulo.strip()[:80] or "Análisis", "tema": tema.strip()[:300],
         "nodos": [], "conexiones": [], "seq": 0, "creado": time.time()}
    guardar(t)
    return t


def activo() -> dict | None:
    """El tablero de la sesión de análisis en curso (si se movió en las últimas horas)."""
    try:
        ident = json.loads(ACTIVO.read_text(encoding="utf-8"))["id"]
    except (OSError, ValueError, KeyError):
        return None
    t = leer(ident)
    vigencia = VIGENCIA if t and t["nodos"] else 20 * 60  # un tablero vacío no deja el análisis abierto toda la tarde
    return t if t and time.time() - t.get("actualizado", 0) < vigencia else None


def _escribir(t: dict):
    """Guarda sin tocar «actualizado» (para anotaciones internas que no son trabajo en el tablero)."""
    CARPETA.mkdir(parents=True, exist_ok=True)
    _ruta(t["id"]).write_text(json.dumps(t, ensure_ascii=False, indent=1), encoding="utf-8")


def activar(t: dict | None):
    """Abre (o cierra con None) el análisis en curso. Cada tablero lleva sus «ratos»: cuándo estuvo abierto, para
    que si el señor pide borrarlo se borre también la conversación de esos ratos (borrar_analisis)."""
    ahora = time.time()
    try:
        anterior = json.loads(ACTIVO.read_text(encoding="utf-8"))["id"]
    except (OSError, ValueError, KeyError):
        anterior = None
    if anterior and (not t or anterior != t["id"]) and (a := leer(anterior)) and a.get("ratos") and a["ratos"][-1][1] is None:
        a["ratos"][-1][1] = ahora
        _escribir(a)
    if t:
        ratos = t.setdefault("ratos", [])
        if anterior != t["id"] or not ratos or ratos[-1][1] is not None:
            ratos.append([ahora, None])
            if _ruta(t["id"]).exists():
                guardado = leer(t["id"]) or t
                guardado["ratos"] = ratos
                _escribir(guardado)
        ACTIVO.write_text(json.dumps({"id": t["id"]}), encoding="utf-8")
    else:
        ACTIVO.unlink(missing_ok=True)


def buscar(nombre: str | None) -> dict | None:
    # los proyectos con contenido primero: «el de los pollos» es el que tiene tarjetas, no un tablero vacío
    lista = sorted(todos(), key=lambda t: not t["nodos"])
    if not nombre:
        return activo() or next(iter(lista), None)
    if exacto := next((t for t in lista if t["id"] == nombre.strip()), None):
        return exacto
    clave = _sin_tildes(nombre)
    for t in lista:  # el más reciente cuyo título o tema contenga todas las palabras
        donde = _sin_tildes(f"{t['titulo']} {t.get('tema', '')}")
        palabras = [w for w in re.findall(r"\w+", clave)
                    if len(w) > 2 and w not in ("tablero", "analisis", "proyecto", "reabre", "retoma", "del", "las", "los", "que")]
        if palabras and all(w in donde for w in palabras):
            return t
    titulos: dict[str, dict] = {}
    for t in lista:  # con títulos repetidos gana el primero (el que tiene contenido)
        titulos.setdefault(_sin_tildes(t["titulo"]), t)
    cerca = difflib.get_close_matches(clave, list(titulos), n=1, cutoff=0.5)
    return titulos[cerca[0]] if cerca else None


# ───────────────────────── acomodar tarjetas ─────────────────────────
def _choca(x: float, y: float, nodos: list[dict]) -> bool:
    return any(x < n["x"] + ANCHO + HUECO and x + ANCHO + HUECO > n["x"] and y < n["y"] + ALTO + HUECO and y + ALTO + HUECO > n["y"]
               for n in nodos)


def _posicion(nodos: list[dict], ancla: dict | None, estilo: str, i: int, total: int) -> tuple[float, float]:
    """Como en LienzzonzoNZO: «arbol» = hijos en fila debajo del padre (pasos, listas, pros/contras); «radial» = ideas
    alrededor del padre (lluvia de ideas); «isla» = tema aparte, lejos de lo que ya hay."""
    if not nodos:
        return 0.0, 0.0
    if estilo == "isla" or ancla is None:
        x0 = max(n["x"] for n in nodos) + ANCHO + 420
        y0 = min(n["y"] for n in nodos)
        for intento in range(40):
            x, y = x0 + (intento % 3) * (ANCHO + 58), y0 + (intento // 3) * (ALTO + 54)
            if not _choca(x, y, nodos):
                return x, y
        return x0, y0
    if estilo == "arbol":
        x = ancla["x"] + (i - (total - 1) / 2) * (ANCHO + 64)
        y = ancla["y"] + ALTO + 150
        for _ in range(12):
            if not _choca(x, y, nodos):
                break
            y += ALTO + HUECO
        return x, y
    base = -math.pi / 2 + i * 0.92  # radial: se buscan huecos en anillos alrededor del padre
    for anillo in range(6):
        rx, ry = 390 + anillo * ANCHO * 0.72, 270 + anillo * ALTO * 0.72
        for giro in (0, 0.42, -0.42, 0.84, -0.84, 1.28, -1.28, math.pi):
            x, y = ancla["x"] + math.cos(base + giro) * rx, ancla["y"] + math.sin(base + giro) * ry
            if not _choca(x, y, nodos):
                return x, y
    return ancla["x"] + 390 + i * 44, ancla["y"] + i * 42


def _tipo(valor) -> str:
    t = _sin_tildes(str(valor or "idea")).strip()
    t = ALIAS.get(t, t)
    return t if t in TIPOS else "idea"


def _datos(texto) -> list[dict]:
    """«Ventas: 120; Costos: 80» -> barras pequeñas dentro de la tarjeta."""
    out = []
    for parte in re.split(r"[;\n]", str(texto or "")):
        m = re.match(r"\s*(.+?)\s*[:=]\s*(-?[\d.,]+)\s*(%?)", parte)
        if m:
            try:
                out.append({"etiqueta": m.group(1)[:40], "valor": float(m.group(2).replace(",", "")), "unidad": m.group(3)})
            except ValueError:
                continue
    return out[:8]


def _alto(n: dict) -> int:
    """Lo que mide más o menos una tarjeta (las listas crecen con sus elementos)."""
    return ALTO + (min(len(n["items"]), 12) * 24 if n.get("items") else 0)


def _acomodar(t: dict):
    """Reacomoda todo como un mapa mental: el tema en el centro, sus secciones repartidas a lado y lado (equilibrando
    el peso, no en espejo) y lo de cada sección abriéndose hacia afuera, cada rama del alto que necesita."""
    _sin_sueltas(t)
    madre, hijos = {}, {}
    for c in t["conexiones"]:
        if c["a"] not in madre and c["a"] != c["de"]:
            madre[c["a"]] = c["de"]
            hijos.setdefault(c["de"], []).append(c["a"])
    por_id = {n["id"]: n for n in t["nodos"]}
    raices = sorted((n for n in t["nodos"] if n["id"] not in madre), key=lambda n: n["tipo"] != "tema")
    if not raices:
        return
    paso, hueco, entre_ramas = ANCHO + 80, 26, 64
    alturas: dict[str, float] = {}

    def debajo(ident: str, vistos: frozenset) -> list[str]:
        return [h for h in hijos.get(ident, []) if h in por_id and h not in vistos]

    def alto_rama(ident: str, vistos=frozenset()) -> float:
        if ident not in alturas:
            vistos = vistos | {ident}
            kids = debajo(ident, vistos)
            juntos = sum(alto_rama(k, vistos) for k in kids) + hueco * max(len(kids) - 1, 0)
            alturas[ident] = max(_alto(por_id[ident]), juntos)
        return alturas[ident]

    def poner(ident: str, x: float, arriba: float, lado: int, vistos=frozenset()):
        n, alto = por_id[ident], alto_rama(ident)
        n["x"], n["y"] = round(x), round(arriba + (alto - _alto(n)) / 2)
        vistos = vistos | {ident}
        kids = debajo(ident, vistos)
        y = arriba + (alto - sum(alturas[k] for k in kids) - hueco * max(len(kids) - 1, 0)) / 2
        for k in kids:
            poner(k, x + lado * paso, y, lado, vistos)
            y += alturas[k] + hueco

    x_libre = 0.0
    for raiz in raices:
        ramas = debajo(raiz["id"], frozenset({raiz["id"]}))
        lados: dict[int, list[str]] = {1: [], -1: []}
        peso = {1: 0.0, -1: 0.0}
        for r in ramas:  # cada rama al lado más liviano: queda equilibrado sin ser un espejo
            lado = 1 if peso[1] <= peso[-1] else -1
            lados[lado].append(r)
            peso[lado] += alto_rama(r, frozenset({raiz["id"]})) + entre_ramas
        hondo = {l: max((_hondo(r, hijos) for r in lados[l]), default=0) for l in lados}
        cx = x_libre + (hondo[-1] * paso + 80 if lados[-1] else 0)
        raiz["x"], raiz["y"] = round(cx), round(-_alto(raiz) / 2)
        for lado, lista in lados.items():
            y = -(peso[lado] - entre_ramas) / 2
            for r in lista:
                poner(r, cx + lado * (paso + 80), y, lado, frozenset({raiz["id"]}))
                y += alturas[r] + entre_ramas
        x_libre = cx + ANCHO + (hondo[1] * paso + 80 if lados[1] else 0) + 300


def _hondo(ident: str, hijos: dict, vistos=frozenset()) -> int:
    """Cuántos niveles baja una rama (para dejarle espacio a lo ancho)."""
    vistos = vistos | {ident}
    return 1 + max((_hondo(h, hijos, vistos) for h in hijos.get(ident, []) if h not in vistos), default=0)


def _sin_sueltas(t: dict):
    """Toda tarjeta cuelga de algo: lo que quedó sin madre (porque se borró su sección, por ejemplo) pasa al tema,
    en vez de quedar como una columna aparte que estira el tablero."""
    raiz = next((n for n in t["nodos"] if n["tipo"] == "tema"), None)
    if not raiz:
        return
    con_madre = {c["a"] for c in t["conexiones"]}
    for n in t["nodos"]:
        if n is not raiz and n["id"] not in con_madre:
            t["conexiones"].append({"de": raiz["id"], "a": n["id"], "etiqueta": ""})


def _ordenado(t: dict) -> bool:
    """Un tablero armado por secciones se mantiene como esquema: al agregar o mover algo se reacomoda solo."""
    return any(n["tipo"] == "seccion" for n in t["nodos"])


def _items(valor) -> list[dict]:
    """«2 spikes; recogedor de grasas; cajas» (o una lista) -> casillas para chulear."""
    crudos = valor if isinstance(valor, list) else re.split(r"[;\n]|(?:^|\s)-\s|,\s+(?=[a-záéíóúñ0-9])", str(valor or ""))
    out = []
    for x in crudos:
        texto = (x.get("texto") if isinstance(x, dict) else str(x)).strip(" -•*·,.")
        if texto:
            out.append({"texto": texto[:120], "hecho": bool(x.get("hecho")) if isinstance(x, dict) else False})
    return out[:40]


def aplicar(t: dict, acciones: list[dict]) -> dict:
    """Crear, cambiar, borrar, conectar o enfocar tarjetas. Devuelve qué pasó, con los ids para seguir usándolos."""
    por_id = {n["id"]: n for n in t["nodos"]}
    temporales: dict[str, dict] = {}
    hecho = {"creadas": [], "cambiadas": [], "borradas": [], "conectadas": 0, "enfoque": None, "errores": [], "movidas": 0}

    def nodo(ref) -> dict | None:
        ref = str(ref or "").strip()
        return por_id.get(ref) or temporales.get(ref)

    # cuántos hijos nuevos tiene cada padre con cada estilo: el árbol los centra bajo el padre
    totales: dict[tuple, int] = {}
    for a in acciones:
        if _sin_tildes(str(a.get("accion", ""))) == "crear":
            clave = (_sin_tildes(str(a.get("estilo") or "radial")), str(a.get("conectar_a") or ""))
            totales[clave] = totales.get(clave, 0) + 1
    vistos: dict[tuple, int] = {}

    for a in acciones[:20]:
        accion = _sin_tildes(str(a.get("accion", "")))
        if accion == "crear" and (igual := _ya_existe(t, a)):
            # ya hay una tarjeta con ese título («crea la de marketing en su sección»): se usa esa, no un duplicado
            if a.get("ref"):
                temporales[str(a["ref"]).strip()] = igual
            madre = nodo(a.get("conectar_a"))
            if madre and madre is not igual and not _desciende(t, madre["id"], igual["id"]):
                t["conexiones"] = [c for c in t["conexiones"] if c["a"] != igual["id"]]
                t["conexiones"].append({"de": madre["id"], "a": igual["id"], "etiqueta": str(a.get("etiqueta") or "")[:40]})
                hecho["movidas"] += 1
            if a.get("texto") and not igual["texto"]:
                igual["texto"] = str(a["texto"]).strip()[:500]
            if a.get("items"):
                ya = {_sin_tildes(i["texto"]) for i in igual.setdefault("items", [])}
                igual["items"] += [i for i in _items(a["items"]) if _sin_tildes(i["texto"]) not in ya]
            hecho["cambiadas"].append(igual["id"])
        elif accion == "crear":
            estilo = _sin_tildes(str(a.get("estilo") or "radial"))
            estilo = estilo if estilo in ("arbol", "radial", "isla") else "radial"
            tipo = _tipo(a.get("tipo"))
            if tipo == "tema" and estilo != "isla" and any(n["tipo"] == "tema" for n in t["nodos"]):
                tipo = "idea"  # un solo tema por tablero; un segundo «tema» es un subtema (salvo que sea una isla aparte)
            padre = nodo(a.get("conectar_a"))
            if not padre and estilo != "isla" and tipo != "tema":
                # sin madre: del tema nuevo de este mismo pedido o, si no, del tema principal (nada queda suelto)
                padre = next((n for n in [nodo(i) for i in hecho["creadas"]] + t["nodos"] if n and n["tipo"] == "tema"), None)
            clave = (estilo, str(a.get("conectar_a") or ""))
            i = vistos.get(clave, 0)
            vistos[clave] = i + 1
            x, y = _posicion(t["nodos"], padre, estilo, i, totales.get(clave, 1))
            t["seq"] += 1
            n = {"id": f"t{t['seq']}", "tipo": tipo, "titulo": str(a.get("titulo") or "Tarjeta").strip()[:80],
                 "texto": str(a.get("texto") or "").strip()[:500], "x": round(x), "y": round(y), "creada": time.time()}
            if d := _datos(a.get("datos")):
                n["datos"] = d
            if a.get("items") or tipo == "lista":
                n["tipo"], n["items"] = "lista", _items(a.get("items"))
            t["nodos"].append(n)
            por_id[n["id"]] = n
            if a.get("ref"):
                temporales[str(a["ref"]).strip()] = n
            if padre:
                t["conexiones"].append({"de": padre["id"], "a": n["id"], "etiqueta": str(a.get("etiqueta") or "")[:40]})
            hecho["creadas"].append(n["id"])
        elif accion in ("cambiar", "actualizar"):
            n = nodo(a.get("id"))
            if not n:
                hecho["errores"].append(f"no existe la tarjeta {a.get('id')}")
                continue
            for campo in ("titulo", "texto"):
                if a.get(campo):
                    n[campo] = str(a[campo]).strip()[:80 if campo == "titulo" else 500]
            if a.get("tipo"):
                n["tipo"] = _tipo(a["tipo"])
            if a.get("datos"):
                n["datos"] = _datos(a["datos"])
            if a.get("items"):
                n["tipo"], n["items"] = "lista", _items(a["items"])
            n["cambiada"] = time.time()
            hecho["cambiadas"].append(n["id"])
        elif accion == "borrar":
            n = nodo(a.get("id"))
            if not n:
                continue
            # lo que colgaba de ella no se pierde: pasa a la madre de la borrada
            arriba = next((c["de"] for c in t["conexiones"] if c["a"] == n["id"]), None)
            hijas = [c for c in t["conexiones"] if c["de"] == n["id"]]
            t["nodos"] = [x for x in t["nodos"] if x["id"] != n["id"]]
            t["conexiones"] = [c for c in t["conexiones"] if n["id"] not in (c["de"], c["a"])]
            if arriba:
                t["conexiones"] += [{**c, "de": arriba} for c in hijas]
            por_id.pop(n["id"], None)
            hecho["borradas"].append(n["id"])
        elif accion == "conectar":
            de, a_ = nodo(a.get("id") or a.get("de")), nodo(a.get("conectar_a") or a.get("a"))
            if de and a_ and de is not a_:
                t["conexiones"].append({"de": de["id"], "a": a_["id"], "etiqueta": str(a.get("etiqueta") or "")[:40]})
                hecho["conectadas"] += 1
        elif accion == "agregar":  # elementos nuevos en una lista que ya existe
            n = nodo(a.get("id"))
            if not n:
                hecho["errores"].append(f"no existe la lista {a.get('id')}")
                continue
            n["tipo"] = "lista"
            ya = {_sin_tildes(i["texto"]) for i in n.setdefault("items", [])}
            n["items"] += [i for i in _items(a.get("items")) if _sin_tildes(i["texto"]) not in ya]
            n["cambiada"] = time.time()
            hecho["cambiadas"].append(n["id"])
        elif accion == "marcar":  # «ya conseguí las cajas»: se chulea (o se desmarca)
            n = nodo(a.get("id"))
            if not n or not n.get("items"):
                continue
            hecho_ = a.get("hecho", True) not in (False, "false", "no", 0)
            if isinstance(a.get("indice"), int) and 0 <= a["indice"] < len(n["items"]):
                elegidos = [n["items"][a["indice"]]]
            else:
                buscado = _sin_tildes(str(a.get("item") or a.get("texto") or ""))
                elegidos = [i for i in n["items"] if buscado and (buscado in _sin_tildes(i["texto"]) or _sin_tildes(i["texto"]) in buscado)]
            for i in elegidos:
                i["hecho"] = hecho_
            if elegidos:
                n["cambiada"] = time.time()
                hecho["cambiadas"].append(n["id"])
        elif accion in ("mover_a", "reubicar"):  # cuelga la tarjeta de otra madre (para ordenar por secciones)
            n, madre = nodo(a.get("id")), nodo(a.get("conectar_a"))
            if not n or not madre or n is madre:
                continue
            if _desciende(t, madre["id"], n["id"]):
                continue  # colgarla de su propia hija haría un círculo
            t["conexiones"] = [c for c in t["conexiones"] if c["a"] != n["id"]]
            t["conexiones"].append({"de": madre["id"], "a": n["id"], "etiqueta": str(a.get("etiqueta") or "")[:40]})
            hecho["movidas"] += 1
            otros = [x for x in t["nodos"] if x is not n]
            hermanos = sum(1 for c in t["conexiones"] if c["de"] == madre["id"]) - 1
            n["x"], n["y"] = (round(v) for v in _posicion(otros, madre, "arbol", hermanos, hermanos + 1))
            hecho["cambiadas"].append(n["id"])
        elif accion == "enfocar":
            n = nodo(a.get("id"))
            if n:
                hecho["enfoque"] = n["id"]
        elif accion in ("titular", "renombrar") and a.get("titulo"):
            t["titulo"] = str(a["titulo"]).strip()[:80]
    if not hecho["enfoque"] and hecho["creadas"]:
        hecho["enfoque"] = hecho["creadas"][-1]
    if _ordenado(t) and (hecho["creadas"] or hecho["borradas"] or hecho["movidas"]):
        _acomodar(t)  # lo nuevo o movido queda pegado a su sección, no a mil pixeles
    return hecho


def _ya_existe(t: dict, a: dict) -> dict | None:
    titulo = _sin_tildes(str(a.get("titulo") or "")).strip(" .")
    if not titulo or _tipo(a.get("tipo")) == "tema":
        return None
    return next((n for n in t["nodos"] if n["tipo"] != "tema" and _sin_tildes(n["titulo"]).strip(" .") == titulo), None)


def _desciende(t: dict, ident: str, de: str) -> bool:
    """¿ident cuelga (directa o indirectamente) de la tarjeta de?"""
    pendientes, vistos = [de], set()
    while pendientes:
        x = pendientes.pop()
        for c in t["conexiones"]:
            if c["de"] == x and c["a"] not in vistos:
                if c["a"] == ident:
                    return True
                vistos.add(c["a"])
                pendientes.append(c["a"])
    return False


def resumen(t: dict, maximo: int = 40) -> str:
    """El tablero en texto compacto, para que Maicol sepa qué hay sin mandarle miles de tokens."""
    if not t["nodos"]:
        return "(vacío)"
    padres = {c["a"]: c["de"] for c in t["conexiones"]}
    lineas = []
    for n in t["nodos"][-maximo:]:
        cuelga = f" ←{padres[n['id']]}" if n["id"] in padres else ""
        lista = ("; ".join(("[x] " if i["hecho"] else "[ ] ") + i["texto"] for i in n["items"])) if n.get("items") else ""
        lineas.append(f"- {n['id']} [{n['tipo']}]{cuelga} {n['titulo']}: {n['texto'][:90]}" + (f" | {lista[:300]}" if lista else ""))
    return "\n".join(lineas)


async def avisar(t: dict, enfoque: str | None = None):
    if DIFUNDIR:
        await DIFUNDIR({"type": "tablero", "tablero": t, "enfoque": enfoque})


CANDADO = asyncio.Lock()  # el escriba y Maicol no escriben el tablero a la vez


def _titular_si_falta(t: dict):
    """Si nadie lo tituló, el tablero se llama como su tema."""
    raiz = next((n for n in t["nodos"] if n["tipo"] == "tema"), None)
    if t["titulo"] == "Análisis" and raiz:
        generico = len(raiz["titulo"].split()) < 2 and raiz["texto"]
        t["titulo"] = (raiz["texto"] if generico else raiz["titulo"])[:60].rstrip(" .,")


ESCRIBA = """Eres el escriba del tablero de análisis de Maicol, un asistente que está construyendo una idea con el señor.
Recibes el tablero actual, lo último que dijo el señor y lo que respondió Maicol. Pasa al tablero TODO lo nuevo:
- Del señor: cada dato, número, recurso, restricción, decisión, idea, duda o emoción, en su propia tarjeta
  (tipo dato, requisito, idea, problema, emocion, evidencia, pregunta…). Lo que pide hacer («analicemos X») no es
  una tarjeta: es el tema.
- De Maicol: lo que aportó (cuentas, estimaciones, ideas, opciones, riesgos, recomendaciones, conclusiones), como
  hallazgo, idea, opcion, riesgo, accion o conclusion. Una tarjeta por aporte, no un resumen de todo. Sus preguntas no
  se anotan, salvo una duda clave que siga abierta y no esté ya en el tablero.
- 'datos' (barras) solo para 2 a 5 cantidades comparables en la MISMA unidad («Ingreso diario: 2400000; Costo diario:
  1440000»). Nada de horas, porcentajes mezclados ni cifras sueltas: esas van en el texto.
Estructura (lo más importante: un esquema ordenado, no todo colgado del tema):
- Bajo el tema van SECCIONES (tipo seccion): las partes de la idea, ej. en un negocio «Operación», «Números»,
  «Clientes y ventas», «Pendientes»; en algo personal «Lo que pasó», «Lo que siento», «Lo que depende de mí».
- Cada tarjeta nueva cuelga de la tarjeta MÁS específica a la que pertenece (una sección, o una tarjeta concreta:
  un costo cuelga de «Números», la duda del precio de la tarjeta del precio…). Del tema solo cuelgan secciones.
  Si no existe la sección adecuada, créala en este mismo pedido (con ref) y cuelga ahí lo nuevo.
- Usa conectar_a con el id existente o el 'ref' de una tarjeta creada en este pedido, y una etiqueta corta en la flecha.
Listas: si él pide una lista («haz una lista de lo que falta», «enlistemos…»), crea UNA tarjeta tipo lista con 'items'
(«2 spikes; recogedor de grasas; cajas»). Si dice cosas para una lista que ya existe («anota ahí…», «agrega…»), usa
'agregar' con el id de esa lista y los 'items': NUNCA tarjetas sueltas para cada elemento. Si dice que ya tiene o hizo
algo de una lista, usa 'marcar' con el id de la lista y el 'item'.
Si algo ya está, no lo repitas: usa 'cambiar' sobre esa tarjeta si se precisó o corrigió. Si no hay tarjeta 'tema',
créala primero (con ref "tema") y usa 'titular' con un título corto del tablero. Títulos de máximo 6 palabras; texto
de 1 o 2 frases, concreto, con las cifras. Si lo dicho no tiene que ver con el tema (música, abrir el tablero,
saludos), no anotes nada. Las órdenes sobre el tablero mismo («organízalo», «compacta el esquema», «mueve la de
marketing a…», «junta esto con…») tampoco: no crees ninguna tarjeta ni sección sobre ordenar el tablero.
Responde SOLO con JSON: {"acciones": [{"accion": "crear", "ref": "…", "tipo": "…", "titulo": "…", "texto": "…",
"conectar_a": "…", "etiqueta": "…", "estilo": "arbol|radial", "datos": "…", "items": "…"},
{"accion": "agregar", "id": "t9", "items": "a; b"}, {"accion": "marcar", "id": "t9", "item": "a"},
{"accion": "cambiar", "id": "t3", "texto": "…"}, {"accion": "titular", "titulo": "…"}]}  — o {"acciones": []} si no hay nada nuevo."""


REORGANIZAR = """Ordenas el tablero de análisis de Maicol, que quedó desordenado (todo colgado del tema). Devuelve SOLO JSON
{"acciones": [...]} para dejarlo como un esquema claro, sin perder nada de lo que dice:
- Si ya hay secciones (tipo seccion), REUTILÍZALAS con su id: no las borres ni crees otra igual. Crea secciones nuevas
  (tipo seccion, con ref) solo para partes de la idea que aún no tengan una (ej. «Operación», «Números», «Clientes y
  ventas», «Pendientes», «Dudas abiertas») y solo si les vas a colgar algo: de 3 a 6 secciones en total, con nombres del
  tema (nada como «Analítica», «Varios» u «Organización»).
- Usa 'mover_a' con id y conectar_a (id o ref de una sección o de la tarjeta más relacionada) para TODA tarjeta que
  cuelgue del tema o de una sección que no le corresponde. Del tema solo deben colgar secciones.
- Tarjetas repetidas (el mismo asunto): 'borrar' la copia y dejar la que tiene más información.
- Si hay una tarjeta que debía ser una lista y elementos sueltos que son de esa lista: 'cambiar' esa tarjeta con 'items'
  (todos los elementos, uno por uno) y 'borrar' las tarjetas sueltas que quedaron dentro de la lista.
- Las preguntas ya respondidas en otras tarjetas se pueden 'borrar'. No inventes información nueva.
Formato: {"accion": "crear", "ref": "ops", "tipo": "seccion", "titulo": "Operación", "conectar_a": "t1"},
{"accion": "mover_a", "id": "t4", "conectar_a": "ops", "etiqueta": "…"}, {"accion": "cambiar", "id": "t9", "items": "a; b; c"},
{"accion": "borrar", "id": "t10"}"""


def leer_acciones(salida: str) -> list[dict]:
    """Las acciones que devolvió la IA, aunque venga con texto alrededor, en bloques ```json o como varios objetos
    seguidos en vez de un solo {"acciones": [...]}."""
    decodificador, acciones, i = json.JSONDecoder(), [], 0
    while (i := salida.find("{", i)) != -1:
        try:
            obj, i = decodificador.raw_decode(salida, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict) and isinstance(obj.get("acciones"), list):
            acciones += obj["acciones"]
        elif isinstance(obj, dict) and obj.get("accion"):
            acciones.append(obj)
    return [a for a in acciones if isinstance(a, dict)]


async def reorganizar(router, t: dict) -> dict:
    """Una IA ordena un tablero existente por secciones (y junta en una lista lo que quedó suelto)."""
    prompt = [{"role": "system", "content": REORGANIZAR},
              {"role": "user", "content": f"Tablero «{t['titulo']}» (id [tipo] ←madre título: texto):\n{resumen(t, 80)}"}]
    salida = await asyncio.wait_for(router.completar(prompt, "inteligente"), 60)
    acciones = leer_acciones(salida)
    async with CANDADO:
        t = leer(t["id"]) or t
        hecho = aplicar(t, [a for a in acciones if isinstance(a, dict)])
        _sin_sueltas(t)
        con_hijas = {c["de"] for c in t["conexiones"]}
        for n in [n for n in t["nodos"] if n["tipo"] == "seccion" and n["id"] not in con_hijas]:
            aplicar(t, [{"accion": "borrar", "id": n["id"]}])  # una sección vacía solo estorba
            hecho["creadas"] = [i for i in hecho["creadas"] if i != n["id"]]
        _acomodar(t)
        guardar(t)
    await avisar(t)
    return hecho


async def escribir(router, dicho: str, respuesta: str):
    """El escriba: después de cada vuelta del modo análisis, una IA aparte pasa al tablero lo que el señor dijo y lo
    que Maicol aportó. Corre en segundo plano (la voz no lo espera) y no depende de que Maicol se acuerde de anotar."""
    t = activo()
    if not t or not (dicho or "").strip():
        return
    prompt = [{"role": "system", "content": ESCRIBA},
              {"role": "user", "content": f"Tablero «{t['titulo']}»:\n{resumen(t, 60)}\n\nEl señor dijo:\n{dicho[:1500]}\n\n"
                                          f"Maicol respondió:\n{(respuesta or '')[:1500]}"}]
    await anotando(t, True)
    try:
        salida = await asyncio.wait_for(router.completar(prompt, "inteligente"), 45)
        acciones = leer_acciones(salida)
    except Exception as e:  # noqa: BLE001 — si el escriba falla, la conversación sigue igual
        log.warning("escriba del tablero: %s", e)
        return
    finally:
        await anotando(t, False)
    acciones = [a for a in acciones if isinstance(a, dict)] if isinstance(acciones, list) else []
    if not acciones:
        return
    async with CANDADO:
        t = leer(t["id"]) or t
        hecho = aplicar(t, acciones)
        _titular_si_falta(t)
        guardar(t)
    log.info("escriba: %d tarjetas nuevas, %d cambiadas en «%s»", len(hecho["creadas"]), len(hecho["cambiadas"]), t["titulo"])
    await avisar(t, hecho["enfoque"])


PIZARRA = """Eres la pizarra de Maicol: mientras él le explica algo al señor en voz alta, tú lo muestras al lado del tablero
de análisis, como lo haría un buen profesor en el tablero. Recibes el tablero, lo que dijo el señor y lo que respondió
Maicol. Si la respuesta tiene cuentas, cifras que se comparan u opciones con pros y contras, arma la pizarra:
- "cuenta": la operación paso a paso, una fila por término, con su signo: la primera sin "op"; luego "+", "-", "×", "÷";
  la última con "op": "=" y el resultado ("destacar": true). Ej. precio 42.000 - pollo 22.000 - caja 1.400 = 18.600.
- "tabla": para comparar (escenarios de precio, opciones): "columnas" y "filas" (listas de textos cortos).
- "cifras": 2 a 4 números clave grandes ("etiqueta" y "valor"), ej. punto de equilibrio 45 pollos/día.
- "nota": una frase corta de remate («Con su horno llega a 63: le sobra margen»).
Usa SOLO cifras que dijo Maicol o el señor o que están en el tablero, escritas en pesos colombianos con punto de miles
("42.000", "1,4 M"), y revisa que la aritmética dé. Uno a tres bloques, lo justo. "tarjetas": los ids del tablero de
los que se habla. Si la respuesta no tiene nada que mostrar (una pregunta, un saludo, algo sin cifras ni opciones),
responde {"pizarra": null}.
Responde SOLO JSON: {"pizarra": {"titulo": "Margen por pollo", "bloques": [{"tipo": "cuenta", "filas": [{"etiqueta":
"Precio de venta", "valor": "42.000"}, {"op": "-", "etiqueta": "Costo del pollo", "valor": "22.000"}, {"op": "=",
"etiqueta": "Ganancia", "valor": "20.000", "destacar": true}]}, {"tipo": "tabla", "columnas": ["Precio", "Ganancia"],
"filas": [["42.000", "18.600"], ["40.000", "16.600"]]}, {"tipo": "cifras", "items": [{"etiqueta": "Equilibrio",
"valor": "45 pollos/día"}]}, {"tipo": "nota", "texto": "…"}], "tarjetas": ["t8"]}}"""

_HAY_QUE_MOSTRAR = re.compile(r"\d|opci[oó]n|compar|versus|\bvs\b|pros|contras|ventaja", re.I)


def _cifra(valor) -> float | None:
    """«42.000» -> 42000; «1,4 M» -> 1400000; «18 a 22 mil» -> None (un rango no se recalcula)."""
    s = str(valor or "").strip().lower().replace("$", "").replace("cop", "").replace("pesos", "").strip()
    m = re.fullmatch(r"(-?\d{1,3}(?:\.\d{3})+|-?\d+)(?:,(\d+))?\s*(k|mil|m|millones)?", s)
    if not m:
        return None
    n = float(m.group(1).replace(".", "") + (f".{m.group(2)}" if m.group(2) else ""))
    return n * {"k": 1e3, "mil": 1e3, "m": 1e6, "millones": 1e6}.get(m.group(3) or "", 1)


def _pesos(n: float) -> str:
    return f"{n:,.0f}".replace(",", ".") if abs(n - round(n)) < 0.005 else f"{n:,.2f}".replace(",", "_").replace(".", ",").replace("_", ".")


def _cuadrar(cuenta: dict):
    """La IA a veces se equivoca sumando: si todas las cifras son números, el resultado lo calcula Maicol."""
    filas = cuenta.get("filas") or []
    if len(filas) < 3 or filas[-1].get("op") != "=":
        return
    total = _cifra(filas[0].get("valor"))
    for f in filas[1:-1]:
        v = _cifra(f.get("valor"))
        if total is None or v is None or f.get("op") not in ("+", "-", "−", "×", "x", "*", "÷", "/"):
            return
        op = f["op"]
        total = total + v if op == "+" else total - v if op in ("-", "−") else total * v if op in ("×", "x", "*") else (total / v if v else None)
    if total is not None and _cifra(filas[-1].get("valor")) != round(total, 2):
        filas[-1]["valor"] = _pesos(total)


def _limpiar_pizarra(p) -> dict | None:
    if not isinstance(p, dict):
        return None
    bloques = []
    for b in p.get("bloques") or []:
        if not isinstance(b, dict) or b.get("tipo") not in ("cuenta", "tabla", "cifras", "nota"):
            continue
        if b["tipo"] == "cuenta" and isinstance(b.get("filas"), list):
            b["filas"] = [{k: (str(v)[:60] if k != "destacar" else bool(v)) for k, v in f.items() if k in ("op", "etiqueta", "valor", "destacar")}
                          for f in b["filas"][:8] if isinstance(f, dict)]
            _cuadrar(b)
        elif b["tipo"] == "tabla":
            b = {"tipo": "tabla", "columnas": [str(c)[:30] for c in (b.get("columnas") or [])][:5],
                 "filas": [[str(c)[:40] for c in fila][:5] for fila in (b.get("filas") or [])[:8] if isinstance(fila, list)]}
        elif b["tipo"] == "cifras":
            b = {"tipo": "cifras", "items": [{"etiqueta": str(i.get("etiqueta", ""))[:40], "valor": str(i.get("valor", ""))[:30]}
                                             for i in (b.get("items") or [])[:4] if isinstance(i, dict)]}
        elif b["tipo"] == "nota":
            b = {"tipo": "nota", "texto": str(b.get("texto", ""))[:200]}
        if any(b.get(k) for k in ("filas", "items", "texto")):
            bloques.append(b)
    if not bloques:
        return None
    return {"titulo": str(p.get("titulo") or "Pizarra")[:60], "bloques": bloques[:3],
            "tarjetas": [str(i) for i in (p.get("tarjetas") or []) if isinstance(i, str)][:6], "hora": time.time()}


async def pizarra(router, dicho: str, respuesta: str):
    """Mientras Maicol explica, al lado del tablero se ve la cuenta, la tabla o las cifras de lo que está diciendo.
    Corre en paralelo con el escriba; si la respuesta no tiene nada que mostrar, no aparece nada."""
    t = activo()
    if not t or not _HAY_QUE_MOSTRAR.search(respuesta or ""):
        return
    prompt = [{"role": "system", "content": PIZARRA},
              {"role": "user", "content": f"Tablero «{t['titulo']}»:\n{resumen(t, 40)}\n\nEl señor dijo:\n{(dicho or '')[:800]}\n\n"
                                          f"Maicol respondió:\n{respuesta[:1500]}"}]
    try:
        salida = await asyncio.wait_for(router.completar(prompt, "inteligente"), 40)
    except Exception as e:  # noqa: BLE001 — sin pizarra la conversación sigue igual
        log.warning("pizarra: %s", e)
        return
    p = None
    decodificador, i = json.JSONDecoder(), 0
    while p is None and (i := salida.find("{", i)) != -1:
        try:
            obj, i = decodificador.raw_decode(salida, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict) and "pizarra" in obj:
            p = _limpiar_pizarra(obj["pizarra"])
            break
    if not p:
        return
    async with CANDADO:
        t = leer(t["id"]) or t
        t["pizarras"] = (t.get("pizarras") or [])[-7:] + [p]  # las últimas se pueden volver a ver
        guardar(t)
    if DIFUNDIR:
        await DIFUNDIR({"type": "pizarra", "id": t["id"], "pizarra": p})


async def anotando(t: dict, si: bool):
    """Que se vea que el escriba está escribiendo (el lápiz en la cabecera del tablero)."""
    if DIFUNDIR:
        await DIFUNDIR({"type": "escriba", "id": t["id"], "activo": si})


def instruccion() -> str:
    """Para las instrucciones de Maicol mientras hay una sesión de análisis abierta."""
    t = activo()
    if not t:
        return ""
    return f"""

MODO ANÁLISIS ACTIVO — tablero «{t['titulo']}» (id {t['id']}){f", tema: {t['tema']}" if t.get('tema') else ""}.
Eres su socio construyendo esta idea con él, no un entrevistador. Lo que manda es ESTE tablero: si la charla venía de
otro tema, sigue con este. En cada vuelta:
1) Aporta primero, con lo que sabes: haz las cuentas con sus datos (capacidad, costos, márgenes, tiempos, punto de
   equilibrio), propón ideas o caminos concretos, señala riesgos o lo que no está viendo, compara con lo que hacen otros.
   Si falta un dato, asume uno razonable y dilo («suponiendo el pollo a 25 mil…»).
   Usa sus datos tal cual los dijo (revisa horarios y cifras antes de calcular) y trátalo siempre de usted.
2) Pregunta solo si de verdad destraba algo, y una sola. Muchas vueltas terminan sin pregunta, con una propuesta
   («Le propongo arrancar así… ¿le suena?»). Nada de interrogatorio dato por dato. Si ya preguntaste algo y no lo
   respondió, NO lo repitas: asume un valor razonable, dilo y sigue construyendo.
3) Ve armando la idea por partes según el tema (negocio: propuesta de valor, cliente, operación, números, canales,
   riesgos; decisión: opciones, pros y contras, criterio; personal: hechos, emociones, patrones, qué depende de él).
   Cuando una parte quede clara, dilo y pasa a la siguiente.
4) Si sirve, ofrece buscar datos reales (precios, competencia, normas) con buscar_web.
5) Tono: negocio o plata → socio práctico y directo; personal o emocional → amigo empático y sincero, SIN pullas ni
   sarcasmo, con tacto pero sin endulzar; estudio o técnico → lógico y riguroso.
6) Mientras hablas, la cámara del tablero va a la tarjeta que nombras y al lado aparece sola una pizarra con tus
   cuentas, tablas y cifras: nombra las partes del tablero de las que hablas («en Números…», «el precio por pollo…»),
   di las cifras redondas y en orden (primero el dato, luego la cuenta, luego el resultado) y no dictes tablas enteras.
7) El tablero lo va anotando solo un escriba (lo que él dice y lo que tú aportas), ordenado por secciones, y si él
   pide una lista la crea con casillas para chulear: NO uses 'tablero' para anotar. Úsalo solo si él pide cambiar o
   borrar algo puntual; si pide ordenar el tablero, usa reorganizar_tablero.
8) Las cuentas hazlas por dentro y di solo el resultado que importa («le da para unos 140 pollos al día, así que el
   reto no es producir sino vender»), sin dictar el procedimiento ni listas (el paso a paso lo muestra la pizarra).
   En voz: 2 a 4 frases, máximo unas 60 palabras, natural, sin leer el tablero (el detalle lo anota el escriba).
9) Cuando la idea esté clara o él lo pida: resume la conclusión y 1 a 3 siguientes pasos. Si dice que ya, usa
   terminar_analisis. Si pide otra cosa (música, abrir algo, una pregunta suelta), atiéndela normal y NO menciones el
   tablero: el análisis queda en pausa hasta que él vuelva al tema.
10) Si pide borrar u olvidar este análisis («borra esto», «bórralo de tu historial»), usa borrar_analisis:
   terminar_analisis solo lo cierra y lo deja guardado. Nunca digas que borraste algo si la herramienta no lo borró.
Tarjetas actuales (id [tipo] ←padre título: texto):
{resumen(t)}"""


# ───────────────────────── herramientas de Maicol ─────────────────────────
DONDE = P("string", "Dónde mostrarlo: 'auto' (tú eliges), 'panel' (tu panel), 'ventana' (ventana grande propia en el PC)",
          ["auto", "panel", "ventana"])
ACCIONES = P("array", "Cambios al tablero, en orden", items={"type": "object", "properties": {
    "accion": {"type": "string", "description": "crear | cambiar | borrar | agregar (elementos a una lista) | marcar (chulear un elemento) | mover_a (colgar de otra tarjeta) | enfocar | titular"},
    "id": {"type": "string", "description": "id de una tarjeta existente (cambiar, borrar, enfocar, conectar desde)"},
    "ref": {"type": "string", "description": "crear: nombre temporal para conectarle otras tarjetas en este mismo pedido"},
    "tipo": {"type": "string", "description": "tema | problema | idea | pregunta | respuesta | emocion | evidencia | hallazgo | requisito | riesgo | opcion | dato | accion | conclusion"},
    "titulo": {"type": "string", "description": "Título corto (máx. 8 palabras)"},
    "texto": {"type": "string", "description": "Contenido breve (1-3 frases)"},
    "conectar_a": {"type": "string", "description": "id o ref de la tarjeta madre (crear) o destino (conectar)"},
    "etiqueta": {"type": "string", "description": "Texto corto de la flecha (ej. 'causa', 'por eso', 'contradice')"},
    "estilo": {"type": "string", "description": "arbol (lista/pasos bajo la madre) | radial (ideas alrededor) | isla (tema aparte)"},
    "datos": {"type": "string", "description": "Opcional, para barras: 'Ventas: 120; Costos: 80'"},
    "items": {"type": "string", "description": "Lista (crear tipo lista, cambiar o agregar): 'a; b; c'"},
    "item": {"type": "string", "description": "marcar: el elemento de la lista que ya está hecho"}}})


async def _mostrar(ctx, t: dict, donde: str | None) -> str:
    return await superficies.mostrar_tablero(ctx, t, donde or "auto")


def _lo_dijo(tema: str, mensaje: str | None) -> bool:
    """¿El tema sale de lo que el señor dijo en este mensaje? (alguna palabra con sustancia en común)."""
    if mensaje is None:  # sin el mensaje a mano (p. ej. desde una prueba o el panel) se confía en el tema
        return True
    palabras = {w for w in re.findall(r"\w+", _sin_tildes(tema)) if len(w) > 3}
    return bool(palabras & set(re.findall(r"\w+", _sin_tildes(mensaje))))


@herramienta("saca_analiticas", "«Saca analíticas», «analicemos», «ayúdame a aclarar/pensar…», «armemos un esquema»: abre un tablero "
             "EN BLANCO donde armas con el señor un esquema de tarjetas (negocio, decisión o algo personal). Para retomar un "
             "proyecto guardado usa mostrar_tablero.",
             {"tema": P("string", "Solo si lo dijo en ESTE mensaje («analicemos lo del gimnasio»); nunca lo saques de antes"),
              "donde": DONDE})
async def saca_analiticas(ctx, tema=None, donde="auto"):
    # siempre en blanco: retomar algo es decisión de él («reabre el de los pollos» -> mostrar_tablero).
    # No se acumulan tableros vacíos: se usa el último que quedó sin estrenar
    if tema and not _lo_dijo(tema, (ctx.extra or {}).get("mensaje")):
        tema = None  # la IA lo sacó de la charla anterior («analicemos algo» no es «el negocio de pollos»)
    t = next((x for x in todos() if not x["nodos"]), None) or crear("Análisis")
    t.update(titulo="Análisis", tema="")  # el vacío reutilizado no hereda el nombre de otra vez
    if tema:
        t.update(titulo=tema.strip()[:60], tema=tema.strip()[:300])
    guardar(t)  # recién usado: un tablero vacío viejo contaría como análisis cerrado y Maicol saldría del modo análisis
    activar(t)
    lugar = await _mostrar(ctx, t, donde)
    if tema:
        return (f"Tablero «{t['titulo']}» abierto en blanco ({lugar}). Arranca construyendo con lo que ya contó: un aporte "
                "concreto y, si hace falta, una pregunta. El escriba lo anota solo en el tablero.")
    proyectos = [x for x in todos() if x["nodos"]][:6]
    if not proyectos:
        return (f"Tablero en blanco abierto ({lugar}). Salúdalo en una frase estilo J.A.R.V.I.S.: «¿Qué desea que analicemos "
                "hoy, señor?», y espera. Lo que él cuente lo anota solo el escriba; tú construye con él.")
    nombres = ", ".join(f"«{x['titulo']}»" for x in proyectos)
    return (f"Tablero en blanco abierto ({lugar}). Salúdalo en una frase estilo J.A.R.V.I.S.: pregúntale qué quiere que analicen "
            f"hoy o si prefiere reabrir uno de sus proyectos ({nombres}); nómbralos solo si son pocos, si no di cuántos tiene. "
            "Si pide reabrir uno, usa mostrar_tablero con su nombre. Lo nuevo lo anota solo el escriba.")


@herramienta("tablero", "Cambia, borra, conecta, mueve o enfoca tarjetas del tablero de análisis cuando el señor lo pide puntualmente "
             "(«borra esa», «cámbiale el título», «une esto con aquello»). Lo nuevo de la charla lo anota solo un escriba.",
             {"acciones": ACCIONES, "tablero_id": P("string", "id del tablero (opcional; por defecto el abierto)")}, ["acciones"])
async def tablero(ctx, acciones, tablero_id=None):
    t = leer(tablero_id) if tablero_id else activo()
    if not t:
        t = crear("Análisis")
        activar(t)
        await _mostrar(ctx, t, "auto")
    if isinstance(acciones, str):
        try:
            acciones = json.loads(acciones)
        except ValueError:
            return "Las acciones deben ser una lista de objetos."
    if isinstance(acciones, dict):
        acciones = [acciones]
    async with CANDADO:
        t = leer(t["id"]) or t  # el escriba pudo haberlo cambiado mientras tanto
        hecho = aplicar(t, [a for a in acciones if isinstance(a, dict)])
        _titular_si_falta(t)
        guardar(t)
        activar(t)
    await avisar(t, hecho["enfoque"])
    partes = []
    if hecho["creadas"]:
        partes.append("creé " + ", ".join(f"{i} ({next(n['titulo'] for n in t['nodos'] if n['id'] == i)})" for i in hecho["creadas"]))
    if hecho["cambiadas"]:
        partes.append("cambié " + ", ".join(hecho["cambiadas"]))
    if hecho["borradas"]:
        partes.append("borré " + ", ".join(hecho["borradas"]))
    if hecho["conectadas"]:
        partes.append(f"{hecho['conectadas']} conexiones nuevas")
    if hecho["errores"]:
        partes.append("ojo: " + "; ".join(hecho["errores"]))
    return (f"Tablero «{t['titulo']}»: {'; '.join(partes) or 'sin cambios'}. Ya se ve en pantalla: no lo leas, sigue construyendo "
            "con él.")


@herramienta("mostrar_tablero", "Reabre un proyecto o tablero de análisis guardado por su nombre o tema («reabre el de los pollos», "
             "«retomemos el análisis del café»): lo carga en la ventana del tablero y queda listo para seguir trabajándolo.",
             {"nombre": P("string", "Nombre o tema del tablero (opcional: por defecto el último)"), "donde": DONDE})
async def mostrar_tablero(ctx, nombre=None, donde="auto"):
    t = buscar(nombre)
    if not t:
        return "No encontré ese tablero." + (f" Los que hay: {', '.join(x['titulo'] for x in todos()[:8])}." if todos() else "")
    activar(t)
    t["actualizado"] = time.time()
    guardar(t)
    lugar = await _mostrar(ctx, t, donde)
    return (f"Reabrí «{t['titulo']}» ({lugar}). En una frase dile dónde iban y propón por dónde seguir (sin leer el tablero).\n"
            f"{resumen(t)}")


@herramienta("reorganizar_tablero", "Ordena el tablero de análisis abierto por secciones (operación, números, pendientes…), junta en "
             "listas lo que quedó suelto y lo reacomoda como un esquema claro. Úsala con «organiza el tablero», «ordénalo».")
async def reorganizar_tablero(ctx):
    t = activo()
    if not t or not t["nodos"]:
        return "No hay un tablero con tarjetas abierto para organizar."
    try:
        hecho = await reorganizar(ctx.router, t)
    except Exception as e:  # noqa: BLE001
        return f"No pude organizarlo ahora ({e}); inténtalo en un momento."
    return (f"Listo: organicé «{t['titulo']}» ({len(hecho['creadas'])} secciones nuevas, {len(hecho['cambiadas'])} tarjetas "
            f"reubicadas, {len(hecho['borradas'])} sueltas que quedaron dentro de listas). Dilo en una frase.")


@herramienta("tableros", "Lista los tableros de análisis guardados (lo que el señor ha analizado con 'saca analíticas').")
async def tableros(ctx):
    lista = todos()
    if not lista:
        return "Todavía no hay tableros de análisis."
    return "\n".join(f"- «{t['titulo']}» ({len(t['nodos'])} tarjetas, {time.strftime('%d/%m %H:%M', time.localtime(t['actualizado']))})"
                     for t in lista[:12])


@herramienta("terminar_analisis", "Cierra el modo análisis SIN borrar nada (el tablero queda guardado para retomarlo luego con "
             "mostrar_tablero). Si él pide borrarlo u olvidarlo, NO es esta: es borrar_analisis.")
async def terminar_analisis(ctx):
    t = activo()
    activar(None)
    return (f"Cerré el análisis «{t['titulo']}». OJO: NO se borró, queda guardado; no digas que lo borraste. Si él quería "
            "borrarlo, usa borrar_analisis.") if t else "No había un análisis abierto."


def _ratos(t: dict) -> list[tuple[float, float]]:
    """Cuándo se habló de este tablero. Los tableros viejos no anotaban sus ratos: desde un poco antes de la primera
    tarjeta (la charla que la originó) hasta la última."""
    ahora = time.time()
    if t.get("ratos"):
        return [(a, b or ahora) for a, b in t["ratos"]]
    marcas = [n.get(k) for n in t["nodos"] for k in ("creada", "cambiada") if n.get(k)]
    return [(min(marcas) - 180, max(marcas) + 120)] if marcas else []


@herramienta("borrar_analisis", "Borra DE VERDAD un análisis: su tablero, la conversación de ese análisis y lo que Maicol "
             "aprendió de ella. Úsala cuando él pida borrarlo u olvidarlo («borra esto», «bórralo de tu historial», «no "
             "quiero saber más de eso»). Por defecto, el análisis abierto o el último que se trabajó.",
             {"nombre": P("string", "Nombre o tema del tablero a borrar (opcional: por defecto el abierto o el último)")},
             peligrosa=True)
async def borrar_analisis(ctx, nombre=None):
    if nombre:
        t = buscar(nombre)
    else:  # «borra esto»: el abierto o el que se acaba de cerrar (nunca uno de hace días por adivinar)
        t = activo() or next((x for x in todos() if x["nodos"] and x.get("ratos")
                              and time.time() - (x["ratos"][-1][1] or time.time()) < 1800), None)
    if not t:
        return "No sé cuál análisis borrar y no borré nada: pregúntale cuál (por su nombre)."
    ratos = _ratos(t)
    mensajes = ctx.memoria.borrar_entre(ctx.sesion, ratos) if ctx.memoria and ctx.sesion else 0
    # lo aprendido en esos ratos que hable de lo mismo (lo demás que aprendió en esa hora se queda)
    claves = superficies._claves(" ".join(f"{n['titulo']} {n.get('texto', '')}" for n in t["nodos"]) + " " + t["titulo"])
    olvidados = 0
    if ctx.memoria:
        for h in ctx.memoria.hechos(500):
            dentro = any(a - 60 <= h["ts"] <= b + 600 for a, b in ratos)
            if dentro and len(claves & superficies._claves(h["texto"])) >= 2 and ctx.memoria.olvidar(h["id"]):
                olvidados += 1
    try:
        json.loads(ACTIVO.read_text(encoding="utf-8"))["id"] == t["id"] and ACTIVO.unlink(missing_ok=True)
    except (OSError, ValueError, KeyError):
        pass
    _ruta(t["id"]).unlink(missing_ok=True)
    if DIFUNDIR:
        await DIFUNDIR({"type": "tablero_borrado", "id": t["id"]})
    return (f"Borrado de verdad: el tablero «{t['titulo']}», {mensajes} mensajes de esa conversación y {olvidados} cosas que "
            "había aprendido de ella. Confírmalo en una frase corta y no vuelvas a mencionar ni resumir ese tema.")
