# M3 — Validation prolongée simulée du suivi et de la rétention

## Périmètre

Ce lot ajoute uniquement tests/integration/test_monitor_soak.py et ce guide.
Aucun changement applicatif, de configuration ou de CI. Aucune planification
supplémentaire de purge n'est ajoutée à la boucle de production.
Rôle : QA, puis sécurité et documentation.

Les scénarios composent run_periodic, refresh_selected, monitor_once, la santé du
collecteur et les rétentions ping/découverte sur SQLite en mémoire, avec les
migrations réelles. Les horloges, attentes, voisins et sondes sont injectés.
Les backends réels cache et ping sont bloqués dans la fixture. Aucun réseau du
propriétaire, fichier de base réel, matériel ou temps d'attente réel utilisé.

## Résultats attendus, pas encore exécutés

- 2 000 cycles espacés de 60 secondes simulées, soit 1 999 minutes écoulées entre
  le premier et le dernier cycle. Changement d'IP après les 1 000 premiers cycles.
- Purge explicite dans le scénario tous les 100 cycles, puis nouvelle exécution
  finale pour vérifier la stabilité. Conservation d'un jour, lots de 100 lignes,
  au plus 10 lots par table et appel.
- Après purge, exactement 1 441 observations de découverte, 1 441 mesures ping et
  1 441 scans ; seuil strict, donc l'échantillon exactement à un jour reste présent.
  Les compteurs attendent 559 suppressions pour chacun de ces trois ensembles.
- Les pings conservés se répartissent entre 441 sur l'ancienne IP et 1 000 sur
  la nouvelle. Un appareil et un état de monitoring, cible et santé préservées
  par chaque purge ; intégrité des clés étrangères vérifiée.
- Trois cas de refus au second cycle : appareil absent, IP avec deux MAC et erreur
  du lecteur. Le premier cycle reste enregistré, aucune ancienne cible réutilisée.
- Scénario en ligne / hors ligne / en ligne, avec sauts simulés de deux jours :
  les événements de transition restent corrects malgré la purge des mesures passées.

Cela représente trois fonctions et cinq cas pytest attendus avec le paramétrage.
La syntaxe Python et la limite de 100 caractères par ligne ont été vérifiées
pendant la préparation. La suite pytest proposée n'a pas été exécutée ici.
Ruff n'est pas installé dans cet environnement de préparation ; son formatage,
mypy, la couverture et les audits restent à vérifier en CI Linux et Windows.

```sh
pytest tests/integration/test_monitor_soak.py -vv --durations=5
```

## Ce que ces tests ne prouvent pas

Ce n'est pas une endurance réelle de 24 heures, ni une mesure de fuite mémoire,
de CPU ou de disque. SQLite est en mémoire : ni WAL sur disque, fsync, reprise
après crash, verrou interprocessus ou installation du script ne sont exercés.
Les tables events et notifications ne font pas l'objet d'une nouvelle politique
de rétention. Aucune taille maximale de la base complète n'est garantie.

Les limites du cache passif demeurent : une association relue peut être ancienne,
statique ou usurpée et le ping n'authentifie pas une MAC. Un seul appareil est
suivi dans le scénario prolongé ; aucune charge multi-appareils n'est simulée.
M3 reste ouvert tant que ses critères restants et la validation terrain ne sont
pas documentés avec leurs résultats réels ; ce lot ne déclare pas sa clôture.
