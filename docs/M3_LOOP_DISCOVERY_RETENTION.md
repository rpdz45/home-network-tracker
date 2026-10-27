# M3 — Rétention découverte optionnelle dans la boucle

## Activation indépendante

`--prune-discovery` exige `discovery_retention.enabled=true`. La configuration
ping `[retention]` et `--prune-ping` ne l'autorisent jamais implicitement.
Refus avant ouverture de base et sonde si l'autorisation découverte manque.
Sans ce nouveau drapeau, comportement et sorties de la boucle restent inchangés.

`--discovery-prune-every-cycles N` accepte 1 à 1 000 000 cycles réussis ; défaut
100. Cette option sans `--prune-discovery` est refusée avant chargement de config.
La cadence est indépendante de celle des pings. Premier passage après N cycles,
pas au démarrage ni en passage final supplémentaire. Un cycle idempotent réussi
compte aussi. Les activations explicites du monitoring restent nécessaires.

## Politique et bornes

Réutilisation de `retain_discovery` sans modification de ses requêtes ni migration.
Durée et taille de lot proviennent de `[discovery_retention]`, mais `max_batches=1`
est imposé ici : un lot d'observations puis un lot de scans, chacun d'au plus
5 000 lignes. Cette borne ne garantit ni temps maximal ni résorption du retard.
La purge est globale à la base, pas limitée aux appareils suivis.

Conservation de la dernière découverte de chaque appareil, du dernier scan réussi,
des cinq derniers scans de statut non réussi et des scans encore référencés ou
non terminés. Pings, identités, états courants, événements et notifications ne sont
pas supprimés par cette politique. Le seuil strict utilise l'heure UTC système.
Une mauvaise horloge peut donc modifier ce qui est considéré ancien.

Ordre : rafraîchissement demandé, suivi réussi, purge ping éventuelle, puis purge
découverte éventuelle. Un arrêt est contrôlé avant chaque politique ; pas de
contrôle ajouté entre les deux phases internes observations/scans. Un SIGTERM
pendant ce passage attend donc sa fin. Les transactions sont celles des fonctions
existantes, jamais communes aux sondes. Une erreur arrête la boucle avec le code 2
sans réessai ; les mesures et lots déjà validés ne sont pas annulés.

Avec le drapeau, le résumé de sortie normale ajoute
`pruned_discovery_observations=N pruned_scans=M`. La purge ping reste distincte.
Les commandes autonomes d'aperçu et d'application ne sont pas modifiées.
Aucune activation sur le poste du propriétaire et aucune commande terrain lancée.
Avant toute suppression réelle : sauvegarde et vérification de l'aperçu avec la
commande autonome `prune-discovery`, puis choix explicite des options de boucle.

## Tests et limites

Tests préparés sur la fixture SQLite temporaire corrigée de la rétention ping :
activation indépendante, défaut sans suppression, cadence et lots bornés,
conservation des cibles/scans protégés, seuil strict, erreurs, arrêt entre
politiques et cadences ping/découverte indépendantes. Réseau et config utilisateur
remplacés ; horloge et attente injectées. Syntaxe, compilation et lignes Python
vérifiées pendant la préparation. Vérification isolée des requêtes SQL sur schéma
minimal : deux passages de deux observations et deux scans, protections conservées.
Ce contrôle ne remplace pas les nouveaux tests du paquet complet, non exécutés ici.
Ruff, mypy, couverture, audits et CI Linux/Windows restent à vérifier.

```text
pytest tests/integration/test_loop_discovery_retention.py tests/integration/test_loop_ping_retention.py tests/unit/test_discovery_retention.py -vv
```

Pas de taille maximale garantie pour toute la base, de validation matériel,
d'endurance réelle de 24 heures, de mesure RSS ou de clôture de M3.
