"""Rutinas que Maicol aprende solo: si usted suele abrir algo a cierta hora, se lo ofrece («¿le abro Spotify?»).

Cada minuto el vigilante le cuenta qué app tiene en primer plano. Aquí se guarda la PRIMERA vez del día (o de la
tanda, tras un rato sin usarla) que aparece cada app, separando días de semana y fin de semana. Si en al menos 4 días
distintos de las últimas 3 semanas la abrió a una hora parecida (±40 min) y hoy todavía no, a esa hora sale como nota
para el vigilante proactivo, que decide si vale la pena ofrecerla y aprende si a usted no le sirve.
"""
import json
import time
from datetime import datetime

from . import config

ARCHIVO = config.DATOS / "rutinas.json"
DIAS = 21            # cuánto historial se mira
MINIMO_DIAS = 4      # días distintos a una hora parecida para llamarlo rutina
VENTANA = 40         # ±minutos alrededor de la hora de costumbre
TANDA = 3 * 3600     # sin usarla este rato, volver a abrirla cuenta como otra «primera vez»
# lo que no tiene sentido ofrecer: el sistema, el propio Maicol, ventanas de paso
IGNORAR = {"", "explorer", "searchhost", "shellexperiencehost", "startmenuexperiencehost", "lockapp", "applicationframehost",
           "systemsettings", "taskmgr", "msedgewebview2", "pythonw", "python", "claude", "textinputhost", "dwm", "rundll32",
           "consent", "openwith", "pickerhost", "ctfmon", "sihost", "taskhostw", "useroobebroker", "screenclippinghost"}


class Rutinas:
    def __init__(self):
        self.visto: dict[str, float] = {}  # app -> última vez en primer plano
        self.datos = self._cargar()

    def _cargar(self) -> dict:
        try:
            return json.loads(ARCHIVO.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"aperturas": []}

    def _guardar(self):
        limite = time.time() - DIAS * 86400
        self.datos["aperturas"] = [a for a in self.datos["aperturas"] if a["ts"] >= limite][-3000:]
        ARCHIVO.write_text(json.dumps(self.datos, ensure_ascii=False), encoding="utf-8")

    def registrar(self, app: str, titulo: str = "", ahora: float | None = None):
        """El vigilante avisa qué app está en primer plano; se anota solo cuando «empieza» a usarla."""
        app = (app or "").lower()
        ahora = ahora or time.time()
        if app in IGNORAR or (app == "msedge" and "maicol" in titulo.lower()):
            return
        previo = self.visto.get(app)
        self.visto[app] = ahora
        if previo and 0 <= ahora - previo < TANDA:
            return
        self.datos["aperturas"].append({"app": app, "ts": ahora})
        self._guardar()

    def _minuto(self, ts: float) -> int:
        d = datetime.fromtimestamp(ts)
        return d.hour * 60 + d.minute

    def sugerencias(self, ahora: float | None = None) -> list[tuple[str, int, str]]:
        """Notas para el vigilante: apps que a esta hora suele abrir y hoy aún no."""
        ahora = ahora or time.time()
        hoy = datetime.fromtimestamp(ahora)
        finde = hoy.weekday() >= 5
        m_ahora = hoy.hour * 60 + hoy.minute
        inicio_hoy = hoy.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
        por_app: dict[str, dict[str, int]] = {}
        usadas_hoy = set()
        for a in self.datos["aperturas"]:
            if a["ts"] >= inicio_hoy:
                usadas_hoy.add(a["app"])
                continue
            d = datetime.fromtimestamp(a["ts"])
            if (d.weekday() >= 5) != finde:
                continue
            dia = d.strftime("%Y-%m-%d")
            m = self._minuto(a["ts"])
            dias = por_app.setdefault(a["app"], {})
            if dia not in dias or abs(m - m_ahora) < abs(dias[dia] - m_ahora):
                dias[dia] = m  # por día, la apertura más cercana a esta hora
        notas = []
        for app, dias in por_app.items():
            if app in usadas_hoy or app in self.visto and ahora - self.visto[app] < TANDA:
                continue
            cerca = sorted(m for m in dias.values() if abs(m - m_ahora) <= VENTANA)
            if len(cerca) < MINIMO_DIAS:
                continue
            costumbre = cerca[len(cerca) // 2]
            if not (costumbre - 10 <= m_ahora <= costumbre + 25):  # desde un poquito antes de la hora de costumbre
                continue
            notas.append((f"rutina:{app}", 1, f"Suele abrir {app} a eso de las {costumbre // 60}:{costumbre % 60:02d} "
                          f"({len(cerca)} de los últimos días {'de fin de semana' if finde else 'de semana'}) y hoy todavía no lo ha abierto. "
                          "Si le sirve, ofrécele abrírselo."))
        return notas


RUTINAS = Rutinas()
