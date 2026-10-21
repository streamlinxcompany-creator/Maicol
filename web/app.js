/* JARVIS · interfaz HUD */
"use strict";

const $ = (s) => document.querySelector(s);
const ICONOS = {
  mic: '<svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
  enviar: '<svg viewBox="0 0 24 24"><path d="M5 12h14M13 6l6 6-6 6"/></svg>',
  detener: '<svg viewBox="0 0 24 24"><rect x="7" y="7" width="10" height="10" rx="1" fill="#001018"/></svg>',
  clip: '<svg viewBox="0 0 24 24"><path d="M21 11.5l-8.6 8.6a5.5 5.5 0 0 1-7.8-7.8l8.6-8.6a3.7 3.7 0 0 1 5.2 5.2l-8.6 8.6a1.8 1.8 0 0 1-2.6-2.6l7.9-7.9"/></svg>',
  ojo: '<svg viewBox="0 0 24 24"><path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
  voz: '<svg viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4zM15.5 8.5a5 5 0 0 1 0 7M18.5 5.5a9 9 0 0 1 0 13"/></svg>',
  mudo: '<svg viewBox="0 0 24 24"><path d="M11 5 6 9H3v6h3l5 4zM22 9l-6 6M16 9l6 6"/></svg>',
  panel: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M9 4v16"/></svg>',
  mas: '<svg viewBox="0 0 24 24"><path d="M12 5v14M5 12h14"/></svg>',
  ajustes: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z"/></svg>',
};

const guardado = (k, d) => { try { const v = localStorage.getItem("jarvis." + k); return v === null ? d : JSON.parse(v); } catch { return d; } };
const guardar = (k, v) => { try { localStorage.setItem("jarvis." + k, JSON.stringify(v)); } catch { /* sin almacenamiento */ } };

// panel lateral (scripts/maicol_lateral.pyw): solo orbe, respuesta y barra mínima
const LATERAL = new URLSearchParams(location.search).has("lateral");
if (LATERAL) {
  document.body.classList.add("lateral");
  document.title = "Maicol lateral";  // así el lanzador la distingue de la ventana grande
  // Edge dibuja su propia barra de título en las apps: el lanzador la sube fuera de la vista si sabe cuánto mide
  const contarMarco = () => {
    const d = devicePixelRatio || 1;  // el lanzador trabaja en píxeles reales
    const lados = Math.max(0, Math.round((outerWidth - innerWidth) / 2 * d));
    const arriba = Math.max(0, Math.round((outerHeight - innerHeight) * d) - lados);
    fetch("/api/lateral", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ arriba, lados, abajo: lados }) }).catch(() => {});
  };
  contarMarco();
  addEventListener("resize", () => { clearTimeout(contarMarco.t); contarMarco.t = setTimeout(contarMarco, 300); });
  if (new URLSearchParams(location.search).get("lado") === "izquierda") document.body.classList.add("lado-izquierda");
  // cada vez que el panel sale del borde, el contenido entra con un desliz
  document.addEventListener("visibilitychange", () => {
    if (document.hidden) return;
    document.body.classList.remove("entrando"); void document.body.offsetWidth; document.body.classList.add("entrando");
    setTimeout(() => document.body.classList.remove("entrando"), 700);
  });
}

const S = {
  ws: null, modo: "espera", info: null, ia: null,
  vozActiva: guardado("voz", true), sonidos: guardado("sonidos", true),
  voz: guardado("vozId", null), velocidad: guardado("velocidad", 20),
  generando: false, burbuja: null, textoActual: "", ptrVoz: 0, enCodigo: false,
  ultimoProveedor: null, adjuntos: [], confirmacion: null, provActual: null,
  hud: guardado("hud", false),
  ligero: guardado("ligero", false), ligeroAuto: false,
  silenciarPC: guardado("silenciarPC", true), porVoz: false,
};

/* ====================== audio ====================== */
let actx = null, analizador = null, datosFreq = null;
const reproductor = new Audio();
reproductor.crossOrigin = "anonymous";

function iniciarAudio() {
  if (actx) return;
  actx = new (window.AudioContext || window.webkitAudioContext)();
  analizador = actx.createAnalyser();
  analizador.fftSize = 256;
  analizador.smoothingTimeConstant = 0.75;
  datosFreq = new Uint8Array(analizador.frequencyBinCount);
  const fuente = actx.createMediaElementSource(reproductor);
  fuente.connect(analizador);
  analizador.connect(actx.destination);
}

function bip(frec = 880, dur = 0.08, tipo = "sine", vol = 0.05, retraso = 0) {
  if (!actx || !S.sonidos) return;
  const o = actx.createOscillator(), g = actx.createGain(), t = actx.currentTime + retraso;
  o.type = tipo; o.frequency.setValueAtTime(frec, t);
  g.gain.setValueAtTime(0, t); g.gain.linearRampToValueAtTime(vol, t + 0.01); g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
  o.connect(g).connect(actx.destination); o.start(t); o.stop(t + dur + 0.02);
}
const sonido = {
  escuchar: () => { bip(660, 0.09); bip(990, 0.12, "sine", 0.05, 0.08); },
  enviar: () => bip(1320, 0.06, "triangle", 0.035),
  fin: () => { bip(990, 0.08, "sine", 0.03); bip(1480, 0.1, "sine", 0.025, 0.07); },
  alerta: () => { bip(520, 0.15, "square", 0.03); bip(520, 0.15, "square", 0.03, 0.22); },
  rotar: () => { bip(400, 0.06, "sawtooth", 0.02); bip(800, 0.08, "sawtooth", 0.02, 0.05); },
};

/* ---- cola de voz: se habla frase a frase mientras llega el texto ---- */
const colaVoz = [];
let hablando = false;

