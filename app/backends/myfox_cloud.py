"""Backend utilisant l'API cloud Myfox (api.myfox.me).

ATTENTION : ce backend dépend des serveurs Myfox, que Somfy arrêtera définitivement le
31 mars 2027. Il fonctionne jusque-là ; ensuite il faudra un backend local (voir README).

Les chemins d'API proviennent de l'API Myfox v2 telle qu'utilisée par l'intégration
communautaire « myfox-api » pour Home Assistant. Les noms de champs des réponses (batterie,
état du volet, historique) ne sont pas documentés officiellement : le code les cherche de
façon tolérante, et ``/api/debug/raw`` permet de vérifier ce que renvoie réellement votre centrale.
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import requests

from ..config import Config
from ..models import Camera, Device, Event
from .base import ALARM_LEVELS, Backend, BackendError

log = logging.getLogger(__name__)

# Listes d'appareils interrogées pour trouver les capteurs et leurs batteries
DEVICE_LISTS = {
    "state": "/device/data/state/items",
    "other": "/device/data/other/items",
    "light": "/device/data/light/items",
    "temperature": "/device/data/temperature/items",
    "shutter": "/device/shutter/items",
    "gate": "/device/gate/items",
    "module": "/device/module/items",
    "socket": "/device/socket/items",
    "heater": "/device/heater/items",
}

BATTERY_KEYS = ("batteryLevel", "battery", "batteryPercent", "batteryPercentage", "batteryStatus")
STATE_KEYS = ("stateLabel", "state", "status", "statusLabel")
LAST_SEEN_KEYS = ("lastStatusDate", "lastSeen", "lastUpdate", "updatedAt", "date")
WHEN_KEYS = ("createdAt", "date", "time", "timestamp", "created", "when")


def parse_battery(item: Dict[str, Any]) -> Optional[int]:
    """Extrait un pourcentage de batterie d'un objet, de façon tolérante."""
    for key in BATTERY_KEYS:
        if key not in item:
            continue
        value = item[key]
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return max(0, min(100, int(value)))
        if isinstance(value, str):
            digits = value.strip().rstrip("%").strip()
            if digits.isdigit():
                return max(0, min(100, int(digits)))
        if isinstance(value, dict):
            for sub in ("level", "percent", "value"):
                if isinstance(value.get(sub), (int, float)) and not isinstance(value.get(sub), bool):
                    return max(0, min(100, int(value[sub])))
    return None


def parse_alarm_level(raw: str) -> str:
    text = (raw or "").lower()
    if "disarm" in text or "désarm" in text or "desarm" in text or "off" == text:
        return "disarmed"
    if "partial" in text or "partiel" in text or "night" in text or "nuit" in text:
        return "partial"
    if "arm" in text or "activ" in text:
        return "armed"
    return "unknown"


def parse_shutter(item: Dict[str, Any]) -> Optional[bool]:
    for key, value in item.items():
        if "shutter" not in key.lower():
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            v = value.lower()
            if v in ("open", "opened", "ouvert", "true"):
                return True
            if v in ("close", "closed", "ferme", "fermé", "false"):
                return False
        if isinstance(value, dict):
            nested = parse_shutter({"shutter": value.get("state") or value.get("status")})
            if nested is not None:
                return nested
    return None


def _first(item: Dict[str, Any], keys: Tuple[str, ...], default: str = "") -> str:
    for key in keys:
        value = item.get(key)
        if value not in (None, ""):
            return str(value)
    return default


