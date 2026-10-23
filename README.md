# Home Network Tracker

Outil local de suivi du réseau domestique : découverte des appareils, suivi de disponibilité (latence, perte de paquets), détection des appareils inconnus et dashboard web local. Toutes les données restent sur ta machine (SQLite).

> **Statut : découverte M2, premier lot de suivi M3, rétention, santé du collecteur et premier lot d'alertes M4 disponibles.** La configuration, SQLite, la découverte passive, l’ARP actif explicitement autorisé, le repli nmap optionnel et borné, les fabricants OUI locaux, la résolution DNS inverse / mDNS optionnelle, les suggestions prudentes pour MAC aléatoires et la liste blanche `known_devices` fonctionnent. Le cycle ICMP explicite `monitor-once`, `prune-history` (aperçu par défaut, suppression en double opt-in), `health-check` et `process-alerts` (dry-run, anti-spam, aucun envoi) sont disponibles. Le suivi périodique (reste de M3), les notifiers Discord / Telegram / e-mail et les règles d'alertes avancées (reste de M4) et le dashboard (M5) ne sont pas encore implémentés. Voir la feuille de route dans `AGENTS.md` (section 8).

## Avertissement

Ne scanne que **tes propres réseaux**. N'utilise jamais cet outil sur un réseau professionnel sans accord écrit du service IT. Voir [docs/SECURITY.md](docs/SECURITY.md).

## Prérequis

- Python 3.11 ou plus.
- Facultatif : binaire `nmap` installé et disponible dans le `PATH` pour le repli actif explicitement activé.
- Windows : Npcap sera requis pour l'ARP brut (scapy) à partir de M2.
- Linux / Raspberry Pi OS : root ou la capacité `CAP_NET_RAW` sera requis pour l'ARP brut à partir de M2.

## Installation pour le développement

Linux / Raspberry Pi OS / macOS :

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pre-commit install
```

Windows (PowerShell) :

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pre-commit install
```

L'installation utilisateur par OS (service, Docker, tâche planifiée) sera documentée au jalon M6.

## Configuration

1. Copie `config.example.toml` vers `config.toml` et adapte `allowed_subnets` à ton réseau. Seules les plages privées RFC 1918 (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) de préfixe /16 ou plus long sont acceptées.
2. Si besoin, copie `.env.example` vers `.env` pour les secrets (jeton d'API, webhooks). `config.toml` et `.env` sont ignorés par Git.
3. Vérifie la configuration :

```bash
nettracker check-config
```

Valeurs par défaut prudentes : mode passif, alertes en `dry-run`, API sur `127.0.0.1`. Toute écoute hors loopback exige un jeton (`NETTRACKER_API_TOKEN`). Le fichier de config se choisit avec `--config` ou la variable `NETTRACKER_CONFIG`. Priorité pour le jeton, le chemin de base et le niveau de log : variables d'environnement, puis `.env`, puis `config.toml`.

## Appareils connus

Au niveau racine de `config.toml` (avant `[scan]`), `known_devices = []` est vide par défaut. Tu peux y inscrire explicitement des MAC : `known_devices = ["00:11:22:33:44:55"]` (exemple fictif). `nettracker check-config` valide les entrées et affiche leur nombre sans énumérer les MAC. Les majuscules et tirets sont normalisés ; doublons, multicast, broadcast et MAC nulle sont refusés.

Seul un appareil réellement observé dans `allowed_subnets` est alors marqué `known`, sans événement de nouvel inconnu ni de confirmation. La liste ne lance aucun scan, ne précrée aucun appareil et ne remplace pas le contrôle de périmètre. Les statuts ignorés et les fusions manuelles restent prioritaires. Retirer une entrée ne révoque pas le statut `known` déjà enregistré : il faut le reclasser explicitement ; aucune commande utilisateur de révocation n’est encore livrée. Une MAC peut être usurpée : cette liste n’est pas une authentification.

## Commandes

```bash
nettracker --help
nettracker --version
nettracker check-config [--config CHEMIN]
nettracker init-db [--config CHEMIN]
nettracker scan-once [--config CHEMIN] [--resolve-names] [--resolve-mdns] [--oui-file CHEMIN]
nettracker monitor-once [--config CHEMIN] --device-id ID [--device-id ID] --enable-monitoring
nettracker prune-history [--config CHEMIN] [--apply]
nettracker health-check [--config CHEMIN]
nettracker process-alerts [--config CHEMIN]
```

`init-db` crée ou met à jour le schéma SQLite ; il peut être relancé sans risque. `scan-once` lit le cache de voisins par défaut. La résolution DNS inverse reste désactivée sans `--resolve-names` et peut émettre des requêtes via le résolveur système. Le mode ARP actif exige en plus `scan.mode = "active"`, `--enable-active` et une cible `--target` explicitement autorisée. Le repli nmap reste désactivé sans `scan.nmap_fallback = true` ; il ne sert qu’après un échec de l’ARP brut et conserve les mêmes garde-fous de cible. Voir [docs/M2_PASSIVE.md](docs/M2_PASSIVE.md).

## Commandes qualité

```bash
ruff check .
ruff format --check .
mypy
pytest --cov
bandit -r src
pip-audit
```

La CI GitHub exécute les mêmes contrôles sur Linux et Windows.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/SECURITY.md](docs/SECURITY.md)
- [docs/TESTING.md](docs/TESTING.md)
- [docs/M2_PASSIVE.md](docs/M2_PASSIVE.md)
- [docs/M3_MONITORING.md](docs/M3_MONITORING.md)
- [docs/M3_HEALTH.md](docs/M3_HEALTH.md)
- [docs/M4_ALERTS.md](docs/M4_ALERTS.md)
- [AGENTS.md](AGENTS.md) : règles de travail pour les agents IA