function limpiarParaVoz(t) {
  return t.replace(/```[\s\S]*?```/g, " ").replace(/`([^`]*)`/g, "$1").replace(/\[([^\]]+)\]\([^)]+\)/g, "$1")
    .replace(/https?:\/\/(www\.)?([^\/\s]+)\S*/g, "$2").replace(/[*_#>|~]/g, "").replace(/\s+/g, " ").trim();
}

// Edge trae las mismas voces neuronales de Microsoft: hablar con ellas empieza en ~0,1 s,
// mientras que pedir el audio al núcleo (edge-tts) tarda de 1 a 9 s según el servidor de Microsoft
function vozNavegador() {
  if (!("speechSynthesis" in window)) return null;
  const id = S.voz || (S.info && S.info.voz) || "";
  const m = id.match(/^([a-z]{2}-[A-Z]{2})-(\w+?)Neural$/);
  if (!m) return null;
  const sinTildes = (s) => s.normalize("NFD").replace(/\p{M}/gu, "");
  const nombre = "Microsoft " + m[2].replace("Multilingual", " Multilingual") + " ";
  return speechSynthesis.getVoices().find((v) => v.lang === m[1] && sinTildes(v.name).startsWith(nombre)) || null;
}

// Edge carga la lista de voces en segundo plano: hasta que llega, se espera (máx. 1,5 s) para no
// decir las primeras frases con el audio del núcleo y el resto con la voz de Edge
const vocesListas = new Promise((ok) => {
  if (!("speechSynthesis" in window) || speechSynthesis.getVoices().length) return ok();
  speechSynthesis.addEventListener("voiceschanged", ok, { once: true });
  setTimeout(ok, 1500);
});

function hablarNavegador(t, voz, volumen = 1) {
  return new Promise((ok) => {
    const u = new SpeechSynthesisUtterance(t);
    u.voice = voz;
    u.volume = volumen;
    // con la voz elegida, su propio idioma: si se pide «es-ES» a una voz en-US, Edge a veces arranca la frase
    // con su voz española por defecto (de mujer). Las Multilingual detectan solas que el texto es español
    u.lang = voz ? voz.lang : "es-ES";
    u.rate = Math.min(2, Math.max(0.5, 1 + S.velocidad / 100));
    u.pitch = Math.min(2, Math.max(0, 1 + (parseFloat((S.info && S.info.voz_tono) || "0") || 0) / 60));
    // la voz de Edge no pasa por el analizador de audio: el orbe late con cada palabra que dice
    if (volumen) {
      u.onstart = () => { vozNativa = true; pulsoVoz = 1; };
      u.onboundary = () => { pulsoVoz = 1; };
    }
    u.onend = () => { if (volumen) vozNativa = false; ok(true); };
    u.onerror = (e) => { if (volumen) vozNativa = false; ok(e.error === "interrupted" || e.error === "canceled"); };
    speechSynthesis.speak(u);
  });
}

function decir(texto) {
  const t = limpiarParaVoz(texto);
  if (!t || !S.vozActiva) return;
  colaVoz.push(vocesListas.then(() => (vozNavegador() ? { nativa: t } : audioNucleo(t))));
  revisarSilencio();  // pausa la música mientras se genera el audio, antes de que empiece a sonar
  if (!hablando) reproducirCola();
}

function audioNucleo(t) {
  const params = new URLSearchParams({ texto: t, velocidad: (S.velocidad >= 0 ? "+" : "") + S.velocidad + "%" });
  if (S.voz) params.set("voz_id", S.voz);
  return fetch("/api/tts?" + params).then((r) => { if (!r.ok) throw new Error("tts"); return r.blob(); })
    .then((b) => URL.createObjectURL(b)).catch(() => ({ respaldo: t }));
}

async function reproducirCola() {
  hablando = true;
  while (colaVoz.length) {
    let item = await colaVoz.shift();
    if (!hablando) break;
    if (item && item.nativa) {
      // una frase a la vez: si la voz de Edge falla en una (p. ej. un corte de red), esa misma frase
      // se pide al núcleo con la misma voz, sin adelantarse ni pisarse con la siguiente
      poner("hablando");
      const voz = vozNavegador();
      // «synthesis-failed» suele ser pasajero (p. ej. justo tras cancelar): un reintento sale al instante
      if (voz && ((await hablarNavegador(item.nativa, voz)) || !hablando || (await hablarNavegador(item.nativa, voz)) || !hablando)) continue;
      item = await audioNucleo(item.nativa);
    }
    poner("hablando");
    if (typeof item === "string") {
      reproductor.src = item;
      try {
        await reproductor.play();
        await new Promise((ok) => { reproductor.onended = ok; reproductor.onerror = ok; reproductor.onpause = ok; });
      } catch { /* autoplay bloqueado */ }
      URL.revokeObjectURL(item);
    } else if (item && item.respaldo && "speechSynthesis" in window) {
      await hablarNavegador(item.respaldo, vozNavegador());  // último recurso: la voz de Edge si la hay, si no la de Windows
    }
  }
  hablando = false;
  if (S.modo === "hablando") poner(S.generando ? "pensando" : "espera");
  revisarSilencio();
}

function callar() {
  colaVoz.length = 0;
  hablando = false;
  reproductor.pause();
  // cancelar sin nada sonando hace fallar la siguiente frase en Edge («synthesis-failed»)
  if ("speechSynthesis" in window && (speechSynthesis.speaking || speechSynthesis.pending)) speechSynthesis.cancel();
  if (S.modo === "hablando") poner("espera");
  revisarSilencio();
}

/* ---- silencio del PC: pausa la música y silencia otros sonidos mientras JARVIS habla o te escucha ---- */
const silencioPC = { activo: false, espera: null, pulso: null };
function navegadorJarvis() {
  const ua = navigator.userAgent;
  if (navigator.brave) return "brave.exe";
  if (/Edg\//.test(ua)) return "msedge.exe";
  if (/OPR\//.test(ua)) return "opera.exe";
  if (/Firefox\//.test(ua)) return "firefox.exe";
  return "chrome.exe";
}
function necesitaSilencio() {
  if (!S.silenciarPC) return false;
  return hablando || colaVoz.length > 0 || S.modo === "escuchando" || escucha.directo || escucha.esperandoComando || (S.generando && S.porVoz && S.vozActiva);
}
let ultimoCalentado = 0;
function precalentar() {
  // despierta la IA local del servidor mientras el usuario habla o escribe (cada 3 min como mucho)
  if (Date.now() - ultimoCalentado < 180000) return;
  ultimoCalentado = Date.now();
  fetch("/api/precalentar", { method: "POST" }).catch(() => {});
}
function pedirSilencio(activar) {
  fetch("/api/silencio", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ activar, navegador: navegadorJarvis() }) }).catch(() => {});
}
function revisarSilencio() {
  if (necesitaSilencio()) {
    clearTimeout(silencioPC.espera); silencioPC.espera = null;
    if (!silencioPC.activo) {
      silencioPC.activo = true;
      pedirSilencio(true);
      silencioPC.pulso = setInterval(() => pedirSilencio(true), 20000);  // el núcleo restaura solo si deja de oír estos avisos
    }
  } else if (silencioPC.activo && !silencioPC.espera) {
    // pequeña pausa antes de devolver el sonido: entre frase y frase no debe volver la música
    silencioPC.espera = setTimeout(() => {
      silencioPC.espera = null;
      if (necesitaSilencio()) return;
      silencioPC.activo = false; clearInterval(silencioPC.pulso);
      pedirSilencio(false);
    }, 1500);
  }
}
addEventListener("pagehide", () => {
  if (silencioPC.activo) navigator.sendBeacon("/api/silencio", new Blob([JSON.stringify({ activar: false })], { type: "application/json" }));
});

function alimentarVoz(final = false) {
  if (!S.vozActiva) return;
  const resto = S.textoActual.slice(S.ptrVoz);
  if (S.enCodigo) return;
  const iCod = resto.indexOf("```");
  let zona = iCod >= 0 ? resto.slice(0, iCod) : resto;
  let corte = -1;
  const re = /[.!?…:;](\s|$)|\n/g;
  let m;
  while ((m = re.exec(zona))) { if (m.index + 1 >= 20 || final) corte = m.index + 1; }
  if (final) corte = zona.length;
  if (corte > 0) {
    decir(zona.slice(0, corte));
    S.ptrVoz += corte;
  }
  if (iCod >= 0 && S.ptrVoz >= S.textoActual.length - resto.length + iCod) {
    S.enCodigo = true;
    decir("Te dejo el detalle en pantalla.");
  }
}

/* ====================== reactor ====================== */
const lienzo = $("#reactor"), g2 = lienzo.getContext("2d");
const nodos = {};       // id proveedor -> {ang, estado}
const rayos = [];       // efectos de rotación/selección
let nivelSuave = 0, tiempo = 0, vozNativa = false, pulsoVoz = 0;
const ACENTOS = { espera: [0, 229, 255], escuchando: [61, 255, 168], pensando: [255, 181, 71], hablando: [0, 229, 255], error: [255, 77, 94], herramienta: [180, 140, 255] };
let colorActual = [0, 229, 255];

function rgba(c, a) { return `rgba(${c[0] | 0},${c[1] | 0},${c[2] | 0},${a})`; }

// resolución limitada: en pantallas con escala 150 %+ dibujar a resolución nativa cuesta el doble sin verse mejor
const DPR = () => Math.min(devicePixelRatio || 1, 1.25);
function ajustarLienzo(c) {
  const r = c.getBoundingClientRect(), d = DPR();
  if (c.width !== Math.round(r.width * d) || c.height !== Math.round(r.height * d)) { c.width = Math.round(r.width * d); c.height = Math.round(r.height * d); return true; }
  return false;
}

function nivelAudio() {
  let objetivo = 0;
  if (vozNativa) {
    pulsoVoz *= 0.9;
    objetivo = 0.32 + 0.5 * pulsoVoz + 0.08 * Math.sin(tiempo * 17) + 0.05 * Math.sin(tiempo * 29);
  } else if (analizador && hablando) {
    analizador.getByteFrequencyData(datosFreq);
    let s = 0; for (let i = 2; i < 60; i++) s += datosFreq[i];
    objetivo = Math.min(1, s / 58 / 160);
  } else if (S.modo === "pensando" || S.modo === "herramienta") {
    objetivo = 0.25 + 0.15 * Math.sin(tiempo * 6);
  } else if (S.modo === "escuchando") {
    objetivo = 0.3 + 0.2 * Math.sin(tiempo * 3);
  }
  nivelSuave += (objetivo - nivelSuave) * 0.2;
  return nivelSuave;
}

