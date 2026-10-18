#!/usr/bin/env python3
"""Point d'entrée : lance la surveillance et l'interface web.

    python run.py
"""
from __future__ import annotations

import logging
import sys

from app.backends import create_backend
from app.config import Config
from app.monitor import Monitor
from app.notifier import Notifier
from app.web import create_app


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    cfg = Config.from_env()

    problems = cfg.validate()
    if problems:
        print("Configuration invalide :", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        print("Éditez votre fichier .env (voir .env.example).", file=sys.stderr)
        return 1

    backend = create_backend(cfg)
    notifier = Notifier(cfg, backend)
    monitor = Monitor(cfg, backend, notifier)
    app = create_app(cfg, backend, monitor, notifier)
    monitor.start()

    if not cfg.ui_password:
        logging.warning("UI_PASSWORD vide : l'interface est ouverte à toute personne qui peut l'atteindre.")
    logging.info("Backend : %s — interface sur http://%s:%s", cfg.backend, cfg.host, cfg.port)
    if cfg.mail_enabled:
        logging.info("Alertes e-mail actives vers %s", ", ".join(cfg.alert_recipients))
    else:
        logging.warning("Alertes e-mail désactivées (ALERT_RECIPIENTS / SMTP non configurés).")

    try:
        from waitress import serve

        serve(app, host=cfg.host, port=cfg.port, threads=4)
    except ImportError:
        app.run(host=cfg.host, port=cfg.port)
    finally:
        monitor.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
