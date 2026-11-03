# Confirmations web Livebox : liaison aux sessions

## Composant et integration actuelle

SessionBoundControl compose SessionStore et ControlGuards. Le premier lot etait
isole ; le parcours est maintenant raccorde a create_app et partage exactement
le magasin de sessions de l'authentification navigateur. Le contrat HTTP courant
est decrit dans LIVEBOX_HTTP_CONFIRMATIONS.md. Le composant ne cree pas lui-meme
de routes, ne construit aucun adaptateur et ne lit pas Authorization.

Le composant et le guard exigent une activation explicite et restent desactives
par defaut. prepare, confirm et confirm_with_request revalident le cookie avant
delegation. request.state ou un Bearer partage ne remplacent pas cette etape.

Le guard lie la confirmation a la session valide, consomme le jeton avant la
revalidation de cible et l'execution, et ne retente pas. Une autre session ou une
nouvelle connexion ne peut pas reprendre le jeton. Une mauvaise session ne
consomme pas celui du proprietaire. Une session revoquee ou expiree est refusee
avant delegation ; cela ne transfere jamais la confirmation a une autre session.

## Deux API de confirmation

confirm renvoie seulement le resultat et conserve ce contrat generique.
confirm_with_request renvoie ConfirmedControl[Result], contenant la requete
revalidee cote serveur et le resultat de l'executeur. Les deux API partagent le
meme chemin de consommation : un jeton utilise par l'une n'est pas reutilisable
par l'autre, y compris apres erreur de l'executeur.

Depuis la PR 85, le handler HTTP appelle confirm_livebox_result, qui utilise
confirm_with_request puis describe_control_result avec l'action de la requete
renvoyee, jamais une nouvelle action du navigateur. Le succes HTTP exige un
ControlResult coherent. None ou un resultat invalide produit 409, sans garantie
d'absence d'effet et sans nouvel essai automatique. Les erreurs connues sont
masquees ; les exceptions inattendues restent propagees par cette frontiere.

## Limites importantes

La validation de session est ponctuelle, pas atomique avec une deconnexion ou
expiration concurrente. Une commande deja admise n'est pas annulee par une
revocation ulterieure. Stockage et verrouillage restent locaux a un processus.

Le composant generique ne choisit pas le routeur et ne valide pas les resultats
specifiques Livebox. Le serveur doit injecter un resolver et un executeur qui
refusent toute cible non Livebox avant effet. Le controle du routeur dans la
frontiere de resultat, apres execution, ne remplace pas cette protection.
Resolvers, executeurs, secrets et politique reseau ne proviennent jamais des
formulaires. HTTP conserve session, CSRF et consentement explicite.

## Validation et prerequis

Les tests synthetiques couvrent sessions distinctes, preparation sans execution,
execution unique, rejeu, revocation, nouvelle connexion, expirations et activation
desactivee par defaut. test_livebox_execution.py ajoute la composition du guard
et des sessions avec validation du resultat et erreurs, sans appel materiel.
La CI historique de la PR 85 ne vaut pas revue independante ou validation reelle.

```sh
python -m pytest tests/unit/test_session_control.py tests/unit/test_control_guards.py tests/unit/test_web_sessions.py tests/unit/test_livebox_execution.py
```

Restent notamment l'examen des cas concurrents, les tests du constructeur reel
avec transport simule a travers HTTP, la revue independante, l'essai navigateur
et la validation materielle separee avec accord explicite. Ne pas activer une
box sur la seule base de ces tests logiciels.
