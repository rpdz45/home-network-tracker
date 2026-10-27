# M3 — Rétention ping optionnelle dans la boucle

## Décision et activation

Rôle : développeur, QA, sécurité et documentation. La boucle conserve son
comportement et son résumé habituels sans `--prune-ping`. Aucune purge à l'import.
L'option exige aussi `retention.enabled=true`, sinon refus avant ouverture de la
base ou sonde. Les activations du monitoring restent obligatoires et inchangées.

`--prune-every-cycles N` choisit une cadence de 1 à 1 000 000 cycles réussis,
100 par défaut. Cette option seule est refusée. La première purge intervient
après N cycles réussis, jamais au démarrage. Pas de purge finale supplémentaire
si le nombre de cycles n'est pas un multiple de N. Une mesure idempotente peut
retourner zéro : un cycle terminé sans erreur compte néanmoins pour la cadence.

## Suppressions et limites

Chaque passage réutilise `prune_ping_samples`, avec `retention.keep_days` et
`retention.batch_size`, mais impose **un seul lot**, même si `retention.max_batches`
est supérieur à un. Au plus 5 000 lignes par passage selon la borne existante de
configuration. Cela réduit le travail entre deux cycles ; aucun rattrapage non
borné. La cadence compte des cycles, pas un temps mural fixe.

Attention : purge de tous les anciens pings de la base, pas seulement de ceux des
appareils sélectionnés. Seules les lignes `source='ping'` strictement antérieures
au seuil sont supprimées ; l'échantillon exactement au seuil reste présent.
Appareils, découvertes, scans, états courants, événements et notifications sont
préservés. La fonction SQL de purge et le schéma ne sont pas modifiés.

Le seuil utilise l'heure UTC courante, après le cycle. Une horloge système erronée
peut donc modifier ce qui est considéré ancien. La purge commence seulement après
le retour réussi du monitoring, hors transaction ouverte, sans sonde ni attente
réseau sous son verrou. Un arrêt demandé avant la purge empêche son lancement.
Un SIGTERM pendant le lot ne l'interrompt pas : la fin de ce lot borné est attendue.

Un échec du rafraîchissement ou du monitoring empêche la purge correspondante.
Une erreur de purge arrête la boucle avec le code 2. Les mesures déjà validées
restent enregistrées : elles ne partagent pas la transaction de suppression.
Le handler SIGTERM est restauré en sortie. Pas de réessai automatique.
Avec l'option, le résumé ajoute `pruned_ping_samples=N` lors d'une sortie gérée
par le résultat de boucle ; en cas d'erreur, le résumé habituel d'erreur reste utilisé.

## Exemple destructif, uniquement après revue et sauvegarde

La configuration doit déjà être validée, la base initialisée et sauvegardée,
les IDs choisis explicitement et `monitor.enabled` / `retention.enabled` activés.
La commande suivante peut envoyer des pings et supprimer définitivement des
anciens pings. Elle n'a pas été exécutée sur le poste du propriétaire.

```text
python -m nettracker.monitor.loop --config config.toml --device-id 1 --enable-monitoring --refresh-passive --cycles 3 --prune-ping --prune-every-cycles 1
```

La commande autonome `prune-history` conserve son aperçu par défaut et son
activation `--apply`. Ici, `--prune-ping` est l'autorisation de suppression propre
à la boucle ; aucune suppression de découverte n'est ajoutée. La base complète
peut donc encore croître. Ni taille disque maximale ni clôture de M3 garanties.

## Vérification

Tests proposés sur migrations réelles dans une base temporaire, transports et
horloges injectés : comportement par défaut, refus sans autorisation de config,
cadence avant I/O, lot unique, seuil strict et tables protégées, erreurs de suivi,
rafraîchissement et purge, arrêt avant purge et restauration du handler.
Aucun paquet réel ou secret de configuration utilisé dans les tests.

Syntaxe AST, compilation et longueurs de lignes Python vérifiées pendant la
préparation. Les tests d'intégration du paquet complet, Ruff, mypy, couverture et
audits restent à valider en CI Linux/Windows ; aucun succès non exécuté annoncé.
Les contrôles isolés éventuels avec dépendances remplacées ne valent pas une
validation du paquet complet, de la portée réseau ou du monitoring réel.

```text
pytest tests/integration/test_loop_ping_retention.py tests/integration/test_monitor_loop.py tests/unit/test_monitor_loop.py -vv
```