function dibujarReactor(dt) {
  ajustarLienzo(lienzo);
  const w = lienzo.width, h = lienzo.height, cx = w / 2, cy = h / 2, R = Math.min(w, h) / 2;
  const obj = ACENTOS[S.modo] || ACENTOS.espera;
  colorActual = colorActual.map((v, i) => v + (obj[i] - v) * 0.08);
  const C = colorActual, nivel = nivelAudio();
  const vel = S.modo === "pensando" || S.modo === "herramienta" ? 3.2 : S.modo === "escuchando" ? 1.6 : 1;
  tiempo += dt;
  g2.clearRect(0, 0, w, h);
  g2.save(); g2.translate(cx, cy);

  // halo
  const halo = g2.createRadialGradient(0, 0, R * 0.1, 0, 0, R * 0.95);
  halo.addColorStop(0, rgba(C, 0.18 + nivel * 0.25)); halo.addColorStop(0.5, rgba(C, 0.04)); halo.addColorStop(1, "rgba(0,0,0,0)");
  g2.fillStyle = halo; g2.beginPath(); g2.arc(0, 0, R, 0, Math.PI * 2); g2.fill();

  // anillo exterior segmentado
  g2.lineWidth = R * 0.006; g2.strokeStyle = rgba(C, 0.5);
  for (let i = 0; i < 4; i++) {
    const a0 = tiempo * 0.15 * vel + i * Math.PI / 2;
    g2.beginPath(); g2.arc(0, 0, R * 0.93, a0, a0 + Math.PI / 3); g2.stroke();
  }
  g2.strokeStyle = rgba(C, 0.15); g2.beginPath(); g2.arc(0, 0, R * 0.88, 0, Math.PI * 2); g2.stroke();

  // nodos de proveedores (la "matriz neuronal")
  const ancho = lienzo.clientWidth;
  const ids = ancho < 150 ? [] : Object.keys(nodos);
  const conEtiquetas = ancho >= 320;
  ids.forEach((id, i) => {
    const n = nodos[id];
    n.ang = -Math.PI / 2 + (i / ids.length) * Math.PI * 2 + tiempo * 0.02;
    const x = Math.cos(n.ang) * R * 0.78, y = Math.sin(n.ang) * R * 0.78;
    const col = n.estado === "activo" ? C : n.estado === "ok" ? [61, 255, 168] : n.estado === "parcial" ? [255, 181, 71] : n.estado === "agotado" ? [255, 77, 94] : [50, 80, 100];
    const r = R * (n.estado === "activo" ? 0.03 + 0.008 * Math.sin(tiempo * 10) : n.estado === "apagado" ? 0.012 : 0.02);
    g2.fillStyle = rgba(col, n.estado === "apagado" ? 0.5 : 0.95);
    g2.beginPath(); g2.arc(x, y, r, 0, Math.PI * 2); g2.fill();
    g2.fillStyle = rgba(col, n.estado === "apagado" ? 0.35 : 0.8);
    g2.font = `${Math.max(9, R * 0.034)}px Rajdhani, sans-serif`; g2.textAlign = "center"; g2.textBaseline = "middle";
    if (conEtiquetas) g2.fillText(n.corto, Math.cos(n.ang) * R * 0.845 * 1.0 + 0, Math.sin(n.ang) * R * 0.845);
    if (n.estado === "activo") {
      g2.strokeStyle = rgba(C, 0.25 + 0.2 * Math.sin(tiempo * 8)); g2.lineWidth = R * 0.004;
      g2.setLineDash([R * 0.02, R * 0.015]); g2.lineDashOffset = -tiempo * R * 0.3;
      g2.beginPath(); g2.moveTo(Math.cos(n.ang) * R * 0.2, Math.sin(n.ang) * R * 0.2); g2.lineTo(x, y); g2.stroke(); g2.setLineDash([]);
    }
  });

  // rayos de rotación entre proveedores
  for (let i = rayos.length - 1; i >= 0; i--) {
    const ry = rayos[i]; ry.v -= 0.012;
    if (ry.v <= 0) { rayos.splice(i, 1); continue; }
    const a = nodos[ry.desde], b = nodos[ry.hasta];
    if (!a || !b) continue;
    const xa = Math.cos(a.ang) * R * 0.78, ya = Math.sin(a.ang) * R * 0.78, xb = Math.cos(b.ang) * R * 0.78, yb = Math.sin(b.ang) * R * 0.78;
    g2.strokeStyle = `rgba(255,181,71,${ry.v})`; g2.lineWidth = R * 0.008;
    g2.beginPath(); g2.moveTo(xa, ya); g2.quadraticCurveTo(0, 0, xb, yb); g2.stroke();
  }

  // ecualizador radial
  const barras = S.ligero ? 48 : 96;
  g2.strokeStyle = rgba(C, 0.35 + nivel * 0.5); g2.lineWidth = R * 0.008;
  g2.beginPath();
  for (let i = 0; i < barras; i++) {
    const a = (i / barras) * Math.PI * 2 - Math.PI / 2;
    let amp = 0.012;
    if (analizador && hablando && !vozNativa) amp += (datosFreq[(i % 48) + 2] / 255) * 0.09;
    else if (vozNativa) amp += nivel * 0.07 * (0.55 + 0.45 * Math.sin(i * 1.3 + tiempo * 21) * Math.sin(i * 0.37 - tiempo * 9));
    else amp += nivel * 0.03 * (0.5 + 0.5 * Math.sin(i * 0.7 + tiempo * 5 * vel));
    const r0 = R * 0.6, r1 = r0 + R * amp;
    g2.moveTo(Math.cos(a) * r0, Math.sin(a) * r0); g2.lineTo(Math.cos(a) * r1, Math.sin(a) * r1);
  }
  g2.stroke();

  // anillo de marcas giratorio
  g2.save(); g2.rotate(-tiempo * 0.3 * vel);
  g2.strokeStyle = rgba(C, 0.6); g2.lineWidth = R * 0.01;
  for (let i = 0; i < 3; i++) { const a0 = i * (Math.PI * 2 / 3); g2.beginPath(); g2.arc(0, 0, R * 0.5, a0, a0 + Math.PI * 0.45); g2.stroke(); }
  g2.restore();
  g2.save(); g2.rotate(tiempo * 0.5 * vel);
  g2.setLineDash([R * 0.01, R * 0.02]); g2.strokeStyle = rgba(C, 0.45); g2.lineWidth = R * 0.02;
  g2.beginPath(); g2.arc(0, 0, R * 0.43, 0, Math.PI * 2); g2.stroke(); g2.setLineDash([]);
  g2.restore();

  // segmentos del reactor (diseño clásico de 10 bobinas)
  g2.save(); g2.rotate(tiempo * 0.12 * vel);
  for (let i = 0; i < 10; i++) {
    const a0 = (i / 10) * Math.PI * 2, a1 = a0 + Math.PI * 2 / 10 * 0.72;
    g2.fillStyle = rgba(C, 0.22 + nivel * 0.5);
    g2.strokeStyle = rgba(C, 0.85);
    g2.lineWidth = R * 0.004;
    g2.beginPath(); g2.arc(0, 0, R * 0.36, a0, a1); g2.arc(0, 0, R * 0.25, a1, a0, true); g2.closePath(); g2.fill(); g2.stroke();
  }
  g2.restore();

  // núcleo
  const rn = R * (0.17 + nivel * 0.05);
  const nucleo = g2.createRadialGradient(0, 0, 0, 0, 0, rn);
  nucleo.addColorStop(0, "rgba(255,255,255,0.98)"); nucleo.addColorStop(0.35, rgba(C, 0.9)); nucleo.addColorStop(1, rgba(C, 0));
  g2.fillStyle = nucleo;
  g2.beginPath(); g2.arc(0, 0, rn, 0, Math.PI * 2); g2.fill();
  g2.strokeStyle = rgba(C, 0.9); g2.lineWidth = R * 0.006;
  g2.beginPath(); g2.arc(0, 0, R * 0.2, 0, Math.PI * 2); g2.stroke();
  g2.restore();
}

/* fondo: rejilla y partículas estáticas (se dibuja solo al cambiar el tamaño de la ventana) */
const fondo = $("#fondo"), gf = fondo.getContext("2d");
const parts = Array.from({ length: 50 }, () => ({ x: Math.random(), y: Math.random(), r: Math.random() * 1.6 + 0.3 }));
function dibujarFondo() {
  if (!ajustarLienzo(fondo) && fondo.dataset.listo) return;
  fondo.dataset.listo = 1;
  const w = fondo.width, h = fondo.height, paso = 46 * DPR();
  gf.clearRect(0, 0, w, h);
  gf.strokeStyle = "rgba(0,229,255,0.035)"; gf.lineWidth = 1;
  gf.beginPath();
  for (let x = 0; x < w; x += paso) { gf.moveTo(x, 0); gf.lineTo(x, h); }
  for (let y = 0; y < h; y += paso) { gf.moveTo(0, y); gf.lineTo(w, y); }
  gf.stroke();
  for (const p of parts) {
    gf.fillStyle = `rgba(0,229,255,${0.15 + p.r * 0.15})`;
    gf.beginPath(); gf.arc(p.x * w, p.y * h, p.r * DPR(), 0, Math.PI * 2); gf.fill();
  }
}
addEventListener("resize", dibujarFondo);

/* el reactor se anima a 30 fps cuando JARVIS hace algo, 12 en reposo (6 en modo ligero) y se detiene si la ventana no se ve */
let ultimoCuadro = 0;
function fpsObjetivo() {
  if (document.hidden) return 0;
  const activo = hablando || S.modo !== "espera";
  if (S.ligero) return activo ? 20 : 6;
  return activo ? 30 : 12;
}
function bucle(t) {
  requestAnimationFrame(bucle);
  const fps = fpsObjetivo();
  if (!fps || t - ultimoCuadro < 1000 / fps - 2) return;
  const dt = ultimoCuadro ? Math.min(0.1, (t - ultimoCuadro) / 1000) : 0.016;
  ultimoCuadro = t;
  dibujarReactor(dt);
}

/* ====================== estado / modo ====================== */
const TEXTO_MODO = { espera: "EN ESPERA", escuchando: "ESCUCHANDO", pensando: "PROCESANDO", hablando: "HABLANDO", error: "ERROR", herramienta: "EJECUTANDO" };
function poner(modo, texto) {
  S.modo = modo;
  document.body.dataset.modo = modo;
  $("#estado").textContent = texto || TEXTO_MODO[modo] || modo.toUpperCase();
  if (modo === "espera") { S.provActual = null; $("#entrada").placeholder = PLACEHOLDER; }
  if (modo === "escuchando") precalentar();
  pintarPildora();
  revisarSilencio();
}

/* ---- modo limpio: píldora de estado, cajón y pantalla de inicio ---- */
const PLACEHOLDER = $("#entrada").placeholder;
const MODO_HUMANO = { escuchando: "Escuchando", pensando: "Pensando", hablando: "Hablando", herramienta: "Trabajando", error: "Error" };
function pintarPildora() {
  const p = $("#pildora");
  if (!p) return;
  let txt;
  if (S.modo !== "espera" && MODO_HUMANO[S.modo]) txt = MODO_HUMANO[S.modo] + (S.provActual ? " · " + S.provActual : "");
  else if (S.ia) {
    const n = S.ia.proveedores.filter((x) => x.configurado && x.ranuras).length;
    txt = `${n} IAs listas · ${S.ia.libres}/${S.ia.total} modelos`;
  } else txt = "Conectando…";
  p.innerHTML = `<i></i>${escapar(txt)}`;
}
function actualizarVacio() { document.body.classList.toggle("vacio", !chat.querySelector(".msg")); }
function aplicarInterfaz() {
  document.body.classList.toggle("limpio", !S.hud);
  document.body.classList.remove("panel");
  actualizarVacio();
  fondo.dataset.listo = "";
  dibujarFondo();
}
function alternarPanel(abrir) { document.body.classList.toggle("panel", abrir ?? !document.body.classList.contains("panel")); }

