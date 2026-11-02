# Affichage de disponibilité du contrôle routeur

La page `/routers` inclut un encadré commun Livebox/Bbox. Il décrit l'état du code dans cette version, pas un diagnostic dynamique de la box ni une certification matérielle.

- Livebox : service et adaptateur développés, aucune route de contrôle web raccordée.
- Bbox : service avec adaptateur injecté, aucun adaptateur HTTP d'écriture de production.
- Quatre boutons de type button sont désactivés et liés à une explication accessible. Aucun formulaire de contrôle ni script n'est ajouté.
- Les diagnostics de lecture préexistants restent séparés et conservent leurs confirmations.
- Aucune simulation interactive : seuls les tests automatisés utilisent des données simulées.

Ce lot ne change ni la configuration d'activation, ni les services, ni les routes d'écriture. Les protections web et la validation matérielle restent à terminer avant un futur raccordement. Le retrait d'un forçage Livebox ne garantit pas l'accès si le calendrier l'interdit.

## Validation

Tests TestClient sans base existante : rendu, boutons désactivés, absence d'appel au transport HTTP sortant, authentification si jeton configuré, en-tête no-store et absence de routes de contrôle aux chemins testés. Ce n'est pas un test navigateur ni une preuve générale d'absence de tout effet réseau.

Commande : `python -m pytest tests/unit/test_router_control_status.py`.

Tests rédigés mais non exécutés par l'assistant. Ruff, formatage, mypy, suite complète et sécurité restent à vérifier en CI Linux/Windows. Aucun test sur réseau ou matériel réel.
