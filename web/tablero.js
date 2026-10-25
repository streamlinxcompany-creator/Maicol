// Tablero de análisis de Maicol («saca analíticas»): lo pinta en vivo, deja moverlo y editarlo a mano,
// y desde aquí mismo se le habla a Maicol (en su panel, ?incrustado=1, la conversación va por el chat del panel).
const $ = (s) => document.querySelector(s);
const params = new URLSearchParams(location.search);
const INCRUSTADO = params.has("incrustado");
if (INCRUSTADO) document.body.classList.add("incrustado");

const TIPOS = {
  tema: ["TEMA", "#e8fbff"], problema: ["PROBLEMA", "#ff4d5e"], idea: ["IDEA", "#00e5ff"], pregunta: ["PREGUNTA", "#ffb547"],
  respuesta: ["RESPUESTA", "#7af4ff"], emocion: ["EMOCIÓN", "#ff7ad9"], evidencia: ["EVIDENCIA", "#9fb4ff"],
  hallazgo: ["HALLAZGO", "#c48bff"], requisito: ["REQUISITO", "#5ad1ff"], riesgo: ["RIESGO", "#ff8a3d"],
  opcion: ["OPCIÓN", "#3dffa8"], dato: ["DATO", "#00e5ff"], accion: ["ACCIÓN", "#3dffa8"], conclusion: ["CONCLUSIÓN", "#ffe066"],
  seccion: ["SECCIÓN", "#7af4ff"], lista: ["LISTA", "#3dffa8"],
};
const T = { tablero: null, id: params.get("id"), sel: null, ajustado: false, moviendo: null, nuevas: false, lineasVistas: new Map() };
const V = { x: 0, y: 0, k: 1 };  // la cámara: desplazamiento y zoom
const H = { propio: false, texto: "", sonido: localStorage.getItem("tablero_sonido") !== "no" };

// ---------- datos ----------
async function cargar(ident) {
  if (!ident) {
    const lista = await fetch("/api/tableros").then((r) => r.json()).catch(() => []);
    ident = lista[0] && lista[0].id;
  }
  if (!ident) { $("#vacio").classList.remove("oculto"); if (!ws) conectar(); return; }  // espera a que Maicol cree uno
  const r = await fetch(`/api/tableros/${encodeURIComponent(ident)}`);
  if (!r.ok) { decir("Ese tablero ya no existe."); return; }
  const cambio = ident !== T.id;
  T.id = ident; T.ajustado = false;
  history.replaceState(null, "", `?id=${ident}${INCRUSTADO ? "&incrustado=1" : ""}`);
  $("#tarjetas").innerHTML = "";
  T.nuevas = false; T.lineasVistas = new Map();
  const datos = await r.json();
  PZ.lista = datos.pizarras || []; PZ.i = PZ.lista.length - 1;
  cerrarPizarra(); botonPizarra();
  pintar(datos);
  if (cambio || !ws) conectar();
  listar();
}

async function guardar(cuerpo) {
  await fetch(`/api/tableros/${T.id}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cuerpo) })
    .catch(() => decir("No pude guardar el cambio; ¿Maicol está prendido?"));
}

let pendienteLista = null;
async function listar() {
  clearTimeout(pendienteLista);
  pendienteLista = setTimeout(async () => {
    const lista = await fetch("/api/tableros").then((r) => r.json()).catch(() => []);
    const sel = $("#lista");
    sel.innerHTML = "";
    for (const t of lista) {
      const o = document.createElement("option");
      o.value = t.id; o.textContent = `${t.titulo} (${t.tarjetas})`; o.selected = t.id === T.id;
      sel.appendChild(o);
    }
    sel.classList.toggle("oculto", lista.length < 2);
  }, 300);
}

// ---------- conversación con Maicol ----------
let ws = null, reintentos = 0;
function conectar() {
  if (ws) { ws.onclose = null; ws.close(); }
  const proto = location.protocol === "https:" ? "wss" : "ws";
  ws = new WebSocket(`${proto}://${location.host}/ws?dispositivo=tablero&tablero=${encodeURIComponent(T.id || "")}` +
    (INCRUSTADO ? "&incrustado=1" : ""));
  ws.onopen = () => {  // si fue una reconexión (el núcleo se reinició), lo que cambió mientras tanto se trae de nuevo
    if (reintentos && T.id) fetch(`/api/tableros/${T.id}`).then((r) => r.ok && r.json()).then((t) => t && pintar(t)).catch(() => {});
    reintentos = 0;
  };
  ws.onmessage = (e) => { try { evento(JSON.parse(e.data)); } catch (_) { /* evento raro: se ignora */ } };
  ws.onclose = () => setTimeout(conectar, Math.min(10000, 800 * 2 ** reintentos++));
}

