# Identification Fing : API locale et dashboard

## Fonction livrée

`nettracker.discovery.fing` lit l'inventaire de l'API locale documentée.
La page `/identification/fing`, liée depuis « Mes appareils », affiche les noms,
fabricants, modèles et catégories réellement retournés. Un champ absent reste
« Non identifié » ; la reconnaissance Fing n'est pas vérifiée indépendamment.
Le mode local sans administration Bbox reste inchangé. Aucun blocage ajouté.

## Configuration Windows / processus serveur

- Installer et configurer Fing Desktop localement ; vérifier ses paramètres de
  confidentialité avant toute activation. Notre code ne l'installe ni ne le lance.
- Fournir `NETTRACKER_FING_ENABLED=true` et `NETTRACKER_FING_API_KEY` dans
  l'environnement du processus serveur. La clé vient des paramètres API Fing.
- Configurer le jeton api.token du dashboard, obligatoire même sur loopback.
- Initialiser la base existante et conserver allowed_subnets correctement borné.
- Redémarrer le dashboard après modification des variables. Le chargeur `.env`
  actuel ne les injecte pas automatiquement dans os.environ.

Aucune clé dans Git, dans l'historique de commandes ou dans ce chat. Le client
reçoit un SecretStr. Le formulaire ne demande ni clé ni URL : seulement CSRF
et confirmation explicite. GET sans lecture réseau ni ouverture de la base.
POST lit la base locale, puis une fois l'API, dans un thread séparé. Une base
absente est refusée avant Fing, sans créer de fichier de base.

## Périmètre et rapprochement

Documentation : https://www.fing.com/integrations/local-api/ ; schéma v1.1.0.
GET unique `/1/devices` vers 127.0.0.1:49090, clé dans auth, aucun réessai,
redirection, proxy d'environnement ou appel cloud ajouté par notre connecteur.
Le mode debug HTTP est désactivé ; les erreurs ne reprennent ni URL authentifiée
ni corps brut. HTTP loopback non chiffré : un logiciel local malveillant reste
hors des garanties. Une API locale ne garantit pas que Fing lui-même est sans
cloud ; revoir ses conditions et réglages avant de confirmer.

Réponse networkId/devices avec MAC, liste IP, état UP/DOWN et champs facultatifs
name/make/model/type. Limites : 2 Mio, 1024 appareils, 16 adresses par appareil,
timeout socket 5 secondes par opération, pas une échéance globale. Compression
refusée. Réseaux validés par le garde-fou RFC1918 existant avant l'appel.
Seules les IPv4 autorisées sont retenues ; IPv6 et hors périmètre sont écartées.
Appareils sans IP admissible comptés séparément. MAC nulle/multicast/invalide,
IP malformée ou associations MAC/IP ambiguës font échouer la lecture, y compris
si d'anciennes attributions DHCP causent une ambiguïté dans l'inventaire Fing.

Rapprochement exact MAC + IP, jamais IP, nom ou marque seuls. La comparaison
porte sur les 500 fiches locales non fusionnées les plus récentes au maximum.
Une correspondance locale multiple n'a pas de lien. Les alias sont affichés
séparément, jamais écrasés ; aucun appareil créé, fusionné ou approuvé.
Cela ne prouve pas cryptographiquement l'identité et ne résout pas une MAC privée
qui change. Aucune inférence de modèle depuis un simple préfixe MAC.

## Affichage et protections

Source affichée : API locale Fing, reconnaissance non confirmée. retrieved_at
est l'heure de récupération, pas la date d'un nouveau scan ; reported_state
est l'état annoncé par Fing, pas une sonde de notre outil. Aucun appel explicite
à un nouveau scan ; Fing peut collecter indépendamment. Champs bornés, secrets
masqués dans les textes et échappement HTML Jinja. Aucun journal d'inventaire,
stockage de réponse brute, envoi externe ou écriture SQLite ajouté.
Les résultats restent dans la réponse affichée ; un nouveau GET ne les conserve pas.

Routeur authentifié existant, contrôle d'origine et Sec-Fetch-Site, CSRF,
confirmation, formulaire limité à 2 Kio / deux champs exacts. Cache-Control:
no-store. Verrou et 60 secondes après chaque tentative, même en erreur.
Compteur propre au processus, réinitialisé au redémarrage : un worker requis.
Aucun appel Fing automatique à l'ouverture ou au rafraîchissement d'une page GET.

## Validation

Les 14 tests client ont passé dans l'environnement isolé du lot précédent.
Pour ce raccordement : syntaxe, helpers de rapprochement et rendu Jinja vérifiés
isolément ; les tests web complets ne sont pas exécutés ici, FastAPI étant absent.
Ruff, mypy et suite complète à vérifier en CI Linux/Windows avant fusion.
Aucun test Fing Desktop réel sur Windows, aucun accès au réseau du propriétaire.

```text
python -m pytest tests/unit/test_fing.py tests/unit/test_web_fing.py
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest --cov
```
