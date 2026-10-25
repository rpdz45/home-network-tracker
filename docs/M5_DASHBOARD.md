# M5 — Dashboard local et gestion des appareils

Le dashboard FastAPI/Jinja2 ne lance aucun scan ni connexion sortante. Les pages GET restent en lecture seule ; le formulaire de la fiche appareil permet désormais de modifier alias/type et de marquer comme connu.

## Utilisation

Initialiser avec `nettracker init-db --config config.toml`, puis lancer `nettracker serve --config config.toml`. Écoute par défaut sur 127.0.0.1:8080. Sans jeton configuré, le dashboard reste en lecture seule. Définir `NETTRACKER_API_TOKEN` dans le fichier .env ignoré par Git, redémarrer le serveur, puis saisir le jeton sur /login pour activer les formulaires.

Pages : / (appareils et santé du collecteur), /devices/{id} (fiche, formulaire, mesures, événements), /events (100 événements), /login. Les listes restent bornées à 500 appareils et 25 mesures/événements par fiche. Pas de graphiques ou rafraîchissement automatique dans ce lot.

## Écritures et sécurité

POST /devices/{id}/edit exige un jeton même sur loopback (cookie HttpOnly SameSite=Strict ou Bearer). Sans jeton configuré : 403. Avec jeton configuré mais sans identifiants : redirection vers /login ; Bearer incorrect : 401. Les formulaires sont réservés aux appareils non fusionnés ; les ignorés ne sont jamais approuvés implicitement.

Corps URL-encodé limité à 4096 octets, quatre champs au maximum : csrf, alias, device_type, mark_known optionnel égal à yes. Champs manquants, inconnus ou répétés refusés. Jeton CSRF HMAC par appareil, clé aléatoire propre au processus et distincte du jeton d’authentification ; redémarrer invalide les formulaires ouverts. Origin, si présent, doit correspondre exactement à l’origine du serveur ; Sec-Fetch-Site cross-site est refusé. Le jeton CSRF est exigé aussi pour Bearer. Aucun jeton d’authentification n’est injecté dans les pages.

Les lectures conservent query_only. Après validation HTTP, une connexion d’écriture dédiée applique alias/type et approbation dans une transaction unique. Toute erreur annule les deux opérations. Le SQL est paramétré et Jinja échappe les valeurs HTML. Aucun événement historique n’est supprimé, aucun scan supplémentaire autorisé. Les en-têtes CSP, nosniff, no-referrer et no-store restent appliqués.

HTTP reste en clair : ne pas exposer sur un réseau non fiable ; utiliser un proxy TLS géré par le propriétaire. Un proxy avec préfixe ou réécriture d’origine peut nécessiter une adaptation ; aucune prise en charge multi-worker des clés CSRF dans ce lot. Un seul jeton partagé, cookie contenant ce jeton, pas de limitation des essais de connexion.

## Validation

Tests ajoutés dans tests/unit/test_web_edits.py avec TestClient en processus et migrations SQLite réelles : authentification, CSRF incorrect, origine externe, corps trop gros, champs invalides, persistance, rollback et échappement. Syntaxe Python et limite de 100 caractères vérifiées ; tests HTTP, Ruff et CI non exécutés dans l’environnement de préparation. Ne pas annoncer ce nouveau commit validé avant CI verte. Aucun test navigateur ou matériel réel.

Commande ciblée : `pytest tests/unit/test_web.py tests/unit/test_web_edits.py tests/unit/test_device_edits.py -vv`. Exécuter ensuite toute la CI avant fusion. Pour un test manuel local : modifier un alias, recharger la page, vider l’alias pour vérifier le repli, puis approuver un appareil de test. Les indicateurs ICMP ne constituent jamais une authentification.
