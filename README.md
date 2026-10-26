# Home Network Tracker

Outil local de suivi du réseau domestique : découverte des appareils, mesures ICMP, événements et dashboard FastAPI/Jinja2. Les données sont stockées sur ta machine dans SQLite, sans télémétrie.

## État du projet

Disponibles : configuration validée, découverte passive, ARP actif explicitement autorisé, repli nmap optionnel et borné, fabricants OUI locaux, DNS inverse/mDNS optionnels, suggestions pour MAC aléatoires, liste known_devices, monitor-once, rétention de l’historique, santé du collecteur et traitement des alertes en dry-run.

Le dashboard M5 est disponible : liste et fiche des appareils, événements, santé du collecteur, alias/type, marquage comme connu et historique ICMP 24 h / 7 jours. Les graphiques agrègent les sondes de la fenêtre en 96 créneaux, sans dépendre des 25 observations du tableau.

Restent notamment à livrer ou valider : planification continue, notifiers Discord/Telegram/e-mail, règles avancées, déploiement M6 et tests sur matériel réel. Le ratio réponses/sondes n’est pas un uptime temporel ; les créneaux sans mesure restent inconnus. La feuille de route de [AGENTS.md](AGENTS.md) reste la référence : les jalons complets ne sont pas déclarés terminés par cette liste.

## Avertissement et prérequis

Ne scanne que tes propres réseaux. Aucun usage sur un réseau professionnel sans accord écrit du service IT. Voir [SECURITY.md](docs/SECURITY.md).

Python 3.11 ou plus. Le mode passif ne demande pas de privilèges. ARP brut : Npcap/droits administrateur sous Windows, root ou CAP_NET_RAW sous Linux/Raspberry Pi OS ; isoler ces privilèges du dashboard. Le binaire nmap est facultatif et doit être installé dans le PATH si son repli est explicitement activé.

## Installation de développement

