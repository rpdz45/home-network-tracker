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

Non testé sur matériel réel : Npcap sous Windows, `CAP_NET_RAW` ou root sous Linux/Raspberry Pi OS, comportement du résolveur DNS du propriétaire, cohérence avec la liste de la box et fonctionnement continu. Les transitions en ligne/hors ligne, les alertes et la reprise automatique appartiennent aux jalons suivants.
