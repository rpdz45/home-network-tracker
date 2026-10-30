# Conservation locale des identifications Fing

La lecture Fing reste facultative. Le dashboard exige son jeton de connexion, NETTRACKER_FING_ENABLED=true et une clé NETTRACKER_FING_API_KEY côté serveur. Ne jamais committer une clé réelle.

## Parcours

1. Sauvegarder la base puis appliquer explicitement les migrations avec `nettracker init-db --config config.toml` avant de démarrer le dashboard. Les routes ne créent ni ne migrent la base.
2. Ouvrir `/identification/fing`, confirmer la lecture et consulter les résultats.
3. Cocher la confirmation de conservation locale, distincte de l'autorisation de lecture, puis sélectionner « Enregistrer les correspondances dans SQLite ».
4. Lire le bilan : enregistrées, inchangées et sans correspondance actuelle. Ce bilan ne remplace pas l'affichage persistant sur la fiche appareil, hors de ce lot.

L'aperçu est conservé côté serveur : le navigateur envoie seulement un jeton opaque, un jeton CSRF et la confirmation. Les champs fabricant/modèle fournis par le navigateur sont refusés. L'aperçu est à usage unique et valable au plus dix minutes ; la date de récupération API est également vérifiée par la couche de stockage.

Un seul aperçu existe par processus. Une nouvelle lecture remplace l'ancien aperçu pour tous les onglets utilisant ce processus. Le redémarrage ou un autre worker peut rendre le jeton inutilisable : refaire une lecture. Prévoir un seul worker pour ce parcours ; aucun cache partagé multiworker n'est fourni.

Le stockage ne relance pas Fing ni un scan. Il revérifie les correspondances MAC/IP avec les découvertes locales actuelles, sans créer d'appareil, changer les alias, approuver la confiance ou rafraîchir la présence. Les résultats restent des déclarations du fournisseur, pas des identités vérifiées indépendamment.

Après un échec de stockage, le jeton est consommé : refaire une lecture avant de réessayer. Une nouvelle tentative de lecture autorisée invalide également l'ancien aperçu, même si l'API échoue.

## Validation

Tests HTTP en processus avec inventaires synthétiques et lecteur Fing remplacé : stockage SQLite, refus de rejeu, authentification, CSRF, origine, confirmation, champs injectés et récupération périmée. Les tests de coffre couvrent expiration et consommation concurrente. Commandes : `pytest tests/unit/test_fing_preview.py tests/unit/test_web_fing_storage.py tests/unit/test_web_fing.py`, puis les contrôles complets de CI.

Ces tests sont ajoutés mais non exécutés au moment de la préparation de ce commit. Aucun test sur Fing réel, navigateur, matériel ou base Windows du propriétaire n'a été effectué. La CI complète et la revue restent obligatoires avant fusion.
