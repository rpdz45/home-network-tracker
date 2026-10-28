# M3 — Boucle ICMP manuelle, rafraîchissement et rétention optionnels

## Périmètre actuel

L'entrée est `python -m nettracker.monitor.loop`, pas une sous-commande
`nettracker monitor-loop`. Elle suit seulement les IDs explicitement choisis,
peut rafraîchir leurs observations depuis le cache local et peut appliquer deux
politiques de rétention indépendantes. Toutes ces options sont explicites.
Elle n'inscrit pas automatiquement de nouveaux appareils, ne démarre ni dashboard,
ni service système, ni tâche planifiée et n'envoie aucune notification.

Le mode `--continuous` reste au premier plan tant que le processus fonctionne.
Ce n'est pas un déploiement M6 : pas de reprise automatique après erreur ou reboot.
Le dashboard se lance séparément et ne réalise lui-même aucune collecte.

## Avant un essai sur son propre réseau

- Installer le paquet et choisir son environnement virtuel.
- Adapter et valider `config.toml` sans publier de donnée du foyer ou de secret.
  Aucun CIDR réel du propriétaire n'est supposé par ce guide.
- Initialiser la base avec les commandes du README ; sauvegarder avant migration
  ou suppression. La boucle exige une base existante au schéma courant et ne la
  migre pas implicitement. `.env` est lu depuis le répertoire courant.
- Inscrire préalablement les appareils via la découverte et relever leurs IDs.
  Les IDs des exemples sont des valeurs à remplacer, pas une sélection recommandée.
- Activer `monitor.enabled=true` et fournir `--enable-monitoring`. Sans cette
  double activation, le suivi est refusé. `allowed_subnets`, fraîcheur, IPv4,
  conflits d'IP et statuts ignorés/fusionnés restent contrôlés à chaque cycle.

Attention : le suivi envoie de vrais pings. `alerts.dry_run` concerne les alertes,
pas les sondes, la découverte active ou les suppressions. Aucun exemple de cette
page n'a été exécuté sur le réseau ou la base du propriétaire pendant sa rédaction.

## Premier essai borné sans purge

Après les prérequis, pour l'appareil dont l'ID réel est choisi à la place de 1.
Le rafraîchissement ci-dessous exige aussi `scan.mode="passive"` :

```powershell
.\.venv\Scripts\python.exe -m nettracker.monitor.loop --config config.toml --device-id 1 --enable-monitoring --refresh-passive --cycles 3 --interval-seconds 60
```

Sur Linux ou Raspberry Pi OS, utiliser `python` de l'environnement virtuel à la
place du chemin Windows. Plusieurs `--device-id` sont possibles ; entre 1 et
64 IDs positifs sont acceptés et les doublons sont dédupliqués.

Sans `--cycles` ni `--continuous`, un seul cycle est exécuté. Pour un suivi manuel
continu après validation de l'essai, remplacer `--cycles 3` par `--continuous` ;
ces deux options sont incompatibles. Aucun consentement à une purge n'est inclus
dans l'exemple : aucun des deux drapeaux de suppression n'y apparaît.

## Rafraîchissement passif : portée et limites

Sans `--refresh-passive`, la boucle ne renouvelle pas les observations ; elles
peuvent devenir trop anciennes (1800 secondes par défaut). Ne pas désactiver ce
garde-fou pour simuler un fonctionnement prolongé réussi.

Avec l'option, une lecture du cache par cycle valide le résultat avant de
renouveler uniquement les appareils sélectionnés. Pas de balayage ARP brut,
nmap, DNS ou mDNS ajouté. Une configuration de scan actif est refusée.
Un appareil absent, une association ambiguë ou une adresse hors périmètre arrête
la boucle ; aucune ancienne IP n'est réutilisée pour inventer une mesure hors ligne.
Le cache peut être ancien ou usurpé : « relu maintenant » ne signifie pas
« présence récente prouvée » et le ping n'authentifie pas une MAC.
Voir [M3_PASSIVE_REFRESH.md](M3_PASSIVE_REFRESH.md).

## Purges séparées, désactivées par défaut

Avant activation, sauvegarder et vérifier les aperçus autonomes :

```text
nettracker prune-history --config config.toml
nettracker prune-discovery --config config.toml
```

Ces exemples ne contiennent pas `--apply`. L'aperçu des scans est calculé avant
suppression des observations : l'application peut ensuite libérer d'autres scans.

