"""Backend de démonstration : fausses données, aucun accès réseau.

Utile pour tester l'interface et la chaîne d'alerte e-mail sans toucher à la vraie centrale.
"""
from __future__ import annotations

import struct
import time
import zlib
from typing import List, Tuple

from ..models import Camera, Device, Event
from .base import ALARM_LEVELS, Backend, BackendError


def _png(width: int = 320, height: int = 180) -> bytes:
    """Génère un petit PNG (dégradé) sans dépendance externe."""
    rows = bytearray()
    for y in range(height):
        rows.append(0)
        for x in range(width):
            rows += bytes((30 + x * 60 // width, 50 + y * 90 // height, 90 + (x + y) * 80 // (width + height)))

    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(bytes(rows)))
        + chunk(b"IEND", b"")
    )


class DemoBackend(Backend):
    name = "demo"
    site_label = "Maison (démo)"
    notice = "Mode démo : les données affichées sont fictives."

    def __init__(self):
        self._level = "disarmed"
        self._shutter = {"cam1": False}
        self._events: List[Event] = [Event("e0", time.strftime("%Y-%m-%d %H:%M:%S"), "Alarme désarmée", "security", "")]
        self._counter = 1

    def get_alarm_state(self) -> Tuple[str, str]:
        return self._level, self._level

    def set_alarm_state(self, level: str) -> None:
        if level not in ALARM_LEVELS:
            raise BackendError("Niveau invalide")
        self._level = level
        self._add_event(f"Alarme {level}", "security")

    def list_cameras(self) -> List[Camera]:
        return [Camera("cam1", "Caméra salon", self._shutter["cam1"])]

    def set_shutter(self, camera_id: str, open_: bool) -> None:
        if camera_id not in self._shutter:
            raise BackendError("Caméra inconnue")
        self._shutter[camera_id] = open_

    def take_snapshot(self, camera_id: str) -> Tuple[bytes, str]:
        if camera_id not in self._shutter:
            raise BackendError("Caméra inconnue")
        return _png(), "image/png"

    def list_devices(self) -> List[Device]:
        return [
            Device("d1", "Détecteur mouvement salon", "state", "Détecteur de mouvement", 87, "OK"),
            Device("d2", "Détecteur mouvement couloir", "state", "Détecteur de mouvement", 52, "OK"),
            Device("d3", "Détecteur mouvement garage", "state", "Détecteur de mouvement", 14, "OK"),
            Device("d4", "Clavier à code (entrée)", "other", "Clavier", 71, "OK"),
        ]

    def get_events(self, limit: int = 30) -> List[Event]:
        return list(reversed(self._events))[:limit]

    # Spécifique à la démo : simule un déclenchement pour tester les e-mails
    def simulate_trigger(self) -> None:
        self._add_event("Intrusion détectée : détecteur salon (démo)", "alarm_triggered")

    def _add_event(self, label: str, kind: str) -> None:
        self._counter += 1
        self._events.append(Event(f"e{self._counter}", time.strftime("%Y-%m-%d %H:%M:%S"), label, kind, ""))
        self._events = self._events[-50:]
