"""Modèles de données communs à tous les backends."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional


@dataclass
class Device:
    id: str
    label: str
    kind: str  # state, other, light, temperature, shutter, ...
    model: str = ""
    battery: Optional[int] = None  # pourcentage, None si inconnu
    state: Optional[str] = None
    last_seen: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Camera:
    id: str
    label: str
    shutter_open: Optional[bool] = None  # None = inconnu

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Event:
    id: str
    when: str
    label: str
    kind: str = ""
    device: str = ""

    def to_dict(self) -> dict:
        return asdict(self)
