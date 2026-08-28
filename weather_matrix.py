"""Meteo dell'osservatorio UniTo per spotify-matrix.

Da affiancare a spotify_matrix.py. Espone:
  - WeatherState / poll_weather : thread di aggiornamento in background
  - render_weather              : frame PIL per la matrice
"""

from __future__ import annotations

import re
import threading
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from selectolax.parser import HTMLParser

WEATHER_URL = "https://www.meteo.dfg.unito.it/principali"

FONT_PATHS = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
)


# --------------------------------------------------------------- parsing

def _classi(node):
    return (node.attributes.get("class") or "").split()


def _testo(node):
    txt = node.text(deep=True, separator=" ")
    return re.sub(r"\s+", " ", txt.replace("\xa0", " ")).strip()


def _numero(valore):
    m = re.search(r"-?\d+(?:[.,]\d+)?", valore)
    return float(m.group().replace(",", ".")) if m else None


def parse_weather(html: str) -> dict[str, float | None]:
    tree = HTMLParser(html)
    body = tree.css_first("div.divTable.ridotta > div.divTableBody")
    if body is None:
        raise RuntimeError("tabella non trovata: il markup del sito e' cambiato")

    righe = [n for n in body.iter() if "divTableRow" in _classi(n)]
    intestazioni = [_testo(c).lower() for c in righe[0].iter()
                    if "divTableHead" in _classi(c)]
    idx = next(i for i, h in enumerate(intestazioni) if "valore" in h)

    grezzi = {}
    for riga in righe[1:]:
        celle = [c for c in riga.iter()
                 if {"divTableCell", "divTableSuperCell"} & set(_classi(c))]
        if len(celle) > idx:
            grezzi[_testo(celle[0]).lower()] = _testo(celle[idx])

    def trova(*parole):
        for nome, valore in grezzi.items():
            if all(p in nome for p in parole):
                return _numero(valore)
        return None

    return {
        "temperatura": trova("temperatura"),
        "umidita": trova("umidit"),
        "vento": trova("velocit", "vento"),
        "pressione": trova("pressione", "mare"),
        "pioggia": trova("pioggia", "cumulata"),
    }


def fetch_weather(timeout: float = 10) -> dict[str, float | None]:
    req = urllib.request.Request(
        WEATHER_URL, headers={"User-Agent": "spotify-matrix/1.0"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        html = resp.read().decode("ISO-8859-1", errors="replace")
    return parse_weather(html)


# --------------------------------------------------------------- polling

@dataclass
class WeatherState:
    data: dict[str, float | None] | None = None


def poll_weather(state: WeatherState, lock: threading.Lock,
                 stop_event: threading.Event, poll_seconds: float = 120.0) -> None:
    """Aggiorna lo stato meteo finche' stop_event non viene alzato."""
    ultimo_errore = None
    while not stop_event.is_set():
        try:
            dati = fetch_weather()
            with lock:
                state.data = dati
            if ultimo_errore is not None:
                print("Meteo: ripristinato", flush=True)
                ultimo_errore = None
        except Exception as exc:
            messaggio = str(exc)
            if messaggio != ultimo_errore:
                print(f"Meteo non disponibile: {messaggio}", flush=True)
                ultimo_errore = messaggio
        stop_event.wait(poll_seconds)


# ------------------------------------------------------------- rendering

def _font(size: int):
    for path in FONT_PATHS:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    try:
        return ImageFont.load_default(size)
    except TypeError:
        return ImageFont.load_default()


def _centrato(draw, y, testo, font, fill, size):
    larghezza = draw.textlength(testo, font=font)
    draw.text(((size - larghezza) / 2, y), testo, font=font, fill=fill)


def render_weather(dati: dict[str, float | None], size: int) -> Image.Image:
    frame = Image.new("RGB", (size, size), (0, 0, 0))
    draw = ImageDraw.Draw(frame)

    grande = _font(max(10, int(size / 3.4)))
    piccolo = _font(max(7, int(size / 7.2)))

    temp = dati.get("temperatura")
    _centrato(draw, 0, f"{temp:.1f}\u00b0" if temp is not None else "--",
              grande, (255, 170, 60), size)

    y = int(size / 2.7)
    draw.line((4, y - 3, size - 5, y - 3), fill=(40, 40, 40))
    passo = int(size / 7.3)

    righe = (
        ("umidita", "UR {:.0f}%", (90, 170, 255)),
        ("vento", "{:.1f} m/s", (120, 220, 200)),
        ("pressione", "{:.0f} hPa", (200, 200, 200)),
        ("pioggia", "{:.1f} mm", (110, 140, 255)),
    )
    for chiave, formato, colore in righe:
        valore = dati.get(chiave)
        if valore is None:
            continue
        _centrato(draw, y, formato.format(valore), piccolo, colore, size)
        y += passo

    return frame