## Licence

MIT, voir [LICENSE](LICENSE).


## Noms mDNS ciblés (M2)

Voir [architecture, sécurité et tests mDNS](docs/MDNS.md).

Par défaut, aucune requête mDNS n'est émise. Deux accords sont nécessaires :
`mdns_enabled = true` dans la table `[scan]` de votre configuration et le drapeau
`--resolve-mdns` lors de l'exécution. Le délai par appareil se règle avec
`mdns_timeout_seconds` (1 seconde par défaut, entre 0,1 et 5 secondes).

```toml
[scan]
mode = "passive"
mdns_enabled = true
mdns_timeout_seconds = 1.0
```

```bash
nettracker scan-once --config config.toml --resolve-mdns
```

**Cette commande n'est plus entièrement passive** : elle lit le cache de voisins,
puis adresse une seule requête PTR UDP au port 5353 de chaque IPv4 observée et
autorisée par `allowed_subnets`. Le cycle est enregistré comme `active` dans SQLite,
y compris après un repli ARP/nmap vers le cache système. Aucun balayage supplémentaire,
parcours DNS-SD de services, envoi multicast, repli TCP ou recours au DNS système
n'est effectué par le backend mDNS. Aucun droit root/admin n'est demandé pour ce
socket UDP ; le pare-feu peut néanmoins le bloquer.

Seuls les noms `.local` valides des réponses PTR correspondant à l'IPv4 interrogée
sont retenus. Une absence de réponse, un refus de permission, une réponse ambiguë
ou malformée laisse le nom inconnu, sans perdre l'observation de l'appareil.
Le nom est un indice non authentifié : il n'accorde aucune confiance ni fusion
automatique aux appareils, notamment ceux à MAC aléatoire.

Si les deux drapeaux `--resolve-mdns --resolve-names` sont présents, mDNS est essayé
en premier, puis le DNS inverse système seulement en l'absence de nom mDNS. Le DNS
système peut contacter un résolveur hors du LAN ; ne pas ajouter `--resolve-names`
si vous souhaitez éviter cet accès.