/* ====================== chat ====================== */
function escapar(t) { return t.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

function markdown(texto) {
  const bloques = [];
  let t = texto.replace(/```(\w*)\n?([\s\S]*?)(```|$)/g, (_, l, c) => { bloques.push(`<pre><code>${escapar(c.replace(/\n$/, ""))}</code></pre>`); return `\u0000${bloques.length - 1}\u0000`; });
  t = escapar(t)
    .replace(/`([^`\n]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>")
    .replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<i>$2</i>")
    .replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/(^|[\s(])(https?:\/\/[^\s<)]+)/g, '$1<a href="$2" target="_blank" rel="noopener">$2</a>')
    .replace(/^#{1,4} (.+)$/gm, "<b>$1</b>");
  const lineas = t.split("\n"); let html = "", lista = null;
  for (const l of lineas) {
    const mu = l.match(/^\s*[-*•] (.+)/), mo = l.match(/^\s*\d+[.)] (.+)/);
    if (mu || mo) {
      const tipo = mu ? "ul" : "ol";
      if (lista !== tipo) { if (lista) html += `</${lista}>`; html += `<${tipo}>`; lista = tipo; }
      html += `<li>${(mu || mo)[1]}</li>`;
    } else {
      if (lista) { html += `</${lista}>`; lista = null; }
      if (l.trim()) html += `<p>${l}</p>`;
    }
  }
  if (lista) html += `</${lista}>`;
  return html.replace(/\u0000(\d+)\u0000/g, (_, i) => bloques[+i]);
}

const chat = $("#chat");
function alFondo() { chat.scrollTop = chat.scrollHeight; }

function burbuja(rol, texto = "", meta = null, imagenes = []) {
  const d = document.createElement("div");
  d.className = "msg " + (rol === "user" ? "usuario" : "jarvis");
  d.innerHTML = `<div class="cuerpo"></div>`;
  d.querySelector(".cuerpo").innerHTML = rol === "user" ? escapar(texto).replace(/\n/g, "<br>") : markdown(texto);
  for (const src of imagenes) { const im = document.createElement("img"); im.src = src; d.appendChild(im); }
  if (meta) ponerMeta(d, meta);
  chat.appendChild(d); alFondo();
  actualizarVacio();
  return d;
}

function ponerMeta(d, m) {
  if (!m || !m.proveedor) return;
  let e = d.querySelector(".meta");
  if (!e) { e = document.createElement("div"); e.className = "meta"; d.appendChild(e); }
  e.textContent = `${m.proveedor} · ${m.modelo} · ${m.segundos}s · ${m.tokens} tok`;
}

/* ---- lienzo visual: lo que Maicol dibuja con mostrar_visual ---- */
const ANCHO_LIENZO_LATERAL = 640;  // en el panel lateral la ventana se ensancha esto hacia el centro de la pantalla
const plantillaLienzo = fetch("/static/lienzo.css").then((r) => r.text()).catch(() => "");

async function mostrarVisual(ev) {
  if (ev.cerrar) return cerrarVisual();
  const css = await plantillaLienzo;
  $("#lienzo-titulo").textContent = ev.titulo || "";
  // sin red ni acceso a la página: solo pinta lo que trae
  $("#lienzo-marco").srcdoc = '<!doctype html><html lang="es"><head><meta charset="utf-8">' +
    `<meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data: blob:; font-src data:">` +
    `<style>${css}</style></head><body>` +
    '<svg width="0" height="0" style="position:absolute"><defs><marker id="flecha" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0L10 5L0 10z" fill="#00e5ff"/></marker></defs></svg>' +
    `<main class="lienzo-contenido">${ev.html || ""}</main></body></html>`;
  S.ultimoVisual = ev;
  document.body.classList.add("con-lienzo");
  $("#lienzo").setAttribute("aria-hidden", "false");
  if (LATERAL) avisarLienzo(ANCHO_LIENZO_LATERAL);
}

function cerrarVisual() {
  document.body.classList.remove("con-lienzo");
  $("#lienzo").setAttribute("aria-hidden", "true");
  if (LATERAL) avisarLienzo(0);
}

function avisarLienzo(ancho) {  // el lanzador del lateral ensancha o encoge la ventana
  fetch("/api/lateral", { method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ lienzo: Math.round(ancho * (devicePixelRatio || 1)) }) }).catch(() => {});
}

function chip(texto, clase = "") {
  const c = document.createElement("div");
  c.className = "chip " + clase; c.textContent = texto;
  chat.appendChild(c); alFondo();
  return c;
}

function subtitulo(texto, usuario = false) {
  const s = $("#subtitulo");
  if (LATERAL) {
    // en el panel lateral la respuesta se ve completa (con la pregunta encima) y baja sola mientras llega
    if (usuario) S.pregunta = texto;
    s.innerHTML = usuario ? `<span class="usuario">${escapar(texto)}</span>`
      : (S.pregunta ? `<span class="pregunta">${escapar(S.pregunta)}</span>` : "") + escapar(limpiarParaVoz(texto));
    s.scrollTop = s.scrollHeight;
    return;
  }
  if (usuario) $("#entrada").placeholder = texto;
  s.innerHTML = usuario ? `<span class="usuario">${escapar(texto)}</span>` : escapar(limpiarParaVoz(texto)).slice(-260);
}

/* ====================== conexión ====================== */
function conectar() {
  const ws = new WebSocket((location.protocol === "https:" ? "wss://" : "ws://") + location.host + "/ws");
  S.ws = ws;
  ws.onopen = async () => {
    $("#sub-marca").textContent = "EN LÍNEA";
    // si el núcleo se actualizó mientras la ventana estaba abierta, recarga la interfaz
    const e = await fetch("/api/estado").then((r) => r.json()).catch(() => null);
    if (e && S.info && S.info.version && e.version !== S.info.version) location.reload();
  };
  ws.onclose = () => { $("#sub-marca").textContent = "RECONECTANDO…"; setTimeout(conectar, 1500); };
  ws.onmessage = (e) => manejar(JSON.parse(e.data));
}

function enviarWS(o) { if (S.ws && S.ws.readyState === 1) { S.ws.send(JSON.stringify(o)); return true; } return false; }

let chipsHerramienta = {};
function manejar(ev) {
  switch (ev.type) {
    case "sistema": return pintarSistema(ev);
    case "ia": return pintarIA(ev);
    case "proveedor": {
      const anterior = S.rotandoDesde;
      S.ultimoProveedor = ev.id_proveedor;
      if (anterior && nodos[anterior] && nodos[ev.id_proveedor]) rayos.push({ desde: anterior, hasta: ev.id_proveedor, v: 1 });
      S.rotandoDesde = null;
      S.provActual = ev.proveedor.replace(/ \(.*\)$/, "");
      marcarActivo(ev.id_proveedor);
      if (S.modo !== "hablando") poner("pensando", "ENLACE: " + ev.proveedor.toUpperCase());
      return;
    }
    case "pensando": if (S.modo !== "hablando") poner("pensando", "RAZONANDO"); return;
    case "rotacion": {
      S.rotandoDesde = ev.desde.split(":")[0];
      sonido.rotar();
      chip(`↻ ${ev.proveedor}: ${ev.motivo} → rotando`, "rot");
      return;
    }
    case "reset":
      S.textoActual = ""; S.ptrVoz = 0; S.enCodigo = false; callar();
      if (S.burbuja) S.burbuja.querySelector(".cuerpo").innerHTML = "";
      return;
    case "token": {
      if (!S.burbuja) { S.burbuja = burbuja("assistant"); S.burbuja.classList.add("escribiendo"); }
      S.textoActual += ev.text;
      S.burbuja.querySelector(".cuerpo").innerHTML = markdown(S.textoActual);
      subtitulo(S.textoActual);
      alFondo();
      alimentarVoz(false);
      return;
    }
    case "herramienta": {
      const clave = ev.nombre + JSON.stringify(ev.args);
      if (ev.estado === "inicio") {
        poner("herramienta", "EJECUTANDO: " + ev.nombre.replace(/_/g, " ").toUpperCase());
        const a = Object.values(ev.args || {}).map((v) => String(v).slice(0, 40)).join(", ");
        chipsHerramienta[clave] = chip(`⚙ ${ev.nombre}(${a})`);
        // el texto previo a la herramienta queda en su burbuja; la respuesta irá en una nueva
        if (S.burbuja) { S.burbuja.classList.remove("escribiendo"); if (!S.textoActual.trim()) S.burbuja.remove(); }
        alimentarVoz(true);
        S.burbuja = null; S.textoActual = ""; S.ptrVoz = 0; S.enCodigo = false;
      } else {
        const c = chipsHerramienta[clave];
        if (c) { c.classList.add("ok"); c.textContent = c.textContent.replace("⚙", "✓"); c.title = ev.resultado || ""; }
        poner("pensando");
      }
      return;
    }
    case "confirmar": return pedirConfirmacion(ev);
    case "fin": {
      if (S.burbuja) { S.burbuja.classList.remove("escribiendo"); ponerMeta(S.burbuja, ev.meta); }
      alimentarVoz(true);
      S.generando = false; S.burbuja = null;
      botonEnviar();
      sonido.fin();
      if (!hablando && !colaVoz.length) poner("espera");
      setTimeout(() => marcarActivo(null), 1500);
      if (escucha.continua) escucha.iniciar();
      return;
    }
    case "error":
      chip("✕ " + ev.texto, "rot"); poner("error"); S.generando = false; botonEnviar();
      setTimeout(() => poner("espera"), 2500);
      return;
    case "archivo":
      tarjetaArchivo(ev);
      if (ev.origen && ev.origen.toLowerCase() !== miDispositivo()) aviso("ARCHIVO", `${ev.nombre} · desde ${ev.origen}`);
      return;
    case "modo":
      document.body.dataset.modo = ev.nombre || "";
      aviso("MODO", ev.nombre ? `Modo ${ev.nombre}${ev.tarea ? " · " + ev.tarea : ""} activado` : "Modo desactivado");
      return;
    case "visual":
      mostrarVisual(ev);
      if (!ev.cerrar) {  // en el registro queda un acceso para volver a verlo
        const c = chip("◈ " + (ev.titulo || "Visual") + " · ver", "visual");
        c.onclick = () => mostrarVisual(ev);
      }
      return;
    case "anuncio":
      burbuja("assistant", ev.texto);
      subtitulo(ev.texto);
      decir(ev.texto);
      return;
    case "externo": {
      // conversación que ocurrió en otro dispositivo (p. ej. el celular): se muestra aquí en vivo
      const icono = { celular: "📱 ", pc: "💻 " }[ev.dispositivo] || "";
      if (ev.texto) burbuja(ev.rol === "user" ? "user" : "assistant", ev.rol === "user" ? icono + ev.texto : ev.texto);
      return;
    }
    case "tecla":
      // tecla rombo del Victus: si habla, se calla; si no, escucha una orden
      iniciarAudio();
      if (!$("#arranque").classList.contains("fuera")) { $("#btn-iniciar").click(); setTimeout(() => escucha.alternarDirecto(), 600); return; }
      if (hablando || colaVoz.length) { callar(); return; }
      escucha.alternarDirecto();
      return;
    case "recordatorio":
      sonido.alerta();
      aviso("RECORDATORIO", ev.texto, true);
      decir(ev.texto);
      return;
  }
}