class MyfoxCloudBackend(Backend):
    name = "myfox_cloud"
    notice = (
        "Mode cloud Myfox : fonctionne jusqu'à l'arrêt des serveurs Somfy/Myfox (31 mars 2027). "
        "Les mises à jour ne sont pas instantanées (interrogation périodique)."
    )

    def __init__(self, cfg: Config):
        self.cfg = cfg
        self.session = requests.Session()
        self._lock = threading.Lock()
        self._access_token: Optional[str] = None
        self._refresh_token: Optional[str] = None
        self._expires_at = 0.0
        self._site_id = cfg.myfox_site_id or ""
        self.site_label = ""

    # ── Authentification ────────────────────────────────────────────────────────────────────
    def _token_request(self, data: Dict[str, str]) -> Dict[str, Any]:
        data = {**data, "client_id": self.cfg.myfox_client_id, "client_secret": self.cfg.myfox_client_secret}
        try:
            r = self.session.post(self.cfg.myfox_token_url, data=data, timeout=20)
        except requests.RequestException as exc:
            raise BackendError(f"Connexion à Myfox impossible : {exc.__class__.__name__}") from exc
        if r.status_code >= 400:
            raise BackendError(f"Authentification Myfox refusée (HTTP {r.status_code}). Vérifiez vos identifiants.")
        try:
            return r.json()
        except ValueError as exc:
            raise BackendError("Réponse d'authentification Myfox illisible") from exc

    def _token(self) -> str:
        with self._lock:
            if self._access_token and time.time() < self._expires_at - 60:
                return self._access_token
            payload = None
            if self._refresh_token:
                try:
                    payload = self._token_request({"grant_type": "refresh_token", "refresh_token": self._refresh_token})
                except BackendError:
                    payload = None
            if payload is None:
                payload = self._token_request(
                    {
                        "grant_type": "password",
                        "username": self.cfg.myfox_username,
                        "password": self.cfg.myfox_password,
                    }
                )
            token = payload.get("access_token")
            if not token:
                raise BackendError("Myfox n'a pas renvoyé de jeton d'accès")
            self._access_token = token
            self._refresh_token = payload.get("refresh_token") or self._refresh_token
            self._expires_at = time.time() + float(payload.get("expires_in", 3600))
            return token

    def _invalidate(self) -> None:
        with self._lock:
            self._access_token = None
            self._expires_at = 0.0

    # ── Requêtes ────────────────────────────────────────────────────────────────────────────
    def _request(self, method: str, path: str, *, retries: int = 2, **kwargs) -> requests.Response:
        url = f"{self.cfg.myfox_api_base}{path}"
        last: Exception | None = None
        for attempt in range(retries + 1):
            try:
                headers = {"Authorization": f"Bearer {self._token()}"}
                r = self.session.request(method, url, headers=headers, timeout=25, **kwargs)
            except requests.RequestException as exc:
                last = exc
                time.sleep(1 + attempt)
                continue
            if r.status_code == 401:
                self._invalidate()
                last = BackendError("Jeton refusé (401)")
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last = BackendError(f"Myfox HTTP {r.status_code}")
                time.sleep(1 + attempt)
                continue
            if r.status_code >= 400:
                raise BackendError(f"Myfox HTTP {r.status_code} sur {path}")
            return r
        raise BackendError(f"Échec de la requête Myfox {path} : {last}")

    @staticmethod
    def _payload(r: requests.Response) -> Any:
        try:
            data = r.json()
        except ValueError:
            return {}
        if isinstance(data, dict) and "payload" in data:
            return data["payload"]
        return data

    def _items(self, path: str) -> List[Dict[str, Any]]:
        payload = self._payload(self._request("GET", path))
        if isinstance(payload, dict):
            payload = payload.get("items", [])
        return [i for i in payload if isinstance(i, dict)] if isinstance(payload, list) else []

    @property
    def site_id(self) -> str:
        if not self._site_id:
            sites = self._items("/client/site/items")
            if not sites:
                raise BackendError("Aucun site trouvé sur ce compte Myfox")
            self._site_id = str(sites[0].get("siteId") or sites[0].get("id"))
            self.site_label = _first(sites[0], ("label", "name"), "Domicile")
        elif not self.site_label:
            self.site_label = "Domicile"
        return self._site_id

    def _site(self, suffix: str) -> str:
        return f"/site/{self.site_id}{suffix}"

    # ── Alarme ──────────────────────────────────────────────────────────────────────────────
    def get_alarm_state(self) -> Tuple[str, str]:
        payload = self._payload(self._request("GET", self._site("/security")))
        raw = ""
        if isinstance(payload, dict):
            raw = _first(payload, ("statusLabel", "status", "securityLevel", "level"))
        return parse_alarm_level(raw), raw

    def set_alarm_state(self, level: str) -> None:
        if level not in ALARM_LEVELS:
            raise BackendError(f"Niveau d'alarme invalide : {level}")
        self._request("POST", self._site(f"/security/set/{level}"))

    # ── Caméras ─────────────────────────────────────────────────────────────────────────────
    def list_cameras(self) -> List[Camera]:
        cams = []
        for item in self._items(self._site("/device/camera/items")):
            cid = _first(item, ("deviceId", "id"))
            if cid:
                cams.append(Camera(id=cid, label=_first(item, ("label", "name"), f"Caméra {cid}"), shutter_open=parse_shutter(item)))
        return cams

    def set_shutter(self, camera_id: str, open_: bool) -> None:
        action = "open" if open_ else "close"
        self._request("POST", self._site(f"/device/{camera_id}/camera/shutter/{action}"))

    def take_snapshot(self, camera_id: str) -> Tuple[bytes, str]:
        r = self._request("POST", self._site(f"/device/{camera_id}/camera/preview/take"), retries=1)
        ctype = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
        if ctype.startswith("image/"):
            return r.content, ctype
        # Certaines réponses renvoient un JSON contenant l'adresse de l'image
        payload = self._payload(r)
        url = _first(payload, ("url", "previewUrl", "imageUrl", "preview")) if isinstance(payload, dict) else ""
        if not url.startswith("http"):
            raise BackendError("Myfox n'a pas renvoyé d'image pour cette caméra")
        img = self.session.get(url, timeout=25, headers={"Authorization": f"Bearer {self._token()}"})
        if img.status_code >= 400:
            raise BackendError(f"Téléchargement de l'image impossible (HTTP {img.status_code})")
        return img.content, img.headers.get("Content-Type", "image/jpeg").split(";")[0]

    # ── Capteurs ────────────────────────────────────────────────────────────────────────────
    def list_devices(self) -> List[Device]:
        found: Dict[str, Device] = {}
        errors = 0
        for kind, suffix in DEVICE_LISTS.items():
            try:
                items = self._items(self._site(suffix))
            except BackendError as exc:
                errors += 1
                log.debug("Liste %s indisponible : %s", kind, exc)
                continue
            for item in items:
                did = _first(item, ("deviceId", "id"))
                if not did:
                    continue
                dev = Device(
                    id=did,
                    label=_first(item, ("label", "name"), f"Appareil {did}"),
                    kind=kind,
                    model=_first(item, ("modelLabel", "model", "modelId")),
                    battery=parse_battery(item),
                    state=_first(item, STATE_KEYS) or None,
                    last_seen=_first(item, LAST_SEEN_KEYS) or None,
                )
                old = found.get(did)
                if old is None or (old.battery is None and dev.battery is not None):
                    found[did] = dev
        if errors == len(DEVICE_LISTS):
            raise BackendError("Impossible de lire les capteurs sur Myfox")
        return sorted(found.values(), key=lambda d: d.label.lower())

    # ── Historique ──────────────────────────────────────────────────────────────────────────
    def get_events(self, limit: int = 30) -> List[Event]:
        payload = self._payload(self._request("GET", self._site("/history")))
        items = payload.get("items", []) if isinstance(payload, dict) else payload
        events: List[Event] = []
        for item in (items or [])[:limit]:
            if not isinstance(item, dict):
                continue
            eid = _first(item, ("historyId", "id", "eventId"))
            if not eid:
                eid = hashlib.sha1(json.dumps(item, sort_keys=True, default=str).encode()).hexdigest()[:16]
            events.append(
                Event(
                    id=eid,
                    when=_first(item, WHEN_KEYS),
                    label=_first(item, ("label", "description", "message", "type"), "Événement"),
                    kind=_first(item, ("type", "eventType", "category")),
                    device=_first(item, ("deviceLabel", "deviceName", "deviceId")),
                )
            )
        return events

    def raw_dump(self) -> dict:
        out: Dict[str, Any] = {}
        paths = {"security": "/security", "history": "/history", "cameras": "/device/camera/items", **DEVICE_LISTS}
        for name, suffix in paths.items():
            try:
                out[name] = self._payload(self._request("GET", self._site(suffix), retries=0))
            except BackendError as exc:
                out[name] = f"erreur : {exc}"
        return out
