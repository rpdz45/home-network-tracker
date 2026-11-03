# Parcours HTTP de confirmation Livebox

## Etat et perimetre

Le parcours web est raccorde a create_app, avec navigation conditionnelle et
rendu par template partage. Il reste absent par defaut. La CI verte des lots
logiciels ne constitue ni une revue de securite independante ni une validation
sur une box reelle. Ne pas activer le materiel sur cette seule base.

Cette note resulte d'une lecture ciblee du code a partir de
33731183632d4fb908765ed3de4ccc52c5fb3447. Ce n'est pas un audit complet.
Aucune commande materielle n'a ete executee pour cette lecture.

## Raccordement au dashboard

create_app partage un SessionStore entre install_browser_auth et les routes de
confirmation. Les appels existants a create_app(settings) ne les activent pas,
meme lorsqu'un guard est fourni sans activation explicite.

Le raccordement exige livebox_guard et livebox_control_enabled=True, fournis
cote serveur. L'indicateur doit etre strictement booleen. L'activation sans jeton
configure ou sans guard leve ValueError avant construction de l'application.
Aucun parametre CLI/TOML d'activation materielle n'est ajoute par ce parcours.

Le guard doit provenir de code serveur de confiance, jamais des champs HTTP.
Le serveur choisit routeur, sous-reseaux, politique de fraicheur et MAC protegees.
Le navigateur fournit seulement un identifiant local et une action stricts lors
de la preparation ; il ne choisit ni adresse IP ni identifiants administrateur.

## Navigation et templates

Le template commun affiche le lien Controle Livebox vers
/routers/livebox/control seulement avec un contexte de session navigateur et
app.state.livebox_control_navigation strictement True. create_app initialise cet
indicateur a False et le passe a True apres installation explicite des routes.
C'est une information de presentation, pas une autorisation.

Les trois etapes utilisent livebox_confirmation.html, heritant de base.html :
formulaire, confirmation et fin de traitement. Elles partagent style, navigation
et lien de retour aux routeurs. Le module renseigne le contexte de session apres
validation, sans rendre son identifiant dans la page.

Les donnees sont transmises au contexte Jinja avec echappement automatique, sans
filtre safe. Les champs caches CSRF et jeton de confirmation restent presents
lorsqu'ils sont necessaires ; ne pas les confondre avec un mot de passe ou le
cookie de session. La page finale ne renvoie pas de champ de confirmation.
Les erreurs HTTP conservent leur rendu existant, hors de ce template.

La CSP de l'installateur et celle du dashboard autorisent les styles inline pour
base.html, interdisent les scripts via default-src 'none' et imposent
form-action 'self', base-uri 'none' et frame-ancestors 'none'. Les pages ont
no-store, no-referrer et nosniff. Dans create_app, le middleware ajoute les
en-tetes globaux aux refus HTTP testes. Un montage isole doit proteger aussi
ses reponses d'erreur : les seuls en-tetes des pages de succes ne suffisent pas.

## Parcours et protections

- GET /routers/livebox/control affiche le formulaire sans execution.
- POST /routers/livebox/control/prepare exige une session, un CSRF lie a cette
  session, un identifiant et une action stricts. Le guard resout la cible cote
  serveur ; la confirmation affiche identifiant, IP, MAC et action prepares.
- POST /routers/livebox/control/confirm exige la meme session, un CSRF lie au
  jeton et une confirmation explicite. Le guard consomme le jeton avant execution
  et revalide la cible. Aucun nouvel essai automatique apres resultat incertain.

Tout en-tete Authorization est refuse, meme avec un cookie valide. Le Bearer des
autres routes n'est pas modifie. Le parsing reutilise browser_auth : origine si
presente, refus cross-site, formulaire URL-encode, taille limitee, champs stricts.
Les erreurs AccessControlError sont rendues sans leur contenu interne.

La page finale annonce seulement la fin sans erreur de l'executeur configure.
Elle ne prouve pas l'acces Internet. Retirer le forcage peut restaurer un
calendrier qui interdit encore l'acces.

