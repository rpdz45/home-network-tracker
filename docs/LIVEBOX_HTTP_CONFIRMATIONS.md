# Parcours HTTP de confirmation Livebox

## Etat et perimetre

Le parcours est raccorde a create_app, avec navigation conditionnelle et rendu
partage. Depuis la PR 85, la confirmation exploite le resultat valide au lieu
d'annoncer seulement une fin sans erreur. Le parcours reste absent par defaut.
Cette note decrit le code issu de la PR 85 ; ce n'est pas un audit complet.
Aucune commande materielle n'a ete executee pour cette mise a jour.

Une CI verte ne constitue ni une revue de securite independante, ni un essai
dans un navigateur reel, ni une validation sur une box. Maintenir le controle
desactive tant que les prerequis du raccordement reel ne sont pas valides.

## Injection et authentification

create_app partage un SessionStore entre install_browser_auth et les routes.
create_app(settings) ne les installe pas. Fournir un guard seul ne les active
pas : livebox_control_enabled=True et un jeton configure sont aussi requis.
L'indicateur doit etre strictement booleen ; une activation sans jeton ou sans
guard leve ValueError. Aucun parametre CLI/TOML d'activation n'est ajoute ici.

Le guard, les secrets, les sous-reseaux, les MAC protegees et le choix du routeur
proviennent exclusivement du serveur. Le navigateur ne choisit ni IP cible, ni
identifiants administrateur. Tout en-tete Authorization est refuse par ce
parcours, meme avec un cookie valide ; le Bearer des autres routes est inchange.

## Parcours et contrat de resultat

- GET /routers/livebox/control affiche le formulaire sans execution.
- POST /prepare sous ce prefixe exige session, CSRF, identifiant local et action
  stricts. Le serveur resout la cible ; la page affiche identifiant, IP, MAC et
  action prepares.
- POST /confirm accepte exactement csrf, token et confirm=yes. Il n'accepte pas
  une nouvelle action, une adresse ou une cible fournie par le navigateur.
- Le handler appelle confirm_livebox_result dans le pool de threads. Cette
  fonction appelle une seule fois SessionBoundControl.confirm_with_request.
- Le guard lie le jeton a la session, le consomme avant revalidation de cible et
  execution, puis renvoie ConfirmedControl(request, result). L'action utilisee
  par describe_control_result est confirmed.request.blocked, cote serveur.

Une mauvaise session ne consomme pas le jeton du proprietaire. Une fois un jeton
valide consomme, un echec de revalidation ou d'execution ne le rend pas rejouable.
Aucun nouvel essai automatique n'est effectue. Le parsing conserve les controles
d'origine si presente, de refus cross-site, de type URL-encode, de taille et de
champs stricts.

create_app et l'installateur acceptent maintenant un ControlGuards generique.
Un succes exige toutefois un ControlResult valide et coherent avec l'action.
Le constructeur build_livebox_control renvoie ControlGuards[ControlResult] :
l'ancien ecart avec ControlGuards[None] est leve. Ne pas supprimer le resultat
avec un wrapper ni contourner sa validation par un cast.

Un executeur renvoyant None, un type invalide ou un etat incoherent produit
HTTP 409 apres execution et consommation du jeton, pas une page de succes.
AccessControlError et LiveboxError dans la frontiere de confirmation/resultat
sont aussi traduites en 409 avec le detail generique :

> Commande refusee ou resultat incertain ; ne pas relancer automatiquement

Le libelle exact, avec accents, est defini par FAILURE_DETAIL dans
web/livebox_results.py. Les details internes des exceptions connues ne sont pas
renvoyes. Les exceptions inattendues ne sont pas absorbees par cette frontiere.
Un 409 ne prouve pas l'absence d'effet de la commande.

## Rendu et signification

Les trois etapes utilisent livebox_confirmation.html, heritant de base.html.
La page finale affiche ControlResultView : titre, modification effectuee ou etat
deja conforme sans modification, etat du calendrier et avertissement.

Un blocage valide indique un forcage Disable avec acces desactive dans le
calendrier lu. Un retrait du forcage indique un override vide ; le calendrier
peut encore desactiver l'acces. Aucun de ces etats ne prouve l'acces Internet
effectif ni la compatibilite materielle. changed rapporte le resultat de
l'executeur ; la presentation n'effectue pas une nouvelle lecture materielle.

