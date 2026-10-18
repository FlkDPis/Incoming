# Écrire un backend local pour la HC2

Le cloud Myfox s'arrête le 31 mars 2027. Pour continuer à piloter la centrale après cette date, il faudra un backend qui n'en dépend pas. **Aucun n'existe aujourd'hui à ma connaissance**, mais l'architecture est prête.

## Ce qui est connu (à vérifier)

Des utilisateurs ont observé, dans une discussion du dépôt communautaire `Angelius007/myfox-api`, que la centrale HC2 se connecte à deux serveurs : `hc2.steadyfox.com` et `core.steadyfox.com`. Ce n'est pas une API : c'est le protocole propriétaire entre la centrale et le cloud. Une piste serait de rediriger ces noms (DNS de votre box ou de Pi-hole) vers un petit serveur maison qui reproduirait ce protocole. **Cela suppose de le rétro-ingénierer** (capture réseau, éventuellement TLS) : c'est un travail de recherche, sans garantie de résultat, et à mener uniquement sur votre propre matériel.

## Comment brancher un nouveau backend

1. Créez `app/backends/local_hc2.py` avec une classe qui hérite de `Backend` ([`base.py`](../app/backends/base.py)) et implémente :
   `get_alarm_state`, `set_alarm_state`, `list_cameras`, `set_shutter`, `take_snapshot`, `list_devices`, `get_events`.
2. Déclarez-la dans `app/backends/__init__.py` (`create_backend`) sous un nom, par exemple `local_hc2`.
3. Ajoutez les éventuels paramètres dans `app/config.py` et `.env.example`.
4. Lancez avec `BACKEND=local_hc2`. L'interface, la surveillance et les e-mails fonctionnent sans autre modification.

Copiez les tests de `tests/test_app.py` (qui utilisent le backend `demo`) pour valider le vôtre.

## Alternative matérielle

Pour la partie « capteurs radio », certains utilisateurs évoquent une passerelle radio indépendante (ex. RFXtrx + Home Assistant). Cela ne remplace pas la centrale d'alarme elle-même ; à étudier selon vos équipements.
