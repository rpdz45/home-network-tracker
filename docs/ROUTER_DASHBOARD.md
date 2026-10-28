# Diagnostic Bbox depuis le dashboard local

## Fonction livrée

Une entrée « Routeurs » ouvre `/routers` sur la même adresse que le dashboard.
Afficher cette page ne contacte aucune box et ne nécessite aucune base SQLite.
Le bouton Bbox lance uniquement le diagnostic de lecture déjà présent dans
`routers.bbox`. Les résultats distinguent accès possible, authentification ou
droits requis, et point indisponible. Ils ne confirment pas une capacité de blocage.
Le module Livebox 5 n'est pas encore raccordé ; aucun blocage/déblocage réel
n'est disponible. La compatibilité de la Bbox WiFi 7 XT reste à confirmer.

## Activation côté serveur

Ces trois nouvelles variables sont lues dans l'environnement du processus à la
création de l'application, pas dans `config.toml` ni automatiquement dans `.env`.
Redémarrer le serveur après un changement. Seule la valeur exacte `true`
active les deux indicateurs ; leur absence ou toute autre valeur les désactive.
Le jeton de connexion au dashboard suit le chargement existant du projet.

Exemple PowerShell avant de lancer le serveur avec la commande habituelle :

```powershell
$env:NETTRACKER_BBOX_DIAGNOSTICS_ENABLED = "true"
$env:NETTRACKER_BBOX_URL = "https://192.168.1.254"
$env:NETTRACKER_BBOX_ALLOW_HTTP = "false"
```

Exemple shell :

```sh
export NETTRACKER_BBOX_DIAGNOSTICS_ENABLED=true
export NETTRACKER_BBOX_URL=https://192.168.1.254
export NETTRACKER_BBOX_ALLOW_HTTP=false
```

Adapter l'adresse à sa propre box et à `allowed_subnets`. Aucun DNS n'est
accepté par le lecteur. L'adresse est validée sans réseau à la création de
l'application avec le garde-fou existant du lecteur, puis de nouveau à chaque
appel du diagnostic. Une adresse invalide n'est pas affichée et désactive le
bouton, sans trafic vers elle. Aucun identifiant ne doit figurer dans cette URL.
HTTPS vérifie le certificat : un certificat non reconnu sera refusé. Ce lot
n'ajoute pas de mécanisme de confiance locale ni de désactivation TLS.
HTTP demande à la fois une URL HTTP et `NETTRACKER_BBOX_ALLOW_HTTP=true` ;
les échanges ne sont alors pas chiffrés. Aucun mot de passe box n'est envoyé.

## Déclenchement et protections

1. Configurer un jeton du dashboard selon les instructions existantes, même
   pour une écoute locale. Ne jamais transmettre ce jeton dans le chat.
2. Ouvrir « Routeurs » et vérifier la cible configurée côté serveur.
3. Cocher la confirmation puis cliquer sur « Lancer le diagnostic Bbox ».

La route POST réutilise l'authentification du dashboard, vérifie l'origine,
le marqueur de requête intersite, un jeton CSRF et la confirmation. Le formulaire
est limité à 2048 octets et deux champs ; aucune cible ne peut y être ajoutée.
Un seul diagnostic à la fois et un intervalle minimal de 10 secondes entre
tentatives sont imposés par instance d'application, y compris après une erreur.
Ces limites ne sont pas partagées entre plusieurs processus ou serveurs.
Les résultats sont rendus dans la réponse POST, sans historique, stockage ou
rafraîchissement automatique. Rafraîchir cette réponse dans le navigateur peut
proposer de renvoyer le formulaire : cela reste soumis aux mêmes protections.

Les erreurs du lecteur produisent une page générique 503 sans corps d'erreur
ni secret. Aucun schéma SQLite, dépendance ou réglage de box n'est modifié.

## Validation

Les nouveaux tests web remplacent systématiquement le lecteur, sans réseau
réel. Ils couvrent les états inactifs, l'authentification, CSRF, confirmation,
origines, limites de formulaire, cible serveur, résultats, erreurs et délai
entre appels. Ils ne prouvent pas la compatibilité du firmware ni TLS réel.

```text
python -m pytest tests/unit/test_web_routers.py
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest --cov
```

CI Linux/Windows et revue nécessaires avant fusion. Ne pas présenter ces
nouveaux tests comme exécutés si l'environnement local n'a pas FastAPI.
