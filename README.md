# HC2 Control — un tableau de bord libre pour votre alarme Myfox / Somfy HC2

Interface web légère (Python + Flask) pour piloter votre centrale **Somfy / Myfox Home Control 2 (HC2)** sans l'application officielle :

- **Armer / désarmer** l'alarme (total, partiel), avec code optionnel pour désarmer
- **Volet de la caméra** : ouvrir / fermer, aperçu de l'image
- **Capteurs et batteries** : détecteurs de mouvement, clavier à code, etc., avec alerte batterie faible
- **Alerte e-mail** quand l'alarme se déclenche : photo de la caméra, heure, capteur, derniers événements
- Historique des derniers événements, mot de passe d'accès, thème clair/sombre, police configurable

> ⚠️ **À lire avant tout : ce que ce projet peut et ne peut pas faire**
>
> Somfy arrêtera définitivement les serveurs Myfox HC2 le **31 mars 2027**. Après cette date, la centrale ne fonctionnera plus qu'en local (télécommande, clavier, détecteurs, sirènes) et **aucune API cloud ne répondra plus**.
>
> Le backend fourni ici (`myfox_cloud`) utilise l'API cloud Myfox : **il fonctionne jusqu'au 31/03/2027, pas après**. À ma connaissance, il n'existe aucune API locale documentée pour la HC2, et la branche Ethernet de la centrale ne suffit pas à elle seule (la centrale parle à des serveurs Myfox, pas à votre réseau local).
>
> Ce dépôt est donc construit pour **survivre à cette échéance** : toute la logique (interface, surveillance, e-mails) ne dépend que d'une interface `Backend` ([`app/backends/base.py`](app/backends/base.py)). Si la communauté trouve un moyen de parler à la centrale en local, il suffira d'écrire un nouveau backend ([`docs/BACKEND_LOCAL.md`](docs/BACKEND_LOCAL.md)).
>
> Autres limites : les mises à jour sont **périodiques** (toutes les ~20 s), pas instantanées, et les noms de champs de l'API Myfox (batterie, historique) n'étant pas documentés officiellement, le code est tolérant mais **doit être validé sur votre installation** (voir « Vérifier chez vous »).

## Démarrage rapide (mode démo, sans centrale)

```bash
git clone <votre-repo> hc2-control && cd hc2-control
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env          # BACKEND=demo par défaut
python run.py
```

Ouvrez http://127.0.0.1:8080 (mot de passe : celui de `UI_PASSWORD` dans `.env`). Le bouton « Simuler une intrusion » permet de tester la chaîne d'alerte e-mail.

## Brancher votre vraie centrale

1. **Créer vos accès API** sur <https://api.myfox.me/dev/apps> : une application de type « Personal application » vous donne un `CLIENT_ID` et un `CLIENT_SECRET`.
2. Dans `.env` :
   ```ini
   BACKEND=myfox_cloud
   MYFOX_CLIENT_ID=...
   MYFOX_CLIENT_SECRET=...
   MYFOX_USERNAME=votre-email-myfox
   MYFOX_PASSWORD=...
   ```
3. Lancez `python run.py`. Le premier site du compte est utilisé (sinon, renseignez `MYFOX_SITE_ID`).

### Vérifier chez vous (important)

Mettez `DEBUG_ENDPOINT=true`, redémarrez, connectez-vous puis ouvrez `/api/debug/raw` : vous y voyez les réponses brutes de votre centrale (alarme, caméras, capteurs, historique).

- Les **batteries** s'affichent si l'un des champs `batteryLevel`, `battery`, `batteryPercent`… est présent. Sinon la colonne indique « n/d » : dites-moi quels champs apparaissent et j'adapte `parse_battery`.
- La **détection d'alarme** repose sur des mots-clés dans l'historique (`ALARM_KEYWORDS`). Regardez les libellés réels dans « Derniers événements » et ajustez la liste. Faites un **vrai test** (déclenchez l'alarme volontairement) avant de vous y fier.
- Remettez `DEBUG_ENDPOINT=false` ensuite.

## Alerte e-mail

Renseignez dans `.env` : `ALERT_RECIPIENTS` (une ou plusieurs adresses), `SMTP_HOST`, `SMTP_PORT`, `SMTP_SECURITY`, `SMTP_USER`, `SMTP_PASSWORD`.
Avec Gmail : activez la validation en 2 étapes puis créez un **mot de passe d'application** (hôte `smtp.gmail.com`, port 587, `starttls`).

Le bouton **« Tester l'e-mail »** envoie un message de test avec une photo. En cas de déclenchement, le mail contient : site, date, événement, capteur concerné, état de l'alarme, photo(s) de la caméra (intégrées et en pièce jointe), derniers événements et capteurs à batterie faible. Un délai anti-spam (`ALERT_COOLDOWN`) évite les doublons.

> **Vie privée** : si le volet est fermé, `ALERT_OPEN_SHUTTER=true` l'ouvre quelques secondes avant la photo (sinon l'image serait noire). Mettez `false` pour ne jamais le faire.

## Sécurité

Cette interface peut **désarmer votre alarme** : traitez-la comme telle.

- Par défaut elle n'écoute que sur `127.0.0.1`. Pour y accéder depuis votre réseau local, mettez `HOST=0.0.0.0` (un `UI_PASSWORD` fort est alors obligatoire) et définissez `UI_PIN` pour exiger un code au désarmement.
- **Ne l'exposez pas directement sur Internet.** Pour un accès à distance, passez par un VPN (WireGuard, Tailscale) ou un reverse proxy en HTTPS avec authentification.
- Définissez `SECRET_KEY` (sinon les sessions sont réinitialisées à chaque redémarrage).
- Ne commitez jamais `.env` (déjà dans `.gitignore`).

## Style / police

Le projet n'embarque aucune police imposée. Pour reprendre celle de votre site :

```ini
FONT_FAMILY="Nom de la police", sans-serif
FONT_CSS_URL=https://fonts.googleapis.com/css2?family=Nom+de+la+police:wght@400;600&display=swap
```

Pour une police auto-hébergée, déposez le fichier `.woff2` dans `app/static/` et ajoutez un `@font-face` en tête de `app/static/style.css`. Les couleurs se changent dans le bloc `:root` du même fichier.

## Lancer au démarrage (Raspberry Pi, NAS…)

Voir [`docs/DEPLOY.md`](docs/DEPLOY.md) (service systemd).

## Architecture

```
run.py                     point d'entrée
app/
  config.py                configuration (.env)
  backends/
    base.py                interface Backend (à implémenter pour un futur backend local)
    myfox_cloud.py         API cloud Myfox (jusqu'au 31/03/2027)
    demo.py                données fictives
  monitor.py               boucle de surveillance + détection d'alarme
  notifier.py              e-mails avec photo (SMTP)
  web.py                   interface Flask + API JSON
  templates/, static/      front-end
tests/                     tests (pytest)
```

## Tests

```bash
pip install -r requirements.txt
pytest
```

## Licence

MIT. Projet communautaire, non affilié à Somfy ni à Myfox. Il n'a pas vocation à remplacer la protection d'une alarme certifiée : ne comptez pas sur lui comme seul moyen d'être prévenu d'une intrusion.