function evento(ev) {
  switch (ev.type) {
    case "tablero":
      if (ev.tablero && !T.id) { cargar(ev.tablero.id); return; }
      if (ev.tablero && ev.tablero.id === T.id) {
        pintar(ev.tablero);
        if (ev.enfoque) llegoTarjeta(ev.enfoque);
      }
      listar();
      return;
    case "tablero_mostrar":
      if (ev.id !== T.id) cargar(ev.id);
      return;
    case "tablero_cambiar":  // Maicol reabrió otro proyecto (o uno en blanco): se carga en esta misma ventana
      if (!INCRUSTADO && ev.id !== T.id) { tocada = false; cargar(ev.id); }
      return;
    case "pizarra":  // Maicol explica con números: la cuenta o la tabla aparece al lado
      if (ev.id === T.id && ev.pizarra) { PZ.lista.push(ev.pizarra); PZ.i = PZ.lista.length - 1; abrirPizarra(); }
      return;
    case "tablero_borrado":  // él pidió borrarlo: no se queda a la vista
      if (ev.id === T.id) {
        if (!INCRUSTADO) { window.close(); return; }
        T.tablero = null; T.id = null; $("#tarjetas").innerHTML = ""; lineas(); cerrarPizarra();
        $("#titulo").textContent = "Análisis"; $("#cuenta").textContent = ""; $("#vacio").classList.remove("oculto");
      }
      listar();
      return;
    case "escriba":  // el lápiz: el escriba está pasando lo nuevo al tablero
      if (ev.id === T.id) anotando(ev.activo);
      return;
    case "pensando": estado("pensando"); return;
    case "herramienta": if (ev.estado === "inicio") estado("pensando"); return;
    case "token": H.texto += ev.text || ""; decir(limpiar(H.texto)); return;
    case "fin":
      if (H.propio && H.texto.trim()) hablar(limpiar(H.texto)); else estado("");
      H.propio = false; H.texto = "";
      return;
    case "externo":  // se habló en otra pantalla (el panel, el celular): aquí se ve
      if (ev.rol === "assistant" && ev.texto) { decir(limpiar(ev.texto)); estado(""); } else if (ev.rol === "user") estado("pensando");
      return;
    case "anuncio": decir(limpiar(ev.texto || "")); return;
    case "confirmar": pedirPermiso(ev); return;
    case "error": decir(ev.texto || "Algo falló."); estado(""); return;
  }
}

// ---------- puente con el panel de Maicol (web/app.js): una sola voz, un solo Maicol ----------
// Lo que usted dice aquí lo responde el panel con su voz de siempre; aquí se ve lo que va diciendo y su estado.
// Solo si no hay panel (p. ej. el tablero abierto en el celular) esta página conversa y habla por su cuenta.
const P = { canal: "BroadcastChannel" in window ? new BroadcastChannel("maicol") : null, id: null, visto: 0, candidatos: [] };
function alPanel(m) { if (P.canal && P.id) P.canal.postMessage({ ...m, a: P.id }); }
if (P.canal) P.canal.onmessage = (e) => {
  const m = e.data || {};
  if (m.tipo === "aqui") { P.candidatos.push(m); return; }
  // lo que Maicol va diciendo (en cualquier pantalla de este PC): la cámara va a la tarjeta de la que habla
  if (m.tipo === "diciendo") return oir(m.texto);
  if (m.tipo === "diciendo_pos") return avanzar(m.r);
  if (m.tipo === "diciendo_fin") return callado();
  if (m.de !== P.id) return;
  P.visto = Date.now();
  if (m.tipo === "texto") decir(limpiar(m.texto));
  else if (m.tipo === "usuario") { decir(`«${m.texto}»`); estado("pensando"); }
  else if (m.tipo === "modo") estado({ hablando: "hablando", pensando: "pensando", herramienta: "pensando", escuchando: "escuchando" }[m.modo] || "");
  else if (m.tipo === "permiso") pedirPermiso({ texto: m.texto, args: m.args }, (ok) => alPanel({ tipo: "permiso", ok }));
  else if (m.tipo === "permiso_listo") $("#confirmar").classList.add("oculto");
};

async function buscarPanel() {  // el lateral primero: es «el» Maicol de este PC
  if (!P.canal || INCRUSTADO) return null;
  if (P.id && Date.now() - P.visto < 15000) return P.id;
  P.candidatos = [];
  P.canal.postMessage({ tipo: "hola" });
  await new Promise((ok) => setTimeout(ok, 300));
  const elegido = P.candidatos.find((c) => c.lateral) || P.candidatos[0];
  P.id = elegido ? elegido.de : null;
  P.visto = elegido ? Date.now() : 0;
  $("#enviar").title = P.id ? "Enviar (responde Maicol desde su panel)" : "Enviar (sin panel: responde esta ventana)";
  return P.id;
}

async function enviar(texto, porVoz = false) {
  texto = texto.trim();
  if (!texto) return;
  if (await buscarPanel()) {
    alPanel({ tipo: "decir", texto, porVoz });
    decir(`«${texto}»`);
    estado("pensando");
    return;
  }
  if (!ws || ws.readyState !== 1) { decir("Sin conexión con Maicol; reintentando…"); return; }
  ws.send(JSON.stringify({ type: "mensaje", texto }));
  H.propio = true; H.texto = "";
  decir(`«${texto}»`);
  estado("pensando");
}

