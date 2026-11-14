# Intégration de l’identité DNS du routeur

## Stockage : schéma version 5

La migration v5 installe `network_identity_observations` et ses index via le mécanisme habituel de `nettracker init-db`. Les migrations v1 à v4 restent inchangées. La constante existante `NETWORK_IDENTITY_V4` conserve son nom pour compatibilité avec le module et ses tests ; elle fournit le SQL de la migration installée en version 5, la version 4 étant déjà utilisée par `scans.degraded`.

Les informations d’identité restent séparées des alias manuels, du statut de confiance et des mesures de présence. Le stockage existant vérifie le rattachement MAC/IP et conserve la source, le serveur interrogé et les dates. Un nom DNS n’est pas une preuve de marque ou de modèle.

Avant toute mise à jour réelle, sauvegarder la base puis appliquer `nettracker init-db --config config.toml`. Le dashboard refuse les versions de schéma antérieures à celle attendue ; il ne migre pas lui-même la base.

## Périmètre de ce premier commit

Seule la migration est raccordée. Ce commit ne déclenche aucune collecte DNS et n’ajoute pas encore d’affichage dans le dashboard. Ces raccordements feront partie des commits suivants sur la même branche.

Les nouveaux tests utilisent uniquement SQLite temporaire et des données synthétiques. Ils couvrent une base neuve, la migration depuis v4, la conservation de l’inventaire, l’idempotence et la relecture d’une observation après réouverture. Leur résultat reste à vérifier en CI ; aucun test sur matériel réel n’est déclaré.