La navigation conditionnelle repose sur une session navigateur et
app.state.livebox_control_navigation strictement True. Elle n'autorise pas une
commande. Les donnees Jinja sont echappees automatiquement, sans filtre safe.
La page finale ne renvoie pas de champ de confirmation ni l'identifiant de
session. Les champs caches CSRF et jeton restent presents aux etapes necessaires.

Les erreurs HTTP gardent leur rendu hors de ce template. La CSP impose
default-src 'none', style-src 'unsafe-inline', form-action 'self', base-uri 'none'
et frame-ancestors 'none'. Les pages ont no-store, no-referrer et nosniff.
Dans create_app, le middleware applique aussi les en-tetes aux refus HTTP testes.
Un montage isole doit proteger ses erreurs : les en-tetes des seules pages de
succes ne suffisent pas.

## Composants reels et limites

build_livebox_control compose inventaire local, guard et adaptateur sans I/O a
la construction. Son utilisation peut lire la base et envoyer des commandes si
explicitement activee. create_app ne construit pas cet adaptateur et ne charge
pas ses secrets. La compatibilite du contrat ne vaut pas raccordement materiel.

resolve_control_target refuse notamment les preuves perimees ou futures, les
cibles absentes/fusionnees, non en ligne et les ambiguities d'adresse. Ces
preuves locales ne constituent pas une authentification materielle.
change_schedule conserve activation et confirmation explicites, modele/firmware
attendus, sous-reseaux autorises, MAC protegees et relecture apres modification.

Le controle du type de routeur dans confirm_livebox_result intervient apres
l'execution : il valide le resultat, pas l'autorisation avant effet. Le resolver
et l'executeur injectes doivent deja refuser toute cible non Livebox avant effet.
La verification de session reste ponctuelle, non atomique avec logout ou une
expiration concurrente. Une revocation n'annule pas une operation deja admise.
Sessions, confirmations et verrouillage restent locaux a un seul processus.

## Prerequis toujours ouverts avant usage reel

- [ ] Tester le constructeur reel avec transport simule a travers HTTP : firmware
  incompatible, inventaire perime/ambigu, MAC protegees, absence de changement,
  relecture divergente et resultat incertain, avec consommation sans rejeu.
- [ ] Revoir secrets hors formulaires/journaux, sous-reseaux, MAC de gestion et
  passerelle, firmware exact, HTTPS et tout besoin exceptionnel d'allow_http.
- [ ] Examiner les courses entre revocation/expiration et admission de commande.
- [ ] Valider mono-processus, terminaison HTTPS, confiance dans les en-tetes de
  proxy et limites de connexion/abus avant exposition.
- [ ] Obtenir une revue de securite independante et un essai navigateur reel.
- [ ] Preparer une validation materielle separee : cible non critique, acces de
  secours, verification manuelle et accord explicite avant toute commande.

La presence du code ou une CI verte ne coche aucune de ces conditions a elle
seule. Ne pas envoyer de commande automatique pour les verifier.

## Validation logicielle

Les tests de ce parcours utilisent inventaire synthetique et executeurs memoire.
TestClient exerce HTTP et connexion ; Jinja StrictUndefined et l'echappement sont
aussi testes. Les tests directs couvrent six combinaisons de resultat, les
sessions refusees, les erreurs connues, les resultats invalides et le non-rejeu.
Le rendu HTTP couvre notamment changement/etat conforme, retrait du forcage,
rejet d'action supplementaire, masquage et non-rejeu apres erreur. Ce ne sont
pas des tests materiels ni une preuve de couverture exhaustive des concurrents.

La PR 85 a obtenu les succes Quality Ubuntu, Quality Windows et Gitleaks sur
9f9632a1b4e6bf9ff8cae7a590f7e2ec4ad43296. Il s'agit du resultat historique du
code, pas d'une validation de cette mise a jour documentaire ni d'une revue
independante. Aucun test n'a ete execute localement par l'assistant.

```sh
ruff check .
ruff format --check .
mypy
python -m pytest
```
