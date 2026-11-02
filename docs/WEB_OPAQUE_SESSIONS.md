# Sessions web opaques

SessionStore est le composant memoire utilise par browser_auth. Sur la branche d'integration, app.py raccorde ce module au dashboard ; voir WEB_SESSION_INTEGRATION.md pour le parcours web et ses limites. Aucun controle routeur n'est active par ces sessions.

Le composant emet un secret aleatoire de 32 octets par session, expire les sessions apres huit heures sans prolongation, permet une revocation individuelle et limite la capacite a 128 sessions par defaut. A saturation, il refuse une nouvelle session sans expulser une session valide. Son verrou protege les operations concurrentes dans un seul processus.

Limites : stockage memoire, invalidation au redemarrage, pas de partage multi-processus. Le jeton opaque reste un secret porteur : ne pas le journaliser, le placer dans une URL ou l'exposer dans les messages d'erreur. La securite du transport HTTP n'est pas assuree par ce composant.

Les tests unitaires couvrent unicite, revocation isolee, expiration absolue, capacite concurrente et entrees invalides. Ils ne prouvent pas a eux seuls l'integration web ni l'isolation des confirmations ControlGuards.

Commande : python -m pytest tests/unit/test_web_sessions.py

Tests non executes par l'assistant ; CI, lint et typage restent a verifier.
