# M3 — Validation simulée multi-appareils

## Périmètre

Rôle : QA, puis sécurité et documentation. Ce lot ajoute uniquement
`tests/integration/test_monitor_multi_device.py` et ce guide. Il ne modifie ni
code applicatif, configuration, migrations, rétention de production, ni CI.
Il complète les tests mono-appareil et les tests de refus de lots existants.

Les scénarios utilisent les migrations réelles sur SQLite en mémoire, les vrais
`refresh_selected`, `monitor_once`, `run_periodic` et les fonctions de rétention.
Lecteur de voisins, sondes et horloge sont injectés ; aucune attente réelle.
Les backends réels et le chargement de configuration utilisateur sont bloqués.
Les IP et MAC sont inventées : elles ne représentent pas le réseau du propriétaire.
Aucun paramètre LAN réel n'est choisi et aucune commande terrain n'est lancée.

## Cinq cas préparés, résultats attendus

### Série prolongée : séparation des historiques

Trois appareils sélectionnés et un quatrième présent dans le cache mais exclu du
suivi. Une sélection contient volontairement un ID répété pour exercer le
dédoublonnage. 2 000 cycles espacés de 60 secondes simulées, soit 6 000 sondes
injectées et 1 999 minutes entre le premier et le dernier cycle.

Le premier appareil change d'IP après 1 000 cycles ; les deux autres restent sur
leurs adresses. Tous restent joignables, sans faux événement de transition au
changement d'IP. La purge est explicitement appelée par le scénario tous les
100 cycles, avec conservation d'un jour, lots de 100 et dix lots au maximum.

Après la dernière purge : 4 323 découvertes, 4 323 pings et 1 441 scans attendus.
Pour le premier appareil : 441 pings sur l'ancienne IP et 1 000 sur la nouvelle ;
pour chacun des deux autres : 1 441 pings. Une purge répétée ne supprime rien.
Les cibles et états de monitoring doivent survivre à chaque purge.

### Transitions indépendantes

Quatre cycles avec des réponses différentes selon l'appareil. Les cinq transitions
attendues sont rattachées aux bons IDs, dans l'ordre ; chaque historique conserve
ses propres adresses et réponses. Douze sondes et douze mesures sont attendues,
malgré l'ID sélectionné en double.

### Cache invalide au cycle suivant : trois cas paramétrés

Après un premier cycle réussi, un appareil manque, deux appareils partagent une
IP ou une cible passe hors du sous-réseau autorisé. Le rafraîchissement doit
refuser avant toute nouvelle sonde ou écriture partielle de découverte. Les
mesures, cibles et états du premier cycle restent inchangés.

Dans tous les scénarios, le quatrième appareil reste sans observation ni état de
monitoring ; les quatre statuts connus sont préservés, les clés étrangères restent
cohérentes et aucune transaction n'est laissée ouverte après les opérations.

## Validation et limites

Les résultats ci-dessus sont des assertions proposées, pas des résultats acquis.
Syntaxe AST, compilation et limite de 100 caractères des lignes Python vérifiées
pendant la préparation. Les tests du paquet complet n'ont pas été exécutés dans
cet environnement. Ruff, mypy, couverture et audits restent à vérifier en CI
Linux/Windows. Aucun succès non exécuté ni mesure de performance n'est annoncé.

```text
pytest tests/integration/test_monitor_multi_device.py tests/integration/test_monitor_soak.py tests/integration/test_monitoring.py -vv
```

Ce lot ne mesure ni RSS, fuite mémoire, CPU, WAL sur disque, charge réelle,
endurance réelle de 24 heures, installation en service ou authentification MAC.
Il ne clôt pas M3 et ne remplace pas la validation sur matériel du propriétaire.
