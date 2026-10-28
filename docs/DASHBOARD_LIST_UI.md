# Liste des appareils : premier lot visuel

## Périmètre

Ce lot succède au socle des dates de la PR nº 41. Le filtre `paris_datetime`
est enregistré dans Jinja et utilisé dans la liste pour la dernière
observation et le dernier scan réussi. La configuration du suivi est transmise
au rendu sans démarrer de collecteur.

La présentation commune évolue : navigation, typographie, cartes, tableaux,
formulaires et styles de focus. La liste dispose d'un défilement horizontal
et de compteurs portant uniquement sur les appareils affichés (500 maximum).
Les noms absents sont remplacés par un identifiant lisible. Les codes de
validation sont traduits, sans modifier les valeurs stockées.

Le suivi configuré, les résultats ICMP historiques et la santé du collecteur
restent distincts. Aucun de ces indicateurs ne prétend authentifier un
appareil ou prouver qu'une boucle tourne actuellement.

## Tests et limites

Huit cas de rendu ont réussi dans un environnement isolé, avec SQLite en
mémoire, Jinja et la logique du formateur de Paris. Le test de raccordement
à l'application est ajouté mais n'a pas été exécuté dans cet environnement.
La suite complète, Ruff, mypy, les contrôles de sécurité et la CI Windows/Linux
restent à exécuter pour ce nouveau commit.

Aucune vérification visuelle dans un navigateur réel ni aucun test sur le
matériel ou le réseau du propriétaire n'a été effectué. Aucun test existant
n'est désactivé.

Les dates et libellés internes du détail, des événements et des graphiques
ne sont pas encore convertis par ce lot. L'identification enrichie, les
filtres de recherche, l'intégration Livebox et l'icône de l'exécutable ne
sont pas livrés ici.

Aucune migration, sonde, notification, purge ou modification de configuration
n'est ajoutée. Les mécanismes d'authentification, de protection CSRF et les
en-têtes de sécurité sont conservés.
