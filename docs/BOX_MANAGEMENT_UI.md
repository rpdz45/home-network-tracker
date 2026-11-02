# Interface de gestion des box — lot Livebox

## État

Branche de développement uniquement. Ce lot ajoute la saisie du mot de passe sur `/routers/livebox`, pas le blocage ni le formulaire Bbox. Ne pas fusionner sans revue et CI verte.

## Configuration

Le jeton du dashboard reste obligatoire. Le processus serveur doit recevoir `NETTRACKER_LIVEBOX5_ENABLED=true` et `NETTRACKER_LIVEBOX5_URL` avec l'adresse IPv4 privée de la box, comprise dans `allowed_subnets`. L'adresse ne peut pas être choisie par le formulaire.

HTTPS est vérifié. HTTP exige `NETTRACKER_LIVEBOX5_ALLOW_HTTP=true` et affiche un avertissement : les échanges vers la box ne sont alors pas chiffrés. Ne pas exposer le formulaire sur un LAN en HTTP ; conserver l'accès local au dashboard pour les essais.

## Utilisation

Ouvrir `/routers/livebox` après authentification. L'identifiant est `admin`, conformément au lecteur existant. Saisir le mot de passe de la box, confirmer la lecture puis envoyer. Le mot de passe saisi n'est ni persisté par la route ni réaffiché. Il faut le ressaisir pour une autre lecture. Un mot de passe déjà configuré par variable d'environnement reste utilisable séparément.

Une lecture au maximum toutes les 60 secondes, avec verrou contre les lectures simultanées. Aucun appel box sur GET. La session créée sur la box peut subsister jusqu'à son expiration ; ce lot ne fournit pas de déconnexion explicite.

## Données et limites

Affichage du nom, IP, MAC, état et firmware fournis par le lecteur existant. Aucune écriture SQLite, aucun changement d'alias, aucune modification des règles réseau. Marque et modèle précis des appareils ne sont pas ajoutés par ce lot. Bbox et contrôle d'accès restent des lots ultérieurs.

## Validation

Tests HTTP avec lecteur simulé et identifiants synthétiques : authentification, CSRF, origine, configuration, mot de passe saisi ou configuré, erreurs sans secret, échappement HTML, limitation des tentatives, taille et doublons.

Commande prévue : `python -m pytest tests/unit/test_router_credentials.py tests/unit/test_web_livebox.py`.

Tests rédigés, non exécutés par l'assistant à ce stade. Ruff, mypy, suite complète et CI Linux/Windows restent à exécuter. Aucun test sur navigateur réel, Livebox réelle ou réseau domestique. Le masquage `SecretStr` n'est pas un chiffrement ni une garantie d'effacement de la mémoire.
