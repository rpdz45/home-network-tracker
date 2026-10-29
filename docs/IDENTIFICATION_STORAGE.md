# Conservation locale des identifications Fing

## État de ce lot

Migration et fonctions de stockage uniquement : aucun bouton, nouvelle route
ou affichage persistant raccordé à ce stade. Les écrans Fing existants restent
en lecture seule. Le raccordement au dashboard constitue le correctif suivant.

## Schéma V3

La migration ajoute device_identifications sans modifier V1/V2. Une ligne par
fiche/source fing_local_api conserve : réseau Fing, MAC/IP du rapprochement,
nom annoncé, fabricant, modèle, catégorie, dates UTC de récupération et de
stockage. verification est fixée à reported : aucune confirmation indépendante.
Les champs restent séparés des alias, noms réseau et fabricants d'interface.
Aucune clé API, réponse brute, personne ou présence actuelle enregistrée.

Après fusion et mise à jour, sauvegarder la base avant la commande existante :

```text
nettracker init-db --config config.toml
```

Aucune migration sur la machine du propriétaire n'est lancée ici. Le dashboard
refuse l'ancien schéma jusqu'à sa mise à jour ; pas de migration implicite au GET.

## Écriture et lecture

save_fing_inventory exige confirmed=True, une prévisualisation côté serveur
récupérée depuis au plus 10 minutes et des dates avec fuseau, sans date future.
Source, tailles, MAC unicast non nulles, doublons et IPv4 privées autorisées
sont revérifiés. Ce délai mesure l'âge de récupération API, pas celui d'un scan.
La future route devra vérifier authentification, CSRF et consentement, conserver
le résultat côté serveur et ne pas accepter de modèles forgés par le navigateur.

Un savepoint rend chaque import atomique, même dans une transaction appelante.
Les 500 fiches non fusionnées les plus récentes sont relues dans la transaction,
avec leur dernière IP de découverte, jamais de ping. Seules les correspondances
exactes MAC + IP uniques sont sauvegardées ; les autres sont comptées unmatched.
Aucune création, fusion, approbation ou modification d'alias, de fabricant réseau,
de statut de confiance, de last_seen, d'observation ou de santé du collecteur.

Une date égale ou antérieure ne remplace pas un enregistrement plus récent.
Une réponse plus récente remplace aussi les champs devenus inconnus : on ne
présente pas un ancien modèle comme nouvellement reconnu. ImportSummary expose
stored, unmatched et unchanged. La lecture get_fing_identification est historique,
masquée si la fiche est fusionnée ou sa MAC différente ; un changement ultérieur
d'IP n'en fait jamais une preuve de présence. L'écran devra montrer source et dates.

Connexion du projet avec sqlite3.Row et clés étrangères, requêtes paramétrées,
erreurs sans valeurs privées ni message SQL brut. Pas de réseau, réessai,
télémétrie, blocage ou modification de politique globale. Dernière identification
par fiche/source, pas un historique illimité. Aucune rétention supplémentaire.

## Vérifications

18 cas pytest sur SQLite réel ont passé isolément : migration V2→V3, préservation,
idempotence, dates, champs inconnus, DHCP, fusion, périmètre, doublons, rollback
imbriqué, verrou et texte fournisseur paramétré. Dataclasses Fing reproduites,
helpers MAC/date/périmètre extraits et exceptions minimales dans ce banc.
Cela ne remplace pas la suite complète ; aucune donnée du propriétaire utilisée.

```text
python -m pytest tests/unit/test_identifications.py tests/unit/test_db.py
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest --cov
```

Ruff, mypy et CI Linux/Windows restent à vérifier avant fusion. Aucun test
matériel ni ouverture de la base Windows du propriétaire.
