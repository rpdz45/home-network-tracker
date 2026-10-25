# M5 — Gestion des appareils : persistance (lot préparatoire)

Lié à l’issue #2. Ce lot ne livre pas encore les formulaires ou les routes HTTP. Le dashboard reste en lecture seule. Aucune migration n’est nécessaire : alias et device_type existent déjà.

## Interfaces

- `update_identity(conn, device_id, alias=..., device_type=...)` remplace les deux champs atomiquement. Un alias vide est enregistré à NULL pour conserver le repli d’affichage existant (nom d’hôte, puis MAC). Alias limité à 120 caractères, sans contrôles ASCII ; types : computer, phone, network, iot, tv, nas, camera, other, ou vide.
- `mark_known(conn, device_id)` persiste le statut known et reste idempotent. Les appareils ignorés ou fusionnés ne sont pas reclassés implicitement. Les événements historiques, MAC, observations et règles de scan restent inchangés.
- Appareil absent : LookupError ; champ invalide ou appareil fusionné : ValueError ; problème SQLite : DatabaseError générique.

## Décision technique et sécurité

Les écritures utilisent des paramètres SQL et un savepoint ; une transaction englobante peut toujours annuler la modification. Ces fonctions n’accordent aucune autorisation HTTP. Le futur adaptateur web devra exiger un jeton même sur loopback pour les écritures, une protection CSRF, des corps bornés et une validation stricte. Les connexions de lecture existantes conservent query_only. Un statut known est un classement manuel, jamais une authentification de l’appareil.

## Validation et limites

Neuf tests SQLite en mémoire, schéma minimal isolé, sans réseau. Exécution ciblée du code avec un substitut de DatabaseError dans l’environnement de calcul : neuf succès ; ce résultat ne valide ni les imports du paquet complet ni les migrations réelles. Aucun test matériel, navigateur ou LAN. Ruff, mypy, bandit, audit des dépendances, gitleaks et suite complète non exécutés pour ce lot : à vérifier avant toute fusion.

Commande de validation dans le dépôt installé : `pytest tests/unit/test_device_edits.py -vv`. Puis exécuter toutes les vérifications de la CI. Ne pas fermer l’issue #2 avant livraison et tests des routes et formulaires.
