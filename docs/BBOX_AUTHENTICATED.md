# Bbox : inventaire administrateur

Le client authentifié est raccordé à `/routers/bbox`, lié depuis « Routeurs ».
GET sans appel réseau ; POST `/routers/bbox/read` pour connexion, inventaire et
tentative de déconnexion. Diagnostic et Livebox restent distincts. Aucun
blocage/déblocage ni changement de politique globale ou calendrier. Compatibilité
WiFi 7 XT et efficacité des règles non certifiées.

## Configuration du processus serveur

- `NETTRACKER_BBOX_AUTH_ENABLED=true` : activation distincte du diagnostic.
- `NETTRACKER_BBOX_URL` : IPv4 RFC1918 autorisée par allowed_subnets, port standard.
- `NETTRACKER_BBOX_PASSWORD` : secret administrateur local, encapsulé en SecretStr.
- `NETTRACKER_BBOX_EXPECTED_MODEL` : modelname API exact, 1 à 128 caractères.
- `NETTRACKER_BBOX_CA_FILE` : facultatif, autorités de certification locales approuvées.
- `NETTRACKER_BBOX_ALLOW_HTTP=true` : accord explicite pour HTTP non chiffré.

Jeton api.token obligatoire, même en loopback. Variables lues à la création de
l'application : redémarrer après modification. Le chargeur `.env` actuel ne les
injecte pas automatiquement dans os.environ. Les fournir au processus par un
moyen local sûr, jamais dans Git, l'historique des commandes ou ce chat.
Le formulaire n'accepte aucun secret, URL, modèle ou chemin de certificat.

Relever modelname dans les informations API d'une session administrateur locale,
sans partager les cookies. Ne pas supposer qu'il vaut le nom commercial.
Le modèle est contrôlé après envoi du mot de passe : faire confiance à la cible
avant de le fournir. HTTPS vérifié ; CA ne désactive ni chaîne ni contrôle du
nom couvrant l'IP. Aucun verify=False, DNS, proxy d'environnement ou redirection.
HTTP expose mot de passe et cookie ; avertissement explicite à l'écran.

## Protections et limites

Authentification existante, CSRF, origine, Sec-Fetch-Site, confirmation explicite,
formulaire de 2 Kio et deux champs exacts. Verrou et délai de 15 minutes après
chaque tentative, réussie ou non ; un refus de cadence ne le prolonge pas.
Compteur local au processus, remis à zéro au redémarrage : un seul worker requis,
pas de garantie contre tout verrouillage du firmware. Aucun réessai automatique.
Échappement HTML, masquage du secret et rendus Cache-Control: no-store.

Client : PUT login avec remember=1, cookie BBOX_ID utilisable requis, GET device
et hosts.list puis tentative POST logout. Référence communautaire étudiée :
https://github.com/hadamrd/bbox-cli ; aucun code importé de cette référence.
Corps bornés à 2 Mio, compression refusée, maximum 512 hôtes aux identifiants et
MAC unicast non nulles uniques. Timeouts par opération, pas un délai global.
États absents/inconnus : None ; blocked ne prouve pas une coupure et n'est pas
affiché comme tel. Les IP retournées ne sont ni scannées ni automatiquement
autorisées comme cibles de contrôle. Pas de réponse brute, numéro de série,
stockage SQLite, journalisation d'inventaire ou envoi externe. Cookies en mémoire.
Une demande logout acceptée n'est pas une preuve indépendante de révocation ;
l'écran avertit si elle échoue. Une session créée peut subsister jusqu'à expiration.

## Validation

Les 16 tests du client ont passé dans l'environnement isolé du lot précédent.
Les nouveaux tests web utilisent l'application réelle et un lecteur simulé,
mais ne sont pas exécutés ici : FastAPI est absent. Syntaxe Python et rendu
Jinja isolé vérifiés seulement. Aucun accès à la box ni test matériel.

```text
python -m pytest tests/unit/test_bbox_session.py tests/unit/test_web_bbox.py
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest --cov
```

CI Linux/Windows, revue des secrets et matériel réel requis avant fusion.
Le blocage/déblocage reste à implémenter, pas à annoncer comme opérationnel.
