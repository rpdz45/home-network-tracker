# Changelog

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Versionnage sémantique.

## [Non publié]

### Ajouté
- M1 : configuration TOML validée (`allowed_subnets` limité aux plages privées RFC 1918 de préfixe /16 ou plus long, API sur loopback sauf jeton), surcharge par variables d'environnement et `.env`.
- M1 : schéma SQLite v1 versionné avec migrations transactionnelles (`src/nettracker/db/migrations.py`, identique au schéma de `docs/ARCHITECTURE.md`).
- M1 : couche repository typée et idempotente (appareils, scans, observations, événements, notifications), horodatages UTC obligatoires, MAC normalisées.
- M1 : CLI `nettracker` avec `--help`, `--version`, `check-config` et `init-db`.
- M1 : `config.example.toml`.
- M0 : structure du dépôt, outillage qualité (ruff, mypy, pytest, bandit, pip-audit, gitleaks), CI Linux et Windows, documentation d'architecture, de sécurité et de test.

### Modifié
- CI : permission `pull-requests: read` pour gitleaks et mise à jour de `setuptools` avant `pip-audit`.