function enviar(texto, porVoz = false) {
  S.porVoz = porVoz;
  texto = (texto || "").trim();
  if (!texto && !S.adjuntos.length) return;
  if (!texto) texto = "¿Qué ves en esta imagen?";
  iniciarAudio();
  callar();
  // la voz «Online» de Edge tarda ~2 s en conectar la primera vez: se calienta mientras la IA piensa
  const vozRapida = S.vozActiva && vozNavegador();
  if (vozRapida) hablarNavegador("Mm.", vozRapida, 0);
  if (S.generando) enviarWS({ type: "detener" });
  burbuja("user", texto, null, S.adjuntos);
  subtitulo(texto, true);
  S.textoActual = ""; S.ptrVoz = 0; S.enCodigo = false; S.burbuja = null;
  if (!enviarWS({ type: "mensaje", texto, voz: porVoz, imagenes: S.adjuntos.length ? S.adjuntos : undefined })) {
    chip("✕ Sin conexión con el núcleo", "rot");
    return;
  }
  S.adjuntos = []; $("#adjuntos").innerHTML = "";
  S.generando = true; botonEnviar();
  sonido.enviar();
  poner("pensando");
  $("#sugerencias").innerHTML = "";
}

function botonEnviar() {
  const b = $("#btn-enviar");
  b.innerHTML = S.generando ? ICONOS.detener : ICONOS.enviar;
  b.classList.toggle("detener", S.generando);
}

/* ====================== confirmaciones ====================== */
function pedirConfirmacion(ev) {
  sonido.alerta();
  S.confirmacion = ev.id;
  const nombres = { ejecutar_comando: "ejecutar un comando en tu PC", escribir_archivo: "escribir un archivo", energia: "cambiar el estado de energía del PC", servidor_comando: "ejecutar un comando en tu servidor", crear_protocolo: "crear un protocolo" };
  $("#modal-texto").textContent = `Maicol solicita permiso para ${nombres[ev.nombre] || ev.nombre}.`;
  $("#modal-args").textContent = Object.entries(ev.args || {}).map(([k, v]) => `${k}: ${typeof v === "string" ? v : JSON.stringify(v, null, 1)}`).join("\n");
  $("#modal").classList.remove("oculto");
  decir("Necesito tu autorización para continuar.");
  poner("pensando", "ESPERANDO AUTORIZACIÓN");
}
function responderConfirmacion(ok) {
  if (!S.confirmacion) return;
  enviarWS({ type: "confirmar", id: S.confirmacion, ok });
  S.confirmacion = null;
  $("#modal").classList.add("oculto");
  chip(ok ? "✓ Autorizado" : "✕ Denegado", ok ? "ok" : "rot");
}

/* ====================== reconocimiento de voz ====================== */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
// «Maicol» lo transcriben de muchas formas; «Jarvis» sigue sirviendo por costumbre
const PALABRA = /\b(maicol|maikol|maykol|maicoll|michael|maicool|maico|mycol|maikel|jarvis|yarvis|jarbis)\b[,.!]?\s*/i;
const escucha = {
  rec: null, activo: false, continua: guardado("continua", false), directo: false, esperandoComando: false, temporizador: null,
  grabador: null, trozos: [],

  crear() {
    if (!SR) return;
    const r = new SR();
    r.lang = "es-CO"; r.continuous = true; r.interimResults = true; r.maxAlternatives = 1;
    r.onresult = (e) => {
      for (let i = e.resultIndex; i < e.results.length; i++) {
        const res = e.results[i], t = res[0].transcript.trim();
        if (!t) continue;
        if (!res.isFinal) {
          if (this.directo || this.esperandoComando) subtitulo(t, true);
          else if (PALABRA.test(t) && hablando) callar(); // interrupción
          continue;
        }
        this.final(t);
      }
    };
    r.onend = () => {
      this.activo = false;
      if (this.continua || this.directo) setTimeout(() => this.iniciar(), 300);
      this.pintar();
    };
    r.onerror = (e) => {
      if (e.error === "not-allowed" || e.error === "service-not-allowed") {
        this.continua = false; this.directo = false; guardar("continua", false);
        aviso("MICRÓFONO", "El navegador bloqueó el micrófono. Permítelo en la barra de direcciones.");
      }
    };
    this.rec = r;
  },

  final(t) {
    if (S.confirmacion) {
      if (/^(s[ií]|claro|adelante|hazlo|autorizo|autorizado|dale|ok|okay|confirmo)\b/i.test(t)) return responderConfirmacion(true);
      if (/^(no|cancela|deniega|negativo|det[eé]nte)\b/i.test(t)) return responderConfirmacion(false);
    }
    if (this.directo || this.esperandoComando) {
      this.directo = false; this.terminarComando();
      if (!this.continua) this.parar();
      const limpio = t.replace(PALABRA, "").trim();
      if (limpio.length > 1) enviar(limpio, true);
      this.pintar();
      return;
    }
    const m = t.match(PALABRA);
    if (!m) return;
    callar();
    const resto = t.slice(m.index + m[0].length).trim();
    if (resto.length > 2) { sonido.escuchar(); enviar(resto, true); }
    else this.esperarComando();
  },

  esperarComando() {
    this.esperandoComando = true;
    sonido.escuchar(); poner("escuchando"); subtitulo("¿Sí?");
    clearTimeout(this.temporizador);
    this.temporizador = setTimeout(() => { this.terminarComando(); if (S.modo === "escuchando") poner("espera"); }, 8000);
  },
  terminarComando() { this.esperandoComando = false; clearTimeout(this.temporizador); },

  iniciar() {
    if (!SR) return;
    if (!this.rec) this.crear();
    if (this.activo) return;
    try { this.rec.start(); this.activo = true; } catch { /* ya iniciado */ }
    this.pintar();
  },
  parar() { if (this.rec && this.activo) try { this.rec.stop(); } catch { /* */ } },

  async alternarDirecto() {
    iniciarAudio();
    if (!SR) return this.grabarRespaldo();
    if (this.directo) { this.directo = false; if (!this.continua) this.parar(); poner("espera"); this.pintar(); return; }
    callar();
    this.directo = true; sonido.escuchar(); poner("escuchando"); subtitulo("Te escucho…");
    this.iniciar(); this.pintar();
  },

  alternarContinua() {
    iniciarAudio();
    if (!SR) { aviso("VOZ", "Este navegador no soporta reconocimiento continuo. Usa Chrome o Edge."); return; }
    this.continua = !this.continua; guardar("continua", this.continua);
    if (this.continua) { this.iniciar(); aviso("ESCUCHA ACTIVA", "Di «Maicol» seguido de tu orden."); }
    else if (!this.directo) this.parar();
    this.pintar();
  },

  // respaldo para navegadores sin Web Speech: graba y transcribe con Whisper (Groq)
  async grabarRespaldo() {
    if (this.grabador && this.grabador.state === "recording") { this.grabador.stop(); return; }
    try {
      const flujo = await navigator.mediaDevices.getUserMedia({ audio: true });
      this.trozos = [];
      this.grabador = new MediaRecorder(flujo);
      this.grabador.ondataavailable = (e) => this.trozos.push(e.data);
      this.grabador.onstop = async () => {
        flujo.getTracks().forEach((t) => t.stop());
        this.directo = false; this.pintar(); poner("pensando", "TRANSCRIBIENDO");
        const fd = new FormData(); fd.append("audio", new Blob(this.trozos, { type: "audio/webm" }), "voz.webm");
        const r = await fetch("/api/stt", { method: "POST", body: fd }).then((x) => x.json()).catch(() => ({}));
        if (r.texto) enviar(r.texto, true); else { aviso("VOZ", r.error || "No pude transcribir."); poner("espera"); }
      };
      this.grabador.start(); this.directo = true; sonido.escuchar(); poner("escuchando"); this.pintar();
    } catch { aviso("MICRÓFONO", "No tengo acceso al micrófono."); }
  },

  pintar() {
    $("#btn-mic").classList.toggle("activo", this.directo || this.esperandoComando);
    $("#btn-escucha").classList.toggle("on", this.continua);
  },
};

