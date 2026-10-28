# Diagnostic Bbox : accès aux points de lecture

## Périmètre

`routers.bbox.read_diagnostic` réalise au maximum trois GET, dans cet ordre :
`/api/v1/device`, `/api/v1/parentalcontrol`, puis
`/api/v1/parentalcontrol/scheduler`.
Ces chemins et leurs enveloppes sont étudiés dans `pkg/client/endpoints.go`
du projet communautaire https://github.com/hadamrd/bbox-cli . Aucun code de
ce projet n'est importé et aucune compatibilité constructeur n'est revendiquée.

Ce lot ne contient ni connexion administrateur, ni mot de passe, ni import de
session navigateur, ni jeton d'écriture, ni commande de blocage. Il n'est pas
raccordé à la configuration ou au dashboard. La cible reste la Bbox WiFi 7 XT,
mais les réponses simulées ne prouvent pas sa compatibilité réelle.

## États retournés

- `accessible` : HTTP 200 et enveloppe JSON attendue. Cela ne prouve ni le
  modèle exact ni la possibilité de bloquer un appareil.
- `authentication_or_permission_required` : HTTP 401 ou 403 ; ce n'est pas
  une absence de règles. Aucune tentative de connexion ou de contournement.
- `unavailable` : HTTP 404 ; aucune déduction sur les autres firmwares.

Le diagnostic s'arrête au premier 401, 403 ou 404. Seuls les points réellement
interrogés figurent dans le résultat ; les suivants ne sont pas déclarés
accessibles ou indisponibles. Une réponse inattendue, une erreur réseau, un
code 429, une redirection ou une erreur serveur font échouer le diagnostic,
sans réessai ni résultat de succès partiel retourné dans ces cas.

## Garde-fous

Activation explicite, IPv4 RFC1918 dans `allowed_subnets`, ports standards,
aucun DNS, aucun proxy d'environnement, aucun suivi de redirection.
HTTPS est vérifié ; aucun certificat autosigné n'est accepté implicitement.
Une Bbox utilisant un certificat non reconnu sera donc refusée : un futur
mécanisme explicite de confiance locale reste à définir, pas de `verify=False`.
HTTP local demande un second accord explicite ; il n'est pas chiffré.

Chaque requête utilise les timeouts HTTPX de 5 secondes. Ce n'est pas un délai
global couvrant tout le diagnostic. Chaque corps est limité à 2 Mio ; les
réponses compressées sont refusées. Les erreurs ne reproduisent ni corps ni
URL. Les données brutes sont analysées puis abandonnées, sans conservation
d'inventaire, journalisation ou stockage sur disque. Les éventuels cookies
émis par la cible restent dans le client en mémoire jusqu'à sa fermeture ;
aucune session navigateur n'est importée et aucun cookie n'est sauvegardé.

## Validation

Les tests utilisent exclusivement HTTPX MockTransport et des réponses
synthétiques. Ils vérifient les enveloppes, les refus d'accès, les résultats
limités aux appels tentés, les cibles interdites, l'accord HTTP, l'absence de
réessai et de redirection, les erreurs génériques et la limite de taille.
Aucun test ne doit contacter une box réelle.

```text
python -m pytest tests/unit/test_bbox.py
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest --cov
```

La suite globale et la CI Linux/Windows restent nécessaires avant fusion.
Ce diagnostic n'identifie pas encore formellement le modèle ou le firmware,
ne lit pas les règles protégées sans authentification et ne permet de bloquer
aucun appareil réel. La lecture authentifiée, l'identification fiable et
l'interface graphique feront l'objet de lots distincts.
