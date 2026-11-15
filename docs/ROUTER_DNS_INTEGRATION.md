# Identification par le DNS du routeur

## Installation et migration

La migration v5 crée `network_identity_observations` et ses index. Les migrations v1 à v4 restent inchangées. Le nom historique `NETWORK_IDENTITY_V4` désigne le SQL initialement proposé ; son installation officielle utilise la version 5, car la version 4 est déjà occupée par `scans.degraded`.

Sauvegarder la base avant la mise à jour, puis lancer `nettracker init-db --config config.toml`. Le dashboard refuse une base dont la version est antérieure ; il ne la migre pas lui-même.

## Collecte explicite

La commande `nettracker identify-dns --help` décrit les options. Elle exige `--device-id ID`, `--dns-server IPV4` et `--enable-dns`, avec `--config config.toml` si nécessaire. Remplacer ID et IPV4 par l’appareil découvert et le serveur DNS local autorisé ; ce ne sont pas des valeurs à copier telles quelles. `--timeout` accepte 0,2 à 5 secondes (1,5 par défaut).

La commande n’ouvre qu’une base existante au schéma courant, sans création ni migration automatique. Elle interroge un seul appareil enregistré, via le serveur explicite : tous deux doivent appartenir à `allowed_subnets`. Aucun repli vers un résolveur système ou public. Les appareils ignorés, fusionnés, sans observation exploitable ou associés à une IP ambiguë sont refusés avant la requête. Le rattachement MAC/IP est revérifié au stockage.

Le nombre affiché compte les observations enregistrées, y compris un résultat d’échec DNS ; un code de sortie 0 ne garantit donc pas qu’un nom a été trouvé.

## Fiche appareil

Le bloc « Noms DNS enregistrés » présente les noms ou résultats des tentatives, le serveur interrogé et les dates de récupération et de stockage. Il affiche les observations du rattachement MAC/IP actuellement enregistré, parmi les 100 dernières informations d’identité. Un changement de rattachement masque les anciennes observations sans les effacer.

L’alias manuel et le titre de fiche restent inchangés. Un échec récent n’efface pas un ancien nom. Afficher ou actualiser la fiche ne lance aucune collecte ; le bloc ne modifie pas la liste d’accueil.

## Limites et validation

Un nom PTR est une déclaration DNS, pas une preuve de marque, de modèle ou de présence actuelle. Cette étape ne collecte pas de modèles matériels et ne réalise pas encore d’enrichissement automatique de tous les appareils.

Les tests ajoutés utilisent SQLite temporaire et des transports DNS simulés : migration, conservation des données, collecte et stockage, commande, affichage, échappement HTML et changement d’IP. Ils ne sont pas exécutés dans cette session ; leur résultat doit être vérifié en CI. Aucun test sur matériel ou réseau réel n’est déclaré.
