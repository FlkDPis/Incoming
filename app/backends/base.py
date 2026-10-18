"""Interface commune des backends.

Le reste de l'application (interface web, surveillance, e-mails) ne parle qu'à cette interface.
Pour le jour où une API locale de la centrale HC2 existera, il suffira d'écrire un nouveau
backend (par ex. ``local_hc2.py``) qui implémente ces méthodes, sans toucher au reste.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Tuple

from ..models import Camera, Device, Event

ALARM_LEVELS = ("armed", "partial", "disarmed")


class BackendError(Exception):
    """Erreur de communication avec la centrale ou son cloud."""


class Backend(ABC):
    name = "base"
    site_label = ""
    #: Texte d'avertissement affiché dans l'interface (ex : dépendance au cloud)
    notice = ""

    @abstractmethod
    def get_alarm_state(self) -> Tuple[str, str]:
        """Retourne (niveau, libellé brut) ; niveau ∈ armed|partial|disarmed|unknown."""

    @abstractmethod
    def set_alarm_state(self, level: str) -> None:
        """Change le niveau de l'alarme (armed|partial|disarmed)."""

    @abstractmethod
    def list_cameras(self) -> List[Camera]: ...

    @abstractmethod
    def set_shutter(self, camera_id: str, open_: bool) -> None: ...

    @abstractmethod
    def take_snapshot(self, camera_id: str) -> Tuple[bytes, str]:
        """Retourne (octets de l'image, type MIME)."""

    @abstractmethod
    def list_devices(self) -> List[Device]:
        """Capteurs / détecteurs avec niveau de batterie si disponible."""

    @abstractmethod
    def get_events(self, limit: int = 30) -> List[Event]:
        """Derniers événements de la centrale."""

    def raw_dump(self) -> dict:
        """Réponses brutes pour le diagnostic (optionnel)."""
        return {}
