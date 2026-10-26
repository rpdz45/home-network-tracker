# M3 — Rafraîchissement passif optionnel de la boucle ICMP

## Décision

La boucle conserve son fonctionnement précédent sans `--refresh-passive`.
Avec cette option, chaque cycle lit une seule fois le cache de voisins local,
valide l'ensemble du résultat, puis renouvelle uniquement les observations
SQLite des appareils explicitement sélectionnés par `--device-id`.
Aucun nouvel appareil n'est inscrit par ce rafraîchissement.
Le statut de confiance des appareils sélectionnés reste inchangé.

Le monitoring exige toujours `monitor.enabled=true` et `--enable-monitoring`.
Le rafraîchissement exige aussi `scan.mode="passive"` ; une configuration active
est refusée, sans repli sur ARP brut ou nmap. Aucun DNS, mDNS ou téléchargement
OUI n'est déclenché. Seuls les pings déjà explicitement autorisés sont actifs.

## Exemple à exécuter uniquement sur son propre réseau

Après configuration des sous-réseaux autorisés, initialisation de la base et
sélection des identifiants existants :

```sh
python -m nettracker.monitor.loop --config config.toml --device-id 1 --enable-monitoring --refresh-passive --cycles 3 --interval-seconds 60
```

Cet exemple peut envoyer des pings ; il n'a pas été exécuté sur un réseau réel
pendant la préparation de ce lot. Sans `--refresh-passive`, aucune lecture du
cache n'est ajoutée et une découverte périmée continue de bloquer le monitoring.

## Refus et limites

- Refus avant écriture et ping si un appareil sélectionné est absent du cache,
  si une MAC sélectionnée possède plusieurs IP, ou si son IP possède plusieurs
  MAC dans le résultat courant, y compris une MAC non sélectionnée.
- Refus des appareils inexistants, ignorés ou fusionnés ; sélection limitée à
  64 identifiants positifs. Refus dans une transaction SQLite déjà ouverte.
- Revalidation des IPv4 privées autorisées, adresses réseau/broadcast et MAC
  unicast. Le résultat du lecteur est limité à 4096 entrées, doublons compris.
  Ce plafond ne limite pas les octets de sortie alloués par le lecteur système.
- La lecture du cache et les pings se font sans verrou de transaction prolongé.
  Les contrôles de fraîcheur, de propriétaire d'IP et de concurrence du service
  ICMP restent appliqués après la persistance du rafraîchissement.
- Un arrêt SIGTERM reçu pendant le rafraîchissement empêche le ping suivant ;
  l'opération de lecture déjà commencée se termine avec son timeout existant.
- Une erreur interrompt la boucle sans réessai automatique. Un échec de ping ne
  supprime pas les observations passives déjà validées et enregistrées.
- Le cache peut être ancien, statique ou usurpé. Le lecteur actuel ne fournit
  aucun âge d'entrée et accepte notamment des entrées Linux STALE. L'horodatage
  renouvelé signifie « relu dans le cache », pas « présence récemment prouvée ».
  Un cache périmé mais cohérent peut donc prolonger une association obsolète.
  Le ping n'authentifie pas une MAC. Ne pas utiliser cette option comme preuve
  d'identité ou de sécurité ; elle est désactivée par défaut pour cette raison.
- Un appareil éteint absent du cache arrête la boucle plutôt que de produire
  artificiellement une mesure hors ligne sur une ancienne IP.
- Les observations de découverte et scans s'accumulent par cycle. La rétention
  des seules mesures ping ne les purge pas ; aucune autonomie longue durée,
  consommation bornée de disque ou clôture complète de M3 n'est annoncée.

## Vérification

Tests préparés sur migrations SQLite réelles, lecteurs et sondes simulés :
changement d'IP, absence et ambiguïtés, périmètre invalide, MAC invalides,
activation et sélection, transaction ouverte, erreur et taille du cache,
ordre CLI et absence de monitoring après erreur de rafraîchissement.
Les backends réels cache et ping sont bloqués dans la fixture.

```sh
pytest tests/integration/test_monitor_refresh.py tests/integration/test_monitor_loop.py tests/unit/test_monitor_loop.py -vv
```

Pendant la préparation, seules les vérifications statiques explicitement
rapportées dans la conversation ont été exécutées. Cette commande pytest,
Ruff, mypy, la couverture et les audits doivent être vérifiés par la CI Linux
et Windows. Aucun test matériel, réseau réel, signal réel ou endurance effectué.
