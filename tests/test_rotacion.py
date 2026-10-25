"""Pruebas del router con proveedores simulados (sin red ni llaves).

    .venv\\Scripts\\python -m tests.test_rotacion
"""
import asyncio
import json
import time

import httpx

from jarvis.router import Ranura, Router, _espera_de, clasificar, sin_sentido


def sse(*trozos):
    cuerpo = "".join(f"data: {json.dumps(t)}\n\n" for t in trozos) + "data: [DONE]\n\n"
    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=cuerpo.encode())


def delta(texto=None, tool=None):
    d = {}
    if texto:
        d["content"] = texto
    if tool:
        d["tool_calls"] = [tool]
    return {"choices": [{"delta": d}]}


def router_falso(manejador, ranuras):
    r = Router()
    r.cliente = httpx.AsyncClient(transport=httpx.MockTransport(manejador))
    r.guardar = lambda forzar=False: None
    r.estrategia = "calidad"
    r.ranuras = [Ranura(prov={"id": pid, "nombre": pid, "base": f"https://{pid}.test", "prioridad": i}, modelo=m, llave="k", n_llave=0, rango=i * 10)
                 for i, (pid, m) in enumerate(ranuras)]
    return r


async def recoger(gen):
    return [ev async for ev in gen]


async def prueba_rota_en_429():
    def h(req):
        if req.url.host == "a.test":
            return httpx.Response(429, headers={"retry-after": "30"}, text='{"error":"rate limit"}')
        return sse(delta("Hola "), delta("señor."))

    r = router_falso(h, [("a", "m1"), ("b", "m2")])
    evs = await recoger(r.stream([{"role": "system", "content": "s"}, {"role": "user", "content": "hola"}]))
    tipos = [e["type"] for e in evs]
    assert tipos[0] == "rotacion", tipos
    assert "".join(e["text"] for e in evs if e["type"] == "delta") == "Hola señor."
    a = r.ranuras[0]
    assert 25 < a.enfriar_hasta - time.time() <= 30, a.enfriar_hasta - time.time()
    # en la siguiente petición la ranura A ni se intenta
    evs = await recoger(r.stream([{"role": "system", "content": "s"}, {"role": "user", "content": "otra"}]))
    assert evs[0]["type"] == "proveedor" and evs[0]["ranura"].startswith("b:")
    print("✓ rota al recibir 429 y respeta retry-after")


async def prueba_cuota_diaria_por_llave():
    def h(req):
        if req.url.host == "a.test":
            return httpx.Response(429, text="Rate limit exceeded: free-models-per-day")
        return sse(delta("ok"))

    r = router_falso(h, [("a", "m1"), ("a", "m2"), ("b", "m3")])
    for x in r.ranuras[:2]:
        x.prov = r.ranuras[0].prov
    r.ranuras[0].prov["cuota_por_llave"] = True
    await recoger(r.stream([{"role": "system", "content": "s"}, {"role": "user", "content": "x"}]))
    assert all(x.enfriar_hasta - time.time() > 3000 for x in r.ranuras[:2]), "toda la cuenta debe enfriarse"
    assert r.ranuras[2].libre(time.time())
    print("✓ cuota diaria de cuenta enfría todos sus modelos (1 h)")


async def prueba_herramientas_en_streaming():
    def h(req):
        return sse(
            delta(tool={"index": 0, "id": "x", "function": {"name": "clima", "arguments": ""}}),
            delta(tool={"index": 0, "function": {"arguments": '{"ciudad": '}}),
            delta(tool={"index": 0, "function": {"arguments": '"Medellín"}'}}),
        )

    r = router_falso(h, [("a", "m1")])
    tools = [{"type": "function", "function": {"name": "clima", "description": "d", "parameters": {"type": "object", "properties": {}}}}]
    evs = await recoger(r.stream([{"role": "system", "content": "s"}, {"role": "user", "content": "clima"}], tools))
    fin = evs[-1]
    assert fin["llamadas"][0]["name"] == "clima" and json.loads(fin["llamadas"][0]["args"]) == {"ciudad": "Medellín"}
    assert len(fin["llamadas"][0]["id"]) == 9
    print("✓ arma llamadas a herramientas que llegan en trozos")


async def prueba_llamadas_paralelas_gemini():
    # Gemini manda dos llamadas distintas con el mismo índice 0
    def h(req):
        return sse(
            delta(tool={"index": 0, "id": "a1", "function": {"name": "clima", "arguments": '{"ciudad": "Cali"}'}}),
            delta(tool={"index": 0, "id": "b2", "function": {"name": "estado_sistema", "arguments": "{}"}}),
        )

    r = router_falso(h, [("a", "m1")])
    tools = [{"type": "function", "function": {"name": "clima", "description": "d"}}]
    evs = await recoger(r.stream([{"role": "system", "content": "s"}, {"role": "user", "content": "x"}], tools))
    nombres = [c["name"] for c in evs[-1]["llamadas"]]
    assert nombres == ["clima", "estado_sistema"], nombres
    print("✓ separa llamadas paralelas que llegan con el mismo índice (Gemini)")


