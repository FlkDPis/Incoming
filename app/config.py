"""Configuration chargée depuis les variables d'environnement (fichier .env)."""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from typing import List

from dotenv import load_dotenv


def _bool(value: str | None, default: bool = False) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in ("1", "true", "yes", "oui", "on")


def _int(value: str | None, default: int) -> int:
    try:
        return int(value) if value not in (None, "") else default
    except ValueError:
        return default


def _list(value: str | None) -> List[str]:
    return [v.strip() for v in (value or "").split(",") if v.strip()]


@dataclass(frozen=True)
class Config:
    backend: str = "demo"

    myfox_client_id: str = ""
    myfox_client_secret: str = ""
    myfox_username: str = ""
    myfox_password: str = ""
    myfox_site_id: str = ""
    myfox_api_base: str = "https://api.myfox.me/v2"
    myfox_token_url: str = "https://api.myfox.me/oauth2/token"

    host: str = "127.0.0.1"
    port: int = 8080
    ui_password: str = ""
    ui_pin: str = ""
    secret_key: str = field(default_factory=lambda: secrets.token_hex(32))

    poll_interval: int = 20
    device_refresh: int = 300
    battery_warn: int = 20
    alarm_keywords: List[str] = field(default_factory=list)
    timezone: str = "Europe/Paris"

    alert_recipients: List[str] = field(default_factory=list)
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_security: str = "starttls"
    smtp_user: str = ""
    smtp_password: str = ""
    mail_from: str = ""
    alert_cooldown: int = 120
    alert_open_shutter: bool = True

    font_family: str = "system-ui, sans-serif"
    font_css_url: str = ""
    debug_endpoint: bool = False

    @classmethod
    def from_env(cls, env_file: str | None = ".env") -> "Config":
        if env_file:
            load_dotenv(env_file)
        g = os.environ.get
        default_keywords = "intrusion,déclench,declench,triggered,sirène,sirene,panic,panique"
        return cls(
            backend=g("BACKEND", "demo").strip().lower(),
            myfox_client_id=g("MYFOX_CLIENT_ID", ""),
            myfox_client_secret=g("MYFOX_CLIENT_SECRET", ""),
            myfox_username=g("MYFOX_USERNAME", ""),
            myfox_password=g("MYFOX_PASSWORD", ""),
            myfox_site_id=g("MYFOX_SITE_ID", ""),
            myfox_api_base=g("MYFOX_API_BASE", "https://api.myfox.me/v2").rstrip("/"),
            myfox_token_url=g("MYFOX_TOKEN_URL", "https://api.myfox.me/oauth2/token"),
            host=g("HOST", "127.0.0.1"),
            port=_int(g("PORT"), 8080),
            ui_password=g("UI_PASSWORD", ""),
            ui_pin=g("UI_PIN", ""),
            secret_key=g("SECRET_KEY") or secrets.token_hex(32),
            poll_interval=max(5, _int(g("POLL_INTERVAL"), 20)),
            device_refresh=max(30, _int(g("DEVICE_REFRESH"), 300)),
            battery_warn=_int(g("BATTERY_WARN"), 20),
            alarm_keywords=[k.lower() for k in _list(g("ALARM_KEYWORDS", default_keywords))],
            timezone=g("TIMEZONE", "Europe/Paris"),
            alert_recipients=_list(g("ALERT_RECIPIENTS")),
            smtp_host=g("SMTP_HOST", ""),
            smtp_port=_int(g("SMTP_PORT"), 587),
            smtp_security=g("SMTP_SECURITY", "starttls").strip().lower(),
            smtp_user=g("SMTP_USER", ""),
            smtp_password=g("SMTP_PASSWORD", ""),
            mail_from=g("MAIL_FROM", "") or g("SMTP_USER", ""),
            alert_cooldown=_int(g("ALERT_COOLDOWN"), 120),
            alert_open_shutter=_bool(g("ALERT_OPEN_SHUTTER"), True),
            font_family=g("FONT_FAMILY", "system-ui, sans-serif"),
            font_css_url=g("FONT_CSS_URL", ""),
            debug_endpoint=_bool(g("DEBUG_ENDPOINT"), False),
        )

    def validate(self) -> List[str]:
        """Retourne la liste des problèmes bloquants de configuration."""
        problems: List[str] = []
        if self.backend == "myfox_cloud":
            for name in ("myfox_client_id", "myfox_client_secret", "myfox_username", "myfox_password"):
                if not getattr(self, name):
                    problems.append(f"{name.upper()} est requis pour BACKEND=myfox_cloud")
        elif self.backend != "demo":
            problems.append(f"BACKEND inconnu : {self.backend!r} (valeurs : myfox_cloud, demo)")
        if self.host not in ("127.0.0.1", "localhost", "::1") and not self.ui_password:
            problems.append("UI_PASSWORD est obligatoire quand HOST n'est pas 127.0.0.1")
        if self.alert_recipients and not (self.smtp_host and self.mail_from):
            problems.append("ALERT_RECIPIENTS est défini mais SMTP_HOST / SMTP_USER (ou MAIL_FROM) manquent")
        return problems

    @property
    def mail_enabled(self) -> bool:
        return bool(self.alert_recipients and self.smtp_host and self.mail_from)
