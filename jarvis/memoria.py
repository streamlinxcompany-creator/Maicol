"""Memoria persistente en SQLite: conversaciones, hechos del usuario y recordatorios."""
import json
import re
import sqlite3
import threading
import time

from . import config

RUTA = config.DATOS / "jarvis.db"


class Memoria:
    def __init__(self):
        self.db = sqlite3.connect(RUTA, check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.lock = threading.Lock()
        with self.lock:
            self.db.executescript(
                """
                CREATE TABLE IF NOT EXISTS mensajes(
                    id INTEGER PRIMARY KEY, sesion TEXT, rol TEXT, contenido TEXT,
                    llamadas TEXT, id_llamada TEXT, meta TEXT, ts REAL);
                CREATE INDEX IF NOT EXISTS ix_msg ON mensajes(sesion, id);
                CREATE TABLE IF NOT EXISTS hechos(
                    id INTEGER PRIMARY KEY, texto TEXT UNIQUE, tipo TEXT DEFAULT 'hecho', ts REAL);
                CREATE TABLE IF NOT EXISTS recordatorios(
                    id INTEGER PRIMARY KEY, texto TEXT, vence REAL, hecho INTEGER DEFAULT 0,
                    canal TEXT, ts REAL);
                """
            )
            try:
                self.db.execute("CREATE VIRTUAL TABLE IF NOT EXISTS hechos_fts USING fts5(texto, content='hechos', content_rowid='id')")
                self.fts = True
            except sqlite3.OperationalError:
                self.fts = False
            self.db.commit()

    def _q(self, sql, args=(), commit=False):
        with self.lock:
            cur = self.db.execute(sql, args)
            if commit:
                self.db.commit()
            return cur

    # ----- conversación -----
    def guardar_mensaje(self, sesion, m: dict, meta: dict | None = None):
        contenido = m.get("content")
        if isinstance(contenido, list):
            contenido = " ".join(p.get("text", "") for p in contenido if p.get("type") == "text") + " [imagen adjunta]"
        self._q("INSERT INTO mensajes(sesion, rol, contenido, llamadas, id_llamada, meta, ts) VALUES(?,?,?,?,?,?,?)",
                (sesion, m["role"], contenido, json.dumps(m["tool_calls"]) if m.get("tool_calls") else None,
                 m.get("tool_call_id"), json.dumps(meta) if meta else None, time.time()), commit=True)

    def historial(self, sesion, limite=30) -> list[dict]:
        filas = self._q("SELECT * FROM mensajes WHERE sesion=? ORDER BY id DESC LIMIT ?", (sesion, limite)).fetchall()[::-1]
        # la ventana debe empezar en un mensaje del usuario (no partir una llamada a herramienta)
        while filas and filas[0]["rol"] != "user":
            filas.pop(0)
        out = []
        for f in filas:
            m = {"role": f["rol"], "content": f["contenido"] or ""}
            if f["llamadas"]:
                m["tool_calls"] = json.loads(f["llamadas"])
            if f["id_llamada"]:
                m["tool_call_id"] = f["id_llamada"]
            out.append(m)
        return out

    def historial_visible(self, sesion, limite=60) -> list[dict]:
        filas = self._q("SELECT rol, contenido, meta, ts FROM mensajes WHERE sesion=? AND rol IN ('user','assistant') AND contenido != '' ORDER BY id DESC LIMIT ?",
                        (sesion, limite)).fetchall()[::-1]
        return [{"rol": f["rol"], "texto": f["contenido"], "meta": json.loads(f["meta"]) if f["meta"] else None, "ts": f["ts"]} for f in filas]

    def borrar_sesion(self, sesion):
        self._q("DELETE FROM mensajes WHERE sesion=?", (sesion,), commit=True)

    def borrar_entre(self, sesion, ratos: list[tuple[float, float]]) -> int:
        """Borra de la conversación lo dicho en esos ratos (un análisis que él pidió olvidar). Devuelve cuántos."""
        total = 0
        for desde, hasta in ratos:
            total += self._q("DELETE FROM mensajes WHERE sesion=? AND ts BETWEEN ? AND ?", (sesion, desde, hasta), commit=True).rowcount
        return total

    def contar_usuario(self, sesion) -> int:
        return self._q("SELECT COUNT(*) FROM mensajes WHERE sesion=? AND rol='user'", (sesion,)).fetchone()[0]

    # ----- hechos a largo plazo -----
    def recordar(self, texto: str, tipo="hecho") -> int | None:
        texto = texto.strip()
        if not texto:
            return None
        try:
            cur = self._q("INSERT INTO hechos(texto, tipo, ts) VALUES(?,?,?)", (texto, tipo, time.time()), commit=True)
        except sqlite3.IntegrityError:
            return None
        if self.fts:
            self._q("INSERT INTO hechos_fts(rowid, texto) VALUES(?,?)", (cur.lastrowid, texto), commit=True)
        return cur.lastrowid

    def olvidar(self, id_: int) -> bool:
        fila = self._q("SELECT texto FROM hechos WHERE id=?", (id_,)).fetchone()
        if not fila:
            return False
        if self.fts:
            self._q("INSERT INTO hechos_fts(hechos_fts, rowid, texto) VALUES('delete', ?, ?)", (id_, fila["texto"]), commit=True)
        self._q("DELETE FROM hechos WHERE id=?", (id_,), commit=True)
        return True

    def hechos(self, limite=200) -> list[dict]:
        return [dict(f) for f in self._q("SELECT id, texto, tipo, ts FROM hechos ORDER BY id DESC LIMIT ?", (limite,)).fetchall()]

    def buscar(self, consulta: str, limite=8) -> list[dict]:
        palabras = [p for p in re.findall(r"\w{3,}", consulta.lower())]
        if not palabras:
            return []
        if self.fts:
            q = " OR ".join(f'"{p}"*' for p in palabras[:12])
            try:
                filas = self._q("SELECT h.id, h.texto, h.tipo FROM hechos_fts f JOIN hechos h ON h.id=f.rowid WHERE hechos_fts MATCH ? ORDER BY rank LIMIT ?", (q, limite)).fetchall()
                return [dict(f) for f in filas]
            except sqlite3.OperationalError:
                pass
        filas = self._q("SELECT id, texto, tipo FROM hechos").fetchall()
        puntuadas = sorted(((sum(p in f["texto"].lower() for p in palabras), f) for f in filas), key=lambda x: -x[0])
        return [dict(f) for s, f in puntuadas if s][:limite]

    # ----- recordatorios -----
    def crear_recordatorio(self, texto, vence: float, canal="web") -> int:
        return self._q("INSERT INTO recordatorios(texto, vence, canal, ts) VALUES(?,?,?,?)", (texto, vence, canal, time.time()), commit=True).lastrowid

    def recordatorios(self, pendientes=True) -> list[dict]:
        sql = "SELECT * FROM recordatorios" + (" WHERE hecho=0" if pendientes else "") + " ORDER BY vence"
        return [dict(f) for f in self._q(sql).fetchall()]

    def vencidos(self) -> list[dict]:
        return [dict(f) for f in self._q("SELECT * FROM recordatorios WHERE hecho=0 AND vence<=?", (time.time(),)).fetchall()]

    def completar_recordatorio(self, id_):
        self._q("UPDATE recordatorios SET hecho=1 WHERE id=?", (id_,), commit=True)

    def cancelar_recordatorio(self, id_) -> bool:
        return self._q("DELETE FROM recordatorios WHERE id=? AND hecho=0", (id_,), commit=True).rowcount > 0