def prueba_firmas_gemini():
    from jarvis.router import firmas_para
    hist = [{"role": "assistant", "content": "", "tool_calls": [
        {"id": "a", "type": "function", "function": {"name": "x", "arguments": "{}"}, "extra_content": {"google": {"thought_signature": "FIRMA"}}},
        {"id": "b", "type": "function", "function": {"name": "y", "arguments": "{}"}}]}]
    g = firmas_para("gemini", hist)[0]["tool_calls"]
    assert g[0]["extra_content"]["google"]["thought_signature"] == "FIRMA"
    assert g[1]["extra_content"]["google"]["thought_signature"] == "skip_thought_signature_validator"
    assert all("extra_content" not in c for c in firmas_para("groq", hist)[0]["tool_calls"])
    print("✓ devuelve la firma de pensamiento solo a Gemini 3")


async def prueba_sin_tools_usa_protocolo():
    vistos = []

    def h(req):
        cuerpo = json.loads(req.content)
        vistos.append("tools" in cuerpo)
        if "tools" in cuerpo:
            return httpx.Response(400, text="this model does not support tools")
        return sse(delta('<herramienta>{"nombre": "clima", "args": {"ciudad": "Cali"}}</herramienta>'))

    r = router_falso(h, [("a", "m1")])
    tools = [{"type": "function", "function": {"name": "clima", "description": "d"}}]
    evs = await recoger(r.stream([{"role": "system", "content": "s"}, {"role": "user", "content": "clima"}], tools))
    fin = evs[-1]
    assert vistos == [True, False], vistos
    assert fin["llamadas"][0]["name"] == "clima" and not any(e["type"] == "delta" for e in evs)
    print("✓ modelo sin tools nativas -> reintenta con protocolo de texto y oculta la etiqueta")


async def prueba_corte_a_mitad():
    def h(req):
        if req.url.host == "a.test":
            return httpx.Response(200, headers={"content-type": "text/event-stream"},
                                  content=(f"data: {json.dumps(delta('Empiezo a '))}\n\n" + 'data: {"error": {"code": 503, "message": "overloaded"}}\n\n').encode())
        return sse(delta("Respuesta completa."))

    r = router_falso(h, [("a", "m1"), ("b", "m2")])
    evs = await recoger(r.stream([{"role": "system", "content": "s"}, {"role": "user", "content": "x"}]))
    tipos = [e["type"] for e in evs]
    assert "reset" in tipos and evs[-1]["texto"] == "Respuesta completa.", tipos
    print("✓ si un proveedor se cae a mitad de respuesta, se reinicia con otro")


async def prueba_todos_agotados():
    r = router_falso(lambda req: httpx.Response(429, text="quota"), [("a", "m1"), ("b", "m2")])
    try:
        await recoger(r.stream([{"role": "system", "content": "s"}, {"role": "user", "content": "x"}]))
    except Exception as e:  # noqa: BLE001
        assert "enfriamiento" in str(e)
        print("✓ con todo agotado avisa cuándo vuelve el primero")
        return
    raise AssertionError("debió fallar")


def prueba_esperas():
    assert _espera_de("Please try again in 1m30.5s", None) == 90.5
    assert _espera_de('"retryDelay": "41s"', None) == 41
    assert _espera_de("try again in 450ms", None) == 0.45
    assert clasificar(429, "Requests per day (RPD) limit").tipo == "cuota_diaria"
    e = clasificar(402, '{"code":"FREE_LIMIT","message":"Free limit reached: 1 reply every 30 seconds per IP. Retry after 1s"}')
    assert e.tipo == "limite" and e.espera == 30, (e.tipo, e.espera)
    assert clasificar(422, "tools[0].function: missing field `parameters`").tipo == "sin_tools"
    assert clasificar(404, "model decommissioned").tipo == "modelo"
    assert clasificar(401, "invalid api key").tipo == "llave"
    print("✓ entiende los mensajes de límite de Groq, Gemini y OpenRouter")


def prueba_sin_sentido():
    # lo que soltó de verdad un modelo gratis desbocado en un ensayo del modo análisis
    assert sin_sentido("En resumen, el modelitoיעבר feasibility con only delivery because que No arbeiten lieu divers irs, "
                       "InteractiveLogicalнавливás birthssten Shan ताoperativeEsc tipos ádu ோเกี่ยวlections 殆Adjしても遇上了 هدفAFP всегда")
    assert sin_sentido("El señor está diciendo que el horno de 6 bandejas rinde 12 pollos cada 45 minutos")
    assert not sin_sentido("Con ese horno le da para unos 140 pollos al día, señor… así que el reto no es producir sino vender.")
    assert not sin_sentido("Hola en japonés se escribe こんにちは y se pronuncia konnichiwa, señor, muy fácil de recordar.")
    print("✓ detecta respuestas desbocadas (basura en mil idiomas o razonamiento interno) y deja pasar las normales")


async def main():
    prueba_esperas()
    prueba_sin_sentido()
    prueba_firmas_gemini()
    for p in (prueba_rota_en_429, prueba_cuota_diaria_por_llave, prueba_herramientas_en_streaming, prueba_llamadas_paralelas_gemini,
              prueba_sin_tools_usa_protocolo, prueba_corte_a_mitad, prueba_todos_agotados):
        await p()
    print("\nTodas las pruebas pasaron.")


if __name__ == "__main__":
    asyncio.run(main())
