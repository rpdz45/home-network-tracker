# Tests

## Principes

- Aucun test n'émet de paquet réel. Tout accès réseau passe par une interface remplacable (scapy, nmap, ping).
- Les tests d'intégration utilisent un réseau simulé (conteneurs ou espaces de noms réseau) quand c'est faisable, sinon des fixtures de captures enregistrées et anonymisées.
- Objectif : au moins 80 % de couverture sur la logique métier (seuil appliqué par `fail_under` dans `pyproject.toml`).

## Lancer les tests

```bash
pytest --cov --cov-report=term-missing
```

Contrôles complémentaires : `ruff check .`, `ruff format --check .`, `mypy`, `bandit -r src`, `pip-audit`.

## Cas à couvrir (à partir de M1)

Timeout, permission refusée, IP qui change après renouvellement DHCP, doublons de MAC, IPv6, appareil qui disparaît puis revient, base verrouillée ou corrompue, adresses MAC privées ou aléatoires (statut « à confirmer »), refus de scanner hors `allowed_subnets`.

## Test terrain (propriétaire, à partir de M2)

Sur ton réseau uniquement, jamais sur un réseau professionnel sans accord écrit du service IT. Un hotspot de téléphone ou un réseau de machines virtuelles convient pour un test isolé.

1. Lancer en `dry-run`.
2. Comparer la liste découverte avec la liste d'appareils de la box.
3. Éteindre puis rallumer un appareil : les transitions sont détectées.
4. Connecter un appareil inconnu : l'alerte ou le statut « à confirmer » apparaît.
5. Laisser tourner 24 h : surveiller CPU, mémoire, taille de la base.
6. Redémarrer la machine : le service reprend seul.

## Retour de bug

Ouvre une issue `bug: ...` avec : OS et version, version de Python, commit (`git rev-parse --short HEAD`), commande exacte, extrait de config sans secrets, logs complets en niveau DEBUG, résultat attendu et obtenu.

## État du jalon M2

Testé hors ligne par la CI : garde-fous de périmètre, cache de voisins simulé, ARP actif simulé avec repli, persistance SQLite, fabricants OUI, résolution de noms injectée et dédoublonnage persistant des suggestions de rapprochement. Ces tests n’émettent aucun paquet réel.

Non testé sur matériel réel : Npcap sous Windows, `CAP_NET_RAW` ou root sous Linux/Raspberry Pi OS, comportement du résolveur DNS du propriétaire, cohérence avec la liste de la box et fonctionnement continu. Le premier lot M3 décrit ci-dessous ajoute des transitions ICMP simulées ; les alertes et la reprise automatique restent à livrer.


## Repli nmap M2

`tests/unit/test_nmap.py` remplace tous les sous-processus et utilise du XML fictif. Il couvre les refus de cible avant appel, le délai, les options fixes sans shell, les erreurs de processus, le XML malformé ou dangereux, les résultats hors cible, les doublons et les MAC absentes ou invalides. `tests/unit/test_strategy.py` couvre l’ordre des replis et l’absence de nmap sans opt-in.

`tests/integration/test_nmap_cli.py` raccorde CLI, stratégie et SQLite avec ARP et nmap simulés : transmission du délai, source dégradée, scan persisté en mode actif, statut `to_confirm` pour MAC locale et mode passif inchangé. Aucun scan réel n’est exécuté. La validation sur Windows/Npcap, Linux/Raspberry Pi et sur le réseau autorisé du propriétaire reste à réaliser.

## Liste blanche M2

`tests/unit/test_known_devices.py` vérifie le défaut vide, la normalisation, les doublons, les adresses invalides/nulles/multicast, les erreurs avant ouverture SQLite et le résumé sans MAC. `tests/integration/test_known_observations.py` vérifie les nouveaux appareils et les promotions, les statuts ignorés/fusionnés, le retrait sans révocation, la réouverture SQLite, le périmètre avec rollback, l’absence de précréation et l’absence de suggestions pour les appareils approuvés.

Le raccordement CLI est testé avec résultats ARP, nmap et cache simulés, DNS injecté et CSV OUI fictif. Aucun test ne lit le réseau du propriétaire ni ne lance de sonde réelle ; les backends ne sont pas validés sur matériel. Pour vérifier seulement la configuration locale sans scan : `nettracker check-config --config config.toml`. La sortie attendue contient le nombre de MAC configurées, jamais leur liste.

## Identifiants pytest et Windows

Les paramètres volumineux doivent avoir des identifiants courts et explicites (`ids=`).
Sans identifiant explicite, pytest peut intégrer toute une chaîne XML dans le nom du test,
puis dans la variable d'environnement `PYTEST_CURRENT_TEST`. Le cas de dépassement de
la limite XML conservait ainsi plus d'un million de caractères dans cet identifiant.
Cela dépasse la limite Windows d'une variable d'environnement et gonfle les journaux.
Ce défaut est une cause probable de l'échec Windows de la PR #11 ; les journaux détaillés
du job initial n'ont pas pu être récupérés et les 144 minutes ne sont pas reproduites localement.
Les six cas de XML invalide gardent leurs charges utiles et leurs assertions de rejet ;
ils vérifient aussi que leur identifiant reste inférieur à 200 caractères.

La CI lance pytest en mode détaillé avec les 15 durées les plus longues. L'étape pytest
est limitée à 5 minutes et le job qualité à 15 minutes : un blocage échoue rapidement,
sans désactiver de test ni réduire le seuil de couverture.

Reproduction hors ligne :

```bash
pytest tests/unit/test_nmap.py -k invalid_or_unsafe_xml -vv
pytest -vv --durations=15 --cov --cov-report=term-missing
```

La validation locale Linux ne remplace pas le contrôle `windows-latest` de la PR.
Aucun scan, appel DNS réel ou test sur le LAN n'est nécessaire pour ce correctif.

Références : [pytest et `PYTEST_CURRENT_TEST`](https://doc.pytest.org/en/6.2.x/example/simple.html#pytest-current-test-environment-variable),
[limite Windows des variables d'environnement](https://support.microsoft.com/en-gb/help/830473/command-prom).

Validation du correctif sous Linux : 207 tests réussis, couverture totale 95,23 % ;
Ruff, formatage, mypy et Bandit réussis. L'audit initial signalait l'ancien pip de
l'environnement temporaire ; après mise à jour de pip et setuptools comme dans la CI,
`pip-audit` ne signale plus de vulnérabilité connue (paquet local non auditable sur PyPI).
Aucun test n'est désactivé et le seuil de couverture reste à 80 %.

## M3 : premier cycle ICMP

`tests/unit/test_ping.py` remplace tous les sous-processus ;
`tests/integration/test_monitoring.py` utilise une horloge et des sondes simulées
avec SQLite temporaire. Cas : double consentement, périmètre, Linux/Windows, erreurs,
latence/perte, transitions et idempotence, DHCP, conflits IP, observation périmée,
SIGINT, concurrence, verrouillage et migration additive. Aucun paquet ICMP réel.
Voir [M3_MONITORING.md](M3_MONITORING.md) pour les commandes de test et ce qui reste
non vérifié sur matériel réel. Le jalon M3 n'est pas terminé : ordonnanceur,
rétention, suivi prolongé et santé du collecteur restent à implémenter.
