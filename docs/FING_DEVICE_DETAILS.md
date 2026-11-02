# Identifications Fing sur la fiche appareil

Après confirmation du stockage, la fiche `/devices/ID` affiche le modèle, le fabricant, le nom et la catégorie déclarés par Fing. Ces champs sont distincts de l'alias personnel, du type renseigné et du fabricant de l'interface réseau.

La section donne la source API locale Fing, la récupération API et l'enregistrement local en heure de Paris. Elle indique l'IPv4 du rapprochement au stockage : cette adresse est historique, pas une garantie de l'IP actuelle. Les dates ne sont ni la date du dernier scan ni une preuve de présence actuelle. Les informations sont déclarées, non vérifiées indépendamment.

Une fiche sans identification conserve un message explicite. Un champ absent reste « Non identifié ». Une fiche fusionnée ou dont la MAC ne correspond plus à celle enregistrée n'affiche pas ce rapport. Un changement ultérieur d'IP n'efface pas le rapport historique ; il ne constitue pas une nouvelle validation.

Consulter la fiche ne contacte pas Fing, ne déclenche aucun scan et ne rafraîchit pas les données enregistrées. Les identifications déjà stockées restent lisibles lorsque l'intégration Fing est désactivée. Elles suivent la politique d'accès existante du dashboard : lecture locale sans jeton possible ; jeton exigé selon la configuration d'exposition. Les textes fournisseur sont échappés par Jinja2 et ne sont pas interprétés comme du HTML.

Aucune nouvelle migration n'est ajoutée. Le schéma V3 existant doit déjà avoir été appliqué explicitement. Voir [le parcours de stockage](FING_STORAGE_DASHBOARD.md).

## Validation prévue

`pytest tests/unit/test_web_fing_details.py tests/unit/test_device_information.py tests/unit/test_web.py`, puis l'ensemble de la CI. Les nouveaux tests utilisent SQLite, des déclarations synthétiques et un lecteur Fing interdit ; ils couvrent l'affichage, les champs absents, l'échappement, la fusion, la MAC modifiée et l'absence de modification des données sur une lecture.

Tests rédigés, non exécutés lors de la préparation de ce commit. Pas de validation sur navigateur réel, LAN, Fing réel ou base Windows du propriétaire. Les liens depuis README, SECURITY et TESTING restent à compléter dans cette branche avant finalisation.
