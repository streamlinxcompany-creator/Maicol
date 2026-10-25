"""Pruebas del modo análisis («Maicol, saca analíticas»): el tablero de tarjetas que Maicol arma preguntando.
Ejecutar: .venv\\Scripts\\python -m tests.test_analisis
"""
import asyncio
import tempfile
from pathlib import Path

from jarvis import analisis as a
from jarvis import herramientas as h
from jarvis import superficies as s
from jarvis.herramientas import Contexto


def main():
    carpeta = Path(tempfile.mkdtemp())
    a.CARPETA, a.ACTIVO = carpeta / "tableros", carpeta / "activo.json"
    eventos = []

    async def difundir(ev):
        eventos.append(ev)

    a.DIFUNDIR = difundir
    ctx = Contexto(router=None, memoria=None, canal="celular", difundir=difundir)

    viejo = a.crear("Análisis")  # un tablero vacío de hace horas: se reutiliza y debe quedar activo de una vez
    viejo["actualizado"] = 0
    a._ruta(viejo["id"]).write_text(__import__("json").dumps(viejo), encoding="utf-8")
    r = asyncio.run(a.saca_analiticas(ctx))
    assert "analicemos hoy" in r and a.activo() and a.activo()["id"] == viejo["id"], r
    assert any(e["type"] == "tablero_mostrar" for e in eventos), "desde el celular se muestra en el panel"
    print("✓ «saca analíticas» abre un tablero vacío y le pide a Maicol saludar «¿Qué desea que analicemos hoy, señor?»")

    r = asyncio.run(a.tablero(ctx, [
        {"accion": "titular", "titulo": "Por qué terminamos"},
        {"accion": "crear", "ref": "raiz", "tipo": "tema", "titulo": "La ruptura", "texto": "Quiero entender qué pasó"},
        {"accion": "crear", "tipo": "emoción", "titulo": "Confusión", "conectar_a": "raiz", "estilo": "radial"},
        {"accion": "crear", "tipo": "pregunta", "titulo": "¿Qué cambió?", "conectar_a": "raiz", "estilo": "arbol", "etiqueta": "explorar"},
        {"accion": "crear", "tipo": "dato", "titulo": "Tiempo juntos", "texto": "x", "datos": "Meses buenos: 14; Meses difíciles: 4"},
    ]))
    t = a.activo()
    assert t["titulo"] == "Por qué terminamos" and len(t["nodos"]) == 4, t
    assert [n["tipo"] for n in t["nodos"]] == ["tema", "emocion", "pregunta", "dato"], "los tipos con tilde o alias se normalizan"
    assert {(c["de"], c["a"]) for c in t["conexiones"]} >= {("t1", "t2"), ("t1", "t3")}, t["conexiones"]
    assert t["nodos"][3]["datos"][0] == {"etiqueta": "Meses buenos", "valor": 14.0, "unidad": ""}
    assert "t2 (Confusión)" in r and "no lo leas" in r
    print("✓ crea tarjetas conectadas por referencia temporal, normaliza tipos y arma barras con los datos")

    posiciones = [(n["x"], n["y"]) for n in t["nodos"]]
    for i, (x, y) in enumerate(posiciones):
        for x2, y2 in posiciones[i + 1:]:
            assert abs(x - x2) >= a.ANCHO or abs(y - y2) >= a.ALTO, f"tarjetas encimadas: {posiciones}"
    print("✓ ninguna tarjeta queda encima de otra")

    asyncio.run(a.tablero(ctx, [{"accion": "cambiar", "id": "t3", "texto": "Él dejó de llegar a tiempo"},
                                {"accion": "borrar", "id": "t2"}, {"accion": "cambiar", "id": "t99", "texto": "x"}]))
    t = a.activo()
    assert next(n for n in t["nodos"] if n["id"] == "t3")["texto"] == "Él dejó de llegar a tiempo"
    assert not any(n["id"] == "t2" for n in t["nodos"]) and not any("t2" in (c["de"], c["a"]) for c in t["conexiones"])
    assert eventos[-1]["type"] == "tablero" and eventos[-1]["tablero"]["id"] == t["id"], "las pantallas lo ven en vivo"
    print("✓ cambia y borra tarjetas (y sus flechas), y avisa a todas las pantallas")

    instr = a.instruccion()
    assert "MODO ANÁLISIS ACTIVO" in instr and "t3 [pregunta] ←t1" in instr
    assert "tablero" in h.relevantes("porque ella siempre decía que no tenía tiempo"), "en pleno análisis el tablero sigue a mano"
    assert "saca_analiticas" in h.relevantes("maicol saca analíticas")
    print("✓ mientras dura el análisis Maicol tiene el método, el tablero resumido y sus herramientas siempre a mano")

    assert a.buscar("terminamos")["id"] == t["id"]
    r = asyncio.run(a.terminar_analisis(ctx))
    assert "queda guardado" in r and a.activo() is None and a.instruccion() == ""
    assert a.buscar("por que terminamos")["id"] == t["id"], "se encuentra por su título para retomarlo"
    print("✓ se cierra el análisis y el tablero queda guardado para retomarlo por nombre")

    s._LATERAL["visto"] = __import__("time").time()
    s.ABIERTOS.clear()
    ctx_pc = Contexto(router=None, memoria=None, canal="voz", difundir=difundir)
    lugar = asyncio.run(s.mostrar_tablero(ctx_pc, t, "ventana"))
    assert "ventana" in lugar and s.tomar_pedidos()[0]["url"].endswith(f"/tablero?id={t['id']}")
    s.ABIERTOS[t["id"]] += 1
    assert "ya estaba abierta" in asyncio.run(s.mostrar_tablero(ctx_pc, t, "ventana"))
    assert s.tomar_pedidos() == [{"traer": f"{t['titulo']} · Maicol", "ancho": 1320, "alto": 860}], "no abre otra: trae la que hay"
    print("✓ en el PC lo abre en una ventana propia (la abre la pestaña lateral, como usuario normal) y no la repite")

    otro = a.crear("Análisis")
    a.activar(otro)
    asyncio.run(a.tablero(ctx, [{"accion": "crear", "tipo": "tema", "titulo": "Objetivo", "texto": "Abrir un café en mi barrio"}]))
    assert a.activo()["titulo"] == "Abrir un café en mi barrio", "sin título, el tablero se llama como su tema"
    print("✓ si Maicol olvida titularlo, el tablero toma el nombre de su tema")
    asyncio.run(a.tablero(ctx, [{"accion": "crear", "tipo": "dato", "titulo": "Arriendo", "datos": "Arriendo: 3"},
                                {"accion": "crear", "tipo": "tema", "titulo": "Competencia"}]))
    otro = a.activo()
    assert [n["tipo"] for n in otro["nodos"]] == ["tema", "dato", "idea"], "un solo tema por tablero"
    assert {(c["de"], c["a"]) for c in otro["conexiones"]} == {("t1", "t2"), ("t1", "t3")}, "nada queda suelto: cuelga del tema"
    print("✓ las tarjetas sin madre cuelgan del tema principal y no se crean dos temas")

    class RouterFalso:  # el escriba: una IA aparte que devuelve las tarjetas en JSON
        def __init__(self, salida):
            self.salida, self.pedido = salida, None

        async def completar(self, mensajes, nivel="rapido"):
            self.pedido = mensajes
            return self.salida

    pollos = a.crear("Análisis")
    a.activar(pollos)
    r = RouterFalso('Claro: {"acciones": [{"accion": "titular", "titulo": "Pollos a domicilio"}, '
                    '{"accion": "crear", "ref": "tema", "tipo": "tema", "titulo": "Pollos a domicilio", "texto": "Cocina oculta"}, '
                    '{"accion": "crear", "tipo": "dato", "titulo": "Horno prestado", "texto": "Libre hasta las 4 pm", "conectar_a": "tema", '
                    '"datos": "Pollos por tanda: 12; Minutos por tanda: 45"}, '
                    '{"accion": "crear", "tipo": "hallazgo", "titulo": "Capacidad diaria", "texto": "Unos 140 pollos", "conectar_a": "tema"}]}')
    asyncio.run(a.escribir(r, "el horno hace 12 pollos cada 45 min y está libre hasta las 4", "Eso da unos 140 pollos al día…"))
    pollos = a.activo()
    assert pollos["titulo"] == "Pollos a domicilio" and [n["tipo"] for n in pollos["nodos"]] == ["tema", "dato", "hallazgo"], pollos
    assert pollos["nodos"][1]["datos"][0]["valor"] == 12 and len(pollos["conexiones"]) == 2
    assert "12 pollos" in r.pedido[1]["content"] and "140 pollos" in r.pedido[1]["content"], "ve lo que dijo él y lo que aportó Maicol"
    assert eventos[-1]["type"] == "tablero", "las pantallas lo ven en vivo"
    asyncio.run(a.escribir(RouterFalso("no entendí"), "ponme música", "Listo"))  # basura o nada nuevo: no rompe ni cambia
    assert len(a.activo()["nodos"]) == 3
    print("✓ el escriba anota solo lo que él dijo y lo que Maicol aportó (aunque la IA de la charla no use el tablero)")

    r = asyncio.run(a.saca_analiticas(ctx))  # con «Pollos a domicilio» activo y lleno: igual abre en blanco
    blanco = a.activo()
    assert not blanco["nodos"] and blanco["id"] != pollos["id"], "siempre empieza vacío"
    assert "reabrir" in r and "«Pollos a domicilio»" in r and "mostrar_tablero" in r, r
    print("✓ siempre abre en blanco y ofrece reabrir sus proyectos guardados por nombre")

    # «analicemos algo porf»: la IA se inventó el tema sacándolo de la charla anterior -> se ignora y pregunta
    ctx_msg = Contexto(router=None, memoria=None, canal="celular", difundir=difundir, extra={"mensaje": "analicemos algo porf"})
    r = asyncio.run(a.saca_analiticas(ctx_msg, tema="Pollos a domicilio"))
    assert "en blanco" in r and "qué quiere que analicen hoy" in r and a.activo()["titulo"] == "Análisis", r
    assert a.buscar("pollos")["id"] == pollos["id"], "reabrir prefiere el proyecto con tarjetas, no un vacío"
    ctx_msg.extra["mensaje"] = "analicemos lo del gimnasio que quiero montar"
    assert "«Montar un gimnasio» abierto en blanco" in asyncio.run(a.saca_analiticas(ctx_msg, tema="Montar un gimnasio"))
    assert a.activo()["titulo"] == "Montar un gimnasio", "si lo dijo en este mensaje, el tema sí vale"
    a.activo()["titulo"] = "Análisis"
    for frase in ("analicemos algo porf", "Maicol, analicemos", "sabes que abramos analiticas", "ponme las analíticas"):
        assert h.atajo(frase) == ("saca_analiticas", {}), frase
    assert h.atajo("analicemos el negocio de pollos") is None, "con tema, mejor que la IA lo entienda completo"
    print("✓ no se inventa el tema: «analicemos algo» abre en blanco y pregunta; «analicemos lo del gimnasio» sí lo toma")

    s.PEDIDOS.clear()
    s.ABIERTOS.clear()
    s.ABIERTOS[blanco["id"]] += 1  # la ventana del tablero está abierta (en blanco)
    ctx_pc = Contexto(router=None, memoria=None, canal="voz", difundir=difundir)
    r = asyncio.run(a.mostrar_tablero(ctx_pc, "el de los pollos"))
    assert a.activo()["id"] == pollos["id"] and "Reabrí «Pollos a domicilio»" in r and "ya estaba abierta" in r, r
    assert any(e == {"type": "tablero_cambiar", "id": pollos["id"]} for e in eventos), "la ventana abierta carga el proyecto"
    assert s.tomar_pedidos() == [{"traer_tablero": True}], "y se trae al frente, sin abrir otra"
    s.ABIERTOS.clear()
    print("✓ «reabre el de los pollos»: lo carga en la misma ventana del tablero y la trae al frente")

    # listas con casillas: «haz una lista de lo que falta» y luego «anota ahí…» van a la MISMA tarjeta
    lst = a.crear("Pollos")
    a.aplicar(lst, [{"accion": "crear", "ref": "tema", "tipo": "tema", "titulo": "Pollos"},
                    {"accion": "crear", "ref": "pend", "tipo": "pendientes", "titulo": "Para arrancar", "conectar_a": "tema"}])
    assert lst["nodos"][1]["tipo"] == "lista" and lst["nodos"][1]["items"] == []
    a.aplicar(lst, [{"accion": "agregar", "id": "t2", "items": "- 2 spike para pollos, recogedor de grasas, cajas para pollo"}])
    a.aplicar(lst, [{"accion": "agregar", "id": "t2", "items": "Recogedor de grasas; empaques"}])  # sin repetir
    assert [i["texto"] for i in lst["nodos"][1]["items"]] == ["2 spike para pollos", "recogedor de grasas", "cajas para pollo", "empaques"]
    a.aplicar(lst, [{"accion": "marcar", "id": "t2", "item": "cajas"}])
    assert [i["hecho"] for i in lst["nodos"][1]["items"]] == [False, False, True, False]
    assert "[x] cajas para pollo" in a.resumen(lst), "Maicol ve qué está chuleado"
    print("✓ listas con casillas: se crean, se les agregan cosas (sin repetir) y se chulean")

    # reorganizar: secciones bajo el tema, cada cosa en su sección y lo suelto adentro de su lista
    des = a.crear("Pollos")
    a.aplicar(des, [{"accion": "crear", "ref": "tema", "tipo": "tema", "titulo": "Pollos"}] +
              [{"accion": "crear", "tipo": "dato", "titulo": f"Dato {k}", "conectar_a": "tema"} for k in range(3)] +
              [{"accion": "crear", "tipo": "requisito", "titulo": "Pendientes", "conectar_a": "tema"},
               {"accion": "crear", "tipo": "requisito", "titulo": "Spikes", "conectar_a": "tema"}])
    a.guardar(des)
    falso = RouterFalso('{"acciones": [{"accion": "crear", "ref": "ops", "tipo": "seccion", "titulo": "Operación", "conectar_a": "t1"},'
                        '{"accion": "mover_a", "id": "t2", "conectar_a": "ops"}, {"accion": "mover_a", "id": "t3", "conectar_a": "ops"},'
                        '{"accion": "mover_a", "id": "t4", "conectar_a": "t3"}, {"accion": "cambiar", "id": "t5", "items": "Spikes"},'
                        '{"accion": "borrar", "id": "t6"}]}')
    hecho = asyncio.run(a.reorganizar(falso, des))
    des = a.leer(des["id"])
    madre = {c["a"]: c["de"] for c in des["conexiones"]}
    assert madre["t2"] == madre["t3"] == "t7" and madre["t4"] == "t3" and madre["t7"] == "t1", madre
    assert not any(n["id"] == "t6" for n in des["nodos"]) and next(n for n in des["nodos"] if n["id"] == "t5")["tipo"] == "lista"
    pos = {n["id"]: (n["x"], n["y"]) for n in des["nodos"]}
    afuera = lambda i: (pos[i][0] - pos["t1"][0]) * (1 if pos["t7"][0] > pos["t1"][0] else -1)  # qué tan afuera del tema
    assert 0 < afuera("t7") < afuera("t2") == afuera("t3") < afuera("t4"), pos  # mapa mental: tema, sección y sus ramas
    for i, (x, y) in enumerate(pos.values()):
        for x2, y2 in list(pos.values())[i + 1:]:
            assert abs(x - x2) >= a.ANCHO or abs(y - y2) >= a.ALTO, f"encimadas: {pos}"
    print("✓ reorganizar: secciones bajo el tema, cada tarjeta en su lugar, lo suelto dentro de su lista y sin encimarse")

    # reorganizar otra vez: si la IA borra una sección vieja, lo de adentro no queda suelto estirando el tablero,
    # y las secciones que quedan vacías (o inventadas, como «Analítica») se quitan
    falso = RouterFalso('{"acciones": [{"accion": "crear", "ref": "num", "tipo": "seccion", "titulo": "Números", "conectar_a": "t1"},'
                        '{"accion": "crear", "ref": "ana", "tipo": "seccion", "titulo": "Analítica", "conectar_a": "t1"},'
                        '{"accion": "borrar", "id": "t7"}, {"accion": "mover_a", "id": "t2", "conectar_a": "num"}]}')
    asyncio.run(a.reorganizar(falso, des))
    des = a.leer(des["id"])
    madre = {c["a"]: c["de"] for c in des["conexiones"]}
    titulos = {n["id"]: n["titulo"] for n in des["nodos"]}
    assert "Analítica" not in titulos.values(), titulos
    assert all(n["id"] in madre for n in des["nodos"] if n["tipo"] != "tema"), f"quedaron sueltas: {madre}"
    assert titulos[madre["t2"]] == "Números" and madre["t3"] == "t1" and madre["t4"] == "t3", madre
    xs = [n["x"] for n in des["nodos"]]
    assert max(xs) - min(xs) < 6 * (a.ANCHO + 80), "el esquema queda compacto"
    print("✓ reorganizar de nuevo: nada queda suelto ni hay secciones vacías")

    # «pon la de marketing en su sección»: si la IA la «crea» otra vez, se mueve la que ya existe (sin duplicar)
    # y queda pegada a la sección, no a mil pixeles
    mk = a.crear("Pollos")
    a.aplicar(mk, [{"accion": "crear", "ref": "tema", "tipo": "tema", "titulo": "Pollos"},
                   {"accion": "crear", "ref": "ops", "tipo": "seccion", "titulo": "Operación", "conectar_a": "tema"},
                   {"accion": "crear", "ref": "mkt", "tipo": "seccion", "titulo": "Marketing y ventas", "conectar_a": "tema"},
                   {"accion": "crear", "tipo": "accion", "titulo": "Marketing en La Ceja", "conectar_a": "ops"}])
    a.aplicar(mk, [{"accion": "crear", "ref": "t50", "tipo": "accion", "titulo": "Marketing en La Ceja", "conectar_a": "t3"},
                   {"accion": "mover_a", "id": "t4", "conectar_a": "t50"}])
    assert len(mk["nodos"]) == 4 and {c["a"]: c["de"] for c in mk["conexiones"]}["t4"] == "t3", mk["conexiones"]
    seccion, tarjeta = (next(n for n in mk["nodos"] if n["id"] == i) for i in ("t3", "t4"))
    assert abs(tarjeta["x"] - seccion["x"]) == a.ANCHO + 80 and abs(tarjeta["y"] - seccion["y"]) < a.ALTO, (seccion, tarjeta)
    a.aplicar(mk, [{"accion": "mover_a", "id": "t3", "conectar_a": "t4"}])  # colgarla de su propia hija: no
    assert {c["a"]: c["de"] for c in mk["conexiones"]}["t3"] == "t1"
    print("✓ mover una tarjeta a su sección: sin duplicarla, pegadita a la sección y sin círculos")

    # la pizarra: la cuenta al lado del tablero (con la suma corregida si la IA se equivoca) y la tabla
    a.activar(mk)
    eventos.clear()
    falso = RouterFalso('{"pizarra": {"titulo": "Margen por pollo", "bloques": [{"tipo": "cuenta", "filas": ['
                        '{"etiqueta": "Precio", "valor": "42.000"}, {"op": "-", "etiqueta": "Pollo", "valor": "22.000"},'
                        '{"op": "-", "etiqueta": "Caja", "valor": "1,4 k"}, {"op": "=", "etiqueta": "Ganancia", "valor": "19.000"}]},'
                        '{"tipo": "tabla", "columnas": ["Precio", "Ganancia"], "filas": [["42.000", "18.600"], ["40.000", "16.600"]]},'
                        '{"tipo": "raro"}], "tarjetas": ["t4", 7]}}')
    asyncio.run(a.pizarra(falso, "¿a cuánto lo vendo?", "A 42 mil le quedan unos 18.600 por pollo."))
    ev = next(e for e in eventos if e["type"] == "pizarra")
    cuenta, tabla = ev["pizarra"]["bloques"]
    assert ev["id"] == mk["id"] and cuenta["filas"][-1]["valor"] == "18.600", cuenta  # 42.000 - 22.000 - 1.400
    assert tabla["filas"][1] == ["40.000", "16.600"] and ev["pizarra"]["tarjetas"] == ["t4"]
    assert a.leer(mk["id"])["pizarras"][-1]["titulo"] == "Margen por pollo", "se guarda para volver a verla"
    eventos.clear()
    asyncio.run(a.pizarra(RouterFalso('{"pizarra": null}'), "hola", "Con 63 pollos al día le alcanza."))
    asyncio.run(a.pizarra(RouterFalso("nunca se llama"), "listo", "Listo, señor."))  # sin cifras: ni se pregunta
    assert not [e for e in eventos if e["type"] == "pizarra"]
    rango = {"tipo": "cuenta", "filas": [{"etiqueta": "Costo", "valor": "20 a 24 mil"}, {"op": "+", "etiqueta": "Caja", "valor": "1.400"},
                                         {"op": "=", "etiqueta": "Total", "valor": "21.400 a 25.400"}]}
    a._cuadrar(rango)
    assert rango["filas"][-1]["valor"] == "21.400 a 25.400", "un rango no se recalcula"
    print("✓ pizarra: la cuenta paso a paso (y bien sumada), la tabla y solo cuando hay algo que mostrar")

    # «explícame»: con el tablero abierto, el visual sale en una pizarra al costado (no el panel encima del tablero)
    eventos.clear()
    s.ABIERTOS[mk["id"]] += 1
    s._LATERAL["visto"] = __import__("time").time()
    s.PEDIDOS.clear()
    viejo, s.config.ES_WINDOWS = s.config.ES_WINDOWS, True
    r = asyncio.run(h.mostrar_visual(ctx, "Punto de equilibrio", "<div class='tarjeta'>45 pollos</div>"))
    pedido = s.tomar_pedidos()[0]["junto_tablero"]
    assert "salió al lado del tablero" in r and "/pizarra?v=" in pedido and "Punto%20de%20equilibrio" in pedido, pedido
    assert not [e for e in eventos if e["type"] == "visual"], "el panel no sale encima de las analíticas"
    assert "45 pollos" in s.pagina_visual(pedido.split("v=")[1].split("&")[0])
    s.LADO["abiertos"] = 1  # ya está afuera: solo cambia lo que muestra
    asyncio.run(h.mostrar_visual(ctx, "Margen", "<p>18.600</p>"))
    assert not s.tomar_pedidos() and eventos[-1]["type"] == "visual_lado" and eventos[-1]["titulo"] == "Margen"
    s.LADO["abiertos"] = 0
    s.ABIERTOS[mk["id"]] -= 1
    eventos.clear()
    asyncio.run(h.mostrar_visual(ctx, "Otro", "<p>x</p>"))
    assert [e for e in eventos if e["type"] == "visual"], "sin la ventana del tablero, va al lienzo de siempre"
    s.config.ES_WINDOWS, s._LATERAL["visto"] = viejo, 0
    print("✓ con las analíticas abiertas, los visuales de Maicol salen en una pizarra al costado del tablero")

    # se guarda sola: si la charla sigue en lo que muestra, se queda; a las 2 vueltas en otra cosa, se va
    s.LADO.update(abiertos=1, claves=s._claves("Punto de equilibrio <b>45 pollos</b> costos fijos 2.000.000 margen"), ajenas=0)
    assert not s.seguir_lado("y si los costos fijos suben?", "El punto de equilibrio sube a unos 55 por día.", False)
    assert not s.seguir_lado("hablemos del marketing en La Ceja", "Grupos de Facebook y volantes.", False)
    assert not s.seguir_lado("ah y el margen por pollo?", "Con margen de 20 mil, el equilibrio queda igual.", False), "volvió al tema"
    assert not s.seguir_lado("pon música", "Listo, sonando.", False)
    assert s.seguir_lado("qué horario abrimos", "De once a tres, para los almuerzos.", False), "2 vueltas en otra cosa"
    assert not s.seguir_lado("x", "y", True), "si en esa vuelta sacó otro visual, la cuenta empieza de nuevo"
    s.LADO.update(abiertos=0, ajenas=0)
    assert not s.seguir_lado("a", "b", False), "sin pizarra afuera no hay nada que guardar"
    print("✓ la pizarra del costado se guarda sola cuando la charla ya va en otra cosa (y se queda si siguen en el tema)")

    # «borra esto de tu historial»: se borra de verdad (tablero, la charla de esos ratos y lo aprendido de eso)
    class MemoriaFalsa:
        def __init__(self):
            self.ratos, self.olvidados = None, []
            self._hechos = [{"id": 1, "texto": "Le dolió que ella le dijera en su casa que no lo quería volver a ver", "ts": 0},
                            {"id": 2, "texto": "Escucha AC/DC en YouTube Music", "ts": 0}]

        def borrar_entre(self, sesion, ratos):
            self.ratos = ratos
            return 12

        def hechos(self, limite=200):
            return self._hechos

        def olvidar(self, id_):
            self.olvidados.append(id_)
            return True

    rel = a.crear("Relación")
    a.activar(rel)
    a.aplicar(rel, [{"accion": "crear", "ref": "tema", "tipo": "tema", "titulo": "La relación"},
                    {"accion": "crear", "tipo": "dato", "titulo": "Lo que dijo en su casa", "texto": "Que no lo quería volver a ver", "conectar_a": "tema"}])
    a.guardar(rel)
    assert a.leer(rel["id"])["ratos"][-1][1] is None, "mientras está abierto, su rato sigue abierto"
    assert "NO se borró" in asyncio.run(a.terminar_analisis(ctx)), "cerrar no es borrar, y Maicol no puede decir que borró"
    rel = a.leer(rel["id"])
    assert rel["ratos"][-1][1] is not None
    mem = MemoriaFalsa()
    for hecho in mem._hechos:
        hecho["ts"] = rel["ratos"][0][0] + 5
    eventos.clear()
    ctx_mem = Contexto(router=None, memoria=mem, canal="web", sesion="web", difundir=difundir)
    r = asyncio.run(a.borrar_analisis(ctx_mem))  # sin nombre: el último que se trabajó
    assert "Borrado de verdad" in r and "12 mensajes" in r and a.leer(rel["id"]) is None, r
    assert mem.ratos and mem.ratos[0][0] == rel["ratos"][0][0] and mem.olvidados == [1], (mem.ratos, mem.olvidados)
    assert eventos[-1] == {"type": "tablero_borrado", "id": rel["id"]}
    assert h.es_peligrosa("borrar_analisis"), "borrar es irreversible: pide permiso"
    assert "borrar_analisis" in h.relevantes("borra esto de tu historial")
    print("✓ «borra esto»: borra el tablero, la charla de esos ratos y lo aprendido de eso (cerrar ya no se hace pasar por borrar)")
    assert "reorganizar_tablero" in a.ORDENES_TABLERO and "tablero" not in a.ORDENES_TABLERO

    s._LATERAL["visto"] = __import__("time").time()
    assert s.abrir_como_usuario("https://music.youtube.com/watch?v=x") and s.tomar_pedidos() == [{"abrir": "https://music.youtube.com/watch?v=x"}]
    s._LATERAL["visto"] = 0
    assert not s.abrir_como_usuario("https://ejemplo.com"), "sin la pestaña lateral, el núcleo lo abre por su cuenta"
    print("✓ lo que el núcleo (administrador) abre, lo abre la pestaña lateral como usuario normal")

    ident = s.guardar_visual("Prueba", "<div class='tarjeta'>hola</div>")
    assert "hola" in s.pagina_visual(ident) and s.pagina_visual("nada") is None
    print("✓ un visual también puede ir en ventana propia")
    print("\nTodas las pruebas pasaron.")


if __name__ == "__main__":
    main()
