# Base IEEE MA-L (fabricants)

La source officielle est le fichier CSV public `oui.csv` de la Registration Authority de l'IEEE (`https://standards-oui.ieee.org/oui/oui.csv`). Il comporte les colonnes `Registry`, `Assignment`, `Organization Name` et `Organization Address`. Les fichiers publiés par l'IEEE sont en UTF-8.

`nettracker.discovery.vendor.parse_ma_l_csv` lit ce format localement ; `lookup_vendor` utilise les 24 premiers bits des MAC universelles et renvoie `None` pour les MAC localement administrées, inconnues ou non publiées. Une affectation MA-L identifie le titulaire du préfixe, pas nécessairement le fabricant du produit final.

Aucune base complète n'est encore embarquée dans cette PR, aucun téléchargement n'est automatique, et les tests utilisent des données inventées. Avant d'intégrer ce résultat au collecteur, choisir une méthode de mise à jour vérifiable de la liste officielle et vérifier ses conditions de réutilisation.
