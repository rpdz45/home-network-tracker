# Parcours HTTP de confirmation Livebox

## Raccordement au dashboard

create_app partage un SessionStore entre install_browser_auth et les routes de
confirmation. Les routes de controle sont absentes par defaut, meme si un guard
est fourni. Les appels existants a create_app(settings) ne les activent pas.

Le raccordement exige deux arguments nommes cote serveur : livebox_guard et
livebox_control_enabled=True. L'indicateur doit etre strictement booleen.
L'activation sans jeton API configure ou sans guard leve ValueError avant la
construction de l'application. Aucun parametre CLI/TOML d'activation ou adaptateur
materiel n'est ajoute par ce raccordement.

Le guard doit etre construit par du code serveur de confiance, jamais depuis les
champs HTTP. Il doit resoudre un inventaire local fiable et refuser les appareils
fusionnes, perimes ou ambigus. L'executeur reste responsable des protections de
l'adaptateur, des limites reseau et de la verification de l'etat apres commande.
Le type ControlGuards[None] correspond au contrat actuel ; il ne valide pas un
adaptateur reel ou ses resultats.

## Navigation

Le template commun propose le lien Controle Livebox vers
/routers/livebox/control uniquement si le contexte contient une session navigateur
et si app.state.livebox_control_navigation vaut strictement True.
create_app initialise cet indicateur a False et le passe a True apres installation
explicite des routes. Cet indicateur est une information de presentation, pas une
autorisation : le modifier ne remplace pas les controles des routes.

Sans activation, sans session navigateur ou avec un acces Bearer, le lien reste
masque dans les pages protegees du dashboard. Les rendus sans contexte HTTP complet
restent pris en charge. Le lien ouvre seulement un formulaire GET, sans commande.
Les pages de preparation et de confirmation conservent leur HTML autonome ; elles
ne reprennent pas encore la navigation et le style des templates du dashboard.

## Parcours

- GET /routers/livebox/control affiche un formulaire sans execution.
- POST /routers/livebox/control/prepare exige une session, un CSRF lie a cette
  session, un identifiant local et une action stricts. Le guard resout la cible
  cote serveur. La confirmation affiche identifiant, IP, MAC et action prepares.
- POST /routers/livebox/control/confirm exige la meme session, un CSRF lie au
  jeton et une confirmation explicite. Le guard consomme le jeton avant execution
  et revalide la cible. Aucun nouvel essai automatique apres un resultat incertain.

Tout en-tete Authorization est refuse sur ce parcours, meme avec un cookie
valide. Les acces Bearer des autres routes ne sont pas modifies.
Le retrait du forcage ne garantit pas l'acces si le calendrier l'interdit.
La page finale indique seulement que l'executeur a termine sans erreur, pas une
preuve d'acces Internet ou de compatibilite materielle.

Le parsing reutilise browser_auth : controle de l'origine si presente, refus
cross-site, formulaire URL-encode, taille limitee et champs stricts.
Les erreurs AccessControlError sont rendues sans leur contenu interne.
Dans create_app, le middleware global ajoute SECURITY_HEADERS aux reponses,
y compris aux refus HTTP testes. Sa CSP globale remplace celle de l'installateur.
Un montage isole doit fournir ses propres protections globales pour les erreurs.

## Validation et limites

Les tests HTTP utilisent une cible synthetique et un executeur qui ajoute seulement
une requete a une liste en memoire. Certains montent une FastAPI isolee ; les tests
dashboard utilisent create_app et son authentification effective, sans navigateur
reel, sans inventaire de production et sans box reelle.

Les tests de rendu de navigation utilisent Jinja StrictUndefined avec contexte
synthetique. Les tests de test_livebox_navigation_http.py utilisent TestClient :
connexion effective, page /routers, lien conditionnel, GET du formulaire sans
execution, refus Bearer meme avec cookie, deconnexion et parcours desactive.
Ils utilisent un chemin de base absent et verifient qu'aucune base n'est creee.
Cela ne remplace pas un essai dans un navigateur reel.

Les controles Quality Linux/Windows et Gitleaks de la PR 79 ont reussi sur
80e65602c7fd9ed1ae9e1ec9965cfeacc3cab19b. Ce resultat ne valide pas les nouveaux
tests HTTP du present lot, ni une activation materielle. Ces nouveaux tests sont
rediges mais non executes par l'assistant.

Commandes a verifier dans l'environnement de developpement et en CI :

```sh
ruff check .
ruff format --check .
mypy
python -m pytest
```

La validation de session reste ponctuelle, non atomique avec une deconnexion
concurrente. Le magasin et les confirmations sont locaux au processus : utiliser
un seul processus. La revocation avant une requete est testable ; aucune garantie
d'annulation d'une execution deja engagee n'est apportee.

Restent : integration des pages de confirmation aux templates, resolution
d'inventaire de production, traitement des resultats et erreurs de l'adaptateur,
revue de securite et validation materielle distincte avant toute activation.
La CI verte ne remplace pas ces etapes.
