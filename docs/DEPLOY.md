# Lancer au démarrage (systemd)

Exemple pour un Raspberry Pi ou un serveur Linux, avec le projet dans `/opt/hc2-control` :

```bash
sudo useradd --system --home /opt/hc2-control hc2
sudo git clone <votre-repo> /opt/hc2-control
cd /opt/hc2-control
sudo python3 -m venv .venv
sudo .venv/bin/pip install -r requirements.txt
sudo cp .env.example .env && sudo nano .env
sudo chown -R hc2:hc2 /opt/hc2-control
sudo chmod 600 /opt/hc2-control/.env
```

`/etc/systemd/system/hc2-control.service` :

```ini
[Unit]
Description=HC2 Control
After=network-online.target
Wants=network-online.target

[Service]
User=hc2
WorkingDirectory=/opt/hc2-control
ExecStart=/opt/hc2-control/.venv/bin/python run.py
Restart=on-failure
RestartSec=10
NoNewPrivileges=true

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now hc2-control
journalctl -u hc2-control -f
```

Pensez à donner une adresse IP fixe (ou une réservation DHCP) à la machine, et à garder l'interface hors d'Internet (VPN recommandé).