## Composants reels deja presents, mais non raccordes au parcours web

- routers/control_service.py : build_livebox_control compose inventaire local,
  guard et adaptateur. Sa construction n'effectue pas d'I/O ; son utilisation
  peut lire la base et envoyer des commandes si explicitement activee.
- db/control_inventory.py : resolve_control_target lit les preuves de decouverte
  locales et refuse notamment cible absente/fusionnee, preuves perimees ou
  futures, cible non en ligne et ambiguite d'adresse. Ces preuves locales ne
  constituent pas une authentification materielle de l'appareil.
- routers/livebox5_control.py : change_schedule exige activation, confirmation,
  modele et firmware attendus, sous-reseaux autorises et MAC protegees. Il relit
  le calendrier apres modification et renvoie ControlResult(changed, state).

Le constructeur reel renvoie ControlGuards[ControlResult]. create_app et
install_livebox_confirmation_routes attendent actuellement ControlGuards[None].
Le handler confirm ignore la valeur retournee. Ne pas contourner cet ecart par
un cast ou un wrapper supprimant le resultat : definir et tester le contrat web.

## Conditions a satisfaire avant raccordement reel

- [ ] Definir le traitement de ControlResult : changement effectif ou etat deja
  conforme, calendrier relu et difference entre retrait du forcage et acces reel.
- [ ] Definir la traduction des erreurs de l'adaptateur, y compris les erreurs
  LiveboxError qui peuvent survenir hors de la phase de modification. Ne pas
  exposer messages internes, secrets ou contexte d'authentification.
- [ ] Tester transport simule, firmware incompatible, inventaire perime/ambigu,
  MAC protegees, absence de changement, relecture divergente et resultat incertain
  a travers le parcours web. Verifier la consommation du jeton sans rejeu.
- [ ] Revoir la configuration serveur : secrets hors formulaires et journaux,
  sous-reseaux explicites, MAC de gestion et passerelle, firmware exact, HTTPS
  et tout besoin exceptionnel d'allow_http. Aucun relachement implicite.
- [ ] Examiner les courses entre revocation/expiration et admission d'une
  commande. La verification actuelle est ponctuelle, pas atomique avec logout ;
  une deconnexion ne peut pas annuler une execution deja admise.
- [ ] Valider le deploiement mono-processus, terminaison HTTPS et confiance dans
  les en-tetes de proxy. Confirmer les limites de connexion et d'abus avant
  exposition ; cette lecture n'etablit pas une protection complete contre l'abus.
- [ ] Obtenir une revue de securite independante et un essai dans un navigateur
  reel. Preparer une validation materielle separee avec cible non critique,
  acces de secours, verification manuelle et accord explicite avant commande.

Aucune case n'est consideree satisfaite par la seule presence d'un module ou
par un resultat CI. Ne pas envoyer de commande automatique pour les verifier.

## Validation logicielle connue

Les tests utilisent inventaire synthetique et executeur en memoire, jamais une
box reelle. TestClient exerce connexion, navigation et refus HTTP ; les tests de
rendu utilisent aussi Jinja StrictUndefined. Ils ne remplacent pas un navigateur.

La PR 81 a obtenu les succes Quality Linux/Windows et Gitleaks sur
4c2b014ddecd62fedf3567882017071f9f2acf9e. Les deux tests ajoutes couvrent navigation
sur les trois etapes, en-tetes, absence de secrets, confirmation unique/rejeu et
echappement de donnees HTML synthetiques. Aucun test n'a ete execute localement
par l'assistant. Ce resultat historique ne valide pas un futur raccordement reel.

Commandes de validation logicielle :

```sh
ruff check .
ruff format --check .
mypy
python -m pytest
```

Le magasin de sessions et les confirmations restent locaux au processus.
Maintenir le parcours desactive tant que les prerequis du raccordement reel
n'ont pas ete examines et valides explicitement.
