# M5 — Aperçu graphique des mesures ICMP

## Périmètre de ce premier lot

La fiche appareil inclut history.html avant le tableau des mesures. Le composant réutilise les 25 dernières observations déjà chargées, toutes sources confondues, puis sélectionne uniquement source=ping. Aucune requête, migration, route, dépendance ou sonde supplémentaire. Aucun JavaScript, CDN, télémétrie ou assouplissement de la CSP. Les formulaires protégés restent inchangés.

Les barres représentent les latences des réponses, dans l’ordre chronologique des mesures. L’espacement est par observation et non par durée. Les non-réponses affichent une croix : aucune latence mesurée, pas 0 ms. Une réponse valide de 0 ms reste une réponse (barre avec minimum visuel de 2 px). L’échelle verticale a un minimum de 1 ms et s’adapte au maximum affiché. Les valeurs exactes et dates restent dans le tableau existant.

Le second graphique indique réponse/non-réponse pour chaque sonde. Le pourcentage est le nombre de mesures avec réponse divisé par le nombre de mesures ICMP affichées : ce n’est ni un uptime temporel ni un taux de paquets reçus. Aucune interpolation entre les mesures. La disponibilité avant, après et entre les observations reste inconnue et est signalée explicitement. Une absence de réponse ICMP ne prouve pas une déconnexion.

## Limites et suite du jalon

Ce lot est un aperçu compact, pas une courbe temporelle sur 24 h ou 7 jours. Une activité de découverte importante peut évincer les anciens pings des 25 observations affichées. Aucun calcul sur tout l’historique, aucune pagination, aucune représentation de durée des pannes. Les périodes sans mesure ne sont pas inventées. Le jalon M5 complet reste ouvert : requête historique dédiée, axe temporel, fenêtres sélectionnables et politique explicite des lacunes à traiter dans un lot ultérieur.

Le tableau permet de lire les données sans dépendre des infobulles ou de la couleur ; le composant indique son contenu aux technologies d’assistance. Rendu navigateur/mobile et accessibilité pratique non vérifiés.

## Tests et validation

Sept tests de rendu Jinja ont réussi dans l’environnement de préparation, avec le contenu exact de history.html chargé via DictLoader. Seul le chargeur de fichiers du setUp a été remplacé pour cette exécution ; le chargement depuis les fichiers du dépôt et l’intégration FastAPI seront vérifiés par la CI. Fixtures synthétiques de test uniquement, aucune donnée du foyer : absence de mesures, découverte exclue, ordre chronologique, ratio sur les échantillons, non-réponse, latence nulle, échappement HTML et borne de 25 observations.

Syntaxe Python et longueur des lignes du nouveau fichier de test vérifiées. Ruff, mypy, suite complète, audits de sécurité et CI non exécutés pour ce commit. Aucun test réseau ou matériel réel. Commande ciblée : pytest tests/unit/test_history_charts.py tests/unit/test_web.py tests/unit/test_web_edits.py -vv. Fusion uniquement après revue et CI complète verte.
