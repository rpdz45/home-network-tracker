# Liste des appareils : présentation et identification enregistrée

## Périmètre

La liste affiche jusqu'à 500 appareils non fusionnés, des plus récemment
observés aux plus anciens. Les compteurs portent sur cette liste, pas sur
un inventaire exhaustif du réseau. Le tableau dispose d'un défilement
horizontal. Les statuts de validation sont traduits sans modifier les
valeurs stockées.

Les dates affichées utilisent le filtre `paris_datetime`. La configuration
du suivi est transmise au rendu sans démarrer de collecteur. Le suivi
configuré, les résultats ICMP historiques et la santé du collecteur restent
distincts : ils ne prouvent ni l'identité d'un appareil, ni sa présence
actuelle, ni le fonctionnement actuel de la boucle de suivi.

## Noms, marque et modèle

Depuis la PR nº 61, les rapports Fing déjà enregistrés peuvent apparaître
directement dans la liste. Le nom principal suit cet ordre de priorité :

1. Alias personnel.
2. Nom réseau enregistré (`hostname`).
3. Nom déclaré dans le rapport Fing associé.
4. Identifiant de repli « Appareil n°… ».

L'alias reste prioritaire et n'est pas remplacé en base par le nom Fing.
Le nom réseau est aussi affiché séparément lorsqu'il est renseigné.

La colonne « Marque et modèle déclarés (Fing) » présente :

- la marque / le fabricant déclaré ;
- le modèle ;
- le nom déclaré ;
- la source Fing et le caractère historique, non vérifié indépendamment ;
- la date de récupération API, qui n'est pas une preuve de fraîcheur
  de l'observation initiale par Fing.

Le fabricant réseau de l'interface reste dans une colonne distincte :
il ne suffit pas à identifier la marque ou le modèle du produit complet.
Une valeur absente reste « Non identifié » ou « Non renseigné ». Sans
rapport associé, la liste indique « Aucune identification enregistrée ».
Les champs Fing optionnels absents ne doivent pas interrompre le rendu,
y compris lorsque Jinja utilise `StrictUndefined`.

## Origine et association des données

La liste lit uniquement les rapports `fing_local_api` stockés localement,
associés au même identifiant d'appareil et à la même adresse MAC. Un rapport
qui ne correspond plus à la MAC de l'appareil n'est pas affiché ; un appareil
fusionné est exclu de la liste. Cette association technique ne constitue
pas une authentification indépendante de l'appareil.

Ouvrir la liste ne lance ni scan, ni appel au lecteur Fing, ni stockage
d'identification. Si aucune identification n'a été enregistrée auparavant,
cette page ne peut pas inventer une marque ou un modèle. Le parcours
d'identification et d'enregistrement volontaire est documenté dans
[FING_STORAGE_DASHBOARD.md](FING_STORAGE_DASHBOARD.md).

## Tests automatisés et validation connue

Les tests de présentation existants restent en place. La PR nº 61 ajoute
des tests du template avec `StrictUndefined` pour les champs Fing absents,
les sources vides, les rapports incomplets, la priorité des noms et
l'échappement HTML.

La PR nº 62 ajoute six cas à travers la vraie route FastAPI et une base
SQLite temporaire :

- rapport enregistré, alias conservé et absence de doublon ;
- rapport absent ;
- modèle absent ;
- modèle contenant du HTML à échapper ;
- changement de MAC ;
- appareil fusionné.

Chaque consultation de ces six cas compare le contenu SQL avant et après
et interdit l'appel au lecteur Fing par remplacement de celui-ci. La
comparaison porte sur les données logiques, pas sur les octets du fichier
SQLite. Les requêtes passent par `TestClient`, sans navigateur réel.

Les contrôles GitHub « Quality (ubuntu-latest) », « Quality
(windows-latest) » et « Secret scan (gitleaks) » ont réussi pour les commits
`cfeebd0` de la PR nº 61 et `40c5b61` de la PR nº 62. Les deux PR ont été
fusionnées le 2 novembre 2026. Ces résultats concernent ces révisions ; ils
ne préjugent pas de la CI d'un commit ultérieur.

Commande ciblée à lancer depuis l'environnement du projet :

```console
python -m pytest tests/unit/test_web_list_fing_storage.py tests/unit/test_web_list_optional_fing.py tests/unit/test_web_list_presentation.py tests/unit/test_web_fing_details.py
```

## Vérification manuelle restant à faire

Aucun contrôle visuel dans un navigateur réel ni aucun essai sur le réseau
ou le matériel du propriétaire n'a été effectué par l'assistant pour ces
lots. Les rapports des tests sont synthétiques.

Lors d'une recette locale, vérifier avec les données déjà enregistrées :

1. La lisibilité du tableau sur une fenêtre étroite et son défilement.
2. La priorité de l'alias et la distinction avec les noms déclarés.
3. L'affichage explicite des modèles absents.
4. La séparation entre fabricant réseau et identification Fing.
5. Les dates, la source et les avertissements sur les données historiques.

Aucune migration, sonde, notification, purge ou modification de
configuration n'est ajoutée par ces changements de liste. Ils ne modifient
pas les mécanismes d'authentification, de protection CSRF ou les en-têtes
de sécurité. Ce guide ne décrit pas la gestion des box ni une nouvelle
fonction de recherche dans la liste.
