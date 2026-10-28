# Base IEEE MA-L : chargement local

## Source et limites

La source officielle est le CSV public de la Registration Authority IEEE :
`https://standards-oui.ieee.org/oui/oui.csv`. Les colonnes utiles sont
`Registry`, `Assignment` et `Organization Name`. Une affectation MA-L
identifie le titulaire d'un préfixe, pas nécessairement la marque commerciale
du produit final, et ne fournit pas le modèle. Les MAC locales/privées et
multicast ne sont pas attribuées à un fabricant par la recherche.

## Chargement automatique

La collecte tente de lire `data/oui/oui.csv` depuis le dossier de lancement
si aucune table de fabricants n'est fournie explicitement. Ce chemin est
relatif au répertoire courant, pas au dossier du fichier de configuration.
Une lecture est effectuée par collecte, pas par appareil. Le fichier est
limité à 8 Mio ; UTF-8 avec ou sans BOM est accepté.

L'option existante `scan-once --oui-file CHEMIN` garde la priorité. Une
table explicitement fournie, même vide, désactive le recours au fichier
par défaut. L'import `nettracker.discovery.vendor.parse_ma_l_csv` reste
compatible après déplacement du lecteur dans `oui_registry`.

Une base absente n'empêche pas la découverte. Une base invalide, vide,
trop volumineuse ou illisible est ignorée avec un avertissement (absence
simple journalisée en DEBUG). Aucun téléchargement ni appel externe
n'est déclenché par le chargement. Les garde-fous de découverte et de
suivi restent inchangés.

## Périmètre de ce premier commit

Aucune base complète n'est embarquée et aucun installateur ou outil de
mise à jour n'est encore livré. Sans fichier installé, les fabricants
ne se remplissent donc pas. L'installation/mise à jour explicite est
l'étape suivante ; les conditions IEEE devront être vérifiées avant toute
redistribution d'une base complète. Les CSV locaux sont ignorés par Git.

## Validation

Onze tests de lecture ont réussi dans un environnement isolé avec des
fichiers synthétiques et sans réseau. Deux cas supplémentaires de collecte
avec SQLite réelle et voisins injectés sont ajoutés mais n'ont pas été
exécutés ici. La suite complète, les anciens tests de fabricants, les
contrôles de qualité et la CI Windows/Linux restent à exécuter. Aucun
test sur le matériel ou le réseau du propriétaire n'a été effectué.
