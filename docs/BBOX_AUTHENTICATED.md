# Client Bbox authentifié : connexion et inventaire

## Fonction de ce lot

`routers.bbox_session.read_authenticated_snapshot` effectue une connexion
administrateur et retourne un inventaire normalisé. C'est un nouveau module ;
le diagnostic Bbox existant et les lecteurs Livebox restent inchangés.
Ce lot n'est pas encore raccordé au dashboard et n'implémente aucun blocage,
déblocage, changement de calendrier, filtrage Wi-Fi ou politique globale.
Le nom de branche décrit la mission globale, pas des fonctions déjà livrées.

## Protocole étudié

Référence communautaire : https://github.com/hadamrd/bbox-cli , notamment
`pkg/client/client.go`, `pkg/client/endpoints.go`, `cmd/host.go` et `cmd/status.go`.
Aucun code de ce projet n'est importé. Les appels retenus sont :

1. PUT `/api/v1/login`, formulaire password et remember=1 comme la référence.
2. Vérification qu'un cookie BBOX_ID non vide serait envoyé à la cible.
3. GET `/api/v1/device`, comparaison exacte du champ modelname avec
   expected_model fourni par le serveur appelant.
4. GET `/api/v1/hosts`, enveloppe hosts.list.
5. Tentative POST `/api/v1/logout` en fin de session, y compris après une
   erreur de lecture, une fois le cookie utilisable obtenu.

Le modèle est vérifié après envoi du mot de passe, pas avant : aucune
identification pré-authentification n'est revendiquée. Il faut faire confiance
à la cible configurée avant de fournir des identifiants. expected_model n'est
ni une preuve cryptographique ni une certification de firmware. La valeur
réellement annoncée par la Bbox WiFi 7 XT n'est pas supposée dans le code.

## Autorisations et transport

Activation et confirmation strictement vraies requises, mot de passe SecretStr
non vide et modèle attendu exact obligatoire. Le module ne lit aucun secret
sur disque ou dans un navigateur. Un futur raccordement devra charger le
secret localement et contrôler authentification, CSRF, confirmation et cadence.
Les booléens de cette API Python ne remplacent pas ces protections web.

La cible conserve le garde-fou existant : IPv4 RFC1918 comprise dans
allowed_subnets, ports standards, aucun DNS, proxy d'environnement ou suivi de
redirection. HTTPS reste vérifié. ca_file permet un fichier d'autorités de
certification explicitement approuvé localement ; cela ne désactive ni la
validation de chaîne ni le contrôle du nom. Un certificat ne couvrant pas
l'IP cible restera refusé, même avec ce fichier. Aucun verify=False.
HTTP requiert un accord supplémentaire explicite et transmet le mot de passe
sans chiffrement. Aucun contournement d'authentification ou import de cookie.

Une seule tentative de connexion, aucun réessai ou rafraîchissement de session.
Les 401, 403, 429, redirections et erreurs serveur sont terminaux. Les timeouts
HTTPX sont configurables entre 0.1 et 30 secondes par opération, pas un délai
global. Chaque corps est limité à 2 Mio et les réponses compressées refusées.
Les erreurs applicatives ne reprennent ni corps, URL, mot de passe ou cookie.
Aucune journalisation ajoutée et aucun jeton secret dans une URL.

## Inventaire et fermeture

Au maximum 512 appareils ; identifiants entiers non négatifs uniques et MAC
unicast non nulles uniques. Une ambiguïté fait échouer la lecture plutôt que
de préparer un futur contrôle sur la mauvaise cible. Les propriétés hostname,
ipaddress, macaddress, active et blocked sont les seules conservées avec id.
Les textes sont bornés et les répétitions du mot de passe masquées. Les données
restent personnelles au foyer : aucun stockage, journalisation ou envoi externe.
Les adresses retournées sont des données de la box, pas des cibles scannées ni
des adresses dont l'appartenance au périmètre est garantie par cette lecture.

active et blocked ne sont reconnus que sous forme booléenne ou entière 0/1.
Un champ absent ou inconnu reste None, jamais False par défaut. blocked reflète
uniquement le champ communiqué ; cela ne prouve pas une coupure Internet.
Le modèle et le firmware sont lus via modelname et main.version, avec repli
sur firmware pour ce dernier. Aucun numéro de série ou réponse brute conservé.

session_closed indique seulement si la requête de déconnexion a reçu un statut
attendu, pas une preuve indépendante de révocation serveur. Si elle échoue, le
résultat marque False ; il ne prétend pas que la session est fermée. Sans cookie
utilisable, aucune lecture ou déconnexion n'est tentée et une erreur est levée.
La session éventuellement créée peut subsister jusqu'à expiration. Les cookies
restent en mémoire et sont abandonnés avec le client, sans sauvegarde sur disque.

## Tests et limites

Tests unittest avec HTTPX MockTransport et valeurs synthétiques seulement.
L'environnement isolé utilise le garde-fou d'origine extrait du module existant
et la classe de base d'erreur minimale ; cela ne remplace pas la suite du dépôt.
Aucun paquet, identifiant réel ou inventaire du foyer utilisé. Le protocole et
la compatibilité du firmware restent à vérifier sur la Bbox du propriétaire.

```text
python -m pytest tests/unit/test_bbox_session.py
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest --cov
```

Le raccordement au dashboard et les écritures de contrôle font partie de la
suite de la mission, pas de ce correctif. CI Linux/Windows, revue des secrets
et tests matériels sont nécessaires avant de déclarer une intégration prête.
