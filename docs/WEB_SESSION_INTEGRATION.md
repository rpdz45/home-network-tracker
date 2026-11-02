# Routes de sessions navigateur : integration en cours

Le module browser_auth fournit login, formulaire de confirmation de deconnexion, deconnexion POST et dependance d'authentification. Il utilise SessionStore et preserve Bearer sans creer de session navigateur pour ce dernier.

IMPORTANT : app.py n'est pas encore raccorde. Les tests utilisent une application FastAPI isolee, pas le dashboard. L'ancien cookie reste utilise par le dashboard jusqu'au prochain raccordement. Aucun controle routeur n'est ajoute.

Le login exige un formulaire strict, un jeton CSRF signe lie a un cookie preauthentification et la verification d'origine. Le cookie preauthentification expire dans le navigateur apres dix minutes ; cette duree n'est pas verifiee cote serveur et le nonce n'est pas a usage unique. Un nouveau GET login renouvelle le nonce du navigateur.

Les sessions ont une expiration serveur de huit heures. Les cookies sont HttpOnly et SameSite strict, Secure quand l'application voit HTTPS. Ne pas exposer le service HTTP sur un reseau non fiable. La terminaison TLS et les en-tetes proxy doivent etre configures avec des mandataires explicitement fiables. Stockage de sessions en memoire dans un seul processus.

Le GET logout ne revoque rien ; le POST exige un CSRF derive de la session. Le module expose l'identite de session valide via request.state.browser_session_id pour les requetes authentifiees par cookie. Cette valeur reste secrete. Aucune route de controle ne la consomme encore.

A faire avant PR d'integration : remplacer les anciennes routes et leur dependance dans app.py, adapter test_web.py et test_web_edits.py, raccorder une navigation vers la deconnexion, verifier les erreurs et les en-tetes globaux. Ne pas installer les deux implementations simultanement.

Tests rediges, non executes par l'assistant. Commande : python -m pytest tests/unit/test_browser_auth.py tests/unit/test_web_sessions.py. CI, formatage, lint et typage restent a verifier.