const limpiar = (t) => String(t).replace(/```[\s\S]*?```/g, "").replace(/[*_#`>]/g, "").replace(/https?:\/\/\S+/g, "").trim();
function decir(t) { $("#voz").textContent = t || "…"; }
function estado(e) {
  $("#estado").className = "punto " + (e || "");
  $(".reactor").className = "reactor " + (e || "");  // el orbe de Maicol late según lo que esté haciendo
}

// sin panel, la misma voz y velocidad que usted eligió en el panel (se guardan en este mismo navegador)
const preferencia = (k, d) => { try { const v = localStorage.getItem("jarvis." + k); return v === null ? d : JSON.parse(v); } catch (_) { return d; } };
let audio = null;
async function hablar(texto) {
  if (!H.sonido || INCRUSTADO || !texto) { estado(""); return; }
  try {
    const vel = Number(preferencia("velocidad", 20)) || 0;
    const q = new URLSearchParams({ texto: texto.slice(0, 700), velocidad: (vel >= 0 ? "+" : "") + vel + "%" });
    if (preferencia("vozId", null)) q.set("voz_id", preferencia("vozId", null));
    const r = await fetch(`/api/tts?${q}`);
    if (!r.ok) throw new Error();
    if (audio) audio.pause();
    audio = new Audio(URL.createObjectURL(await r.blob()));
    estado("hablando");
    oir(texto);
    audio.onended = () => { estado(""); callado(); };
    await audio.play();
  } catch (_) { estado(""); }
}

// el permiso lo pide Maicol desde el panel (escondido detrás del tablero) o, sin panel, el núcleo directo
function pedirPermiso(ev, alResponder) {
  const args = typeof ev.args === "string" ? ev.args
    : Object.entries(ev.args || {}).map(([k, v]) => `${k}: ${String(v).slice(0, 160)}`).join(" · ");
  $("#confirmar-txt").textContent = ev.texto ? `${ev.texto}\n${args}` : `${(ev.nombre || "").replace(/_/g, " ")} — ${args}`;
  $("#confirmar").classList.remove("oculto");
  const responder = (ok) => {
    $("#confirmar").classList.add("oculto");
    if (alResponder) alResponder(ok);
    else if (ws && ws.readyState === 1) ws.send(JSON.stringify({ type: "confirmar", id: ev.id, ok }));
  };
  $("#confirmar-si").onclick = () => responder(true);
  $("#confirmar-no").onclick = () => responder(false);
}

// ---------- pintar ----------
function pintar(t) {
  T.tablero = t;
  $("#titulo").textContent = t.titulo;
  document.title = `${t.titulo} · Maicol`;
  $("#cuenta").textContent = t.nodos.length === 1 ? "1 tarjeta" : `${t.nodos.length} tarjetas`;
  $("#vacio").classList.toggle("oculto", t.nodos.length > 0);
  const cont = $("#tarjetas");
  const quedan = new Map([...cont.children].map((el) => [el.dataset.id, el]));
  let nuevas = 0, movidas = false;
  for (const n of t.nodos) {
    let el = quedan.get(n.id);
    const firma = JSON.stringify([n.tipo, n.titulo, n.texto, n.datos || null, n.items || null]);
    if (!el) {
      el = tarjeta(n);
      if (T.nuevas) {  // llegó mientras usted mira: aparece con brillo (varias, una tras otra)
        el.classList.add("nueva");
        el.style.animationDelay = `${nuevas * 0.14}s, ${nuevas * 0.14 + 0.3}s`;
        nuevas++;
        setTimeout(() => { el.classList.remove("nueva"); el.style.animationDelay = ""; }, 3200);
      }
      cont.appendChild(el);
    } else if (el.dataset.firma !== firma && !el.querySelector("[contenteditable='true']")) {
      llenar(el, n);
      el.classList.remove("flash"); void el.offsetWidth; el.classList.add("flash");
    }
    el.dataset.firma = firma;
    if (!T.moviendo || T.moviendo.id !== n.id) {
      const antes = [parseFloat(el.style.left), parseFloat(el.style.top)];
      if (T.nuevas && !Number.isNaN(antes[0]) && (Math.abs(antes[0] - n.x) > 2 || Math.abs(antes[1] - n.y) > 2)) {
        el.classList.add("deslizando"); movidas = true;  // se reacomodó: se desliza a su lugar, no salta
        clearTimeout(el.deslizar); el.deslizar = setTimeout(() => el.classList.remove("deslizando"), 900);
      }
      el.style.left = n.x + "px"; el.style.top = n.y + "px";
    }
    quedan.delete(n.id);
  }
  for (const el of quedan.values()) el.remove();
  lineas();
  if (movidas) animarLineas(900);
  if (!T.ajustado && t.nodos.length) { T.ajustado = true; requestAnimationFrame(() => ajustar(false)); }
  T.nuevas = true;  // lo que llegue de aquí en adelante, llega en vivo
}

function tarjeta(n) {
  const el = document.createElement("article");
  el.dataset.id = n.id;
  el.innerHTML = '<div class="tipo"><span></span><i></i></div><h3></h3><p></p><ul class="items"></ul><div class="barras"></div>' +
    '<button class="borrar" title="Borrar tarjeta">✕</button>';
  llenar(el, n);
  el.querySelector(".borrar").onclick = (e) => { e.stopPropagation(); el.remove(); lineas(); guardar({ accion: "borrar", id: n.id }); };
  for (const campo of ["h3", "p"]) el.querySelector(campo).addEventListener("dblclick", (e) => editar(e.currentTarget, n.id));
  return el;
}

function llenar(el, n) {
  const [nombre, color] = TIPOS[n.tipo] || TIPOS.idea;
  el.className = `tarjeta ${n.tipo}${T.sel === n.id ? " sel" : ""}`;
  el.style.setProperty("--c", color);
  el.querySelector(".tipo span").textContent = nombre;
  el.querySelector(".tipo i").textContent = n.id;
  el.querySelector("h3").textContent = n.titulo;
  el.querySelector("p").textContent = n.texto || "";
  // listas: casillas para chulear (el clic lo guarda y lo ven todas las pantallas)
  const items = el.querySelector(".items");
  items.innerHTML = "";
  (n.items || []).forEach((it, indice) => {
    const li = document.createElement("li");
    li.className = it.hecho ? "hecho" : "";
    li.innerHTML = "<span class='casilla'></span><span></span>";
    li.children[1].textContent = it.texto;
    li.onpointerdown = (e) => e.stopPropagation();  // chulear no arrastra la tarjeta
    li.onclick = (e) => {
      e.stopPropagation();
      it.hecho = !it.hecho;
      li.classList.toggle("hecho", it.hecho);
      pie();
      guardar({ accion: "marcar", id: n.id, indice, hecho: it.hecho });
    };
    items.appendChild(li);
  });
  const pie = () => {  // «2 de 5» en la esquina de la lista
    const total = (n.items || []).length, listos = (n.items || []).filter((i) => i.hecho).length;
    el.querySelector(".tipo i").textContent = total ? `${listos}/${total} · ${n.id}` : n.id;
  };
  pie();
  const barras = el.querySelector(".barras");
  barras.innerHTML = "";
  const datos = n.datos || [];
  const max = Math.max(...datos.map((d) => Math.abs(d.valor)), 1);
  for (const d of datos) {
    const fila = document.createElement("div");
    fila.className = "barra";
    fila.innerHTML = "<span></span><div class='riel'><b></b></div><span></span>";
    fila.children[0].textContent = d.etiqueta;
    fila.querySelector("b").style.width = `${Math.round((Math.abs(d.valor) / max) * 100)}%`;
    fila.children[2].textContent = `${d.valor.toLocaleString("es-CO")}${d.unidad || ""}`;
    barras.appendChild(fila);
  }
}

function editar(campo, id) {
  campo.contentEditable = "true";
  campo.focus();
  document.getSelection().selectAllChildren(campo);
  const listo = () => {
    campo.contentEditable = "false";
    campo.removeEventListener("blur", listo);
    const el = campo.closest(".tarjeta");
    guardar({ accion: "cambiar", id, titulo: el.querySelector("h3").textContent.trim(), texto: el.querySelector("p").textContent.trim() });
  };
  campo.addEventListener("blur", listo);
  campo.onkeydown = (e) => {
    if (e.key === "Escape" || (e.key === "Enter" && (campo.tagName === "H3" || e.ctrlKey))) { e.preventDefault(); campo.blur(); }
  };
}

function caja(el) {
  return { x: parseFloat(el.style.left) || 0, y: parseFloat(el.style.top) || 0, w: el.offsetWidth, h: el.offsetHeight };
}

function lineas() {
  const svg = $("#lineas");
  svg.querySelectorAll("g").forEach((g) => g.remove());
  if (!T.tablero) return;
  const els = new Map([...$("#tarjetas").children].map((el) => [el.dataset.id, el]));
  for (const c of T.tablero.conexiones) {
    const a = els.get(c.de), b = els.get(c.a);
    if (!a || !b) continue;
    const A = caja(a), B = caja(b);
    const dx = B.x + B.w / 2 - (A.x + A.w / 2), dy = B.y + B.h / 2 - (A.y + A.h / 2);
    let d, mx, my;
    // lado a lado (como en el mapa mental) si hay espacio entre las dos a lo ancho; si no, de borde inferior a superior
    if (Math.abs(dx) < (A.w + B.w) / 2 + 20) {
      const y1 = dy > 0 ? A.y + A.h : A.y, y2 = dy > 0 ? B.y : B.y + B.h, x1 = A.x + A.w / 2, x2 = B.x + B.w / 2, ym = (y1 + y2) / 2;
      d = `M${x1},${y1} C${x1},${ym} ${x2},${ym} ${x2},${y2}`; mx = (x1 + x2) / 2; my = ym;
    } else {  // lado a lado
      const x1 = dx > 0 ? A.x + A.w : A.x, x2 = dx > 0 ? B.x : B.x + B.w, y1 = A.y + A.h / 2, y2 = B.y + B.h / 2, xm = (x1 + x2) / 2;
      d = `M${x1},${y1} C${xm},${y1} ${xm},${y2} ${x2},${y2}`; mx = xm; my = (y1 + y2) / 2;
    }
    const tipo = (T.tablero.nodos.find((n) => n.id === c.a) || {}).tipo || "idea";
    const g = document.createElementNS("http://www.w3.org/2000/svg", "g");
    const p = document.createElementNS("http://www.w3.org/2000/svg", "path");
    p.setAttribute("d", d);
    p.setAttribute("stroke", (TIPOS[tipo] || TIPOS.idea)[1]);
    p.style.color = (TIPOS[tipo] || TIPOS.idea)[1];
    // una conexión nueva se dibuja de punta a punta (si se repinta a mitad, sigue donde iba)
    const clave = c.de + ">" + c.a, ahora = performance.now();
    if (!T.lineasVistas.has(clave)) T.lineasVistas.set(clave, T.nuevas ? ahora : 0);
    const edad = ahora - T.lineasVistas.get(clave);
    if (edad < 1600) { p.setAttribute("pathLength", "1"); p.classList.add("nueva"); p.style.animationDelay = `${(400 - edad) / 1000}s`; }
    if (HABLA.tarjeta && (c.a === HABLA.tarjeta || c.de === HABLA.tarjeta)) p.classList.add("viva");
    p.setAttribute("marker-end", `url(#punta-${TIPOS[tipo] ? tipo : "idea"})`);
    g.appendChild(p);
    if (c.etiqueta) {
      const tx = document.createElementNS("http://www.w3.org/2000/svg", "text");
      tx.setAttribute("x", mx); tx.setAttribute("y", my - 4); tx.setAttribute("text-anchor", "middle");
      tx.textContent = c.etiqueta;
      g.appendChild(tx);
    }
    svg.appendChild(g);
  }
}

function puntas() {  // una punta de flecha por color (los marcadores no heredan el color de la línea)
  const defs = $("#lineas defs");
  defs.innerHTML = "";
  for (const [tipo, [, color]] of Object.entries(TIPOS)) {
    defs.insertAdjacentHTML("beforeend", `<marker id="punta-${tipo}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" ` +
      `markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="${color}"/></marker>`);
  }
}

function animarLineas(ms) {  // mientras las tarjetas se deslizan, las líneas las siguen
  const hasta = performance.now() + ms;
  const paso = () => { lineas(); if (performance.now() < hasta) requestAnimationFrame(paso); };
  requestAnimationFrame(paso);
}

function anotando(si) {
  $("#anotando").classList.toggle("oculto", !si);
  clearTimeout(anotando.t);
  if (si) anotando.t = setTimeout(() => $("#anotando").classList.add("oculto"), 60000);
}

// ---------- la pizarra: la cuenta, la tabla o las cifras de lo que Maicol está explicando ----------
const PZ = { lista: [], i: -1 };
function botonPizarra() { $("#ver-pizarra").classList.toggle("oculto", !PZ.lista.length); }

function abrirPizarra() {
  const p = PZ.lista[PZ.i];
  if (!p) return;
  const caja = $("#pizarra"), estaba = caja.classList.contains("abierta");
  $("#piz-titulo").textContent = p.titulo || "Pizarra";
  $("#piz-ant").disabled = PZ.i <= 0; $("#piz-sig").disabled = PZ.i >= PZ.lista.length - 1;
  $(".piz-nav").classList.toggle("oculto", PZ.lista.length < 2);
  const cuerpo = $("#piz-cuerpo");
  cuerpo.innerHTML = "";  let espera = 0.15;  // cada cosa aparece después de la anterior, como si la fuera escribiendo
  for (const b of p.bloques || []) {
    let el;
    if (b.tipo === "cuenta") {
      el = document.createElement("div"); el.className = "cuenta-piz";
      for (const f of b.filas || []) {
        const fila = document.createElement("div");
        fila.className = "fila" + (f.op === "=" ? " total" : "") + (f.destacar ? " destacar" : "");
        fila.innerHTML = "<span class='op'></span><span class='et'></span><span class='val'></span>";
        fila.children[0].textContent = { "*": "×", x: "×", "/": "÷", "-": "−" }[f.op] || f.op || "";
        fila.children[1].textContent = f.etiqueta || "";
        fila.style.animationDelay = espera + "s";
        contar(fila.children[2], f.valor || "", espera + 0.1, f.op === "=" ? 1300 : 700);
        espera += f.op === "=" ? 0.5 : 0.32;
        el.appendChild(fila);
      }
    } else if (b.tipo === "tabla") {
      el = document.createElement("table"); el.className = "tabla-piz";
      const cab = el.createTHead().insertRow();
      for (const c of b.columnas || []) { const th = document.createElement("th"); th.textContent = c; cab.appendChild(th); }
      const cuerpoT = el.createTBody();
      for (const fila of b.filas || []) {
        const tr = cuerpoT.insertRow();
        tr.style.animationDelay = espera + "s";
        fila.forEach((celda, i) => { const td = tr.insertCell(); if (i) contar(td, celda, espera, 700); else td.textContent = celda; });
        espera += 0.22;
      }
    } else if (b.tipo === "cifras") {
      el = document.createElement("div"); el.className = "cifras-piz";
      for (const it of b.items || []) {
        const d = document.createElement("div");
        d.innerHTML = "<b></b><span></span>";
        d.children[1].textContent = it.etiqueta || "";
        d.style.animationDelay = espera + "s";
        contar(d.children[0], it.valor || "", espera, 1100);
        espera += 0.18;
        el.appendChild(d);
      }
    } else if (b.tipo === "nota") {
      el = document.createElement("p"); el.className = "nota-piz"; el.textContent = b.texto || "";
    }
    if (!el) continue;
    el.style.animationDelay = (espera - 0.1) + "s";
    espera += 0.15;
    cuerpo.appendChild(el);
  }
  caja.classList.add("abierta");
  botonPizarra();
  aludir(p.tarjetas || []);
  // la pizarra tapa la derecha: si nadie movió la cámara, el tablero se corre para que se vea completo
  if (!estaba && !HABLA.antes && !tocada) setTimeout(() => ajustar(), 80);
}

function cerrarPizarra() {
  const estaba = $("#pizarra").classList.contains("abierta");
  $("#pizarra").classList.remove("abierta");
  aludir([]);
  if (estaba && !HABLA.antes && !tocada && T.tablero) setTimeout(() => ajustar(), 80);
}

function aludir(ids) {  // las tarjetas de las que habla la pizarra se iluminan un rato
  for (const el of $("#tarjetas").children) el.classList.toggle("aludida", ids.includes(el.dataset.id));
  clearTimeout(aludir.t);
  if (ids.length) aludir.t = setTimeout(() => aludir([]), 9000);
}

// los números de la pizarra «corren» hasta su valor («42.000», «1,4 M», «45 pollos/día»)
function contar(el, texto, retraso, ms) {
  texto = String(texto);
  const m = texto.match(/(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d+))?/);
  if (!m) { el.textContent = texto; return; }
  const decimales = m[2] ? m[2].length : 0, puntos = m[1].includes(".") || Number(m[1].replace(/\./g, "")) >= 10000;
  const final = Number(m[1].replace(/\./g, "") + (m[2] ? "." + m[2] : ""));
  const formato = (n) => {
    const [ent, dec] = n.toFixed(decimales).split(".");
    return (puntos ? ent.replace(/\B(?=(\d{3})+(?!\d))/g, ".") : ent) + (dec ? "," + dec : "");
  };
  const antes = texto.slice(0, m.index), despues = texto.slice(m.index + m[0].length);
  el.textContent = antes + formato(0) + despues;
  setTimeout(() => {
    const t0 = performance.now();
    const paso = (ahora) => {
      const t = Math.min(1, (ahora - t0) / ms), e = 1 - (1 - t) ** 4;
      el.textContent = antes + formato(final * e) + despues;
      if (t < 1) requestAnimationFrame(paso);
    };
    requestAnimationFrame(paso);
  }, retraso * 1000);
}

// ---------- Maicol habla y la cámara lo sigue: va a la tarjeta de la que está hablando ----------
const HABLA = { frases: [], actual: -1, tarjeta: null, antes: null, fin: null, toque: 0 };
const VACIAS = new Set(("para pero como este esta esto esos esas sobre entre desde hasta cuando donde porque tiene tienen puede " +
  "pueden seria hacer queda quedaria mucho poco mas menos senor usted ustedes nuestro nuestra todo toda todos todas cada mismo " +
  "misma algo bien ahora entonces tambien unos unas aqui alli eso ese esa sigue siendo bastante caso casos ambos dice decir").split(" "));
const sinTildes = (s) => String(s).normalize("NFD").replace(/\p{M}/gu, "").toLowerCase();
const raices = (t) => new Set((sinTildes(t).match(/\p{L}{4,}/gu) || []).filter((w) => !VACIAS.has(w)).map((w) => w.slice(0, 5)));
function cifras(t) {  // «42 k», «42.000» y «42 mil» son la misma cifra
  const out = new Set();
  for (const m of String(t).matchAll(/(\d{1,3}(?:\.\d{3})+|\d+(?:[.,]\d+)?)\s*(k|mil|M)?(?![\p{L}])/gu)) {
    const n = Number(/^\d{1,3}(\.\d{3})+$/.test(m[1]) ? m[1].replace(/\./g, "") : m[1].replace(",", "."));
    const v = n * (m[2] ? (m[2] === "M" ? 1e6 : 1e3) : 1);
    if (v >= 2) out.add(v);
  }
  return out;
}

function tarjetaDe(frase) {
  if (!T.tablero) return null;
  const fr = raices(frase), fc = cifras(frase);
  let mejor = null, puntos = 0;
  for (const n of T.tablero.nodos) {
    if (n.tipo === "tema") continue;
    const enTitulo = [...raices(n.titulo)].filter((w) => fr.has(w)).length;
    const cuerpo = n.tipo === "seccion" ? "" : `${n.texto || ""} ${(n.items || []).map((i) => i.texto).join(" ")}`;
    const enTexto = [...raices(cuerpo)].filter((w) => fr.has(w)).length;
    const enCifras = [...cifras(`${n.titulo} ${cuerpo}`)].filter((v) => fc.has(v)).length;
    const p = enTitulo * 3 + enTexto + enCifras * 3 - (n.tipo === "seccion" ? 1 : 0);
    if (p > puntos) { puntos = p; mejor = n.id; }
  }
  return puntos >= 3 ? mejor : null;
}

function oir(texto) {  // empieza un trozo de lo que dice: se parte en frases para saber por dónde va
  clearTimeout(HABLA.fin);
  const frases = [], partes = String(texto || "").split(/(?<=[.!?…])\s+/);
  let i = 0;
  for (const f of partes) { frases.push({ texto: f, desde: i / Math.max(1, texto.length) }); i += f.length + 1; }
  HABLA.frases = frases; HABLA.actual = -1;
  avanzar(0);
}

function avanzar(r) {
  let i = 0;
  while (i + 1 < HABLA.frases.length && HABLA.frases[i + 1].desde <= r) i++;
  if (i === HABLA.actual || !HABLA.frases[i]) return;
  HABLA.actual = i;
  const id = tarjetaDe(HABLA.frases[i].texto);
  if (!id || id === HABLA.tarjeta) return;
  HABLA.tarjeta = id;
  for (const el of $("#tarjetas").children) el.classList.toggle("hablando", el.dataset.id === id);
  lineas();
  if (Date.now() - HABLA.toque < 6000) return;  // usted está moviendo el tablero: solo se ilumina
  if (!HABLA.antes) HABLA.antes = { ...V };
  acercar(id);
}

function acercar(id) {
  const el = [...$("#tarjetas").children].find((e) => e.dataset.id === id);
  if (!el) return;
  const c = caja(el), m = margenes();
  const k = Math.min(1.1, Math.max(0.85, V.k));
  const cx = m.lados + (innerWidth - m.lados - m.der) / 2, cy = m.arriba + (innerHeight - m.arriba - m.abajo) / 2;
  irA(cx - (c.x + c.w / 2) * k, cy - (c.y + c.h / 2) * k, k, true, 950);
}

// el escriba anotó algo: la cámara va a verlo aparecer y, si Maicol ya no está hablando, vuelve a mostrar todo
function llegoTarjeta(id) {
  seleccionar(id);
  if (Date.now() - HABLA.toque < 6000) return;
  if (tocada && !HABLA.antes) return enfocar(id);
  requestAnimationFrame(() => acercar(id));
  clearTimeout(llegoTarjeta.t);
  llegoTarjeta.t = setTimeout(() => {  // y luego se aleja un poco: se ve la sección donde quedó, no todo el mapa
    if (!HABLA.antes && Date.now() - HABLA.toque > 6000) verSeccion(id);
  }, 3200);
}

function callado() {  // terminó de hablar: la cámara se aleja hasta ver la sección de la que hablaba (no todo el mapa)
  clearTimeout(HABLA.fin);
  HABLA.fin = setTimeout(() => {
    const ultima = HABLA.tarjeta;
    HABLA.tarjeta = null; HABLA.frases = []; HABLA.actual = -1;
    for (const el of $("#tarjetas").children) el.classList.remove("hablando");
    lineas();
    if (HABLA.antes && ultima && Date.now() - HABLA.toque > 6000) verSeccion(ultima);
    HABLA.antes = null;
  }, 2200);
}

// la rama del mapa a la que pertenece una tarjeta: su sección (o la rama que sale del tema) con todo lo que cuelga
function ramaDe(id) {
  if (!T.tablero) return [];
  const madre = {}, hijas = {};
  for (const c of T.tablero.conexiones) {
    if (madre[c.a]) continue;
    madre[c.a] = c.de; (hijas[c.de] = hijas[c.de] || []).push(c.a);
  }
  const tipo = (i) => (T.tablero.nodos.find((n) => n.id === i) || {}).tipo;
  let raiz = id;
  for (let i = 0; i < 50 && madre[raiz] && tipo(raiz) !== "seccion" && tipo(madre[raiz]) !== "tema"; i++) raiz = madre[raiz];
  if (tipo(raiz) === "tema") return [id];
  const rama = [raiz];
  for (let i = 0; i < rama.length && rama.length < 200; i++) for (const h of hijas[rama[i]] || []) if (!rama.includes(h)) rama.push(h);
  return rama;
}

function verSeccion(id) {
  const ids = new Set(ramaDe(id));
  const els = [...$("#tarjetas").children].filter((e) => ids.has(e.dataset.id));
  const foco = els.find((e) => e.dataset.id === id);
  if (!els.length || !foco) return;
  const cajas = els.map(caja), m = margenes();
  const x0 = Math.min(...cajas.map((c) => c.x)), y0 = Math.min(...cajas.map((c) => c.y));
  const x1 = Math.max(...cajas.map((c) => c.x + c.w)), y1 = Math.max(...cajas.map((c) => c.y + c.h));
  const ancho = innerWidth - m.lados - m.der, alto = innerHeight - m.arriba - m.abajo;
  const holgura = 60;  // un poco de aire alrededor de la sección
  const k = Math.min(0.95, ancho / (x1 - x0 + 2 * holgura), alto / (y1 - y0 + 2 * holgura));
  if (k >= 0.45) {  // la sección cabe: se encuadra completa
    irA(m.lados + (ancho - (x1 - x0) * k) / 2 - x0 * k, m.arriba + (alto - (y1 - y0) * k) / 2 - y0 * k, k, true, 1100);
  } else {  // es muy grande: se queda cerca de la tarjeta, sin alejarse tanto que ya no se lea
    const c = caja(foco), cx = m.lados + ancho / 2, cy = m.arriba + alto / 2;
    irA(cx - (c.x + c.w / 2) * 0.45, cy - (c.y + c.h / 2) * 0.45, 0.45, true, 1100);
  }
}

// ---------- cámara ----------
function camara() { $("#mundo").style.transform = `translate(${V.x}px, ${V.y}px) scale(${V.k})`; }
const limitar = (k) => Math.min(2.2, Math.max(0.2, k));

function zoomEn(cx, cy, factor) {
  const k = limitar(V.k * factor);
  V.x = cx - (cx - V.x) * (k / V.k);
  V.y = cy - (cy - V.y) * (k / V.k);
  V.k = k;
  camara();
}

function margenes() {  // lo que tapan la cabecera, la barra de Maicol y la pizarra
  const der = $("#pizarra").classList.contains("abierta") ? $("#pizarra").offsetWidth + 40 : 40;
  return { arriba: 70, abajo: INCRUSTADO ? 30 : 150, lados: 40, der };
}

let vuelo = 0;
function irA(x, y, k, animar = true, ms = 450) {
  const mio = ++vuelo;  // un vuelo nuevo corta el anterior
  if (!animar) { V.x = x; V.y = y; V.k = k; return camara(); }
  const desde = { ...V }, t0 = performance.now();
  const paso = (ahora) => {
    if (mio !== vuelo) return;
    const t = Math.min(1, (ahora - t0) / ms), e = t < 0.5 ? 4 * t ** 3 : 1 - (-2 * t + 2) ** 3 / 2;
    V.x = desde.x + (x - desde.x) * e; V.y = desde.y + (y - desde.y) * e; V.k = desde.k + (k - desde.k) * e;
    camara();
    if (t < 1) requestAnimationFrame(paso);
  };
  requestAnimationFrame(paso);
}

function ajustar(animar = true) {
  const els = [...$("#tarjetas").children];
  if (!els.length) return;
  // recién abierta, la ventana puede medir 0: el zoom saldría al mínimo y fuera de lugar
  if (innerWidth < 200 || innerHeight < 200) { setTimeout(() => ajustar(false), 200); return; }
  const cajas = els.map(caja), m = margenes();
  const x0 = Math.min(...cajas.map((c) => c.x)), y0 = Math.min(...cajas.map((c) => c.y));
  const x1 = Math.max(...cajas.map((c) => c.x + c.w)), y1 = Math.max(...cajas.map((c) => c.y + c.h));
  const ancho = innerWidth - m.lados - m.der, alto = innerHeight - m.arriba - m.abajo;
  const k = limitar(Math.min(ancho / (x1 - x0), alto / (y1 - y0), 1.05));
  irA(m.lados + (ancho - (x1 - x0) * k) / 2 - x0 * k, m.arriba + (alto - (y1 - y0) * k) / 2 - y0 * k, k, animar);
}

function enfocar(id) {  // si la tarjeta nueva quedó fuera de la vista, la cámara va hacia ella
  const el = [...$("#tarjetas").children].find((e) => e.dataset.id === id);
  if (!el) return;
  seleccionar(id);
  const c = caja(el), m = margenes();
  const sx = V.x + c.x * V.k, sy = V.y + c.y * V.k, sw = c.w * V.k, sh = c.h * V.k;
  const dentro = sx >= m.lados && sy >= m.arriba && sx + sw <= innerWidth - m.der && sy + sh <= innerHeight - m.abajo;
  if (dentro) return;
  const k = Math.max(V.k, 0.6), cx = m.lados + (innerWidth - m.lados - m.der) / 2, cy = m.arriba + (innerHeight - m.arriba - m.abajo) / 2;
  irA(cx - (c.x + c.w / 2) * k, cy - (c.y + c.h / 2) * k, k);
}

function seleccionar(id) {
  T.sel = id;
  for (const el of $("#tarjetas").children) el.classList.toggle("sel", el.dataset.id === id);
}

// ---------- ratón y dedos: mover el lienzo, acercar, arrastrar tarjetas ----------
const vista = $("#vista"), dedos = new Map();
let pan = null, pellizco = null;

vista.addEventListener("pointerdown", (e) => {
  if (e.target.closest("[contenteditable='true'], .borrar")) return;
  const el = e.target.closest(".tarjeta");
  vista.setPointerCapture(e.pointerId);
  dedos.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (dedos.size === 2) {  // dos dedos: pellizcar para acercar
    const [a, b] = [...dedos.values()];
    pellizco = { d: Math.hypot(a.x - b.x, a.y - b.y), k: V.k };
    pan = null; T.moviendo = null;
    return;
  }
  if (el) {
    const c = caja(el);
    T.moviendo = { id: el.dataset.id, el, sx: e.clientX, sy: e.clientY, ox: c.x, oy: c.y, movido: false };
  } else {
    pan = { sx: e.clientX, sy: e.clientY, ox: V.x, oy: V.y };
    vista.classList.add("arrastrando");
  }
});

vista.addEventListener("pointermove", (e) => {
  if (!dedos.has(e.pointerId)) return;
  dedos.set(e.pointerId, { x: e.clientX, y: e.clientY });
  if (pellizco && dedos.size === 2) {
    const [a, b] = [...dedos.values()];
    zoomEn((a.x + b.x) / 2, (a.y + b.y) / 2, (pellizco.k * Math.hypot(a.x - b.x, a.y - b.y) / pellizco.d) / V.k);
  } else if (T.moviendo) {
    const m = T.moviendo, dx = (e.clientX - m.sx) / V.k, dy = (e.clientY - m.sy) / V.k;
    if (Math.abs(dx) + Math.abs(dy) > 3) m.movido = true;
    m.el.style.left = m.ox + dx + "px"; m.el.style.top = m.oy + dy + "px";
    lineas();
  } else if (pan) {
    V.x = pan.ox + e.clientX - pan.sx; V.y = pan.oy + e.clientY - pan.sy;
    camara();
  }
});

function soltar(e) {
  dedos.delete(e.pointerId);
  if (dedos.size < 2) pellizco = null;
  if (T.moviendo && dedos.size === 0) {
    const m = T.moviendo;
    T.moviendo = null;
    if (m.movido) {
      const c = caja(m.el);
      const n = T.tablero.nodos.find((x) => x.id === m.id);
      if (n) { n.x = c.x; n.y = c.y; }
      guardar({ accion: "mover", id: m.id, x: c.x, y: c.y });
    } else seleccionar(m.id);
  }
  if (dedos.size === 0) { pan = null; vista.classList.remove("arrastrando"); }
}
// mientras usted no mueva la cámara, el tablero se mantiene encuadrado aunque cambie el tamaño de la ventana
let tocada = false;
vista.addEventListener("pointerdown", (e) => { HABLA.toque = Date.now(); vuelo++; if (!e.target.closest(".tarjeta")) tocada = true; });
vista.addEventListener("wheel", () => { tocada = true; HABLA.toque = Date.now(); vuelo++; }, { passive: true });
addEventListener("resize", () => { if (!tocada) ajustar(false); });
vista.addEventListener("pointerup", soltar);
vista.addEventListener("pointercancel", soltar);
vista.addEventListener("wheel", (e) => { e.preventDefault(); zoomEn(e.clientX, e.clientY, Math.exp(-e.deltaY * 0.0015)); }, { passive: false });

// ---------- controles ----------
$("#centrar").onclick = () => ajustar();
$("#ver-pizarra").onclick = () => ($("#pizarra").classList.contains("abierta") ? cerrarPizarra() : abrirPizarra());
$("#piz-cerrar").onclick = () => cerrarPizarra();
$("#piz-ant").onclick = () => { if (PZ.i > 0) { PZ.i--; abrirPizarra(); } };
$("#piz-sig").onclick = () => { if (PZ.i < PZ.lista.length - 1) { PZ.i++; abrirPizarra(); } };
$("#cerrar").onclick = () => window.close();  // la ventana va sin marco (como el panel): este es su botón de cerrar
// usted cambió de proyecto aquí: Maicol también (si no, seguía hablando del anterior)
$("#lista").onchange = async (e) => { await cargar(e.target.value); guardar({ accion: "activar" }); };
$("#form").onsubmit = (e) => { e.preventDefault(); enviar($("#texto").value); $("#texto").value = ""; };
$("#sonido").classList.toggle("apagado", !H.sonido);
$("#sonido").onclick = () => {
  H.sonido = !H.sonido;
  try { localStorage.setItem("tablero_sonido", H.sonido ? "si" : "no"); } catch (_) { /* sin almacenamiento */ }
  $("#sonido").classList.toggle("apagado", !H.sonido);
  if (!H.sonido && audio) audio.pause();
};
addEventListener("keydown", (e) => {
  if (e.target.closest && e.target.closest("input, [contenteditable='true']")) return;
  if (e.key === "f" || e.key === "F") ajustar();
});

const Reconocer = window.SpeechRecognition || window.webkitSpeechRecognition;
if (!Reconocer) $("#mic").classList.add("oculto");
$("#mic").onclick = async () => {
  if (!Reconocer) return;
  const r = new Reconocer();
  r.lang = "es-CO"; r.interimResults = true;
  $("#mic").classList.add("activo"); estado("escuchando");
  if (audio) audio.pause();
  if (await buscarPanel()) alPanel({ tipo: "callar" });  // si Maicol estaba hablando, se calla para oírlo
  let ultimo = "", enviado = false, cierre = null;
  const mandar = () => { if (enviado || !ultimo) return; enviado = true; clearTimeout(cierre); try { r.abort(); } catch (_) { /* */ } enviar(ultimo, true); };
  r.onresult = (e) => {
    const res = e.results[e.results.length - 1];
    ultimo = res[0].transcript;
    decir(ultimo);
    if (res.isFinal) return mandar();
    // con música de fondo el reconocimiento no nota que usted terminó: se manda cuando lo entendido deja de cambiar
    clearTimeout(cierre);
    cierre = setTimeout(mandar, 1600);
  };
  r.onend = () => { $("#mic").classList.remove("activo"); if ($("#estado").classList.contains("escuchando")) estado(""); };
  r.start();
};

// la entrada empieza cuando la ventana se pone a crecer desde el panel (primer cambio de tamaño); si nadie la
// transforma (en el panel, en el celular), empieza sola
function aparecer() {
  if (!document.body.classList.contains("entrando")) return;
  document.body.classList.remove("entrando");
  document.body.classList.add("aparecio");
}
addEventListener("resize", () => setTimeout(aparecer, 60), { once: true });
setTimeout(aparecer, INCRUSTADO ? 50 : 900);

puntas();
cargar(T.id);
buscarPanel();  // desde ya: así se sabe si Maicol está en este PC (y el botón de enviar lo dice)
