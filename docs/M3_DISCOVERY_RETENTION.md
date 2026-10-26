# M3 — Moteur de rétention de découverte

## Périmètre de ce lot

Module `nettracker.db.discovery_retention`, sans migration, sans modification de
la purge ping existante, sans commande CLI et sans purge automatique dans la boucle.
`retain_discovery(conn, now)` retourne un aperçu sans modifier les données.
Seul `enabled=True` active les suppressions ; aucun appel de production ajouté.
Le raccordement ultérieur à la CLI devra exiger une activation en configuration
et une confirmation explicite de suppression, comme la purge ping existante.

## Politique

- Seules les observations `source='discovery'` strictement antérieures au seuil
  sont candidates ; la dernière de chaque appareil reste conservée, même ancienne.
  L'ordre `(seen_at DESC, id DESC)` correspond à la sélection du monitoring.
- Les scans ne sont candidats que si début et fin précèdent strictement le seuil.
  Conservation des scans inachevés et de tout scan référencé par une observation,
  quelle que soit sa source. Aucun lien de clé étrangère n'est effacé ou détaché.
- Conservation du dernier succès par date de fin et des cinq derniers problèmes
  par identifiant, pour les besoins du suivi de santé avec son réglage par défaut.
  Un historique de problèmes demandé au-delà de cinq entrées n'est pas garanti.
- Aucun appareil, statut, état de monitoring, ping, événement ou notification supprimé.
- Valeurs par défaut : 30 jours, lots de 500, au plus 100 lots par table. Bornes :
  1–3650 jours, 1–5000 lignes par lot, 1–1000 lots par table. Booléens refusés comme limites.
  Horloge avec fuseau, clés étrangères actives et absence de transaction préexistante exigées.

## Transactions et limites

Les observations sont traitées avant les scans. Les candidats sont recalculés
sous `BEGIN IMMEDIATE` à chaque lot. Un échec annule le lot courant, mais pas les
lots précédemment validés. Une nouvelle exécution peut reprendre le nettoyage.
L'aperçu compte les scans actuellement supprimables, avant la suppression des
observations : il peut en annoncer moins que l'application complète. Ses comptes
sont indicatifs si une autre connexion modifie la base entre les lectures.

Le nombre de lignes supprimées par appel est plafonné séparément pour chaque
table ; la durée d'une requête et le volume de données inspectées ne le sont pas.
L'aperçu parcourt ses résultats sans les charger tous en mémoire. Aucun `VACUUM`,
aucune promesse de réduction immédiate du fichier SQLite ni de taille maximale.

## Vérifications

Treize cas pytest ont passé dans un environnement temporaire : SQLite réel avec
schéma minimal des colonnes utiles, module proposé et exceptions du dépôt.
Ce ne sont pas des tests d'intégration avec les migrations et l'application complète.
Cas : aperçu sans écriture, conservation et ordre chronologique, égalités de dates,
pings préservés, scans parents, santé du collecteur, lots et reprises, seuil strict,
limites invalides, transaction appartenant à l'appelant, rollback du lot fautif,
clés étrangères et horloge naïve. Aucun accès réseau ni base du propriétaire.

Commande après publication : `pytest tests/unit/test_discovery_retention.py -q`.
Ruff, mypy, couverture globale, audits et CI Linux/Windows restent à vérifier.
Les tests d'intégration avec les migrations, le monitoring concurrent, les alertes
et une base volumineuse restent à ajouter avant de présenter M3 comme terminé.
