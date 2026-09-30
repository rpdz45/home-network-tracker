# Home Network Tracker

Outil local de suivi du réseau domestique : découverte des appareils, suivi de disponibilité (latence, perte de paquets), détection des appareils inconnus et dashboard web local. Toutes les données restent sur ta machine (SQLite).

> **Statut : jalon M0 (fondations).** Le dépôt contient la structure, l'outillage et la CI. Aucune fonctionnalité réseau n'est encore implémentée. Voir la feuille de route dans `AGENTS.md` (section 8).

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

## Configuration

Copie `.env.example` vers `.env` et renseigne uniquement les canaux de notification utilisés. Le fichier `.env` est ignoré par Git. Les paramètres métier (`allowed_subnets`, mode passif ou actif, etc.) arrivent avec M1.

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
- [docs/SECURITY.md](docs/SECURITY.md)
- [docs/TESTING.md](docs/TESTING.md)
- [AGENTS.md](AGENTS.md) : règles de travail pour les agents IA

## Licence

MIT, voir [LICENSE](LICENSE).
