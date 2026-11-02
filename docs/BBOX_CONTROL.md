# Contrat de contrôle Bbox : orchestration préparatoire

Ce module n'implémente aucun appel HTTP d'écriture. `BboxControlPort` est une interface injectée et aucun adaptateur de production n'est fourni. Ce n'est donc pas encore une fonctionnalité de blocage Bbox utilisable.

`change_bbox_access` impose activation et confirmation, sous-réseaux privés autorisés, protection de la passerelle et du poste de gestion, modèle/firmware exacts, correspondance unique MAC/IPv4/identifiant et état connu. Une cible déjà dans l'état demandé ne provoque aucune écriture. Après une seule écriture, une relecture cohérente est obligatoire. Toute exception après la tentative donne un résultat incertain sans nouvelle tentative.

## Protocole restant à établir

Source communautaire examinée : https://github.com/hadamrd/bbox-cli/blob/main/pkg/client/endpoints.go ; blob consulté : 5bae028ae6619434050cab2ee04309115a5f828d.

Ses fonctions HostBlock/HostUnblock combinent un appel parentalcontrol et un repli vers un PUT de hosts. Ne pas copier ce repli : plusieurs tentatives pourraient modifier des mécanismes différents. ParentalHostSet inscrit ou retire une MAC du contrôle parental ; cela ne prouve pas un blocage immédiat indépendant du calendrier.

Avant tout adaptateur HTTP : vérifier le protocole sur le modèle/firmware concerné, établir la signification du champ blocked et sa relecture, préserver les règles et calendriers existants, traiter session et jeton d'écriture sans fuite, et interdire tout repli ou nouvel essai implicite. Une réponse HTTP de succès ne suffit pas.

## Limites

La relecture vérifie l'état rapporté par la box, pas la connectivité Internet. Elle ne certifie pas la préservation des calendriers ni des règles non exposées dans BboxSnapshot. La contrainte active=True peut empêcher le déblocage d'un appareil devenu inactif ; refus volontaire tant que la sémantique n'est pas validée.

Les confirmations à usage unique, la résolution SQLite et la sérialisation restent à assembler pour Bbox avec ControlGuards. Aucune route web ni activation ajoutée. Aucun test sur réseau ou matériel réel.

## Validation

Tests synthétiques : écriture unique, relecture, idempotence, timeout après modification simulée, relecture contradictoire et refus avant écriture. Tests rédigés mais non exécutés par l'assistant. Ruff, formatage, mypy, couverture et sécurité restent à vérifier en CI.

Commande : `python -m pytest tests/unit/test_bbox_control.py`.
