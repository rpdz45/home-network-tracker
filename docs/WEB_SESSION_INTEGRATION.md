# Sessions navigateur : raccordement au dashboard

Sur cette branche, app.py installe browser_auth a la place des anciennes routes de connexion et utilise sa dependance sur le routeur protege. Le cookie ne contient plus le jeton partage : il contient un secret de session opaque. L'ancien cookie est refuse ; une nouvelle connexion est necessaire. Bearer reste accepte sans creer de session navigateur. Sans jeton configure, la lecture publique existante reste disponible. Aucun controle routeur n'est ajoute.

La navigation affiche Se deconnecter uniquement lorsque la requete a ete authentifiee par une session navigateur. Ce lien ouvre GET /logout, qui demande confirmation sans revoquer la session. POST /logout exige un CSRF derive de cette session, la revoque puis supprime son cookie. Les autres navigateurs ne sont pas deconnectes.

Le login exige un formulaire strict, un CSRF signe lie au cookie de preauthentification et une verification d'origine lorsque l'en-tete Origin est present ; Sec-Fetch-Site cross-site est refuse. Le cookie de preauthentification expire dans le navigateur apres dix minutes. Cette duree n'est pas verifiee cote serveur et le nonce n'est pas a usage unique. Un nouveau GET /login renouvelle le nonce du navigateur.

Les sessions expirent cote serveur apres huit heures, sans prolongation. Stockage memoire, capacite de 128 sessions, un seul processus ; redemarrer invalide les sessions. A saturation, les nouvelles connexions recoivent 503 sans eviction d'une session valide.

Les cookies sont HttpOnly et SameSite strict, Secure lorsque l'application voit HTTPS. HTTP n'est pas chiffre : ne pas exposer ce dashboard sur un reseau non fiable. La terminaison TLS et les en-tetes proxy demandent une configuration avec des mandataires explicitement fiables.

request.state.browser_session_id contient un secret porteur pour les requetes authentifiees par cookie : ne pas le journaliser ni le rendre dans le HTML. Le template ne teste que sa presence. Aucune confirmation de controle routeur ne le consomme encore.

Les pages de connexion et de confirmation de deconnexion sont actuellement rendues par le module, pas par login.html ni base.html. Elles recoivent les en-tetes globaux du dashboard. L'ancien template login.html n'est plus utilise par app.py.

## Validation

Tests rediges, non executes par l'assistant. Les tests isoles du module ne remplacent pas les tests sur create_app. Les tests du dashboard sont adaptes au login CSRF et couvrent le refus de l'ancien cookie et la deconnexion isolee. Les tests de navigation couvrent session navigateur, Bearer, lecture sans jeton, absence d'exposition du secret et GET /logout non destructif.

Commande ciblee : python -m pytest tests/unit/test_browser_auth.py tests/unit/test_web_sessions.py tests/unit/test_web.py tests/unit/test_web_edits.py tests/unit/test_web_session_navigation.py

Restent a verifier : formatage, lint, typage, suite complete, CI Linux/Windows, revue de securite et comportement navigateur reel. Aucun resultat CI n'est affirme dans ce document.
