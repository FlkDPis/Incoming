"""Envoi des e-mails d'alerte (alarme déclenchée, batterie faible) avec photo de la caméra."""
from __future__ import annotations

import html
import logging
import smtplib
import ssl
import time
from datetime import datetime
from email.message import EmailMessage
from email.utils import make_msgid
from typing import List, Optional, Tuple
from zoneinfo import ZoneInfo

from .backends.base import Backend
from .config import Config
from .models import Device, Event

log = logging.getLogger(__name__)

Snapshot = Tuple[str, Optional[bytes], str, str]  # (nom caméra, octets, mime, message d'erreur)


class Notifier:
    def __init__(self, cfg: Config, backend: Backend):
        self.cfg = cfg
        self.backend = backend

    @property
    def enabled(self) -> bool:
        return self.cfg.mail_enabled

    def _now(self) -> str:
        try:
            tz = ZoneInfo(self.cfg.timezone)
        except Exception:
            tz = None
        return datetime.now(tz).strftime("%d/%m/%Y à %H:%M:%S")

    # ── Photos ──────────────────────────────────────────────────────────────────────────────
    def capture_snapshots(self) -> List[Snapshot]:
        shots: List[Snapshot] = []
        try:
            cameras = self.backend.list_cameras()
        except Exception as exc:  # noqa: BLE001
            return [("Caméra", None, "", f"liste des caméras indisponible ({exc})")]
        for cam in cameras:
            try:
                if self.cfg.alert_open_shutter and cam.shutter_open is not True:
                    try:
                        self.backend.set_shutter(cam.id, True)
                        time.sleep(4)  # laisse le temps au volet de s'ouvrir
                    except Exception as exc:  # noqa: BLE001
                        log.warning("Ouverture du volet impossible (%s) : %s", cam.label, exc)
                last_exc: Exception | None = None
                for _ in range(3):
                    try:
                        data, mime = self.backend.take_snapshot(cam.id)
                        shots.append((cam.label, data, mime or "image/jpeg", ""))
                        break
                    except Exception as exc:  # noqa: BLE001
                        last_exc = exc
                        time.sleep(2)
                else:
                    shots.append((cam.label, None, "", str(last_exc)))
            except Exception as exc:  # noqa: BLE001
                shots.append((cam.label, None, "", str(exc)))
        return shots

    # ── Composition ─────────────────────────────────────────────────────────────────────────
    def _build(self, subject: str, intro: str, rows: List[Tuple[str, str]], events: List[Event],
               shots: List[Snapshot], low_battery: List[Device]) -> EmailMessage:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.cfg.mail_from
        msg["To"] = ", ".join(self.cfg.alert_recipients)

        text = [intro, ""]
        text += [f"{k} : {v}" for k, v in rows]
        if events:
            text += ["", "Événements récents :"] + [f"- {e.when} — {e.label}" for e in events[:8]]
        if low_battery:
            text += ["", "Batteries faibles :"] + [f"- {d.label} : {d.battery} %" for d in low_battery]
        for name, data, _, err in shots:
            if data is None:
                text.append(f"Photo {name} indisponible : {err}")
        msg.set_content("\n".join(text))

        esc = html.escape
        parts = [f"<h2 style='margin:0 0 8px'>{esc(intro)}</h2>", "<table cellpadding='4' style='border-collapse:collapse'>"]
        parts += [f"<tr><td><b>{esc(k)}</b></td><td>{esc(v)}</td></tr>" for k, v in rows]
        parts.append("</table>")
        cids = []
        for name, data, mime, err in shots:
            if data is None:
                parts.append(f"<p><i>Photo {esc(name)} indisponible : {esc(err)}</i></p>")
            else:
                cid = make_msgid(domain="hc2.local")
                cids.append((cid, data, mime, name))
                parts.append(f"<p><b>{esc(name)}</b><br><img src='cid:{cid[1:-1]}' style='max-width:640px;width:100%'></p>")
        if events:
            parts.append("<h3>Événements récents</h3><ul>" + "".join(f"<li>{esc(e.when)} — {esc(e.label)}</li>" for e in events[:8]) + "</ul>")
        if low_battery:
            parts.append("<h3>Batteries faibles</h3><ul>" + "".join(f"<li>{esc(d.label)} : {d.battery} %</li>" for d in low_battery) + "</ul>")
        msg.add_alternative("<html><body style='font-family:sans-serif'>" + "".join(parts) + "</body></html>", subtype="html")

        html_part = msg.get_body(("html",))
        for cid, data, mime, _ in cids:
            maintype, _, subtype = mime.partition("/")
            html_part.add_related(data, maintype=maintype or "image", subtype=subtype or "jpeg", cid=cid)
        for idx, (name, data, mime, _) in enumerate((s for s in shots if s[1] is not None), 1):
            maintype, _, subtype = mime.partition("/")
            ext = "png" if "png" in mime else "jpg"
            msg.add_attachment(data, maintype=maintype or "image", subtype=subtype or "jpeg", filename=f"camera-{idx}.{ext}")
        return msg

    # ── Envoi ───────────────────────────────────────────────────────────────────────────────
    def _send(self, msg: EmailMessage) -> None:
        cfg = self.cfg
        ctx = ssl.create_default_context()
        if cfg.smtp_security == "ssl":
            server = smtplib.SMTP_SSL(cfg.smtp_host, cfg.smtp_port, timeout=30, context=ctx)
        else:
            server = smtplib.SMTP(cfg.smtp_host, cfg.smtp_port, timeout=30)
        with server:
            if cfg.smtp_security == "starttls":
                server.starttls(context=ctx)
            if cfg.smtp_user:
                server.login(cfg.smtp_user, cfg.smtp_password)
            server.send_message(msg)

    def send_alarm_alert(self, site: str, trigger_events: List[Event], recent: List[Event],
                         alarm_label: str, low_battery: List[Device]) -> bool:
        if not self.enabled:
            return False
        shots = self.capture_snapshots()
        first = trigger_events[0] if trigger_events else None
        rows = [
            ("Site", site or "Domicile"),
            ("Date", self._now()),
            ("Événement", first.label if first else "Alarme déclenchée"),
            ("Capteur", (first.device if first and first.device else "—")),
            ("État de l'alarme", alarm_label or "inconnu"),
        ]
        msg = self._build(f"🚨 Alarme déclenchée — {site or 'Domicile'}", "Votre alarme s'est déclenchée", rows, recent, shots, low_battery)
        self._send(msg)
        log.info("E-mail d'alarme envoyé à %s", self.cfg.alert_recipients)
        return True

    def send_low_battery(self, site: str, devices: List[Device]) -> bool:
        if not self.enabled or not devices:
            return False
        rows = [("Site", site or "Domicile"), ("Date", self._now()), ("Seuil", f"{self.cfg.battery_warn} %")]
        msg = self._build("🔋 Batterie faible — " + (site or "Domicile"), "Des capteurs ont une batterie faible", rows, [], [], devices)
        self._send(msg)
        return True

    def send_test(self, site: str) -> None:
        if not self.enabled:
            raise RuntimeError("E-mail non configuré (ALERT_RECIPIENTS / SMTP_HOST)")
        shots = self.capture_snapshots() if self.backend else []
        rows = [("Site", site or "Domicile"), ("Date", self._now())]
        msg = self._build("✅ Test d'alerte — " + (site or "Domicile"), "Ceci est un e-mail de test", rows, [], shots, [])
        self._send(msg)
