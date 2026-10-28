# Validation personnelle : affichage et persistance

La PR nº 43 traduit le classement interne `known` par « Reconnu ».
Le test HTTP de modification cherchait encore le code anglais dans la page.
Il vérifie désormais le libellé français et lit directement la base de test
pour contrôler le statut `known`, l'alias et le type persistés après la requête.
Les autres tests, notamment authentification, CSRF et refus des champs
invalides, restent inchangés et aucun test n'est désactivé.

Une reproduction isolée du fragment Jinja de validation échoue avec
l'ancienne assertion et réussit avec l'assertion française. Le test HTTP
complet et la suite entière n'ont pas été exécutés dans cet environnement.
Les annotations publiques identifient un échec Pytest, mais ne fournissent
pas la trace complète : ce correctif ne prétend pas exclure d'autres échecs.
La nouvelle CI Windows/Linux doit confirmer le résultat avant toute fusion.

Aucun changement de logique applicative, schéma ou collecte réseau.
