# M3 — Première boucle ICMP explicitement autorisée

## Périmètre et commande

Ce premier lot ajoute une entrée de module, sans modifier nettracker monitor-once ni ajouter encore une sous-commande nettracker monitor-loop : python -m nettracker.monitor.loop. Le module ne découvre aucun appareil, ne supprime rien, n’envoie aucune notification et ne démarre pas le dashboard. Il ne remplace pas un service système ou une tâche planifiée M6.

L’exécution réelle émet des paquets ICMP uniquement sur les appareils sélectionnés et autorisés. Elle nécessite monitor.enabled=true dans la configuration et --enable-monitoring. alerts.dry_run n’empêche pas ces sondes : ce n’est pas un mode de simulation de la collecte. Remplacer les identifiants des exemples par ceux de tes appareils, sur ton propre réseau seulement.

Exemple borné : python -m nettracker.monitor.loop --config config.toml --device-id 1 --enable-monitoring --cycles 3 --interval-seconds 60. Plusieurs --device-id sont acceptés, jamais d’énumération automatique. Sans --cycles ni --continuous, un seul cycle est exécuté. --continuous est un opt-in explicite et incompatible avec --cycles.

## Ordonnancement

Les cycles sont séquentiels. L’intervalle est un délai après la fin d’un cycle, pas une fréquence départ-à-départ : aucun chevauchement, rattrapage ou lancement en parallèle. Défaut 60 secondes ; entier entre 10 et 86400. Nombre fini de cycles entre 1 et 1000000. L’attente passe par Event.wait, injectable dans les tests ; seuls des compteurs sont conservés en mémoire, pas une liste de résultats.

Chaque cycle appelle le monitor_once existant : activation, 1 à 64 identifiants positifs, périmètre privé autorisé, IPv4, fraîcheur de découverte, conflits d’IP et états ignorés/fusionnés sont revérifiés. Les mesures du cycle restent transactionnelles et aucun verrou SQLite n’est gardé pendant l’attente ou le ping. Une erreur arrête la boucle, sans tentative automatique ; les cycles antérieurs déjà validés restent enregistrés.

La base doit exister et son schéma correspondre à la version du programme. Le module ne lance aucune migration implicite. .env est lu dans le répertoire courant, comme indiqué par l’appel à load_settings. Les erreurs de domaine ou SQLite donnent le code 2 avec le nom de leur classe, sans imprimer leurs détails ni les secrets de configuration. Un résumé des compteurs est affiché à la fin normale ou après interruption traitée.

## Arrêt et fraîcheur

Ctrl+C pendant l’ordonnanceur est traité avec code 130 ; un cycle interrompu n’est pas compté comme terminé. SIGTERM demande l’arrêt via un Event ; une attente est interrompue, mais un cycle déjà en cours peut aller jusqu’à sa fin. Le handler précédent est restauré et la connexion est fermée. Le délai d’arrêt dépend donc des sondes séquentielles déjà en cours et de leurs timeouts ; aucun arrêt instantané n’est garanti. Exécuter l’entrée CLI dans le thread principal.

La boucle ne rafraîchit pas les observations de découverte. Avec max_observation_age_seconds=1800 par défaut, elle finira par refuser une observation devenue périmée. Actualiser séparément la découverte avant de reprendre ; ne pas désactiver le garde-fou pour obtenir artificiellement un fonctionnement 24 h. Le mode continu de ce lot n’est donc pas encore une orchestration autonome découverte/suivi.

## Tests et limites connues

Treize tests ont réussi dans l’environnement de préparation en exécutant le contenu exact du module chargé en mémoire et les tests d’ordonnancement/arguments : cycle unique, répétition, attentes entre cycles uniquement, arrêt avant/durant un cycle, attente interruptible, propagation d’erreur sans reprise, Ctrl+C pendant cycle/attente, bornes et modes CLI incompatibles. Aucune attente réelle, aucun socket, aucun processus ping, aucune donnée du foyer. Syntaxe et limite de 100 caractères vérifiées sur les deux fichiers Python.

Les chemins CLI complets après chargement de la configuration, les imports du paquet installé, les migrations réelles, les signaux système réels, Ruff, mypy, couverture, audits et CI complète n’ont pas été exécutés pour ce lot. Les tests des garde-fous de monitor_once restent nécessaires en CI ; les tests présents ici ne prouvent pas seuls leur intégration sur plusieurs cycles. Aucun test Windows/Linux sur matériel, réseau réel, durée longue ou déploiement. Le jalon M3 complet reste ouvert.

Commande de validation sans réseau : pytest tests/unit/test_monitor_loop.py tests/unit/test_ping.py tests/integration/test_monitoring.py -vv, puis toute la CI. Ne pas fusionner avant revue et CI verte. Le README décrit encore l’absence d’orchestration continue intégrée : cette limite demeure vraie pour l’ensemble découverte/suivi, et cette page précise le nouvel outil de répétition ICMP seul.
