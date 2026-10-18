"""Application Flask : interface web + API JSON."""
from __future__ import annotations

import hmac
import logging
import time
from datetime import timedelta
from functools import wraps
from typing import Optional

from flask import Flask, Response, abort, jsonify, redirect, render_template, request, session, url_for

from .backends.base import ALARM_LEVELS, Backend, BackendError
from .config import Config
from .monitor import Monitor
from .notifier import Notifier

log = logging.getLogger(__name__)

MAX_FAILS = 5
LOCK_SECONDS = 60


def create_app(cfg: Config, backend: Backend, monitor: Optional[Monitor], notifier: Notifier) -> Flask:
    app = Flask(__name__)
    app.config.update(
        SECRET_KEY=cfg.secret_key,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        MAX_CONTENT_LENGTH=64 * 1024,
    )
    fails: dict[str, list[float]] = {}  # ip -> horodatages des échecs récents

    def authed() -> bool:
        return (not cfg.ui_password) or session.get("auth") is True

    def login_required(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if not authed():
                if request.path.startswith("/api/"):
                    return jsonify(error="Non authentifié"), 401
                return redirect(url_for("login"))
            return view(*args, **kwargs)

        return wrapper

    def same(a: str, b: str) -> bool:
        return hmac.compare_digest(a.encode(), b.encode())

    @app.after_request
    def headers(resp: Response) -> Response:
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "no-referrer"
        resp.headers["Cache-Control"] = "no-store"
        return resp

    def ui_context() -> dict:
        return {
            "font_family": cfg.font_family,
            "font_css_url": cfg.font_css_url,
            "site": backend.site_label or "Domicile",
        }

    # ── Pages ───────────────────────────────────────────────────────────────────────────────
    @app.route("/login", methods=["GET", "POST"])
    def login():
        if authed():
            return redirect(url_for("index"))
        error = None
        if request.method == "POST":
            ip = request.remote_addr or "?"
            now = time.time()
            recent = [t for t in fails.get(ip, []) if now - t < LOCK_SECONDS]
            fails[ip] = recent
            if len(recent) >= MAX_FAILS:
                error = "Trop de tentatives. Réessayez dans une minute."
            elif same(request.form.get("password", ""), cfg.ui_password):
                session.clear()
                session["auth"] = True
                session.permanent = True
                fails.pop(ip, None)
                return redirect(url_for("index"))
            else:
                recent.append(now)
                error = "Mot de passe incorrect."
        return render_template("login.html", error=error, **ui_context())

    @app.post("/logout")
    def logout():
        session.clear()
        return redirect(url_for("login"))

    @app.get("/")
    @login_required
    def index():
        return render_template(
            "index.html",
            pin_required=bool(cfg.ui_pin),
            notice=backend.notice,
            mail_enabled=notifier.enabled,
            demo=backend.name == "demo",
            battery_warn=cfg.battery_warn,
            has_logout=bool(cfg.ui_password),
            **ui_context(),
        )

    # ── API ─────────────────────────────────────────────────────────────────────────────────
    @app.get("/api/status")
    @login_required
    def status():
        data = monitor.snapshot() if monitor else {}
        data["backend"] = backend.name
        data["site"] = backend.site_label or "Domicile"
        data["now"] = time.time()
        return jsonify(data)

    @app.post("/api/alarm")
    @login_required
    def set_alarm():
        body = request.get_json(silent=True) or {}
        level = body.get("level")
        if level not in ALARM_LEVELS:
            return jsonify(error="Niveau invalide"), 400
        if level == "disarmed" and cfg.ui_pin and not same(str(body.get("pin", "")), cfg.ui_pin):
            return jsonify(error="Code incorrect"), 403
        try:
            backend.set_alarm_state(level)
        except BackendError as exc:
            return jsonify(error=str(exc)), 502
        log.info("Alarme -> %s (depuis %s)", level, request.remote_addr)
        if monitor:
            monitor.refresh_now()
        return jsonify(ok=True, level=level)

    @app.post("/api/camera/<camera_id>/shutter")
    @login_required
    def shutter(camera_id: str):
        action = (request.get_json(silent=True) or {}).get("action")
        if action not in ("open", "close"):
            return jsonify(error="Action invalide"), 400
        try:
            backend.set_shutter(camera_id, action == "open")
        except BackendError as exc:
            return jsonify(error=str(exc)), 502
        if monitor:
            monitor.refresh_now()
        return jsonify(ok=True)

    @app.get("/api/camera/<camera_id>/snapshot")
    @login_required
    def snapshot(camera_id: str):
        try:
            data, mime = backend.take_snapshot(camera_id)
        except BackendError as exc:
            return jsonify(error=str(exc)), 502
        if not mime.startswith("image/"):
            abort(502)
        return Response(data, mimetype=mime)

    @app.post("/api/test-email")
    @login_required
    def test_email():
        try:
            notifier.send_test(backend.site_label)
        except Exception as exc:  # noqa: BLE001
            return jsonify(error=str(exc)), 500
        return jsonify(ok=True)

    @app.post("/api/demo/trigger")
    @login_required
    def demo_trigger():
        if backend.name != "demo":
            abort(404)
        backend.simulate_trigger()  # type: ignore[attr-defined]
        if monitor:
            monitor.refresh_now()
        return jsonify(ok=True)

    @app.get("/api/debug/raw")
    @login_required
    def debug_raw():
        if not cfg.debug_endpoint:
            abort(404)
        return jsonify(backend.raw_dump())

    return app