/* ====================== paneles ====================== */
function fmtBytes(b) { if (b == null) return "-"; const u = ["B/s", "KB/s", "MB/s", "GB/s"]; let i = 0; while (b >= 1024 && i < 3) { b /= 1024; i++; } return b.toFixed(b < 10 && i ? 1 : 0) + " " + u[i]; }

function medidor(k, valor, texto) {
  const m = document.querySelector(`.medidor[data-k="${k}"]`);
  if (!m) return;
  const v = valor == null ? 0 : Math.max(0, Math.min(100, valor));
  m.querySelector(".valor").style.strokeDashoffset = 264 * (1 - v / 100);
  m.querySelector("b").textContent = texto ?? (valor == null ? "--" : Math.round(v) + "%");
  const malo = k === "bateria" ? v < 20 : v > 90, alto = k === "bateria" ? v < 40 : v > 70;
  m.classList.toggle("critico", valor != null && malo);
  m.classList.toggle("alto", valor != null && alto && !malo);
}

function pintarSistema(s) {
  medidor("cpu", s.cpu); medidor("ram", s.ram); medidor("disco", s.disco);
  if (s.bateria != null) medidor("bateria", s.bateria, Math.round(s.bateria) + (s.enchufado ? "⚡" : "%"));
  else medidor("bateria", 100, "AC");
  // sin cargador se activa el modo ligero solo (y se quita al conectarlo, salvo que lo hayas puesto tú)
  const enBateria = s.bateria != null && s.enchufado === false;
  if (enBateria && !S.ligero) { S.ligero = true; S.ligeroAuto = true; document.body.classList.add("ligero"); }
  else if (!enBateria && S.ligeroAuto) { S.ligero = false; S.ligeroAuto = false; document.body.classList.remove("ligero"); }
  $("#subida").textContent = fmtBytes(s.subida); $("#bajada").textContent = fmtBytes(s.bajada);
  const h = (Date.now() / 1000 - s.arranque) / 3600;
  $("#encendido").textContent = h > 24 ? `${(h / 24).toFixed(1)} d` : `${h.toFixed(1)} h`;
}

const CORTOS = { gemini: "GEMINI", groq: "GROQ", cerebras: "CEREBRAS", mistral: "MISTRAL", github: "GITHUB", openrouter: "OPENROUTER", nvidia: "NVIDIA", sambanova: "SAMBANOVA", cohere: "COHERE", cloudflare: "CLOUDFLARE", huggingface: "HUGGINGFACE", ollama: "OLLAMA", pollinations: "POLLINATIONS" };

function estadoProv(p) {
  if (!p.configurado || !p.ranuras) return "apagado";
  if (p.activo || S.ultimoActivo === p.id) return "activo";
  if (p.libres === 0) return "agotado";
  if (p.libres < p.ranuras) return "parcial";
  return "ok";
}
function fmtFalta(s) { s = Math.max(0, Math.round(s)); return s > 3600 ? `${Math.floor(s / 3600)}h ${Math.floor(s % 3600 / 60)}m` : `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`; }

function pintarIA(e) {
  S.ia = e;
  const cont = $("#proveedores");
  const activos = e.proveedores.filter((p) => p.configurado && p.ranuras);
  $("#resumen-ia").textContent = `${activos.length} IAs · ${e.libres}/${e.total} ranuras`;
  pintarPildora();
  document.querySelectorAll("#estrategias button").forEach((b) => b.classList.toggle("activa", b.dataset.e === e.estrategia));
  const orden = [...e.proveedores].sort((a, b) => (b.configurado && b.ranuras ? 1 : 0) - (a.configurado && a.ranuras ? 1 : 0));
  cont.innerHTML = "";
  if (activos.every((p) => p.sin_llave)) {
    const a = document.createElement("div"); a.className = "aviso-llaves";
    a.textContent = "⚡ Solo tengo el proveedor de emergencia. Agrega llaves gratis (2 min) para respuestas instantáneas →";
    a.onclick = abrirAjustes; cont.appendChild(a);
  }
  for (const p of orden) {
    const est = estadoProv(p);
    if (!nodos[p.id]) nodos[p.id] = { corto: CORTOS[p.id] || p.id.toUpperCase(), ang: 0 };
    nodos[p.id].estado = est;
    const d = document.createElement("div");
    d.className = "prov " + est;
    d.title = (p.modelos || []).map((m) => `${m.libre ? "●" : "○"} ${m.id}${m.vision ? " 👁" : ""}${m.tools ? "" : " (sin tools)"}${m.libre ? "" : " — " + m.motivo + " " + fmtFalta(m.falta)} · hoy ${m.hoy}`).join("\n") || p.nota || "";
    let derecha;
    if (est === "apagado") {
      derecha = p.registro ? `<a href="${p.registro}" target="_blank" rel="noopener" onclick="setTimeout(abrirAjustes, 300)">${p.sin_llave ? "instalar" : "obtener llave"}</a>` : "";
    } else {
      derecha = `<span class="prov-dato">${p.libres}/${p.ranuras} · ${p.peticiones_dia} hoy</span>`;
    }
    d.innerHTML = `<span class="luz"></span><span class="prov-nombre">${escapar(p.nombre)}</span>${derecha}`;
    if (est !== "apagado") d.innerHTML += `<div class="prov-barra"><i style="width:${(p.libres / p.ranuras) * 100}%"></i></div>`;
    if ((est === "parcial" || est === "agotado") && p.motivo) d.innerHTML += `<div class="prov-nota">${escapar(p.motivo)} · vuelve en ${fmtFalta(p.proximo)}</div>`;
    else if (est === "apagado" && p.configurado === false && p.nota) d.innerHTML += `<div class="prov-nota">${escapar(p.nota)}</div>`;
    cont.appendChild(d);
  }
}

function marcarActivo(id) {
  S.ultimoActivo = id;
  if (S.ia) pintarIA(S.ia);
}

function aviso(titulo, texto, alerta = false) {
  const a = document.createElement("div");
  a.className = "aviso" + (alerta ? " alerta" : "");
  a.innerHTML = `<b>${escapar(titulo)}</b>${escapar(texto)}`;
  $("#avisos").appendChild(a);
  setTimeout(() => a.remove(), alerta ? 15000 : 6000);
  a.onclick = () => a.remove();
}

/* ====================== ajustes ====================== */
async function abrirAjustes() {
  $("#ajustes").classList.remove("oculto");
  const sel = $("#sel-voz");
  if (!sel.options.length) {
    const voces = await fetch("/api/voces").then((r) => r.json()).catch(() => []);
    const actual = S.voz || (S.info && S.info.voz);
    sel.innerHTML = voces.map((v) => `<option value="${v.id}" ${v.id === actual ? "selected" : ""}>${v.id.replace("Neural", "")} · ${v.genero === "Male" ? "masculina" : "femenina"}</option>`).join("");
  }
  pintarLlaves();
  const estadoLocal = await fetch("/api/estado").then((r) => r.json()).catch(() => null);
  if (estadoLocal && estadoLocal.ia_local) $("#sel-local").value = estadoLocal.ia_local.modo;
  const mems = await fetch("/api/memorias").then((r) => r.json()).catch(() => []);
  $("#memorias").innerHTML = mems.length ? "" : '<div class="vacio">Aún no sé nada de ti. Cuéntame cosas y las recordaré.</div>';
  for (const m of mems) {
    const f = document.createElement("div"); f.className = "fila-mem";
    f.innerHTML = `<span>${escapar(m.texto)}</span><button title="Olvidar">✕</button>`;
    f.querySelector("button").onclick = async () => { await fetch("/api/memorias/" + m.id, { method: "DELETE" }); f.remove(); };
    $("#memorias").appendChild(f);
  }
  const est = await fetch("/api/estado").then((r) => r.json()).catch(() => ({ recordatorios: [] }));
  $("#lista-recordatorios").innerHTML = est.recordatorios.length
    ? est.recordatorios.map((r) => `<div class="fila-mem"><span>${new Date(r.vence * 1000).toLocaleString("es")}: ${escapar(r.texto)}</span></div>`).join("")
    : '<div class="vacio">Sin recordatorios pendientes.</div>';
}

const DATOS = [
  ["USUARIO_NOMBRE", "Tu nombre", "Samuel"], ["USUARIO_TRATAMIENTO", "Cómo quieres que te llame (opcional)", "señor, jefe, Sam…"],
  ["CIUDAD", "Ciudad para el clima (vacío = automático)", "Medellín"], ["NOTION_TOKEN", "Notion: secreto de tu integración (notion.so/profile/integrations)", "ntn_…"],
  ["TELEGRAM_TOKEN", "Token del bot de Telegram (@BotFather)", "123456:ABC…"],
  ["TELEGRAM_USUARIOS", "Tu ID de Telegram (el bot te lo dice)", "123456789"], ["SERVIDOR_HOST", "IP del servidor CasaOS", "192.168.1.50"],
  ["SERVIDOR_USUARIO", "Usuario SSH del servidor", "casaos"], ["SERVIDOR_MAC", "MAC del servidor (Wake-on-LAN)", "AA:BB:CC:DD:EE:FF"],
  ["OLLAMA_URL", "Ollama (en el PC o en CasaOS)", "http://192.168.1.50:11434/v1"], ["CLOUDFLARE_ACCOUNT_ID", "Cloudflare: Account ID", ""],
];

