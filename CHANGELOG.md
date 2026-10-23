# Changelog

Format inspiré de [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Versionnage sémantique.

## [Non publié]

### Ajouté
- M5 (lot 1) : tableau de bord web local **en lecture seule** (`nettracker serve`) : liste des appareils avec bloc santé du collecteur, fiche d'un appareil, événements récents avec statut des alertes. Écoute sur 127.0.0.1 par défaut ; avec un jeton, toutes les pages l'exigent (Bearer ou cookie `HttpOnly` / `SameSite=Strict` via `/login`), comparaison en temps constant. Connexion SQLite `query_only`, CSP stricte, échappement HTML, pas de `/docs`. Aucune migration, aucun JavaScript.
- M4 (lot 2) : une alerte `offline` n'est examinée qu'après `alerts.offline_after_minutes` (5, 0 = immédiat) et est annulée (`suppressed`, `recovered`) si un `online` plus récent existe pour le même appareil. Détection de latence soutenue : `process-alerts` crée un événement `latency_high` quand la moyenne des 3 derniers pings ayant répondu dépasse `alerts.latency_high_ms` (200), une seule fois par épisode. Aucune migration, aucun accès réseau.
- M4 (lot 1) : moteur d'alertes sans envoi réseau. Commande `process-alerts` : enregistre une ligne `notifications` par événement alertable (`new_device`, `collector_stale`, `offline`, `latency_high`, `merge_suggested`), en `dry_run` par défaut, avec anti-spam par type et appareil (`alerts.cooldown_minutes`, 30) et limite par exécution (`alerts.max_events_per_run`, 200). `to_confirm` et `online` n'alertent pas. Le mode réel exige des notifiers (pas encore livrés).
- M3 : commande `health-check` : dernier scan réussi, ancienneté, problèmes récents ; code de sortie 3 si le collecteur est périmé. Enregistre un événement `collector_stale` une seule fois par panne (réarmé par un scan réussi), sans notification ni migration. Section `[health]` (`stale_after_minutes`, défaut 15).
- M3 : commande `prune-history` : aperçu en lecture seule par défaut ; suppression réelle seulement avec `retention.enabled=true` **et** `--apply`. Seuls les échantillons ping sont supprimés (lots bornés, une transaction par lot) ; appareils, observations de découverte, états, événements et notifications ne sont jamais touchés.
- M3 : section de configuration `[retention]` validée (`enabled`, `keep_days`, `batch_size`, `max_batches`), désactivée par défaut ; résumé affiché par `check-config`.
- M3 : cycle ICMP explicite `monitor-once` (double opt-in `monitor.enabled` + `--enable-monitoring`) et migration SQLite V2 additive (`sightings.source`, `monitor_state`).
- M2 : découverte passive (cache de voisins), ARP actif explicitement autorisé, repli nmap optionnel, fabricants OUI locaux, DNS inverse et mDNS ciblé en opt-in, liste blanche `known_devices`, suggestions prudentes pour MAC aléatoires.
- M1 : configuration TOML validée (`allowed_subnets` limité aux plages privées RFC 1918 de préfixe /16 ou plus long, API sur loopback sauf jeton), surcharge par variables d'environnement et `.env`.
- M1 : schéma SQLite v1 versionné avec migrations transactionnelles (`src/nettracker/db/migrations.py`, identique au schéma de `docs/ARCHITECTURE.md`).
- M1 : couche repository typée et idempotente (appareils, scans, observations, événements, notifications), horodatages UTC obligatoires, MAC normalisées.
- M1 : CLI `nettracker` avec `--help`, `--version`, `check-config` et `init-db`.
- M1 : `config.example.toml`.
- M0 : structure du dépôt, outillage qualité (ruff, mypy, pytest, bandit, pip-audit, gitleaks), CI Linux et Windows, documentation d'architecture, de sécurité et de test.

### Modifié
- CI : permission `pull-requests: read` pour gitleaks et mise à jour de `setuptools` avant `pip-audit`.
