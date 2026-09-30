# Architecture

Document de conception du jalon M0. Aucune logique métier n'est encore écrite ; ce document fixe les composants, les flux, le schéma de données et les choix structurants.

## 1. Vue d'ensemble

```
            +-----------------+
            |   CLI / service |  nettracker run | status | ...
            +--------+--------+
                     |
   +-----------------+------------------+
   |                                    |
+--v-----------+                 +------v------+
|  Collecteur  |                 |  API + Web  |  FastAPI, 127.0.0.1 par défaut
| discovery/   |                 |  api/ web/  |
| monitor/     |                 +------^------+
+--+-----------+                        |
   |   événements              lecture    |
   |                                    |
+--v-----------+   écriture      +------+------+
|   alerts/    +----------------> SQLite (db/)  |
| règles +     |                 +-------------+
| notifiers    |
+--------------+
```

Le collecteur et l'API sont deux processus logiques qui ne communiquent que par la base SQLite. L'API ne scanne jamais.

## 2. Composants

| Module | Rôle | Droits |
|---|---|---|
| `config.py` | Charge et valide la config (TOML + variables d'environnement), dont `allowed_subnets` | Aucun |
| `db/` | Schéma, migrations simples, repository | Aucun |
| `discovery/` | Table ARP système (passif), balayage ARP (scapy), repli `nmap -sn`, fabricant OUI, noms (DNS inverse, mDNS) | Seul le module ARP brut exige root/admin |
| `monitor/` | Ping périodique, latence, perte, détection des transitions en ligne / hors ligne | Aucun |
| `alerts/` | Règles, anti-spam, notifiers Discord, Telegram, e-mail, mode `dry-run` | Aucun |
| `api/`, `web/` | Liste et détail des appareils, graphiques, événements, action « marquer comme connu », page de santé | Aucun |
| `cli.py` | Point d'entrée (`nettracker`) | Aucun |

## 3. Flux de données

1. Le collecteur lit la config et vérifie chaque cible contre `allowed_subnets` (garde-fou, voir section 5).
2. Un cycle de découverte produit des observations (MAC, IP, nom, fabricant) via une interface remplaçable.
3. Les observations sont écrites de façon idempotente : mise à jour de `devices`, ajout d'une ligne `sightings`, enregistrement du cycle dans `scans`.
4. Les transitions (nouvel appareil, passage hors ligne, retour, latence anormale) créent des lignes `events`.
5. Le moteur d'alertes lit les nouveaux `events`, applique les règles et l'anti-spam, puis écrit `notifications` (envoyée, `dry_run`, échouée, supprimée).
6. L'API lit la base et affiche le résultat.

## 4. Schéma SQLite (version 1, brouillon)

Horodatages : texte ISO 8601 en UTC. Les écritures sont idempotentes.

```sql
CREATE TABLE schema_version (version INTEGER NOT NULL);

CREATE TABLE devices (
    id                INTEGER PRIMARY KEY,
    mac               TEXT    NOT NULL UNIQUE,
    alias             TEXT,
    device_type       TEXT,
    hostname          TEXT,
    vendor            TEXT,
    is_randomized_mac INTEGER NOT NULL DEFAULT 0,
    status            TEXT    NOT NULL DEFAULT 'unknown'
                      CHECK (status IN ('known', 'unknown', 'to_confirm', 'ignored')),
    merged_into       INTEGER REFERENCES devices(id),
    first_seen        TEXT    NOT NULL,
    last_seen         TEXT    NOT NULL
);

CREATE TABLE scans (
    id            INTEGER PRIMARY KEY,
    started_at    TEXT    NOT NULL,
    finished_at   TEXT,
    mode          TEXT    NOT NULL CHECK (mode IN ('passive', 'active')),
    subnet        TEXT,
    status        TEXT    NOT NULL CHECK (status IN ('ok', 'error', 'denied')),
    error         TEXT,
    devices_found INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE sightings (
    id              INTEGER PRIMARY KEY,
    device_id       INTEGER NOT NULL REFERENCES devices(id),
    scan_id         INTEGER REFERENCES scans(id),
    ip              TEXT    NOT NULL,
    ipv6            TEXT,
    online          INTEGER NOT NULL,
    latency_ms      REAL,
    packet_loss_pct REAL,
    seen_at         TEXT    NOT NULL
);
CREATE INDEX idx_sightings_device_time ON sightings (device_id, seen_at);

CREATE TABLE events (
    id         INTEGER PRIMARY KEY,
    device_id  INTEGER REFERENCES devices(id),
    kind       TEXT NOT NULL CHECK (kind IN (
                   'new_device', 'online', 'offline', 'latency_high',
                   'to_confirm', 'merge_suggested', 'collector_stale')),
    details    TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE notifications (
    id      INTEGER PRIMARY KEY,
    event_id INTEGER NOT NULL REFERENCES events(id),
    channel TEXT NOT NULL,
    status  TEXT NOT NULL CHECK (status IN ('sent', 'dry_run', 'failed', 'suppressed')),
    error   TEXT,
    sent_at TEXT NOT NULL
);
```

Le schéma définitif est fixé et testé en M1.

## 5. Garde-fou de périmètre

Avant toute émission de paquet, une fonction unique vérifie la cible :

- la cible appartient à l'un des `allowed_subnets` ;
- la cible est une adresse privée (RFC 1918) ;
- sinon, le scan est refusé, une ligne `scans` avec `status = 'denied'` est écrite, et rien n'est émis.

Toute interface réseau (scapy, nmap, ping) passe par cette vérification et est remplacable dans les tests, si bien qu'aucun test n'émet de paquet réel.

## 6. Décisions (ADR courtes)

- **ADR-001 SQLite** : base locale, un seul fichier, sans service à administrer. Suffisant pour un foyer.
- **ADR-002 Découverte à trois niveaux** : table ARP système (passif, sans privilèges), scapy ARP (actif, privilèges), repli `nmap -sn`. Le mode passif est le défaut et sert aussi de mode dégradé quand Npcap ou les droits manquent.
- **ADR-003 FastAPI + Jinja2** : pages rendues côté serveur et graphiques légers ; pas de front-end séparé. Grafana uniquement sur demande.
- **ADR-004 Config TOML + variables d'environnement** : `tomllib` est dans la bibliothèque standard ; les secrets ne vivent que dans `.env`.
- **ADR-005 Interfaces remplacables** : tout accès réseau est derrière une interface, pour tester sans réseau réel.
- **ADR-006 Un collecteur, une API** : ils ne partagent que la base. L'API écoute sur `127.0.0.1` par défaut.

## 7. Ajouts retenus pour la v0.1

Ces points sont ajoutés sans changer les règles d'`AGENTS.md` ; ils tiennent chacun dans une colonne, un écran ou un module.

- **Alias et type d'appareil** : colonnes `alias` et `device_type`, action « renommer » dans le dashboard (M5).
- **Santé du collecteur** : dernier scan réussi et erreurs récentes lus dans `scans`, événement `collector_stale` si le dernier scan est trop ancien (M3, M4).
- **Mode dégradé** : lecture de la table ARP système seule quand scapy ou les droits manquent (M2).
- **Fusion des MAC aléatoires** : statut `to_confirm` et événement `merge_suggested` quand un nouvel appareil partage nom d'hôte ou mDNS avec un appareil connu ; la fusion reste validée à la main (M2, M4).

## 8. Reporté après la v0.1

Suivi de la bande passante, découverte IPv6 (NDP), export CSV et rapport périodique, comptes multi-utilisateurs. Une fonctionnalité qui ne tient pas dans une colonne, un écran ou un module est reportée en issue `v0.2`.