async function pintarLlaves() {
  const actuales = await fetch("/api/llaves").then((r) => r.json()).catch(() => ({}));
  const cont = $("#llaves"); cont.innerHTML = "";
  for (const p of (S.ia ? S.ia.proveedores : [])) {
    if (!p.llave_env) continue;
    const v = actuales[p.llave_env] || "";
    const f = document.createElement("div"); f.className = "fila-llave";
    f.innerHTML = `<span>${escapar(p.nombre)} ${p.configurado && p.ranuras ? '<span class="ok">● conectado</span>' : ""}</span>
      <a href="${p.registro}" target="_blank" rel="noopener">obtener gratis ↗</a>
      <input data-k="${p.llave_env}" type="password" autocomplete="off" placeholder="${v ? "guardada " + v : p.llave_env}">`;
    cont.appendChild(f);
  }
  const datos = $("#datos"); datos.innerHTML = "";
  for (const [k, etiqueta, ejemplo] of DATOS) {
    const v = actuales[k] || "";
    const f = document.createElement("div"); f.className = "fila-llave";
    const secreto = k.endsWith("TOKEN");
    f.innerHTML = `<span>${etiqueta}</span><span></span><input data-k="${k}" type="${secreto ? "password" : "text"}" autocomplete="off" placeholder="${secreto && v ? "guardado " + v : ejemplo}" value="${secreto ? "" : escapar(v)}">`;
    datos.appendChild(f);
  }
}

async function guardarLlaves() {
  const cambios = {};
  document.querySelectorAll("#llaves input, #datos input").forEach((i) => {
    const secreto = i.type === "password";
    if (secreto ? i.value.trim() : true) cambios[i.dataset.k] = i.value.trim();
  });
  aviso("MATRIZ NEURONAL", "Guardando y descubriendo modelos…");
  const e = await fetch("/api/llaves", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(cambios) }).then((r) => r.json());
  pintarIA(e);
  const n = e.proveedores.filter((p) => p.configurado && p.ranuras).length;
  aviso("MATRIZ NEURONAL", `${n} IAs conectadas · ${e.total} ranuras.`);
  decir(`Matriz actualizada. Tengo ${n} inteligencias artificiales y ${e.total} ranuras de modelos disponibles.`);
  pintarLlaves();
}

async function probarConexiones() {
  const caja = $("#resultado-prueba");
  caja.innerHTML = '<div class="vacio">Llamando a cada IA…</div>';
  const res = await fetch("/api/probar", { method: "POST" }).then((r) => r.json()).catch(() => []);
  if (!res.length) { caja.innerHTML = '<div class="vacio">No hay proveedores configurados.</div>'; return; }
  caja.innerHTML = res.map((r) => `<div class="fila-prueba ${r.ok ? "ok" : "mal"}"><b>${r.ok ? "✓" : "✕"} ${escapar(r.nombre)}${r.llave > 1 ? " #" + r.llave : ""}</b>
    <span>${r.ok ? `${escapar(r.modelo)} · ${r.segundos}s · ${r.modelos} modelos` : `${escapar(r.error || "error")} — ${escapar((r.detalle || "").slice(0, 110))}`}</span></div>`).join("");
  const ok = res.filter((r) => r.ok).length;
  decir(`${ok} de ${res.length} conexiones funcionan.`);
}

function pintarBotonVoz() {
  const b = $("#btn-silencio");
  b.innerHTML = S.vozActiva ? ICONOS.voz : ICONOS.mudo;
  b.classList.toggle("apagado", !S.vozActiva);
  $("#chk-voz").checked = S.vozActiva;
}

/* ====================== reloj ====================== */
function reloj() {
  const d = new Date();
  $("#reloj").textContent = d.toLocaleTimeString("es-CO", { hour12: false });
  $("#fecha").textContent = d.toLocaleDateString("es-CO", { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

/* ====================== arranque ====================== */
const SUGERENCIAS = ["¿Qué clima hace hoy?", "Dame las noticias del día", "Mira mi pantalla", "¿Cómo está mi PC?", "Recuérdame tomar agua en 30 minutos",
  "¿Cuántas IAs tengo disponibles?", "Ejecuta el protocolo trabajo", "¿Cómo está mi servidor?"];

async function arrancar() {
  const log = $("#log-arranque");
  const linea = (t) => new Promise((ok) => { log.textContent += t + "\n"; setTimeout(ok, 160 + Math.random() * 160); });
  await linea("> Iniciando núcleo cognitivo ...................");
  let info = null;
  for (let i = 0; !info; i++) {
    const r = await fetch("/api/estado", { cache: "no-store" }).catch(() => null);
    if (r && r.status === 401) {
      await linea("> Sesión no válida en este dispositivo.");
      await linea("  En el PC: ⚙ → 📱 Conectar el celular, y escanea el QR.");
      $("#btn-iniciar").textContent = "SIN SESIÓN";
      return;
    }
    if (r && r.ok) info = await r.json().catch(() => null);
    if (info) break;
    if (i === 5) {
      // en el celular casi siempre es Tailscale apagado: lo decimos claro y seguimos intentando solos
      await linea("> Sin conexión con el cerebro.");
      await linea("  ¿Está encendido Tailscale en este dispositivo? Reintentando…");
      $("#btn-iniciar").textContent = "ESPERANDO CONEXIÓN…";
    }
    await new Promise((ok) => setTimeout(ok, i < 5 ? 700 : 3000));
  }
  if (log.textContent.includes("Sin conexión")) await linea("> Conexión recuperada.");
  S.info = info;
  const provs = info.ia.proveedores.filter((p) => p.configurado && p.ranuras);
  await linea(`> Matriz neuronal ............ ${provs.length} IAs gratis · ${info.ia.total} ranuras`);
  for (const p of provs) await linea(`    · ${p.nombre.padEnd(26, ".")} ${p.ranuras} modelos`);
  await linea(`> Herramientas ............... ${info.herramientas} módulos`);
  await linea(`> Síntesis de voz ............ ${(S.voz || info.voz).replace("Neural", "")}`);
  await linea(`> Reconocimiento de voz ...... ${SR ? "en línea" : "respaldo Whisper"}`);
  await linea(`> Enlace Telegram ............ ${info.telegram ? "activo" : "inactivo"}`);
  await linea(`> Recordatorios pendientes ... ${info.recordatorios.length}`);
  await linea("> Todos los sistemas operativos.");
  const b = $("#btn-iniciar"); b.disabled = false; b.textContent = "INICIAR SISTEMA";
  b.focus();
  if (new URLSearchParams(location.search).get("tecla")) {
    // abierta con la tecla rombo: arranca sola y se pone a escuchar
    setTimeout(() => { b.click(); setTimeout(() => escucha.alternarDirecto(), 900); }, 200);
  } else if (new URLSearchParams(location.search).get("lateral")) {
    setTimeout(() => b.click(), 200);  // panel lateral: es acceso rápido, arranca solo
  }
  b.onclick = () => {
    iniciarAudio();
    $("#arranque").classList.add("fuera");
    sonido.escuchar();
    const nombre = info.tratamiento || info.usuario;
    const soloRespaldo = provs.every((p) => p.sin_llave);
    const remates = ["Aquí estoy, ¿qué inventamos hoy?", "Volví. ¿Qué tenemos?", "Listo para lo que sea… dentro de lo legal.", "¿En qué lío nos metemos hoy?"];
    let saludo = `${info.saludo}${nombre ? ", " + nombre : ""}. ${remates[Math.floor(Math.random() * remates.length)]}`;
    if (soloRespaldo) saludo += " Eso sí, ando con el cerebro de emergencia: ponme llaves gratis en ajustes y me pongo serio.";
    subtitulo(saludo); decir(saludo);
    if (escucha.continua) escucha.iniciar();
  };
  const hist = await fetch("/api/historial").then((r) => r.json()).catch(() => []);
  for (const m of hist) burbuja(m.rol, m.texto, m.meta);
  $("#sugerencias").innerHTML = "";
  for (const s of SUGERENCIAS) { const x = document.createElement("button"); x.textContent = s; x.onclick = () => enviar(s); $("#sugerencias").appendChild(x); }
}

/* ====================== eventos de la interfaz ====================== */
function iniciarUI() {
  $("#btn-mic").innerHTML = ICONOS.mic;
  $("#btn-ojo").innerHTML = ICONOS.ojo;
  $("#btn-clip").innerHTML = ICONOS.clip;
  $("#btn-clip").onclick = () => $("#subir").click();
  $("#subir").onchange = (e) => { subirArchivos([...e.target.files]); e.target.value = ""; };
  setTimeout(archivosCompartidos, 1500);
  $("#btn-config").innerHTML = ICONOS.ajustes;
  $("#btn-panel").innerHTML = ICONOS.panel;
  $("#btn-nueva-sup").innerHTML = ICONOS.mas;
  $("#chk-hud").checked = S.hud;
  $("#chk-hud").onchange = (e) => { S.hud = e.target.checked; guardar("hud", S.hud); aplicarInterfaz(); };
  $("#btn-panel").onclick = () => alternarPanel();
  $("#pildora").onclick = () => alternarPanel(true);
  $("#velo").onclick = () => alternarPanel(false);
  aplicarInterfaz();
  botonEnviar(); pintarBotonVoz(); escucha.pintar();
  $("#chk-sonidos").checked = S.sonidos;
  $("#vel-voz").value = S.velocidad; $("#vel-txt").textContent = (S.velocidad >= 0 ? "+" : "") + S.velocidad + "%";
  if (!S.info || !S.info.pc) { /* el botón de pantalla solo sirve en el PC */ }

  const entrada = $("#entrada");
  entrada.addEventListener("input", () => {
    precalentar(); entrada.style.height = "auto"; entrada.style.height = Math.min(entrada.scrollHeight, 160) + "px"; });
  entrada.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); const t = entrada.value; entrada.value = ""; entrada.style.height = "auto"; enviar(t); }
  });
  entrada.addEventListener("paste", (e) => {
    for (const it of e.clipboardData.items) {
      if (it.type.startsWith("image/")) {
        const f = it.getAsFile(), lector = new FileReader();
        lector.onload = () => {
          S.adjuntos.push(lector.result);
          const im = document.createElement("img"); im.src = lector.result; im.title = "Clic para quitar";
          im.onclick = () => { S.adjuntos = S.adjuntos.filter((x) => x !== lector.result); im.remove(); };
          $("#adjuntos").appendChild(im);
        };
        lector.readAsDataURL(f);
        e.preventDefault();
      }
    }
  });
  $("#btn-enviar").onclick = () => {
    if (S.generando) { enviarWS({ type: "detener" }); callar(); S.generando = false; botonEnviar(); poner("espera"); return; }
    const t = entrada.value; entrada.value = ""; entrada.style.height = "auto"; enviar(t);
  };
  $("#btn-mic").onclick = () => escucha.alternarDirecto();
  $("#btn-escucha").onclick = () => escucha.alternarContinua();
  $("#btn-ojo").onclick = () => enviar("Mira mi pantalla y dime lo más importante que ves.");
  $("#btn-silencio").onclick = () => { S.vozActiva = !S.vozActiva; guardar("voz", S.vozActiva); if (!S.vozActiva) callar(); pintarBotonVoz(); };
  $("#btn-config").onclick = abrirAjustes;
  $("#cerrar-ajustes").onclick = () => $("#ajustes").classList.add("oculto");
  $("#chk-voz").onchange = (e) => { S.vozActiva = e.target.checked; guardar("voz", S.vozActiva); pintarBotonVoz(); };
  $("#chk-silenciar").checked = S.silenciarPC;
  $("#chk-silenciar").onchange = (e) => { S.silenciarPC = e.target.checked; guardar("silenciarPC", S.silenciarPC); revisarSilencio(); };
  $("#chk-ligero").checked = S.ligero;
  $("#chk-ligero").onchange = (e) => { S.ligero = e.target.checked; S.ligeroAuto = false; guardar("ligero", S.ligero); document.body.classList.toggle("ligero", S.ligero); };
  document.body.classList.toggle("ligero", S.ligero);
  $("#chk-sonidos").onchange = (e) => { S.sonidos = e.target.checked; guardar("sonidos", S.sonidos); };
  $("#sel-voz").onchange = (e) => { S.voz = e.target.value; guardar("vozId", S.voz); decir("Así sonará mi voz a partir de ahora."); };
  $("#vel-voz").oninput = (e) => { S.velocidad = +e.target.value; guardar("velocidad", S.velocidad); $("#vel-txt").textContent = (S.velocidad >= 0 ? "+" : "") + S.velocidad + "%"; };
  $("#btn-recargar").onclick = async () => { aviso("PROVEEDORES", "Releyendo .env y descubriendo modelos…"); const e = await fetch("/api/recargar", { method: "POST" }).then((r) => r.json()); pintarIA(e); aviso("PROVEEDORES", `${e.total} ranuras disponibles.`); };
  $("#btn-enfriar").onclick = async () => pintarIA(await fetch("/api/reiniciar_enfriamientos", { method: "POST" }).then((r) => r.json()));
  const nuevaConversacion = async () => { await fetch("/api/nueva_conversacion", { method: "POST" }); chat.innerHTML = ""; actualizarVacio(); subtitulo("Conversación nueva. La memoria a largo plazo se conserva."); };
  $("#btn-nueva").onclick = nuevaConversacion;
  $("#btn-nueva-sup").onclick = nuevaConversacion;
  $("#btn-celular").onclick = async () => {
    const caja = $("#qr-celular");
    caja.classList.remove("oculto");
    caja.innerHTML = '<div class="vacio">Generando código…</div>';
    const r = await fetch("/api/qr_celular").then((x) => x.json()).catch(() => ({ error: "Sin respuesta" }));
    if (r.error) { caja.innerHTML = `<div class="vacio">${escapar(r.error)}</div>`; return; }
    caja.innerHTML = `<img src="data:image/png;base64,${r.png}" alt="QR para el celular">
      <div class="vacio">Con Tailscale encendido en el celular, escanéalo con la cámara. Sirve una sola vez y vence en ${Math.round(r.vence_en / 60)} min.</div>`;
  };
  $("#sel-local").onchange = async (e) => {
    await fetch("/api/llaves", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ IA_LOCAL_MODO: e.target.value }) });
    aviso("IA LOCAL", e.target.options[e.target.selectedIndex].text);
  };
  $("#btn-guardar-llaves").onclick = async () => { await guardarLlaves(); probarConexiones(); };
  $("#btn-probar").onclick = probarConexiones;
  $("#modal-si").onclick = () => responderConfirmacion(true);
  $("#modal-no").onclick = () => responderConfirmacion(false);
  document.querySelectorAll("#estrategias button").forEach((b) => (b.onclick = async () => {
    await fetch("/api/estrategia/" + b.dataset.e, { method: "POST" });
    document.querySelectorAll("#estrategias button").forEach((x) => x.classList.toggle("activa", x === b));
  }));
  document.addEventListener("keydown", (e) => {
    if (e.ctrlKey && e.code === "Space") { e.preventDefault(); escucha.alternarDirecto(); }
    if (e.key === "Escape") { callar(); alternarPanel(false); $("#ajustes").classList.add("oculto"); if (S.confirmacion) responderConfirmacion(false); }
  });
}

