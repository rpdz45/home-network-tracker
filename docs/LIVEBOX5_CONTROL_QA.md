# QA de la session de contrôle Livebox

Le fichier `tests/unit/test_livebox5_control_failures.py` complète les
tests du parcours normal avec un transport HTTP entièrement simulé.

Scénarios ajoutés :

- timeout après modification simulée, refus HTTP d'écriture, relecture
  contradictoire ou illisible : résultat incertain, une seule écriture ;
- calendrier absent, JSON invalide, réponse trop grande, redirection :
  aucun changement si la lecture initiale n'est pas exploitable ;
- appareil de gestion, passerelle, adresse du routeur, cible hors périmètre
  et contrôle désactivé : aucune connexion ;
- blocage déjà forcé : pas de réécriture ;
- retrait du forçage ou absence de forçage alors que le calendrier interdit
  encore l'accès : état bloqué conservé dans le résultat, sans annoncer
  une autorisation Internet.

Le scénario timeout simule une modification appliquée avant la perte de
réponse. Il vérifie l'absence de nouvel essai, pas l'état d'une vraie box.
Les assertions de confidentialité portent sur les erreurs affichées, pas
sur une garantie d'effacement des secrets en mémoire.

Tests rédigés mais non exécutés par l'assistant. CI à vérifier après
publication : Ruff, formatage, mypy, pytest et contrôles de sécurité.
Aucun code applicatif modifié, aucun paquet vers une box réelle.
Ces tests ne certifient ni le protocole du firmware du propriétaire,
ni la protection web ou contre les actions concurrentes restant à raccorder.
