# Fiche appareil, historique et événements

## Périmètre

Ce lot poursuit la refonte après la PR nº 42. Une macro partagée affiche
les dates en heure de Paris dans la fiche, les événements et l'historique.
L'horodatage source reste disponible au survol pour distinguer les heures
locales répétées lors du changement d'heure. Les calculs UTC, les fenêtres,
les 96 créneaux et les agrégations ICMP sont inchangés.

La fiche traduit le type et le classement personnel, donne un nom de
remplacement et distingue les observations du cache des résultats ping.
Une observation de découverte ne présente plus son indicateur comme une
preuve de disponibilité actuelle ni ses valeurs comme des mesures ICMP.
Le modèle reste explicitement indisponible : aucune identification nouvelle
n'est inventée. Les codes techniques des événements et notifications sont
conservés pour le diagnostic.

## Validation

Les 15 tests existants de `test_history_charts.py` sont conservés. Leur
environnement Jinja enregistre désormais le filtre de dates. Sept tests
complètent la couverture de la fiche, des événements, de l'échappement et
du changement d'heure. Les 22 tests ont réussi dans un environnement isolé
avec les modules temporels du projet, SQLite en mémoire et une base HTML
minimale pour le rendu des gabarits.

Cela ne valide pas le rendu avec le style complet dans un navigateur,
les routes HTTP, les migrations réelles ni la suite complète du dépôt.
Ruff, mypy, les contrôles de sécurité et la CI Windows/Linux restent à
exécuter pour ce lot. Aucun test existant n'est désactivé.

## Sécurité et limites

Aucun changement de schéma, de routes, de configuration ou de collecte.
Les champs du formulaire et sa protection CSRF sont conservés ; les données
affichées restent échappées. Aucun paquet réseau réel n'a été envoyé par
les tests et aucun test sur le matériel du propriétaire n'a été effectué.

Ce lot ne livre ni intégration Livebox, ni identification de marque ou de
modèle supplémentaire, ni lancement Windows ou icône d'exécutable.
