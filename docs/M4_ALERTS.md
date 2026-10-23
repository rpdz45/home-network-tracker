# M4 – Moteur d'alertes (lot 1)

## Périmètre de ce lot

Transformer les événements déjà stockés en lignes `notifications`, avec anti-spam et mode `dry-run`. **Aucun envoi réseau n'existe encore** : les notifiers (Discord, Telegram, e-mail) arrivent dans un lot suivant. Ne sont pas livrés ici : les règles « hors ligne depuis X minutes » et « latence anormale » (génération d'événements `latency_high`), la planification et le dashboard.

## Fonctionnement

`nettracker process-alerts` lit les événements qui n'ont encore aucune ligne dans `notifications` (du plus ancien au plus récent, au plus `alerts.max_events_per_run`) et enregistre une ligne par événement et par canal. Un événement déjà enregistré n'est jamais retraité : la commande peut être relancée sans risque.

| Événement | Alerte | Gravité |
|---|---|---|
| `new_device` | oui | critical |
| `collector_stale` | oui | critical |
| `offline` | oui | warning |
| `latency_high` | oui | warning |
| `merge_suggested` | oui | info |
| `to_confirm` | non | (appareil à MAC aléatoire : jamais d'alerte critique) |
| `online` | non | (retour d'un appareil) |

## Statuts enregistrés

- `dry_run` : mode par défaut (`alerts.dry_run = true`). Rien n'est envoyé, aucun notifier n'est appelé ; canal `dry-run`.
- `suppressed` : anti-spam, canal `all`, erreur `cooldown`.
- `sent` / `failed` : mode réel, un enregistrement par notifier. En cas d'échec, seul le **nom du type d'exception** est stocké (jamais le message, qui pourrait contenir un secret). Un envoi échoué n'est pas réessayé dans ce lot.

## Anti-spam

Un événement est supprimé si un événement **de même type et du même appareil** (ou sans appareil pour `collector_stale`) a déjà produit une alerte `sent` ou `dry_run` dans les `alerts.cooldown_minutes` précédant son horodatage (30 min par défaut). Les événements supprimés ou en échec ne démarrent pas de nouveau délai : une suppression ne se prolonge donc pas indéfiniment. Des types différents pour un même appareil ne se suppriment pas entre eux.

## Configuration

```toml
[alerts]
dry_run = true            # tant que true, rien n'est jamais envoyé
cooldown_minutes = 30     # délai anti-spam par type et appareil (1 à 1440)
max_events_per_run = 200  # événements traités par exécution (1 à 1000)
```

Avec `dry_run = false` et aucun notifier configuré (c'est le cas dans ce lot), la commande refuse de s'exécuter avec une erreur claire et n'écrit rien.

## Sécurité

- Aucun accès réseau, aucun secret lu ou écrit dans ce lot. Les futurs notifiers liront leurs secrets dans `.env` uniquement.
- Les messages contiennent l'alias ou le nom d'hôte et la MAC de l'appareil : ce sont des données du foyer, qui ne quitteront la machine que vers les canaux choisis par le propriétaire (règle 11 d'`AGENTS.md`).
- Le journal ne contient que l'identifiant et le type de l'événement, pas le texte du message.

## Tests

`tests/unit/test_alerts.py` (SQLite en mémoire, notifiers factices, aucun réseau) : dry-run sans envoi, seuls les types prévus sont traités, traitement unique, anti-spam par appareil et type, délai non prolongé par une suppression, message lisible, détails de `collector_stale`, échec enregistré sans son message, échec sans délai, refus sans notifier, limite par exécution, horloge sans fuseau refusée. `tests/unit/test_cli_alerts.py` : commande, relance sans doublon, refus du mode réel, cooldown invalide, ligne de `check-config`.

```bash
pytest tests/unit/test_alerts.py tests/unit/test_cli_alerts.py -vv
```

## Limites connues

- Aucun notifier réel : le mode réel n'est pas utilisable avant le lot suivant.
- Les événements `offline` sont déjà créés dès le premier cycle sans réponse ICMP (voir `M3_MONITORING.md`) ; le seuil « hors ligne depuis X minutes » viendra avec un lot dédié.
- La commande ne tourne pas toute seule : planification (cron, timer, tâche planifiée) à ta charge.
- Le moteur lit les événements en SQL directement ; si un nouveau type d'événement doit alerter, il faut l'ajouter à `alerts/rules.py` **et** à la requête (un test vérifie la cohérence).
- Aucune validation sur matériel réel.
