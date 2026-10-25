// Los números en palabras para la voz (igual que numeros() en jarvis/voz.py): «1.400» -> «mil cuatrocientos»,
// «24 k» -> «veinticuatro mil», «$25.000» -> «veinticinco mil pesos», «11:00 am» -> «once de la mañana».
// Sin esto la voz lee «1.4 k» o «1.400» cifra por cifra. En pantalla el texto queda con sus números.
(function (raiz) {
  const UNIDADES = ["cero", "uno", "dos", "tres", "cuatro", "cinco", "seis", "siete", "ocho", "nueve", "diez", "once", "doce",
    "trece", "catorce", "quince", "dieciséis", "diecisiete", "dieciocho", "diecinueve", "veinte", "veintiuno", "veintidós",
    "veintitrés", "veinticuatro", "veinticinco", "veintiséis", "veintisiete", "veintiocho", "veintinueve"];
  const DECENAS = ["", "", "", "treinta", "cuarenta", "cincuenta", "sesenta", "setenta", "ochenta", "noventa"];
  const CENTENAS = ["", "ciento", "doscientos", "trescientos", "cuatrocientos", "quinientos", "seiscientos", "setecientos",
    "ochocientos", "novecientos"];

  function menorMil(n) {
    if (n === 100) return "cien";
    const c = Math.floor(n / 100), r = n % 100;
    let s = c ? CENTENAS[c] : "";
    if (r) s += (s ? " " : "") + (r < 30 ? UNIDADES[r] : DECENAS[Math.floor(r / 10)] + (r % 10 ? " y " + UNIDADES[r % 10] : ""));
    return s;
  }
  // «un»/«ún» delante de mil, millones o una cosa («veintiún pollos», «un millón»)
  const corto = (s) => s.replace(/veintiuno$/, "veintiún").replace(/uno$/, "un");

  function enPalabras(n, apocope = false) {
    if (!Number.isFinite(n) || n < 0 || n >= 1e12) return null;
    n = Math.floor(n);
    if (n === 0) return "cero";
    const millones = Math.floor(n / 1e6), miles = Math.floor((n % 1e6) / 1000), resto = n % 1000;
    const partes = [];
    if (millones) partes.push(millones === 1 ? "un millón" : corto(enPalabras(millones)) + " millones");
    if (miles) partes.push(miles === 1 ? "mil" : corto(menorMil(miles)) + " mil");
    if (resto) partes.push(apocope ? corto(menorMil(resto)) : menorMil(resto));
    return partes.join(" ");
  }

  function decimal(entero, dec) {  // «3,5» -> «tres coma cinco»; «0,05» -> «cero coma cero cinco»
    const ceros = dec.match(/^0*/)[0].length;
    return `${enPalabras(Number(entero))} coma ${"cero ".repeat(ceros)}${dec.length > ceros ? enPalabras(Number(dec)) : ""}`.trim();
  }

  // un número escrito: «1.400», «1.260.000», «3,5», «1.4», «42»
  const NUM = "\\d{1,3}(?:\\.\\d{3})+(?:,\\d+)?|\\d+(?:[.,]\\d+)?";
  function valor(s) {
    if (/^\d{1,3}(\.\d{3})+(,\d+)?$/.test(s)) return Number(s.replace(/\./g, "").replace(",", "."));
    return Number(s.replace(",", "."));
  }
  function leer(s, apocope) {  // el número tal como se dice
    if (/^\d{1,3}(\.\d{3})+$/.test(s) || /^\d+$/.test(s)) {
      if (s.replace(/\./g, "").length > 12) return s;  // un teléfono o un código: que lo lea como venga
      return enPalabras(valor(s), apocope);
    }
    const m = s.match(/^(\d+(?:\.\d{3})*)[.,](\d+)$/);
    return m ? decimal(m[1].replace(/\./g, ""), m[2]) : s;
  }
  const ESCALA = { k: 1e3, mil: 1e3, m: 1e6, mm: 1e6, millon: 1e6, "millón": 1e6, millones: 1e6 };

  function numeros(t) {
    t = String(t);
    // horas: «11:00 am», «3:30 pm», «a las 2 pm»
    t = t.replace(/\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?\s*m\.?(?![\p{L}])/giu, (_, h, mi, ap) => {
      const hora = Number(h), min = Number(mi || 0);
      const cuando = ap.toLowerCase() === "a" ? "de la mañana" : (hora === 12 || hora < 7 ? "de la tarde" : "de la noche");
      return `${hora === 1 ? "una" : enPalabras(hora)}${min ? " y " + enPalabras(min) : ""} ${cuando}`;
    });
    t = t.replace(/\b(\d{1,2}):(\d{2})\b/g, (_, h, mi) => {
      const hora = Number(h), min = Number(mi);
      return `${hora === 1 ? "una" : enPalabras(hora)}${min ? " y " + enPalabras(min) : ""}`;
    });
    t = t.replace(/~\s*(?=\d)/g, "unos ");
    t = t.replace(/(\d)\s*[x×]\s*(?=\d)/g, "$1 por ");  // «20 x 63» -> «veinte por sesenta y tres»
    // «$25.000», «24 k», «1.4 k», «3,5 M», «$ 2 millones» («5 m» son metros: la M de millones va en mayúscula)
    const re = new RegExp(String.raw`(\$\s*)?(${NUM})(?:\s*(k|K|mil|MM|M|millones|millón|millon)(?![\p{L}\p{N}]))?(\s+(?:pesos|COP|cop|d[oó]lares|USD|usd)(?![\p{L}]))?`, "gu");
    t = t.replace(re, (todo, peso, num, escala, moneda, pos, texto) => {
      const antes = texto[pos - 1];
      if (antes && /[\p{L}\d.,]/u.test(antes)) return todo;  // parte de una palabra o de otro número («t22»)
      const despues = texto.slice(pos + todo.length);
      const cosa = /^\s+\p{L}/u.test(despues) && !/^\s+(?:de|a|y|o|e|u|por|entre|al|más|menos|que)(?![\p{L}])/iu.test(despues);
      const factor = escala ? ESCALA[escala.toLowerCase()] : 1;
      let dicho;
      if (factor > 1 && !/^\d{1,3}(\.\d{3})+$/.test(num) && !/^\d+$/.test(num)) {
        dicho = enPalabras(Math.round(valor(num) * factor), true);  // «1.4 k» = 1.400, «3,5 M» = 3.500.000
      } else if (factor > 1) {
        const v = valor(num);
        dicho = factor === 1e3 ? (v === 1 ? "mil" : `${leer(num, true)} mil`) : (v === 1 ? "un millón" : `${leer(num, true)} millones`);
      } else dicho = leer(num, cosa || !!peso || !!moneda);
      if (dicho === null || dicho === num) return todo;
      const pesos = peso && !moneda && !/^\s+pesos/i.test(despues) ? " pesos" : "";
      return dicho + pesos + (moneda || "");
    });
    return t.replace(/ millones (?=pesos)/g, " millones de ").replace(/ millón (?=pesos)/g, " millón de ");
  }

  raiz.numerosEnPalabras = numeros;
  if (typeof module !== "undefined") module.exports = { numeros, enPalabras };
})(typeof window !== "undefined" ? window : globalThis);