/* ---- archivos entre dispositivos ---- */
function miDispositivo() { return /Android|iPhone|iPad/i.test(navigator.userAgent) ? "celular" : "pc"; }
function pesoLegible(n) { const u = ["B", "KB", "MB", "GB"]; let i = 0; while (n >= 1024 && i < 3) { n /= 1024; i++; } return (i ? n.toFixed(1) : n) + " " + u[i]; }
const archivosMostrados = new Set();
function tarjetaArchivo(a) {
  if (archivosMostrados.has(a.id)) return;
  archivosMostrados.add(a.id);
  if (/\.glb$/i.test(a.nombre || "")) return tarjetaVisor3D(a);
  const d = document.createElement("div");
  d.className = "msg jarvis archivo";
  const img = (a.tipo || "").startsWith("image/") ? `<img src="${a.url}" alt="">` : "";
  d.innerHTML = `${img}<a class="descargar" href="${a.url}" download="${escapar(a.nombre)}">⬇ ${escapar(a.nombre)}</a>
    <div class="meta">${pesoLegible(a.tamano)} · desde ${escapar(a.origen || "?")} · ${escapar(a.cuando || "")}</div>`;
  chat.appendChild(d); alFondo(); actualizarVacio();
}
function tarjetaVisor3D(a) {
  // el visor (three.js) se carga como módulo aparte; si aún no está listo, espera su aviso
  const d = document.createElement("div");
  d.className = "msg jarvis visor3d";
  chat.appendChild(d); alFondo(); actualizarVacio();
  const montar = () => window.Visor3D.montar(d, a.url, a.nombre);
  if (window.Visor3D) montar(); else window.addEventListener("visor3d-listo", montar, { once: true });
}
async function subirArchivos(lista) {
  for (const f of lista) {
    const fd = new FormData();
    fd.append("archivo", f, f.name);
    fd.append("origen", miDispositivo());
    chip(`⬆ Enviando ${f.name}…`);
    const r = await fetch("/api/archivos", { method: "POST", body: fd }).then((x) => x.json()).catch(() => ({ error: "sin conexión" }));
    if (r.error) chip(`✕ ${f.name}: ${r.error}`, "rot");
  }
}
async function archivosCompartidos() {
  // al abrir desde «Compartir → JARVIS» de Android, muestra lo recién recibido
  const p = new URLSearchParams(location.search);
  if (!p.has("compartido")) return;
  const lista = await fetch("/api/archivos").then((r) => r.json()).catch(() => []);
  lista.slice(0, Math.max(1, +p.get("compartido") || 1)).reverse().forEach(tarjetaArchivo);
  aviso("ARCHIVO", "Recibido. Dime qué hago con él, por ejemplo «guárdalo en el escritorio del PC».");
  history.replaceState(null, "", "/");
}

/* ---- app instalable (PWA) ---- */
let invitacionInstalar = null;
if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  invitacionInstalar = e;
  $("#btn-instalar").classList.remove("oculto");
  if (/Android|iPhone/i.test(navigator.userAgent)) aviso("MAICOL", "Puedes instalarme como app: ⚙ → 📲 Instalar Maicol como app.");
});
addEventListener("appinstalled", () => { $("#btn-instalar").classList.add("oculto"); aviso("MAICOL", "Instalado. Ya estoy en tu pantalla de inicio."); });
$("#btn-instalar").onclick = async () => {
  if (!invitacionInstalar) return;
  invitacionInstalar.prompt();
  await invitacionInstalar.userChoice;
  invitacionInstalar = null;
};

iniciarUI();
reloj(); setInterval(reloj, 1000);
conectar();
dibujarFondo();
requestAnimationFrame(bucle);
arrancar();

$("#lienzo-cerrar").onclick = cerrarVisual;
addEventListener("keydown", (e) => { if (e.key === "Escape" && document.body.classList.contains("con-lienzo")) cerrarVisual(); });
if (LATERAL) avisarLienzo(0);  // al (re)cargar el panel, sin lienzo abierto