Linux / Raspberry Pi OS / macOS :

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
pre-commit install
```

Windows (PowerShell) :

```powershell
py -3.11 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
pre-commit install
```

Service, Docker et tâche planifiée : jalon M6, pas encore fournis par ces commandes.

## Configuration et démarrage du dashboard

1. Copier config.example.toml vers config.toml et adapter allowed_subnets à ton réseau. Seules les plages privées RFC 1918 de préfixe /16 ou plus long sont acceptées.
2. Copier .env.example vers .env pour les secrets. config.toml et .env sont ignorés par Git ; ne jamais committer un jeton réel.
3. Valider, initialiser la base puis démarrer :

```bash
nettracker check-config --config config.toml
nettracker init-db --config config.toml
nettracker serve --config config.toml
```

Le dashboard écoute par défaut sur http://127.0.0.1:8080. Il n’effectue ni découverte ni ping : il lit les données enregistrées par les commandes séparées. Recharger la page pour voir les nouvelles données.

Sans jeton, l’accès loopback est en lecture seule. Pour activer les modifications, définir un jeton long et aléatoire dans NETTRACKER_API_TOKEN dans .env, redémarrer puis se connecter via /login. Les écritures exigent ce jeton même en local. Toute écoute hors loopback exige également un jeton. HTTP reste en clair : réseau de confiance seulement ou proxy TLS géré par le propriétaire.

Le fichier de configuration se choisit avec --config ou NETTRACKER_CONFIG. Pour le jeton, le chemin de base et le niveau de log : environnement, puis .env, puis config.toml. Défauts prudents : découverte passive, suivi désactivé, alertes dry-run, API sur loopback.

## Appareils et historique

La fiche permet de modifier alias/type et d’approuver un appareil inconnu. Un alias vide retombe sur le nom d’hôte puis la MAC. Les appareils fusionnés ne sont pas modifiables ; les ignorés ne sont pas approuvés implicitement. Les événements historiques restent présents. Aucun bouton de révocation du statut connu n’est livré dans ce lot.

known_devices = [] se configure à la racine de config.toml, avant [scan]. Les MAC sont normalisées ; doublons, multicast, broadcast et MAC nulle sont refusés. La liste ne lance aucun scan et ne précrée aucun appareil. Retirer une MAC ne révoque pas son statut persisté. Une MAC peut être usurpée : connu est un classement manuel, pas une authentification.

Les fenêtres 24 h / 7 jours utilisent des créneaux de 15 / 105 minutes. Les dates sont en UTC, fin exclue et tronquée à la seconde. Les barres indiquent les moyennes de latence des réponses ; le tableau dépliable fournit aussi les maxima et les nombres de sondes. Aucun remplissage des périodes vides ni interpolation. Une non-réponse ICMP ne prouve pas une déconnexion. Voir [M5_DASHBOARD.md](docs/M5_DASHBOARD.md) et [M5_HISTORY_CHARTS.md](docs/M5_HISTORY_CHARTS.md).

## Collecte et commandes

```bash
nettracker --help
nettracker --version
nettracker check-config [--config CHEMIN]
nettracker init-db [--config CHEMIN]
nettracker serve [--config CHEMIN]
nettracker scan-once [--config CHEMIN] [--resolve-names] [--resolve-mdns] [--oui-file CHEMIN]
nettracker monitor-once [--config CHEMIN] --device-id ID [--device-id ID] --enable-monitoring
nettracker prune-history [--config CHEMIN] [--apply]
nettracker health-check [--config CHEMIN]
nettracker process-alerts [--config CHEMIN]
```

init-db est relançable et applique les migrations. Sauvegarder la base avant une migration ou une suppression réelle.

### Découverte et noms

scan-once lit le cache de voisins par défaut. ARP actif exige scan.mode="active", --enable-active et --target explicitement autorisée par allowed_subnets. Le repli nmap exige aussi scan.nmap_fallback=true, ne s’active qu’après échec de l’ARP brut et reste borné. Voir [M2_PASSIVE.md](docs/M2_PASSIVE.md).

La résolution DNS inverse reste désactivée sans --resolve-names ; elle peut contacter un résolveur hors LAN. mDNS exige scan.mdns_enabled=true et --resolve-mdns ; mdns_timeout_seconds vaut 1 seconde par défaut (0,1 à 5 secondes). Une seule requête PTR unicast UDP/5353 par IPv4 observée et autorisée, sans découverte de services, multicast ou IPv6. Ce cycle est actif, même après repli vers le cache système. Aucun privilège brut n’est nécessaire pour ce socket UDP ; le pare-feu peut le bloquer.

Avec --resolve-mdns et --resolve-names, mDNS précède le DNS inverse en l’absence de nom. Les noms .local retenus restent des indices non authentifiés, sans confiance ou fusion automatique. Les équipements multicast-only peuvent être manqués ; le délai cumulé dépend du nombre d’IP. Voir [MDNS.md](docs/MDNS.md).

### Mesures ICMP

monitor-once exige monitor.enabled=true et --enable-monitoring, uniquement pour les appareils explicitement sélectionnés, récemment découverts et dans le périmètre autorisé. Les latences, pertes et transitions restent locales. Pas encore de planification continue intégrée. Voir [M3_MONITORING.md](docs/M3_MONITORING.md).

### Rétention

prune-history ne supprime que les anciens échantillons source=ping, jamais les appareils, découvertes, événements ou notifications. Aperçu par défaut ; suppression réelle uniquement avec retention.enabled=true et --apply. Paramètres : keep_days=30 (1 à 3650), batch_size=500 (1 à 5000), max_batches=100 (1 à 1000). Au plus batch_size × max_batches lignes par exécution ; relancer si nécessaire. Pas de planification automatique.

### Santé et alertes

health-check indique le dernier scan réussi et les erreurs récentes. Au-delà de health.stale_after_minutes (15 par défaut), collector_stale est enregistré une fois par panne et le code de sortie vaut 3. La commande ne tourne pas seule et n’envoie rien. Voir [M3_HEALTH.md](docs/M3_HEALTH.md).

process-alerts traite les événements enregistrés avec anti-spam par type/appareil (alerts.cooldown_minutes=30 par défaut). Le statut to_confirm des MAC privées ne déclenche pas d’alerte. Aucun notifier n’est encore livré : dry-run enregistre des notifications locales sans envoi, et le mode réel est refusé. Voir [M4_ALERTS.md](docs/M4_ALERTS.md).

## Qualité et limites de validation

```bash
ruff check .
ruff format --check .
mypy
pytest --cov
bandit -r src
pip-audit
```

La CI vérifie la qualité sur Linux et Windows et recherche les secrets avec gitleaks. Une CI verte ne remplace pas les essais sur matériel réel. Aucun test du projet ne doit envoyer de paquets réels ; les tests HTTP utilisent un client en processus, une horloge fixe et des données de test, sans navigateur réseau.

Ce lot de consolidation ajoute dix fonctions de test HTTP, dont cinq cas paramétrés de période invalide. Leur syntaxe et la longueur des lignes ont été vérifiées pendant la préparation, mais leur exécution et Ruff restent à valider en CI. Ne pas les présenter comme réussis avant ce contrôle. Les essais navigateur/mobile, charge et LAN restent à réaliser.

## Documentation

- [ARCHITECTURE.md](docs/ARCHITECTURE.md), [SECURITY.md](docs/SECURITY.md), [TESTING.md](docs/TESTING.md)
- [M2_PASSIVE.md](docs/M2_PASSIVE.md), [MDNS.md](docs/MDNS.md)
- [M3_MONITORING.md](docs/M3_MONITORING.md), [M3_HEALTH.md](docs/M3_HEALTH.md)
- [M4_ALERTS.md](docs/M4_ALERTS.md)
- [M5_DASHBOARD.md](docs/M5_DASHBOARD.md), [M5_DEVICE_EDITS.md](docs/M5_DEVICE_EDITS.md), [M5_HISTORY_CHARTS.md](docs/M5_HISTORY_CHARTS.md)
- [AGENTS.md](AGENTS.md) : feuille de route et règles de contribution

## Licence

MIT, voir [LICENSE](LICENSE).
