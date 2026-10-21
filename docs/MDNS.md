# Enrichissement mDNS ciblé (M2)

## Architecture

Rôle architecte : retenir un enrichissement PTR direct-unicast vers l'IPv4 déjà
observée, et non une découverte multicast globale. La
[RFC 6762, sections 5.5 et 6.7](https://www.rfc-editor.org/rfc/rfc6762.txt)
définit les requêtes unicast directes sur UDP 5353 et les réponses aux clients
utilisant un port éphémère. Ce sous-ensemble est intentionnel : il préserve un
destinataire strictement couvert par `allowed_subnets`, sans diffusion aux autres
appareils/interfaces du LAN. Il n'implémente pas tout mDNS/DNS-SD.

Rôle développeur : `discovery/mdns.py` vérifie le périmètre et le délai avant
l'appel remplaçable ; `dnspython>=2.8` gère l'encodage, la compression DNS et le
transport borné. [`dns.query.udp`](https://dnspython.readthedocs.io/en/stable/query.html)
est utilisé avec une IP littérale, le port fixe 5353, contrôle de source et de
réponse, sans résolveur système ni repli TCP. Une seule tentative par observation
dédoublonnée ; délai fini de 0,1 à 5 secondes. Les réponses expirées, tronquées,
ambiguës, d'une autre question/classe/type ou contenant des noms hors `.local`
sont ignorées. Une erreur de périmètre demeure fatale.

Double opt-in : `scan.mdns_enabled=false` par défaut, plus `--resolve-mdns` à chaque
commande. Le cache reste la source des observations en mode passif, mais le cycle
avec requêtes mDNS est enregistré en mode actif. L'option DNS inverse existante
reste indépendante ; quand les deux sont demandées, mDNS précède le DNS système.
La colonne `devices.hostname` et les suggestions manuelles existantes sont
réutilisées, sans migration ni nouvelle confiance sur les noms.

Alternative écartée : une bibliothèque de découverte multicast continue activerait
des sockets et interfaces hors des seules cibles observées. Contrepartie assumée :
compatibilité incomplète avec les appareils multicast-only, aucun IPv6 ni navigateur
de services ; validation terrain encore nécessaire.

## Sécurité

Rôle sécurité : mDNS reste éteint sans `scan.mdns_enabled=true` **et**
`--resolve-mdns`. Cette activation émet des requêtes actives même si les appareils
proviennent du cache passif ; le cycle SQLite est donc marqué `active`. Chaque
IPv4 passe par `require_allowed_target` avant le transport, qui contacte uniquement
cette adresse au port UDP 5353. Aucun multicast global, DNS système implicite,
parcours de services, télémétrie ou besoin de privilège brut n'est introduit.

`dnspython` contrôle le port/l'adresse source et la correspondance avec la question
émise ; le backend refuse les réponses tronquées, expirées ou ambiguës et les noms
hors `.local`. Cela n'authentifie pas l'appareil : une réponse PTR peut être usurpée.
Un nom ne doit jamais rendre un appareil connu ou fusionner des MAC automatiquement.
Les noms sont stockés dans SQLite localement, pas journalisés par ce backend.

Le délai d'attente reste fini, configurable et sans nouvelle tentative ; SIGINT
n'est pas avalé. Une absence de réponse ou une permission refusée conserve
l'observation sans nom. Limites : le délai s'applique par IPv4, et le cumul d'un
cycle dépend du nombre de voisins. La compatibilité réelle reste à vérifier sur
chaque OS, réseau et appareil. La résolution DNS inverse historique
`--resolve-names` reste susceptible de contacter un résolveur hors LAN si demandée.

## Tests

Rôle QA : `tests/unit/test_mdns.py` remplace le transport UDP ou le lookup. Les
messages DNS sont des fixtures construites en mémoire, pas des captures du foyer.
Cas couverts : désactivation, IPv4 publique/hors périmètre, CIDR, IPv6, configuration
et délais invalides (dont NaN/infini), timeout, permission refusée, message malformé,
nom `.local` normalisé, nom externe/invalide, PTR expiré/ambigu, mauvaise question,
classe/type/identifiant, réponse tronquée et propagation de SIGINT.

`tests/integration/test_mdns_cli.py` relie CLI, collecteur et SQLite avec voisins et
transport simulés : double opt-in, réglage du délai, chemins cache/ARP/nmap/repli,
dédoublonnage, stockage du nom, MAC aléatoire restant `to_confirm`, cycle actif,
refus hors périmètre avant transport et DNS système seulement sur opt-in distinct.

```bash
pytest tests/unit/test_mdns.py tests/integration/test_mdns_cli.py -vv
ruff check .
ruff format --check .
mypy
pytest --cov --cov-report=term-missing
bandit -r src
pip-audit
```

Aucun de ces tests mDNS n'ouvre de socket réelle. Ils ne valident ni le pare-feu,
ni la compatibilité multicast-only/PTR des appareils, ni le comportement réel
Linux/Windows/Raspberry Pi. Pour le test propriétaire, adapter `allowed_subnets`,
activer `scan.mdns_enabled` et lancer `nettracker scan-once --config config.toml
--resolve-mdns` uniquement sur son LAN. Cette commande émet des paquets ; elle
n'est pas un dry-run, même avec `alerts.dry_run=true` qui ne concerne que les alertes.
