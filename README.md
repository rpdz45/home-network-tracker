# Home Network Tracker

Outil local de suivi du réseau domestique : découverte des appareils, suivi de disponibilité (latence, perte de paquets), détection des appareils inconnus et dashboard web local. Toutes les données restent sur ta machine (SQLite).

> **Statut : jalon M1 (données et configuration).** La configuration, la base SQLite et la CLI de base fonctionnent. La découverte réseau (M2), le suivi (M3), les alertes (M4) et le dashboard (M5) ne sont pas encore implémentés. Voir la feuille de route dans `AGENTS.md` (section 8).

## Avertissement

Ne scanne que **tes propres réseaux**. N'utilise jamais cet outil sur un réseau professionnel sans accord écrit du service IT. Voir [docs/SECURITY.md](docs/SECURITY.md).

## Prérequis

- Python 3.11 ou plus.
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

## Commandes

```bash
nettracker --help
nettracker --version
nettracker check-config [--config CHEMIN]
nettracker init-db [--config CHEMIN]
```

`init-db` crée ou met à jour le schéma SQLite ; il peut être relancé sans risque.

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
- [AGENTS.md](AGENTS.md) : règles de travail pour les agents IA

## Licence

MIT, voir [LICENSE](LICENSE).
