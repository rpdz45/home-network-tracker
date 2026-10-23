# M4 – Moteur d'alertes (lots 1 et 2)

## Périmètre

Transformer les événements stockés en lignes `notifications`, avec anti-spam, mode `dry-run`, un délai avant d'alerter sur un appareil hors ligne et une détection de latence soutenue. **Aucun envoi réseau n'existe encore** : les notifiers (Discord, Telegram, e-mail) arrivent dans un lot suivant. Aucune migration : seules les tables `events`, `notifications`, `sightings` et `scans` du schéma existant sont utilisées.

## Fonctionnement

`nettracker process-alerts` exécute dans cet ordre :

1. **Détection de latence** : crée au besoin des événements `latency_high` (voir plus bas).
2. **Traitement des événements en attente** : ceux qui n'ont encore aucune ligne dans `notifications`, du plus ancien au plus récent, au plus `alerts.max_events_per_run`. Une ligne est enregistrée par événement et par canal ; un événement déjà enregistré n'est jamais retraité, la commande peut donc être relancée sans risque.

| Événement | Alerte | Gravité |
|---|---|---|
| `new_device` | oui | critical |
| `collector_stale` | oui | critical |
| `offline` | oui, après délai | warning |
| `latency_high` | oui | warning |
| `merge_suggested` | oui | info |
| `to_confirm` | non | (appareil à MAC aléatoire : jamais d'alerte critique) |
| `online` | non | (sert seulement à annuler une alerte hors ligne) |

## Hors ligne depuis X minutes

Un événement `offline` n'est pris en compte qu'une fois plus ancien que `alerts.offline_after_minutes` (5 par défaut ; 0 = immédiat). Tant qu'il est plus récent, il reste en attente sans occuper la limite par exécution. À l'échéance, s'il existe un événement `online` **plus récent pour le même appareil**, l'appareil est revenu : la ligne est enregistrée en `suppressed` avec l'erreur `recovered` et aucune alerte n'est produite. Un `online` d'un autre appareil, ou antérieur, n'annule rien.

## Latence élevée

Pour chaque appareil ayant un échantillon ping récent (moins de 60 minutes), la moyenne de ses **3 derniers échantillons ayant répondu** est comparée à `alerts.latency_high_ms` (200 par défaut). Au-dessus du seuil (comparaison stricte), un événement `latency_high` est créé avec la moyenne dans ses détails. Un seul événement par épisode : tant qu'aucun échantillon à ou sous le seuil n'a été vu depuis le dernier événement, rien de nouveau n'est créé. Un échantillon normal réarme la règle. Les sondes sans réponse sont ignorées (elles relèvent de `offline`). Ces échantillons n'existent que si tu lances `monitor-once` (double opt-in).

## Statuts enregistrés

- `dry_run` : mode par défaut (`alerts.dry_run = true`). Rien n'est envoyé, aucun notifier n'est appelé ; canal `dry-run`.
- `suppressed` : canal `all`, erreur `cooldown` (anti-spam) ou `recovered` (appareil revenu).
- `sent` / `failed` : mode réel, un enregistrement par notifier. En cas d'échec, seul le **nom du type d'exception** est stocké (jamais le message, qui pourrait contenir un secret). Un envoi échoué n'est pas réessayé dans ce lot.

## Anti-spam

Un événement est supprimé si un événement **de même type et du même appareil** (ou sans appareil pour `collector_stale`) a déjà produit une alerte `sent` ou `dry_run` dans les `alerts.cooldown_minutes` précédant son horodatage (30 min par défaut). Les événements supprimés ou en échec ne démarrent pas de nouveau délai : une suppression ne se prolonge donc pas indéfiniment. Des types différents pour un même appareil ne se suppriment pas entre eux.

## Configuration

```toml
[alerts]
dry_run = true             # tant que true, rien n'est jamais envoyé
cooldown_minutes = 30      # délai anti-spam par type et appareil (1 à 1440)
max_events_per_run = 200   # événements traités par exécution (1 à 1000)
offline_after_minutes = 5  # délai avant une alerte hors ligne (0 à 1440 ; 0 = immédiat)
latency_high_ms = 200      # seuil de latence moyenne (1 à 60000)
```

Avec `dry_run = false` et aucun notifier configuré (c'est le cas pour l'instant), la commande refuse de s'exécuter avec une erreur claire avant toute écriture.

## Sécurité

- Aucun accès réseau, aucun secret lu ou écrit. Les futurs notifiers liront leurs secrets dans `.env` uniquement.
- Les messages contiennent l'alias ou le nom d'hôte et la MAC de l'appareil : ce sont des données du foyer, qui ne quitteront la machine que vers les canaux choisis par le propriétaire (règle 11 d'`AGENTS.md`).
- Le journal ne contient que l'identifiant et le type de l'événement, pas le texte du message.
- La détection de latence ne lit que des échantillons déjà stockés : elle n'envoie aucune sonde.

## Tests

`tests/unit/test_alerts.py` et `tests/unit/test_cli_alerts.py` (lot 1) : dry-run, types traités, anti-spam, échecs, limites, commande. `tests/unit/test_alert_rules.py` (lot 2, SQLite en mémoire, horloge injectée) : alerte hors ligne retardée puis déclenchée à l'échéance, délai nul, délai réservé à `offline`, annulation par un `online` ultérieur du même appareil (et pas par un autre appareil ni un `online` antérieur), latence soutenue, un événement par épisode, réarmement, échantillons insuffisants, seuil strict, sondes sans réponse, échantillons anciens, seuil invalide, enchainement détection puis envoi, message de latence.

```bash
pytest tests/unit/test_alerts.py tests/unit/test_alert_rules.py tests/unit/test_cli_alerts.py -vv
```

## Limites connues

- Aucun notifier réel : le mode réel n'est pas utilisable avant le lot suivant.
- Une alerte hors ligne n'est examinée qu'à l'échéance du délai et seulement quand `process-alerts` tourne : le retard réel dépend de ta planification. L'appareil qui revient puis repart dans le délai produit deux `offline` ; le premier est annulé (`recovered`), le second suit son propre délai.
- Le nombre d'échantillons (3) et la fenêtre de fraîcheur (60 minutes) de la latence sont des constantes, non configurables.
- La commande n'affiche pas le nombre d'événements `latency_high` créés (le compte est dans le résumé interne) ; ils sont consultables dans la table `events`.
- La commande ne tourne pas toute seule : planification (cron, timer, tâche planifiée) à ta charge.
- Le moteur lit les événements en SQL directement ; si un nouveau type d'événement doit alerter, il faut l'ajouter à `alerts/rules.py` **et** à la requête (un test vérifie la cohérence).
- Aucune validation sur matériel réel.
