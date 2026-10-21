# M3 : premier cycle de suivi ICMP

## Architecte — périmètre et décision

Ce lot ajoute **un cycle unique explicite**, pas un service périodique. Le jalon M3
reste ouvert : ordonnanceur, rétention, suivi prolongé et santé du collecteur
(issue #3) ne sont pas encore livrés. Les paramètres réels OS, box et réseau du
propriétaire ne sont pas renseignés : aucun réseau réel n'est supposé, les valeurs
prudentes du dépôt sont conservées.

ADR : réutiliser `sightings` avec une colonne `source` (`discovery` ou `ping`) plutôt
que mélanger silencieusement présence dans le cache ARP et réponses ICMP. La migration
V2 est additive ; les lignes existantes restent `discovery`. `monitor_state`
conserve uniquement le dernier état par appareil pour dédupliquer les transitions,
même si une future rétention supprime des mesures anciennes. L'historique reste dans
`sightings`. Les tables et migrations existantes ne sont pas réécrites.

Un premier résultat établit une référence sans événement de transition. Une nouvelle
IPv4 découverte réinitialise cette référence. Seuls les changements ultérieurs de
réponse ICMP sur la même IP créent `online` / `offline`. Ce sont des indications de
joignabilité ICMP, pas une preuve de présence physique ou d'identité MAC.

## Développeur — utilisation

Dans `config.toml`, ajouter une section distincte (ne pas dupliquer `[monitor]`) :

```toml
[monitor]
enabled = true
packets = 3
timeout_seconds = 1.0
max_observation_age_seconds = 1800
```

- `enabled=false` par défaut ; il faut également `--enable-monitoring` à chaque appel.
- `packets` : 1 à 5 tentatives successives par appareil, 3 par défaut.
- `timeout_seconds` : de 0,1 à 5 secondes par tentative, 1 par défaut ; le processus
  reçoit un budget supplémentaire de 0,5 seconde pour terminer proprement.
- `max_observation_age_seconds` : de 60 à 86400 secondes, 1800 par défaut.

Effectuer une découverte récente (passive par défaut) puis utiliser les identifiants
**de sa propre base** ; l'exemple 1/2 ci-dessous est fictif :

```bash
nettracker scan-once --config config.toml
nettracker monitor-once --config config.toml --device-id 1 --device-id 2 --enable-monitoring
```

Les identifiants sont actuellement consultables localement dans SQLite (`SELECT id,
mac, alias FROM devices;`). Pas encore de commande de liste ni de dashboard dans ce
lot. Il faut 1 à 64 identifiants explicites ; les doublons sont dédupliqués. L'option
`--enable-active` de découverte ARP n'active pas le suivi ICMP. La configuration seule
ne lance aucun processus. `alerts.dry_run` ne bloque **pas** les sondes autorisées.

Le cycle valide tous les appareils avant la première sonde : non fusionnés, non
ignorés, dernière observation de découverte récente, IPv4 privée dans
`allowed_subnets`. Les adresses réseau/broadcast de ces sous-réseaux sont refusées.
Une IPv4 revendiquée aussi récemment ou plus récemment par un autre appareil est
refusée ; si ce dernier a changé d'IP, son ancienne revendication n'est plus courante.
Ce contrôle réduit les erreurs DHCP sans authentifier le détenteur actuel de l'IP.
Une nouvelle découverte est nécessaire pour réévaluer une observation périmée.

## Sécurité — transport et persistance

Linux/Raspberry Pi OS : binaire `ping` compatible iputils dans le PATH (paquet
`iputils-ping` si absent). Windows : `ping.exe` système. Le programme n'utilise pas
scapy ni de socket brute et ne demande pas root/admin. Le binaire Linux peut avoir
besoin de sa capacité système habituelle ; si elle manque, le cycle échoue clairement,
sans élévation automatique. Autres OS refusés pour ce premier lot.

Chaque tentative utilise une liste d'arguments fixe, sans shell ni DNS, une seule
IPv4 littérale et une charge de 16 octets. L'environnement impose une locale C sous
Linux. Les temps anglais/français/allemands/espagnols/portugais sont reconnus pour les
réponses Windows ; une sortie inconnue échoue sans mesure. Le `PATH` et le binaire
ping de la machine doivent être fiables. Aucun scan de ports ni balayage n'est ajouté.

Les non-réponses ICMP donnent une perte de 100 %, distincte d'un processus introuvable,
d'une permission refusée, d'un délai de sous-processus dépassé ou d'un format invalide :
ces derniers interrompent le cycle sans créer de fausse transition hors ligne.
Sous Windows, un code 1 n'est accepté comme non-réponse qu'avec un texte de délai
reconnu ; les autres diagnostics (dont erreurs de routage) échouent prudemment.
La latence moyenne porte uniquement sur les réponses ; `temps<1 ms` est conservé
comme borne approximative de 1 ms, pas comme une précision submilliseconde.

Aucune transaction n'est ouverte pendant les sondes, et un appel depuis une transaction
existante est refusé. Une fois toutes les réponses obtenues, les cibles sont revalidées
sous verrou d'écriture, puis les mesures, états et transitions sont écrits atomiquement.
Un changement de découverte concurrent, une erreur SQLite ou SIGINT annule les
écritures du cycle. Les sondes déjà émises ne peuvent évidemment pas être annulées.
La clé unique appareil/date et l'état courant rendent une réécriture identique idempotente.
Les dates ne peuvent pas reculer. `last_seen`, statut de confiance et nom de l'appareil
ne changent pas à la suite d'une réponse ping. Aucun notifier ou envoi externe.

## QA — vérifications et limites

Les tests utilisent uniquement des sorties inventées, des sous-processus remplacés,
une horloge injectée et des bases SQLite temporaires. Ils couvrent double opt-in,
hors périmètre, IPv6, CIDR, réseau/broadcast, bornes, absence de ping, permission,
timeout, formats Windows/Linux, perte partielle/totale, SIGINT, DHCP, conflit d'IP,
observation périmée, changements concurrents, migrations V1/V2, idempotence et verrou SQLite.

```bash
pytest tests/unit/test_ping.py tests/integration/test_monitoring.py -q
ruff check .
ruff format --check .
mypy
pytest --cov --cov-report=term-missing
bandit -r src
pip-audit
```

**Non testé sur matériel réel** : aucun LAN, pare-feu, Raspberry Pi ou Windows réel.
La CI teste Windows et Linux avec les mêmes transports simulés, pas les droits ICMP
ni les sorties de toutes les versions/locales de ping. Un appareil peut refuser ou
limiter ICMP alors qu'il est connecté ; `offline` signifie uniquement « aucune réponse
ICMP pendant ce cycle ». Il n'y a ni seuil de plusieurs cycles avant transition,
ni ordonnanceur, rétention, notifier ou mesure d'uptime temporel dans ce lot.
Le cycle est séquentiel, jusqu'à 64 appareils fois 5 tentatives fois 5,5 secondes
(plus surcoût système), et n'est pas un test de débit. La base continue de croître :
sans rétention M3, ne pas planifier encore une exécution longue sans surveillance.

Pour le test terrain, adapter `allowed_subnets`, découvrir une cible de son propre
réseau puis exécuter explicitement la commande ci-dessus. Comparer réponses ICMP et
connexion réelle, éteindre/rallumer une cible de test et observer les transitions.
Sauvegarder la base avant migration V2 ; une version ancienne du programme refusera
ensuite le schéma plus récent. Aucune fusion automatique de cette PR.
