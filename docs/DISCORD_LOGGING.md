# Confidentialité des journaux Discord

## Problème et correction

HTTPX journalise l'URL complète des requêtes au niveau INFO. Le chemin d'un webhook Discord contient un secret : masquer seulement les exceptions ne suffit donc pas.

Le notifier installe avant tout envoi un filtre sur `httpx` et sur les loggers de transport HTTPCore utilisés (`connection`, `http11`, `http2`, `proxy`, `socks`). Les chemins `/api/webhooks/...` deviennent `/api/webhooks/[redacted]`, y compris au niveau DEBUG et avec un client HTTP injecté. Le filtre ne conserve aucun secret, ne s'accumule pas à chaque notifier et laisse les autres traces HTTP disponibles. Il reste actif pour la durée du processus et masque aussi ces chemins dans les autres requêtes des loggers concernés.

La livraison Discord, les garde-fous réseau, le mode `dry-run`, les règles d'alertes et le schéma SQLite restent inchangés.

## Vérification hors ligne

```bash
pytest tests/unit/test_discord_logging.py tests/unit/test_discord_notifier.py -vv
```

Les 18 nouveaux cas couvrent INFO/DEBUG, succès, redirection refusée, erreurs HTTP, cibles de transport, plusieurs handlers, préservation des autres journaux et installation idempotente. Ils utilisent des jetons générés pour le test, `httpx.MockTransport` ou des lignes de journal synthétiques ; aucun envoi à Discord ni scan réseau.

## Limites et rotation

La protection concerne les messages des loggers standards listés, pas un transport personnalisé, des hooks ou des handlers qui journalisent des requêtes brutes ailleurs. Elle ne protège ni les captures réseau ni les champs additionnels de journaux personnalisés. Les futures versions HTTPX/HTTPCore peuvent demander une adaptation si leurs loggers ou leur format changent.

Si une URL de webhook a déjà été enregistrée, révoquer le webhook dans Discord, remplacer le secret dans `.env` et protéger les anciens journaux. Le correctif n'efface pas les journaux existants. Aucun test sur webhook réel, matériel, réseau domestique ou navigateur n'est effectué pour ce lot.
