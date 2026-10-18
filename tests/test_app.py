import threading
import time

import pytest

from app.backends.demo import DemoBackend
from app.backends.myfox_cloud import parse_alarm_level, parse_battery, parse_shutter
from app.config import Config
from app.models import Event
from app.monitor import Monitor, find_trigger_events
from app.notifier import Notifier
from app.web import create_app


# ── Parsing tolérant des réponses Myfox ─────────────────────────────────────────────────────
def test_parse_battery_variants():
    assert parse_battery({"batteryLevel": 87}) == 87
    assert parse_battery({"battery": "42%"}) == 42
    assert parse_battery({"battery": {"level": 15}}) == 15
    assert parse_battery({"batteryLevel": 250}) == 100
    assert parse_battery({"batteryLevel": True}) is None
    assert parse_battery({}) is None


def test_parse_alarm_level():
    assert parse_alarm_level("disarmed") == "disarmed"
    assert parse_alarm_level("Désarmée") == "disarmed"
    assert parse_alarm_level("Partial") == "partial"
    assert parse_alarm_level("armed") == "armed"
    assert parse_alarm_level("???") == "unknown"


def test_parse_shutter():
    assert parse_shutter({"shutterState": "open"}) is True
    assert parse_shutter({"shutter": "closed"}) is False
    assert parse_shutter({"label": "x"}) is None


# ── Détection d'alarme ──────────────────────────────────────────────────────────────────────
KEYWORDS = ["intrusion", "déclench", "triggered"]


def test_find_trigger_events_only_new_and_matching():
    seen = set()
    evs = [Event("1", "", "Alarme armée"), Event("2", "", "Intrusion détectée")]
    assert [e.id for e in find_trigger_events(evs, seen, KEYWORDS)] == ["2"]
    assert find_trigger_events(evs, seen, KEYWORDS) == []  # déjà vus
    evs.append(Event("3", "", "Alarme déclenchée"))
    assert [e.id for e in find_trigger_events(evs, seen, KEYWORDS)] == ["3"]


class FakeNotifier:
    enabled = True

    def __init__(self):
        self.alarm_calls = []
        self.done = threading.Event()

    def send_alarm_alert(self, *args):
        self.alarm_calls.append(args)
        self.done.set()

    def send_low_battery(self, *args):
        pass


def make_cfg(**kw):
    return Config(alarm_keywords=KEYWORDS, alert_cooldown=60, ui_password="secret", ui_pin="1234", **kw)


def test_monitor_alerts_once_after_priming_and_respects_cooldown():
    cfg, backend, notifier = make_cfg(), DemoBackend(), FakeNotifier()
    mon = Monitor(cfg, backend, notifier)
    mon.refresh_devices()
    mon.refresh_fast()  # amorçage : pas d'alerte
    assert notifier.alarm_calls == []
    backend.simulate_trigger()
    mon.refresh_fast()
    assert notifier.done.wait(2)
    assert len(notifier.alarm_calls) == 1
    backend.simulate_trigger()
    mon.refresh_fast()
    time.sleep(0.2)
    assert len(notifier.alarm_calls) == 1  # anti-spam
    assert mon.snapshot()["last_alert"] is not None


# ── E-mail ──────────────────────────────────────────────────────────────────────────────────
def test_email_contains_photo_and_details(monkeypatch):
    cfg = make_cfg(alert_recipients=["moi@example.com"], smtp_host="smtp.example.com", mail_from="alarme@example.com",
                   alert_open_shutter=True)
    backend = DemoBackend()
    notifier = Notifier(cfg, backend)
    monkeypatch.setattr("app.notifier.time.sleep", lambda s: None)
    sent = []
    monkeypatch.setattr(notifier, "_send", sent.append)
    ev = Event("9", "2026-10-18 10:00", "Intrusion détectée", "alarm_triggered", "Détecteur salon")
    assert notifier.send_alarm_alert("Maison", [ev], [ev], "armed", [])
    msg = sent[0]
    assert "Alarme déclenchée" in msg["Subject"]
    assert msg["To"] == "moi@example.com"
    kinds = [p.get_content_type() for p in msg.walk()]
    assert "text/html" in kinds and "image/png" in kinds
    body = msg.get_body(("plain",)).get_content()
    assert "Détecteur salon" in body and "Intrusion détectée" in body
    assert backend.list_cameras()[0].shutter_open is True  # volet ouvert avant la photo


# ── Interface web ───────────────────────────────────────────────────────────────────────────
@pytest.fixture()
def client():
    cfg, backend = make_cfg(), DemoBackend()
    notifier = Notifier(cfg, backend)
    app = create_app(cfg, backend, None, notifier)
    return app.test_client(), backend


def login(c):
    return c.post("/login", data={"password": "secret"})


def test_auth_required(client):
    c, _ = client
    assert c.get("/api/status").status_code == 401
    assert c.get("/").status_code == 302
    assert c.post("/login", data={"password": "bad"}).status_code == 200
    assert login(c).status_code == 302
    assert c.get("/api/status").status_code == 200


def test_login_lockout(client):
    c, _ = client
    for _ in range(5):
        c.post("/login", data={"password": "bad"})
    r = c.post("/login", data={"password": "secret"})
    assert r.status_code == 200 and "Trop de tentatives" in r.get_data(as_text=True)


def test_alarm_pin_and_levels(client):
    c, backend = client
    login(c)
    assert c.post("/api/alarm", json={"level": "armed"}).status_code == 200
    assert backend.get_alarm_state()[0] == "armed"
    assert c.post("/api/alarm", json={"level": "disarmed"}).status_code == 403
    assert c.post("/api/alarm", json={"level": "disarmed", "pin": "0000"}).status_code == 403
    assert c.post("/api/alarm", json={"level": "disarmed", "pin": "1234"}).status_code == 200
    assert c.post("/api/alarm", json={"level": "bogus"}).status_code == 400


def test_shutter_and_snapshot(client):
    c, backend = client
    login(c)
    assert c.post("/api/camera/cam1/shutter", json={"action": "open"}).status_code == 200
    assert backend.list_cameras()[0].shutter_open is True
    r = c.get("/api/camera/cam1/snapshot")
    assert r.status_code == 200 and r.mimetype == "image/png" and r.data.startswith(b"\x89PNG")
    assert c.post("/api/camera/cam1/shutter", json={"action": "nope"}).status_code == 400
    assert c.get("/api/debug/raw").status_code == 404


def test_config_validation():
    assert Config(backend="myfox_cloud").validate()
    assert any("UI_PASSWORD" in p for p in Config(host="0.0.0.0").validate())
    assert Config(backend="demo").validate() == []
