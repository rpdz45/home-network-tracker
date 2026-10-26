# M3 — Réouverture SQLite et reprise après verrou

## Périmètre

Tests et documentation uniquement, sur fichiers créés dans le répertoire temporaire
pytest avec les migrations réelles. La fixture exige le mode WAL et remplace le
backend ping réel par un refus ; toutes les sondes des scénarios sont injectées.
Aucune base du propriétaire, purge réelle ou opération réseau utilisée.
Rôle : QA, puis sécurité et documentation.

## Trois scénarios préparés

1. Fermer et rouvrir la connexion entre trois mesures en ligne / hors ligne / en
   ligne. Vérifier les transitions, le statut à confirmer, last_seen et la cible,
   y compris après purge des observations de découverte remplacées. Réouvrir à
   nouveau et rejouer le dernier horodatage sans doubler mesure ou événement.
2. Après un premier cycle validé pour deux appareils, ouvrir deux connexions sur
   le fichier. Une connexion conserve BEGIN IMMEDIATE ; le cycle de monitoring
   doit échouer explicitement sans changer les données déjà validées ni annuler
   la transaction de l'autre connexion. Libérer le verrou, fermer les connexions,
   rouvrir puis réussir le cycle ; le rejeu ne doit pas doubler les écritures.
3. Pendant les sondes simulées, une seconde connexion valide un changement d'IP.
   Le cycle devenu obsolète doit annuler toutes ses mesures, même celle du premier
   appareil. Après réouverture, le changement de découverte doit rester présent
   et une relance doit sélectionner la nouvelle IP.

Les connexions appartiennent au même processus et les entrelacements sont pilotés,
pas parallèles. Le timeout de verrou de 0,01 seconde limite l'attente du test ;
aucune durée d'exécution exacte n'est imposée. Les sondes précèdent la transaction
d'écriture : elles peuvent être appelées avant l'erreur de verrou. L'idempotence
vérifiée concerne les écritures, pas l'absence de nouveaux appels de sonde.

## Vérification et limites

Trois cas pytest attendus. Pendant la préparation : syntaxe AST, compilation et
limite de 100 caractères par ligne vérifiées. Les tests proposés n'ont pas été
exécutés ici : le paquet nettracker et Ruff ne sont pas installés dans cet
environnement. Ruff, mypy, couverture et CI Linux/Windows restent à vérifier.

```sh
pytest tests/integration/test_monitor_disk_recovery.py -vv
```

Le refus simple d'un verrou est déjà couvert dans test_monitoring.py ; ce lot
ajoute la relance et la réouverture, ainsi que le changement sur une autre connexion.
Aucun arrêt brutal de processus, panne électrique, disque plein, corruption injectée,
fsync instrumenté, test interprocessus ou relance automatique de service exercé.
Aucune nouvelle logique de reprise ou de purge n'est ajoutée à la production.
Ce n'est ni une endurance réelle de 24 heures ni une preuve d'absence de fuite
mémoire ; M3 complet reste ouvert.
