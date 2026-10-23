# M3 – Santé du collecteur

## Objectif

Un outil de surveillance qui tombe en panne sans prévenir est pire que pas d'outil. `nettracker health-check` indique si la découverte tourne encore et enregistre un événement `collector_stale` lorsqu'elle s'est arrêtée.

## Fonctionnement

- La commande lit la table `scans`, déjà alimentée par chaque cycle de découverte (`scan-once`). Aucune nouvelle table, aucune migration.
- Dernier scan réussi = plus récent `finished_at` d'un scan au statut `ok`. Un scan en erreur ne compte pas comme un succès.
- Le collecteur est **périmé** (`STALE`) si ce dernier succès date de plus de `health.stale_after_minutes` (comparaison stricte : exactement au seuil, il n'est pas périmé).
- Les 5 derniers scans non réussis (erreur ou jamais terminés) sont listés avec le nom du type d'exception, jamais le détail du message.
- Aucun scan réussi enregistré : la commande l'indique et ne déclare pas de panne (pas de point de référence).

## Anti-spam

Un seul événement `collector_stale` est créé par période de panne. Tant que le dernier `collector_stale` est plus récent que le dernier scan réussi, rien de nouveau n'est écrit, même si la commande est relancée. Le premier scan réussi suivant réarme la règle : une nouvelle panne produit un nouvel événement. La vérification et l'écriture se font dans une transaction.

## Configuration

```toml
[health]
# Minutes sans scan réussi avant de déclarer le collecteur périmé (1 à 10080).
stale_after_minutes = 15
```

Choisis un seuil nettement supérieur à l'intervalle réel entre deux `scan-once` (au moins 2 à 3 fois), sinon tu auras de fausses alertes. Cette cohérence n'est pas vérifiée automatiquement : `scan.interval_seconds` n'est pas encore utilisé par un ordonnanceur.

## Utilisation

```bash
nettracker health-check --config config.toml
```

Code de sortie : `0` collecteur sain (ou aucun scan encore), `3` collecteur périmé, `1` erreur de configuration ou de base. Le code 3 permet de brancher la commande sur une tâche planifiée ou un autre outil de supervision. La commande ne tourne pas toute seule : planifie-la (cron, systemd timer, tâche planifiée Windows) ; la planification intégrée est un lot ultérieur.

## Sécurité

- Lecture et écriture de la base locale uniquement : aucun paquet réseau, aucun sous-processus, aucun privilège.
- **Aucune notification n'est envoyée** : l'événement est seulement enregistré localement. L'envoi (Discord, Telegram, e-mail, mode `dry-run`) relève du jalon M4. Le test `test_recording_never_creates_a_notification` vérifie qu'aucune ligne n'est ajoutée à `notifications`.
- Les erreurs de scan stockées ne contiennent que le nom du type d'exception, pas de chemin, de MAC ni d'IP.

## Tests

`tests/unit/test_health.py` (SQLite en mémoire, horloge injectée, aucun `sleep`) : aucun scan, succès récent, seuil strict, un seul événement par panne, réarmement après succès, scan en erreur non compté comme succès, lecture sans écriture, aucune notification, liste de problèmes bornée, arguments invalides. `tests/unit/test_cli_health.py` : commande, codes de sortie, un seul événement après deux exécutions, seuil invalide refusé, ligne `health` de `check-config`.

```bash
pytest tests/unit/test_health.py tests/unit/test_cli_health.py -vv
```

## Limites connues

- Seuls les scans de découverte sont suivis. `monitor-once` n'écrit pas dans `scans` : une panne du suivi ICMP n'est pas détectée ici.
- Un collecteur qui n'a jamais réussi un scan n'est pas déclaré périmé ; ses échecs apparaissent dans les problèmes récents.
- Si l'horloge de la machine recule, l'ancienneté peut être négative et le collecteur n'est pas déclaré périmé.
- Pas de bloc « santé » dans le dashboard (M5 non commencé) : cette commande en est la source de données.
- Aucune validation sur matériel ou sur une exécution de plusieurs jours.
