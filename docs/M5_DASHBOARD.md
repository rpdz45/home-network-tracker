# M5 – Tableau de bord local (lot 1, lecture seule)

## Périmètre

`nettracker serve` lance un tableau de bord web **en lecture seule** (FastAPI + Jinja2, HTML et CSS en ligne, aucun JavaScript). Il ne scanne jamais, n'écrit jamais dans la base et n'ouvre aucune connexion sortante. Ne sont pas livrés dans ce lot : les graphiques de latence et d'uptime, l'action « marquer comme connu », le renommage (alias, type) et la mise à jour automatique de la page.

## Pages

| Chemin | Contenu |
|---|---|
| `/` | Liste des appareils non fusionnés (nom, MAC, IP, fabricant, statut, état ICMP, dernière observation) et bloc **santé du collecteur** (OK, périmé ou aucun scan réussi, avec le seuil `health.stale_after_minutes`) |
| `/devices/{id}` | Fiche d'un appareil, 25 dernières mesures (découverte et ping), 25 derniers événements avec statut des alertes |
| `/events` | 100 derniers événements, appareil concerné et statut des alertes (`dry_run`, `sent`, `suppressed`, `failed`) |
| `/login` | Formulaire de jeton (seulement si un jeton est configuré) |

Les statuts ICMP sont des indications : une réponse n'authentifie pas l'appareil, une absence de réponse ne prouve pas une déconnexion.

## Utilisation

```bash
nettracker init-db --config config.toml   # une fois
nettracker serve --config config.toml     # http://127.0.0.1:8080 par défaut
```

La commande refuse de démarrer si la base n'existe pas. Pour garder les données à jour, lance à côté `scan-once`, `monitor-once`, `health-check` et `process-alerts` (le tableau de bord lit ce que ces commandes ont enregistré).

## Sécurité

- Écoute sur `127.0.0.1` par défaut. Une adresse hors loopback est refusée par la configuration tant qu'aucun jeton n'est défini (`api.token` / `NETTRACKER_API_TOKEN`).
- Avec un jeton, **toutes** les pages l'exigent : en-tête `Authorization: Bearer <jeton>`, ou cookie de session posé par `/login` (`HttpOnly`, `SameSite=Strict`, 8 heures). Sans identifiants, un navigateur est redirigé vers `/login` ; un mauvais jeton donne 401. Le jeton est comparé en temps constant et n'apparaît ni dans les pages ni dans les journaux. Il n'est jamais accepté dans l'URL.
- **Le trafic est en HTTP clair** : le jeton et le cookie transitent en clair sur le réseau. N'expose le tableau de bord que sur un réseau de confiance, ou derrière un proxy TLS que tu gères.
- Connexion SQLite avec `PRAGMA query_only` : toute écriture serait refusée par SQLite (test dédié). Aucune route ne modifie quoi que ce soit (POST et DELETE sur les pages renvoient 405, seul `/login` accepte un POST).
- En-têtes : `Content-Security-Policy` stricte (`default-src 'none'`, style en ligne seulement), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cache-Control: no-store`. L'échappement HTML est automatique (test avec un nom d'hôte contenant une balise script). Les pages `/docs` et `/openapi.json` sont désactivées.
- Le formulaire de connexion refuse les corps de plus de 4 Kio. Il n'y a pas de limitation du nombre d'essais : utilise un jeton long et aléatoire.
- Une base absente ou d'un schéma ancien donne une page 503 générique, sans chemin ni détail interne.

## Tests

`tests/unit/test_web.py` (client de test en processus, aucun réseau) : liste sans appareils fusionnés, échappement HTML, fiche et 404/422, événements avec statut d'alerte, santé OK puis périmée (horloge injectée), en-têtes et pages de documentation absentes, aucune route d'écriture, connexion SQLite en lecture seule, 503 sans chemin, redirection vers `/login`, jeton Bearer, cookie strict et `HttpOnly`, jeton absent des pages, corps de connexion trop gros. `tests/unit/test_cli_serve.py` : démarrage sur l'adresse configurée (serveur remplacé), refus sans base, refus d'une adresse LAN sans jeton.

```bash
pytest tests/unit/test_web.py tests/unit/test_cli_serve.py -vv
```

## Limites connues

- Aucun test sur un navigateur réel ni sur plusieurs jours d'exécution.
- Pas de rafraîchissement automatique : recharge la page.
- Listes bornées (500 appareils, 100 événements, 25 lignes par fiche), sans pagination.
- Un seul jeton partagé, pas de comptes (hors périmètre de la v0.1).
- Le cookie contient le jeton lui-même (pas de session séparée) ; d'où l'avertissement sur le HTTP clair.
