# Assemblage Bbox avec adaptateur injecté

`build_bbox_control` assemble le résolveur SQLite, `ControlGuards` et `change_bbox_access`. Aucun adaptateur HTTP d'écriture, aucune route web et aucune activation dans l'application ne sont ajoutés. Ce n'est pas encore un contrôle Bbox utilisable sur matériel.

## Contrat serveur

La configuration fixe le chemin SQLite, les sous-réseaux, le modèle/firmware exacts, l'IPv4 de passerelle et les deux MAC protégées. Le contrôle est désactivé par défaut ; la fraîcheur vaut 60 secondes et est limitée à cinq minutes. La passerelle doit correspondre à l'endpoint du futur adaptateur, qui devra le vérifier indépendamment.

Une seule instance doit être partagée par les requêtes d'un processus. La préparation et la confirmation relisent SQLite avec une connexion dédiée en mode=ro, fermée après résolution. Une base absente n'est pas créée. Les cibles protégées et l'IP du routeur sont refusées avant ouverture de session.

`session_factory` vient exclusivement du code serveur. Elle ouvre une session seulement après consommation de la confirmation et revalidation locale. Le même port sert à la lecture initiale, à l'unique écriture éventuelle et à la relecture. Le gestionnaire de contexte doit fermer la session et ne pas supprimer les exceptions. Une exception inattendue est nettoyée ; une erreur supprimée sans résultat provoque un refus incertain. Aucune nouvelle tentative automatique.

## Limites

Le verrou est local à une instance et à un processus. Aucune atomicité entre SQLite et le routeur. Les limites du résolveur et de bbox_control s'appliquent : identité physique non prouvée, champ blocked et préservation des calendriers non validés sur matériel, cible active exigée.

L'adaptateur HTTP, la gestion sûre des identifiants et du jeton d'écriture, l'authentification web, CSRF/origine, limites de requêtes et découverte fiable des MAC protégées restent à implémenter et valider avant activation.

## Validation

Tests avec SQLite temporaire et port synthétique : préparation sans session, cycle de confirmation/fermeture, refus du rejeu, changement d'inventaire, résultat incertain et refus avant session. Aucun paquet réseau réel.

Commande : `python -m pytest tests/unit/test_bbox_control_service.py tests/unit/test_bbox_control.py tests/unit/test_control_guards.py tests/unit/test_control_inventory.py`.

Tests rédigés mais non exécutés par l'assistant. Ruff, formatage, mypy, couverture, suite complète et sécurité restent à vérifier en CI Linux/Windows. Aucun test sur matériel réel.
