"""Surveillance en arrière-plan : état de l'alarme, capteurs, détection de déclenchement."""
from __future__ import annotations

import logging
import threading
import time
from typing import Dict, Iterable, List, Set

from .backends.base import Backend
from .config import Config
from .models import Event
from .notifier import Notifier

log = logging.getLogger(__name__)


def find_trigger_events(events: Iterable[Event], seen: Set[str], keywords: List[str]) -> List[Event]:
    """Retourne les nouveaux événements d'alarme et met à jour ``seen``.

    Un événement est un déclenchement si son libellé/type contient l'un des mots-clés.
    """
    new_matches: List[Event] = []
    for ev in events:
        if ev.id in seen:
            continue
        seen.add(ev.id)
        haystack = f"{ev.label} {ev.kind}".lower()
        if any(k in haystack for k in keywords):
            new_matches.append(ev)
    return new_matches


class Monitor(threading.Thread):
    def __init__(self, cfg: Config, backend: Backend, notifier: Notifier):
        super().__init__(name="hc2-monitor", daemon=True)
        self.cfg = cfg
        self.backend = backend
        self.notifier = notifier
        self._halt = threading.Event()
        self._wake = threading.Event()
        self._state_lock = threading.Lock()
        self._seen: Set[str] = set()
        self._primed = False
        self._last_alert = 0.0
        self._battery_alerted: Set[str] = set()
        self._prev_triggered = False
        self._last_devices = 0.0
        self.state: Dict = {
            "alarm": "unknown", "alarm_label": "", "cameras": [], "devices": [], "events": [],
            "updated": None, "devices_updated": None, "error": None, "last_alert": None,
        }

    # ── Accès thread-safe ───────────────────────────────────────────────────────────────────
    def snapshot(self) -> Dict:
        with self._state_lock:
            return dict(self.state)

    def _set(self, **kwargs) -> None:
        with self._state_lock:
            self.state.update(kwargs)

    def refresh_now(self) -> None:
        self._last_devices = 0.0
        self._wake.set()

    def stop(self) -> None:
        self._halt.set()
        self._wake.set()

    # ── Cycles ──────────────────────────────────────────────────────────────────────────────
    def refresh_fast(self) -> None:
        level, label = self.backend.get_alarm_state()
        events = self.backend.get_events(30)
        triggered_state = any(k in (label or "").lower() for k in self.cfg.alarm_keywords)

        new_triggers = find_trigger_events(events, self._seen, self.cfg.alarm_keywords)
        if not self._primed:
            # Premier passage : on mémorise l'historique existant sans alerter
            self._primed = True
            new_triggers = []
            self._prev_triggered = triggered_state
        elif triggered_state and not self._prev_triggered and not new_triggers:
            new_triggers = [Event("state-" + str(int(time.time())), "", f"État de l'alarme : {label}", "alarm_state", "")]
        self._prev_triggered = triggered_state

        self._set(alarm=level, alarm_label=label, events=[e.to_dict() for e in events[:15]],
                  updated=time.time(), error=None)
        if new_triggers:
            self._dispatch_alarm(new_triggers, events, label)

    def refresh_devices(self) -> None:
        devices = self.backend.list_devices()
        cameras = self.backend.list_cameras()
        self._set(devices=[d.to_dict() for d in devices], cameras=[c.to_dict() for c in cameras],
                  devices_updated=time.time())
        self._check_batteries(devices)

    def _check_batteries(self, devices) -> None:
        low = [d for d in devices if d.battery is not None and d.battery <= self.cfg.battery_warn]
        fresh = [d for d in low if d.id not in self._battery_alerted]
        recovered = {d.id for d in devices if d.battery is not None and d.battery > self.cfg.battery_warn + 10}
        self._battery_alerted -= recovered
        if fresh and self.notifier.enabled:
            self._battery_alerted.update(d.id for d in fresh)
            threading.Thread(target=self._safe, args=(self.notifier.send_low_battery, self.backend.site_label, fresh), daemon=True).start()

    def _dispatch_alarm(self, triggers: List[Event], recent: List[Event], label: str) -> None:
        now = time.time()
        log.warning("ALARME détectée : %s", triggers[0].label)
        self._set(last_alert=now)
        if not self.notifier.enabled:
            return
        if now - self._last_alert < self.cfg.alert_cooldown and self._last_alert:
            log.info("E-mail d'alarme ignoré (délai anti-spam)")
            return
        self._last_alert = now
        low = [d for d in self._devices_objs() if d.battery is not None and d.battery <= self.cfg.battery_warn]
        threading.Thread(
            target=self._safe,
            args=(self.notifier.send_alarm_alert, self.backend.site_label, triggers, recent, label, low),
            daemon=True,
        ).start()

    def _devices_objs(self):
        from .models import Device

        return [Device(**d) for d in self.snapshot()["devices"]]

    @staticmethod
    def _safe(fn, *args) -> None:
        try:
            fn(*args)
        except Exception:  # noqa: BLE001
            log.exception("Échec de l'envoi de l'e-mail")

    # ── Boucle ──────────────────────────────────────────────────────────────────────────────
    def run(self) -> None:
        while not self._halt.is_set():
            try:
                if time.time() - self._last_devices >= self.cfg.device_refresh:
                    self.refresh_devices()
                    self._last_devices = time.time()
                self.refresh_fast()
            except Exception as exc:  # noqa: BLE001
                log.error("Erreur de surveillance : %s", exc)
                self._set(error=str(exc))
            self._wake.wait(self.cfg.poll_interval)
            self._wake.clear()
