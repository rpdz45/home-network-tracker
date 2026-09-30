# Découverte passive M2

`nettracker scan-once --config config.toml` initialise la base si nécessaire, lit une fois la table de voisins du système et enregistre uniquement les adresses IPv4 privées présentes dans `allowed_subnets`. La commande ne lance ni balayage ARP ni scan de ports. Elle refuse `scan.mode = "active"` tant que la découverte active n'est pas implémentée.

Pour renseigner le titulaire d'un préfixe MAC, fournir un CSV IEEE MA-L local avec `nettracker scan-once --config config.toml --oui-file CHEMIN`. La commande ne télécharge rien ; un fichier absent ou mal formé est refusé avant ouverture de la base. Les MAC localement administrées restent sans fabricant déduit. La base complète n'est pas embarquée ; la source officielle et les réserves d'interprétation figurent dans `data/oui/README.md`.

La table système ne contient que les voisins déjà connus de la machine ; zéro résultat ne signifie donc pas qu'aucun appareil n'est connecté. Sous Linux, la commande utilise `ip -4 neigh show` (outil `ip` requis) ; sous Windows, `arp -a`. Le mode cache uniquement est annoncé dans les logs. Les tests de la CLI remplacent le collecteur et les tests SQLite injectent un lecteur simulé : aucun paquet n'est émis par les tests et aucun réseau réel n'a été vérifié.

Les paramètres du propriétaire non renseignés dans `AGENTS.md` conservent les défauts de la section 3 : mode passif, SQLite local, API sur loopback et alertes en dry-run. Le CIDR doit néanmoins être indiqué explicitement dans la configuration ; aucun sous-réseau n'est deviné ou scanné par défaut. La configuration du matériel, des notifications et des priorités reste à préciser.
