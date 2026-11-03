# Confirmations web Livebox : liaison aux sessions

Ce premier lot ajoute SessionBoundControl, une composition de SessionStore et ControlGuards. Il ne cree aucune route HTTP, ne modifie pas create_app et n'active aucun bouton ni adaptateur reel. Les tests utilisent une cible Livebox synthetique et un executeur qui ajoute seulement une requete dans une liste memoire.

Le composant est desactive par defaut. Une activation explicite du composant et du guard est necessaire. prepare et confirm revalident le cookie dans le magasin de sessions avant delegation. Un simple identifiant conserve dans request.state ou un jeton Bearer partage ne remplace pas cette validation. Le composant ne lit pas l'en-tete Authorization.

Le guard lie le jeton de confirmation a la session valide, relit la cible et consomme le jeton avant execution. Une autre session ou une nouvelle connexion ne peut pas reprendre le jeton de la premiere. Les sessions revoquees ou expirees sont refusees avant delegation. Les confirmations refusees a ce stade restent dans le guard jusqu'a leur nettoyage habituel ; elles ne deviennent pas utilisables par une nouvelle session.

## Limites importantes

La validation de session est ponctuelle, pas atomique avec une deconnexion concurrente ou l'expiration. Une commande deja admise n'est pas annulee par une revocation ulterieure. Aucun engagement de suppression de cette course concurrente n'est fourni par ce lot. Stockage et verrouillage restent locaux a un seul processus.

Le composant est generique : le serveur devra injecter exclusivement le guard Livebox pour les futures routes Livebox. Ni les resolvers, ni les executeurs, ni les secrets ne doivent provenir des formulaires. Il faudra partager exactement le meme SessionStore que l'authentification du dashboard ; ce partage n'est pas encore raccorde dans create_app.

## Validation et suite

Tests rediges, non executes par l'assistant : deux sessions distinctes, preparation sans execution, execution unique, refus du rejeu, revocation, nouvelle connexion, expiration de session avant la confirmation, expiration du jeton et desactivation par defaut.

Commande : python -m pytest tests/unit/test_session_control.py tests/unit/test_control_guards.py tests/unit/test_web_sessions.py

Restent a faire : partage du magasin avec l'authentification, routes prepare/confirm avec CSRF et confirmation de l'appareil/action exacts, rendu des erreurs sans secrets, tests HTTP de deconnexion et d'expiration, validation des cas concurrents, CI Linux/Windows et revue. Aucun test sur box reelle et aucune commande reseau envoyee par ces tests.
