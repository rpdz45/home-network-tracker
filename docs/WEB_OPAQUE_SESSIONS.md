# Sessions web opaques : composant preparatoire

Ce lot ajoute uniquement SessionStore et ses tests. Il ne modifie pas app.py : le cookie actuel et l'authentification Bearer restent inchanges. Aucun controle routeur n'est active.

Le composant emet un secret aleatoire de 32 octets par session, expire les sessions apres huit heures sans prolongation, permet une revocation individuelle et limite la capacite a 128 sessions. A saturation, il refuse une nouvelle session sans expulser une session valide. Son verrou protege les operations concurrentes dans un seul processus.

Limites : stockage memoire, invalidation au redemarrage, pas de partage multi-processus. Le jeton opaque reste un secret porteur : ne pas le journaliser, le placer dans une URL ou l'exposer dans les messages d'erreur.

Integration a realiser : emission uniquement apres authentification et verification anti-CSRF du login, cookie HttpOnly/SameSite et Secure selon le deploiement HTTPS, expiration serveur coherente avec le cookie, deconnexion protegee, maintien du Bearer pour les routes existantes. Les futures confirmations de controle devront exiger une session navigateur valide ; ne pas leur attribuer une identite commune derivee du jeton partage.

Les tests couvrent unicite, revocation isolee, expiration absolue, capacite concurrente et entrees invalides. Ils ne prouvent ni integration web ni isolation des confirmations ControlGuards.

Commande : python -m pytest tests/unit/test_web_sessions.py

Tests non executes par l'assistant ; CI, lint et typage restent a verifier.
