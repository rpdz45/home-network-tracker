# Assemblage du service de contrôle Livebox

`build_livebox_control` assemble le résolveur SQLite, `ControlGuards` et `change_schedule`. La fabrique ne lit ni la base ni le réseau lors de sa construction. Elle ne crée aucune route et n'active aucune fonctionnalité dans l'application existante.

## Configuration serveur

`LiveboxControlConfig` exige un chemin SQLite, une URL de box, les sous-réseaux autorisés, un `SecretStr`, le firmware attendu et les MAC de gestion et de passerelle. `enabled` et `allow_http` sont faux par défaut. La fraîcheur vaut 60 secondes et ne peut dépasser cinq minutes.

Les MAC protégées sont validées et normalisées à la construction. Les paramètres d'endpoint, les identifiants, le modèle et le firmware restent contrôlés par l'adaptateur avant une modification. Le champ mot de passe est exclu de la représentation de la configuration.

## Flux

1. Construire une seule instance partagée dans une application à un seul processus.
2. Préparer avec identifiant local et action ; utiliser une liaison de session issue de l'authentification serveur.
3. Chaque résolution ouvre une connexion SQLite dédiée en `mode=ro`, puis la ferme : aucune création d'une base absente et aucun partage de connexion entre threads.
4. Confirmer consomme le jeton, relit les preuves locales et exécute l'adaptateur uniquement si la cible reste identique.
5. L'adaptateur applique ses protections et vérifie la relecture ; aucun nouvel essai automatique en cas de résultat incertain.

## Limites et raccordement restant

Aucune route web, authentification, protection CSRF/origine ni limitation des requêtes n'est ajoutée. La découverte fiable des MAC protégées reste à fournir. Le service ne doit pas être activé avant ces raccordements et leur revue.

Le verrou est local à l'instance et au processus, pas distribué. Le service ne verrouille pas les écritures de découverte ; une modification après résolution reste possible. Une libération restaure le calendrier sans garantir un accès immédiat. Les limites de confiance et de volume du résolveur SQLite s'appliquent toujours.

## Validation

Tests avec SQLite temporaire et `httpx.MockTransport` : préparation sans HTTP, confirmation complète et une seule écriture simulée, refus du rejeu, changement d'inventaire, contrôle désactivé, MAC protégée et base absente non créée.

Commande : `python -m pytest tests/unit/test_control_service.py tests/unit/test_control_inventory.py tests/unit/test_control_guards.py tests/unit/test_livebox5_control.py`.

Tests rédigés mais non exécutés par l'assistant. Ruff, formatage, mypy, couverture, suite complète et sécurité restent à vérifier en CI Linux/Windows. Aucun test sur réseau ou matériel réel.