| Politique dans la boucle | Autorisations requises | Cadence propre | Borne par passage |
|---|---|---|---|
| Anciens pings | `retention.enabled=true` et `--prune-ping` | `--prune-every-cycles N` | Un lot de `retention.batch_size` |
| Découvertes remplacées et anciens scans inutilisés | `discovery_retention.enabled=true` et `--prune-discovery` | `--discovery-prune-every-cycles N` | Un lot d'observations puis un lot de scans de `discovery_retention.batch_size` |

Chaque cadence vaut 100 cycles réussis par défaut, avec N entre 1 et 1000000.
Un réglage de cadence sans son drapeau est refusé. Premier passage après N cycles,
pas au démarrage ni à la sortie en supplément. Un cycle idempotent sans erreur
compte aussi. `keep_days` et `batch_size` viennent de chaque section de config,
mais la boucle impose `max_batches=1` même si la configuration autorise davantage.
Au plus 5000 lignes par lot, pas une garantie de durée ni de résorption du retard.

Les purges sont globales à la base, pas limitées aux IDs suivis. Elles peuvent
supprimer définitivement des historiques. La découverte conserve notamment sa
dernière observation par appareil, le dernier scan réussi, les cinq derniers scans
de statut non réussi par ordre d’ID et les scans encore référencés ou non terminés. Les politiques ne suppriment
ni appareils, états courants, événements ou notifications. Le seuil strict dépend
de l'heure UTC système. Les autres données peuvent continuer à croître : aucune
borne de taille pour la base complète. Les commandes autonomes gardent leur
activation `--apply`, distincte des drapeaux propres à la boucle.

Détails : [M3_LOOP_PING_RETENTION.md](M3_LOOP_PING_RETENTION.md),
[M3_LOOP_DISCOVERY_RETENTION.md](M3_LOOP_DISCOVERY_RETENTION.md).

## Ordonnancement, sorties et arrêt

Cycles séquentiels, sans chevauchement ni rattrapage. `--interval-seconds` est un
délai après chaque cycle terminé, pas une fréquence départ-à-départ : 60 secondes
par défaut, de 10 à 86400. Un nombre fini de cycles va de 1 à 1000000.
Ordre : rafraîchissement demandé, suivi, purge ping éventuelle, puis découverte.
Les mesures d'un cycle sont transactionnelles ; aucun verrou de transaction
n'est maintenu pendant une sonde ou l'attente entre cycles.

Une erreur de suivi empêche les purges suivantes ; une erreur de purge arrête
la boucle sans annuler les mesures ou lots déjà validés. Pas de réessai automatique.
Les erreurs de domaine/SQLite donnent le code 2 et le nom de la classe, sans ses
détails. Le résumé `cycles=... measurements=...` n'est affiché qu'à la sortie
normale ou après interruption traitée, pas à chaque cycle. Avec les options,
il ajoute `pruned_ping_samples=...` et/ou
`pruned_discovery_observations=... pruned_scans=...`.

Ctrl+C dans l'ordonnanceur renvoie 130. SIGTERM demande l'arrêt via un Event ;
le handler précédent est restauré et la connexion fermée en sortie gérée.
Un contrôle précède chaque politique de purge, mais pas les deux phases internes
découverte/scans. Un travail déjà commencé peut donc finir : pas d'arrêt instantané
garanti. Les mesures déjà validées peuvent subsister malgré une interruption.
Exécuter cette entrée CLI dans le thread principal.

## État de validation et limites M3

Les contrôles qualité Linux, Windows et gitleaks des PR #38 et #39 ont réussi
le 27 octobre 2026 sur les têtes 62137b54 et 8648256d respectivement. Les bases
et transports des scénarios de test sont synthétiques. Ces validations ne sont
ni des essais de la commande sur matériel réel ni une endurance de 24 heures.
Le diagnostic `resource_profile` reste synthétique et sa mémoire tracemalloc
n'est pas le RSS. Il ne constitue pas une preuve générale d'absence de fuite.

Cette mise à jour est documentaire seulement : aucun nouveau test, aucune
configuration ni activation de collecte/purge. Les options ont été relues dans
le code de la branche ; les commandes ci-dessus n'ont pas été exécutées pendant
la rédaction. Revue et CI de la PR documentaire restent nécessaires avant fusion.
La validation terrain, l'endurance réelle et le déploiement restent à documenter
avec leurs résultats effectifs. Le jalon M3 complet reste ouvert.
