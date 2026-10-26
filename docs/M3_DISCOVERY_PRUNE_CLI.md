# M3 — Commande de purge de découverte

## Utilisation

Le script installé `nettracker` pointe maintenant vers `nettracker.entrypoint`.
Cet adaptateur délègue les commandes existantes à `nettracker.cli.main`, sans
modifier leur logique. Réinstaller le paquet après mise à jour de la branche.
Le nouveau nom apparaît dans le complément de l'aide racine.
Pour un appel Python explicite, utiliser `python -m nettracker.entrypoint` ;
`nettracker.cli.main` reste l'ancienne interface et n'ajoute pas cette commande.

Ajouter cette section indépendante à la configuration TOML existante :

```toml
[discovery_retention]
enabled = false
keep_days = 30
batch_size = 500
max_batches = 100
```

Aperçu : `nettracker prune-discovery --config config.toml`.
Les limites de cette section sont strictement typées ; les booléens ne sont pas
acceptés à la place des nombres. L'activation de `[retention]` pour les pings
n'autorise jamais la purge de découverte.

Suppression uniquement avec `discovery_retention.enabled=true` et l'option
`--apply`. Exemple destructif à ne lancer qu'après sauvegarde et vérification
de l'aperçu : `nettracker prune-discovery --config config.toml --apply`.
Aucune purge réelle n'a été lancée pendant la préparation de ce lot.

## Sécurité et limites

La base doit exister et son schéma doit correspondre à la version courante.
La commande ne crée pas de base et n'exécute aucune migration implicite.
L'aperçu ouvre SQLite avec `mode=ro` ; l'application utilise `mode=rw` sans
création. Les clés étrangères sont activées et le timeout de verrou est de 5 s.
La commande ne force pas un changement de mode de journalisation. SQLite peut
néanmoins utiliser ses fichiers auxiliaires ; aucune absence totale d'effet sur
le système de fichiers n'est promise. Les erreurs SQLite sont contrôlées.

L'aperçu des scans précède la suppression des observations : l'application peut
libérer davantage de scans. Les limites de lots, conservations et possibilités
de validation partielle décrites dans M3_DISCOVERY_RETENTION.md restent valables.
Aucun nettoyage automatique n'est ajouté au monitoring. Aucun paquet réseau.

## Vérification

Tests préparés avec les migrations réelles et des fichiers SQLite temporaires :
aperçu sans mutation, autorisation distincte, application et cible conservée,
base absente, schéma incompatible, corruption, valeurs par défaut et typage,
délégation des commandes existantes et aide racine.
Les tests d'intégration de ce lot n'ont pas été exécutés pendant la préparation.
Seules les vérifications syntaxiques et de longueur de ligne explicitement
rapportées ont été faites ; Ruff, mypy et CI Linux/Windows restent à vérifier.
Commande : `pytest tests/integration/test_discovery_prune_cli.py -q`.
Aucun test de charge, concurrence interprocessus, interruption réelle ou matériel.