**Limites et test terrain** : le choix des requêtes directes unicast peut manquer
les appareils n'acceptant que le multicast ou ne publiant pas de PTR inverse. IPv6,
l'écoute continue et la découverte de services ne sont pas implémentées. Le délai
total peut atteindre le nombre d'IPv4 observées multiplié par le délai configuré.
La commande ci-dessus est à lancer uniquement sur votre réseau ; aucune validation
sur matériel réel n'a été réalisée pour ce lot.

## Premier suivi ICMP (M3)

`monitor-once` mesure la joignabilité ICMP des seuls appareils sélectionnés, avec
`monitor.enabled=true` **et** `--enable-monitoring`. Le suivi est désactivé par défaut ;
les IPv4 doivent être privées, autorisées et récemment découvertes. Les mesures de
latence/perte et les transitions sont locales dans SQLite (migration V2 additive).
Une non-réponse n'est pas une preuve de déconnexion : un pare-feu peut bloquer ICMP.
Voir [docs/M3_MONITORING.md](docs/M3_MONITORING.md) pour configuration, commandes,
droits système, tests simulés et limites. Pas encore de planification ; aucune
validation sur réseau ou matériel réel n'a été effectuée pour ce lot.

## Rétention de l'historique (M3)

`prune-history` supprime les anciens échantillons ping (latence / perte de paquets) pour éviter que la base grossisse indéfiniment. Seules les lignes `sightings` dont la source est `ping` sont concernées : appareils, observations de découverte, états courants, événements et notifications ne sont jamais supprimés.

```toml
[retention]
enabled = false     # doit passer à true pour autoriser la suppression
keep_days = 30      # échantillons strictement plus vieux que N jours (1 à 3650)
batch_size = 500    # lignes par transaction (1 à 5000)
max_batches = 100   # lots maximum par exécution (1 à 1000)
```

```bash
# Aperçu en lecture seule (comportement par défaut) : rien n'est modifié
nettracker prune-history --config config.toml

# Suppression réelle : exige retention.enabled = true ET --apply
nettracker prune-history --config config.toml --apply
```

Sans `retention.enabled = true`, `--apply` est refusé avec un message d'erreur. Une exécution supprime au plus `batch_size × max_batches` lignes ; relance la commande si l'aperçu en annonce davantage. Pas de planification automatique (cron / service : lot ultérieur). Sauvegarde ta base avant la première suppression réelle. Aucune validation sur matériel réel n'a été effectuée pour ce lot ; seuls les tests unitaires le couvrent.

## Santé du collecteur (M3)

`health-check` indique si la découverte tourne encore : date du dernier `scan-once` réussi, ancienneté, derniers échecs. Au-delà de `health.stale_after_minutes` (15 par défaut) sans scan réussi, il enregistre un événement `collector_stale` **une seule fois par panne** et rend le code de sortie 3.

```bash
nettracker health-check --config config.toml
```

La commande n'envoie aucune notification (alertes : M4) et ne tourne pas toute seule : planifie-la toi-même. Voir [docs/M3_HEALTH.md](docs/M3_HEALTH.md) pour le fonctionnement, les limites et les tests. Aucune validation sur matériel réel n'a été effectuée pour ce lot.

## Alertes (M4, lot 1)

`process-alerts` transforme les événements déjà enregistrés (nouvel appareil, collecteur périmé, hors ligne, latence, fusion suggérée) en lignes `notifications`, avec un anti-spam par type et appareil (`alerts.cooldown_minutes`, 30 minutes par défaut). Les appareils à MAC aléatoire en attente de confirmation (`to_confirm`) ne déclenchent jamais d'alerte.

```bash
nettracker process-alerts --config config.toml
```

**Rien n'est envoyé** : tant que `alerts.dry_run = true` (défaut), la commande enregistre seulement des lignes `dry_run`, et le mode réel est refusé car aucun notifier (Discord, Telegram, e-mail) n'est encore livré. La commande est relançable sans doublon et ne tourne pas toute seule. Voir [docs/M4_ALERTS.md](docs/M4_ALERTS.md). Aucune validation sur matériel réel n'a été effectuée pour ce lot.
