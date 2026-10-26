# M3 — Profilage hors ligne de ressources

## Utilisation et sécurité

Après installation du paquet :

```sh
python -m nettracker.resource_profile --cycles 1000 --warmup 1500
```

L'outil ne lit ni config.toml ni .env et n'accepte aucun chemin de base ou cible.
Il crée sa propre base SQLite dans un nouveau répertoire temporaire, avec les
migrations du projet. Un seul appareil fictif est suivi ; cache, sondes et attentes
sont injectés, sans paquet réseau. La base et son répertoire sont supprimés à la
sortie normale ou lors des exceptions gérées. Une interruption brutale du processus
peut laisser des fichiers temporaires : aucune garantie de nettoyage après crash.

Le module ne démarre rien lors d'un simple import. Il ne modifie ni la CLI installée
ni le monitoring de production. Exécuter ce diagnostic dans un processus dédié ;
le contrôle de tracemalloc global n'est pas une synchronisation entre threads.
Une session tracemalloc déjà active est refusée sans être arrêtée ou remplacée.

## Ce qui est mesuré

Après l'échauffement, deux fenêtres de même longueur produisent un rapport JSON.
Les valeurs par défaut exécutent 1 500 cycles d'échauffement puis 1 000 par fenêtre,
soit 3 500 cycles fictifs. Chaque paramètre est limité à 1–5 000 entiers non booléens.
L'horloge métier avance d'une minute par cycle ; aucune attente réelle de minute.
Le profil prend néanmoins du temps CPU et fait des écritures sur disque temporaire.

Le rapport indique version Python, plateforme, nombre de cycles, temps écoulé et
CPU, allocations Python suivies avant/après GC, delta et pic par fenêtre, nombres
d'observations, pings et scans, et tailles des fichiers principal et WAL avant leur
fermeture. GC et instrumentation contribuent aux coûts mesurés. Les requêtes de
comptage et les relevés de taille viennent après la mesure de temps et de mémoire.
Les tailles peuvent changer lors de la fermeture ou d'un checkpoint SQLite.

La rétention d'un jour est appliquée dans ce scénario tous les 100 cycles et en fin
de phase ; elle n'est pas ajoutée à la boucle de production. Les tailles physiques
ne suivent pas nécessairement le nombre de lignes et ne sont pas plafonnées.

## Limites et validation

Le champ memory_scope vaut tracemalloc-python-not-rss. Ce n'est pas la mémoire RSS,
ni la totalité des allocations natives de SQLite ou d'autres bibliothèques. Un delta
peut être négatif. Aucun seuil automatique de fuite ou de performance n'est imposé.
Le profil porte sur un appareil toujours joignable, sans DHCP, transport réel,
alertes, charge multiple, crash ou endurance réelle de 24 heures. M3 reste ouvert.

Huit cas pytest préparés : deux petites fenêtres et nettoyage, quatre limites
invalides, trace préexistante préservée, erreur d'ouverture nettoyée et JSON CLI.
Le fichier applicatif et le fichier de tests passent ici syntaxe AST, compilation
et contrôle des lignes à 100 caractères. Le paquet nettracker et Ruff ne sont pas
installés dans cet environnement : ni pytest, ni Ruff, ni mypy, ni ce profil complet
n'ont été exécutés pendant la préparation. Aucun chiffre de performance annoncé.
Validation attendue en CI : `pytest tests/unit/test_resource_profile.py -vv`, puis
les contrôles Linux/Windows complets. Les tests utilisent seulement de petites phases.
