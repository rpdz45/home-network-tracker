# Contrôle d'accès Livebox et Bbox : socle commun

## Périmètre de ce lot

`routers.control` définit une demande de blocage/déblocage et un service commun
pour deux familles d'adaptateurs : Livebox 5 et Bbox. Il n'implémente encore
aucun adaptateur réseau et n'ajoute aucun bouton au dashboard.
Les deux valeurs de `RouterKind` sont des identifiants de travail, pas une
certification de compatibilité. Le modèle exact de Bbox reste à préciser.
L'ancien lot de page d'attente Livebox n'est pas inclus.

## Garanties du service

- Aucune action par défaut : activation et confirmation explicites requises.
- Adresse IPv4 privée RFC1918 comprise dans `allowed_subnets`.
- MAC unicast non nulle, normalisée en majuscules.
- Adaptateur correspondant à la famille demandée.
- Lecture préalable obligatoire ; état inconnu = aucun changement tenté.
- Pas d'écriture si la règle correspond déjà à la demande.
- Une seule écriture au maximum, puis relecture obligatoire.
- Aucun succès si la relecture ne confirme pas l'état demandé.
- Aucun nouvel essai automatique après un timeout ou une erreur.

Une relecture confirme la règle de la box, pas l'absence effective de tout
trafic Internet. L'API ne fournit pas de garantie sur les données mobiles,
les autres interfaces ou le changement d'adresse MAC d'un appareil.

## Raccordement encore nécessaire

L'interface web devra imposer une authentification, une protection CSRF,
une confirmation liée à la cible et à l'action, et une limitation des requêtes.
Les deux booléens du service ne constituent pas ces protections.
Les adaptateurs devront vérifier modèle et firmware, garder les secrets en
local, préserver les règles préexistantes, protéger l'appareil de gestion et
la passerelle contre un blocage accidentel, et rendre les erreurs sans secrets.
La cible devra être résolue depuis l'inventaire local, et non faire confiance
à une IP et une MAC fournies arbitrairement par le navigateur.

Après une erreur d'écriture, l'interface devra présenter un état incertain et
proposer une lecture explicite, sans annoncer un échec garanti ni réessayer
l'écriture. Le déblocage ne doit pas supprimer un calendrier antérieur : sa
sémantique exacte sera fixée par adaptateur après lecture de l'état existant.

## Références étudiées, pas garanties constructeur

- LiveboxMonitor, discussion technique sur restriction Internet et filtrage
  Wi-Fi : https://github.com/p-dor/LiveboxMonitor/issues/34
- bbox-cli, API d'administration avec authentification, jeton d'écriture et
  fonctions distinctes par hôte / contrôle parental / filtrage Wi-Fi :
  https://github.com/hadamrd/bbox-cli

Ces implémentations communautaires ne prouvent pas la compatibilité des box
du propriétaire. Aucun code de ces projets n'est importé dans ce lot.
Aucun contournement d'authentification ou attaque de déconnexion n'est ajouté.
Le lecteur Livebox 5 existant reste strictement en lecture seule.

## Tests et validation

Les tests utilisent seulement des adaptateurs en mémoire : blocage, déblocage,
idempotence, confirmation absente, état inconnu, relecture contradictoire,
timeout, mauvais adaptateur, cibles interdites et MAC invalides.
Aucun paquet réseau, identifiant réel ou inventaire du foyer n'est utilisé.

Commandes dans l'environnement de développement du dépôt :

```text
python -m pytest tests/unit/test_router_control.py
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest --cov
```

Les résultats locaux doivent être distingués de la CI et des tests matériels.
Ce lot seul ne permet de bloquer aucun appareil réel.
