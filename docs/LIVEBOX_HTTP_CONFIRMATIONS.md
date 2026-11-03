# Parcours HTTP de confirmation Livebox

Le module livebox_confirmations fournit un installateur explicite, desactive par defaut. create_app n'est pas modifie dans ce lot : aucune nouvelle commande utilisable depuis le dashboard de production. Aucun adaptateur reel n'est construit, aucune configuration d'activation reelle n'est ajoutee.

Les tests montent une application FastAPI isolee avec browser_auth et les routes de controle partageant exactement le meme SessionStore. Le guard resout une cible Livebox synthetique et son executeur ajoute seulement une requete dans une liste memoire. Ce n'est ni un test navigateur ni une preuve de compatibilite avec une box.

## Parcours

- GET /routers/livebox/control affiche un formulaire, sans resolution d'inventaire ni execution.
- POST /routers/livebox/control/prepare exige une session, un CSRF lie a cette session, un identifiant local et une action stricts. Le guard resout la cible cote serveur ; le formulaire de confirmation affiche IP, MAC, identifiant et action effectivement prepares.
- POST /routers/livebox/control/confirm exige la meme session, un CSRF lie au jeton et une case de confirmation explicite. SessionBoundControl revalide la session avant delegation au guard. Aucun renvoi automatique ni nouvel essai apres un resultat incertain.

Les routes refusent tout en-tete Authorization, meme en presence d'un cookie : le parcours est exclusivement navigateur. Le Bearer des autres routes n'est pas modifie. Le retrait du forcage n'est pas une garantie d'acces si le calendrier l'interdit.

Le parsing reutilise les controles de browser_auth : origine si presente, refus cross-site, type de contenu, taille limitee, champs stricts. Les erreurs du guard sont rendues sans leur contenu interne. Les pages de succes ont no-store, no-referrer et CSP restrictive ; les reponses d'erreur necessiteront aussi les en-tetes globaux lors du raccordement a create_app.

## Limites et suite

L'installateur exige un guard Livebox fiable fourni par le serveur, jamais par le formulaire. Le type de resultat None convient a l'executeur simule de ces tests ; le futur adaptateur reel et ses resultats verifies doivent faire l'objet d'un raccordement distinct. La page finale annonce seulement la fin sans erreur de l'executeur, pas un acces Internet prouve.

La validation de session reste ponctuelle, non atomique avec une deconnexion concurrente. Un seul processus. Restent a realiser : raccordement dans create_app avec magasin partage, integration aux templates et a la navigation, tests sur le dashboard reel, limites et erreurs reseau de l'adaptateur, revue securite et validation materielle avant activation.

Tests rediges mais non executes par l'assistant. Commande : python -m pytest tests/unit/test_livebox_confirmations.py tests/unit/test_session_control.py tests/unit/test_browser_auth.py

Ruff check, Ruff format, mypy, suite complete et CI Linux/Windows restent a verifier. Aucun succes CI affirme.
