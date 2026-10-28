# Livebox 5 dans le dashboard : lecture administrateur

## Périmètre

La page Routeurs donne accès à `/routers/livebox`. Afficher ces pages ne
contacte pas la box. Le bouton POST `/routers/livebox/read` utilise exclusivement
le lecteur `routers.livebox5.read_snapshot` existant, sans modifier ses appels
autorisés ni ajouter de blocage, déblocage ou fonction de contrôle Wi-Fi.
La découverte réseau sans accès administrateur est une fonction distincte.

## Configuration locale

Variables de l'environnement du processus, lues à la création de l'application :

- `NETTRACKER_LIVEBOX5_ENABLED=true` : activation explicite, sinon désactivée.
- `NETTRACKER_LIVEBOX5_URL` : origine IPv4 privée de la box, sans identifiants.
- `NETTRACKER_LIVEBOX5_PASSWORD` : mot de passe administrateur local.
- `NETTRACKER_LIVEBOX5_ALLOW_HTTP=true` : autorisation supplémentaire du HTTP.

Ces nouvelles variables ne sont pas chargées automatiquement depuis `.env`
ou `config.toml`. Leur modification exige de redémarrer le serveur. Seule la
valeur exacte `true` active les indicateurs. Le jeton du dashboard utilise
le chargement existant et reste requis même pour une écoute sur localhost.
Configurer les secrets localement, sans les envoyer dans le chat, les mettre
dans une URL ou les enregistrer dans Git. Aucun exemple ne contient de mot
de passe réel. Le secret reste dans l'environnement et en mémoire dans un
`SecretStr` ; ce masquage ne protège pas contre un administrateur de la machine.

L'adresse est validée sans réseau à la création de la page, puis par le lecteur
lors de chaque action : IPv4 RFC1918 dans allowed_subnets, ports standards,
aucun DNS ni redirection. HTTPS vérifie le certificat, sans exception implicite.
En HTTP, le mot de passe et les échanges ne sont pas chiffrés : l'avertissement
est visible avant confirmation. Un nom de modèle annoncé n'est pas une preuve
cryptographique d'identité, particulièrement en HTTP.

## Déclenchement

Ouvrir Routeurs puis « Ouvrir la lecture Livebox 5 », vérifier la cible et
cocher l'autorisation de connexion administrateur avant de cliquer. Le mot
de passe n'est jamais un champ du formulaire et n'entre pas dans le contexte
du template. L'identification avant envoi des identifiants reste celle du
lecteur existant ; la disponibilité sans authentification dépend du firmware.

Le lecteur crée un contexte administrateur sur la box ; il ne le libère pas
explicitement. Ce contexte peut subsister jusqu'à expiration. Une tentative
par minute au maximum et une seule à la fois sont autorisées par instance,
y compris après une erreur. Aucun réessai automatique. Ces limites ne sont
pas partagées entre plusieurs processus ou serveurs.

La route utilise l'authentification existante, contrôle l'origine, le marqueur
intersite, CSRF, la confirmation et les deux champs de formulaire. La limite
du corps est 2048 octets. La cible et le secret ne peuvent pas être remplacés
par le navigateur. Une erreur du lecteur produit une page 503 générique.

## Affichage et limites

Seuls Name, IPAddress, PhysAddress et un Active booléen sont présentés. Les
champs absents, structurés ou non reconnus restent non renseignés. Les textes
sont limités à 120 caractères et échappés par Jinja ; une éventuelle répétition
du secret dans ces champs ou le firmware est masquée avant affichage.
La réponse brute et les autres propriétés ne sont pas affichées. Le nombre
indiqué est celui des appareils retournés, pas une garantie d'appareils en ligne
ni d'inventaire complet. Aucun modèle exact d'appareil n'est garanti.

Aucune écriture SQLite, télémétrie, conservation d'historique ou lecture
périodique. Le résultat est rendu dans la réponse POST avec les en-têtes
existants no-store ; un rafraîchissement peut proposer de renvoyer le formulaire
et reste soumis aux mêmes protections. Les réglages d'accès ne sont pas modifiés.

## Validation

Les tests web remplacent le lecteur par des réponses synthétiques ; aucune
box ni aucun mot de passe réel. Ils couvrent activation, secrets manquants,
authentification, origine, CSRF, confirmation, taille, HTTP, affichage limité,
masquage du secret, erreurs et limitation des tentatives.

```text
python -m pytest tests/unit/test_web_livebox.py tests/unit/test_web_routers.py
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest --cov
```

Distinguer tests isolés, CI et tests matériels. Sans FastAPI localement, les
tests web ne sont pas revendiqués comme exécutés. Compatibilité réelle du
firmware et efficacité d'un futur blocage restent non vérifiées.
