# Formulaire administrateur Bbox

## Périmètre

Ce lot ajoute la saisie du mot de passe dans `/routers/bbox`, avec le lecteur existant. Il ne fournit ni blocage/déblocage ni identification précise des marques et modèles des appareils.

## Configuration côté serveur

- Jeton du dashboard obligatoire.
- `NETTRACKER_BBOX_AUTH_ENABLED=true`.
- `NETTRACKER_BBOX_URL` : origine IPv4 privée explicitement autorisée par `allowed_subnets`.
- `NETTRACKER_BBOX_EXPECTED_MODEL` : valeur exacte attendue du modèle API, à vérifier localement ; ne pas la deviner à partir du nom commercial.
- `NETTRACKER_BBOX_CA_FILE` : fichier de confiance TLS optionnel.
- HTTP exige `NETTRACKER_BBOX_ALLOW_HTTP=true` : mot de passe et cookie ne sont alors pas chiffrés sur ce lien. Garder le dashboard local pour les essais, sans exposition LAN en HTTP.

L'adresse, le modèle et le fichier de confiance ne sont jamais fournis par le formulaire. Le lecteur transmet le mot de passe avant de vérifier le modèle : vérifier la cible de confiance avant toute saisie.

## Utilisation

Après authentification au dashboard, ouvrir `/routers/bbox`, saisir le mot de passe, confirmer puis lancer la lecture. Le lecteur utilise un mot de passe seul ; aucun identifiant utilisateur n'est transmis. Un champ username non vide est refusé.

La route ne persiste pas le mot de passe saisi, ne le réaffiche pas et ne le conserve pas pour une prochaine lecture. SecretStr masque les représentations ; ce n'est ni un chiffrement ni une garantie d'effacement mémoire. Le mode historique via `NETTRACKER_BBOX_PASSWORD` reste disponible séparément.

Le verrou empêche deux lectures simultanées. Attendre 15 minutes après une tentative terminée, même en cas d'échec. Aucun appel box à l'ouverture de la page. Le lecteur tente une déconnexion ; son acceptation ne prouve pas indépendamment la révocation du cookie.

## Validation et limites

Tests avec lecteur simulé : mot de passe saisi et configuré, absence de secret dans le rendu, échappement HTML, délai après succès et échec, CSRF, origine, champs invalides et périmètre. Aucun paquet vers une box réelle dans ces tests.

Commande prévue : `python -m pytest tests/unit/test_router_credentials.py tests/unit/test_web_bbox.py tests/unit/test_bbox_session.py`.

Tests rédigés, non exécutés par l'assistant à ce stade. Ruff, formatage, mypy, suite complète et contrôles de sécurité restent à vérifier avant fusion. Aucun essai navigateur, Bbox réelle ou réseau domestique. Aucune migration ni écriture d'inventaire SQLite. Compatibilité matérielle non certifiée.
