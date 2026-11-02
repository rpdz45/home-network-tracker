# Restriction Internet Livebox 5 : préparation des commandes

## Périmètre de ce commit

Le module `routers.livebox5_access` analyse une réponse de planificateur
et prépare les paramètres de `Scheduler.overrideSchedule`. Il ne contient
aucun transport, authentification, route web ou appel réel à une box.
Le lecteur existant `routers.livebox5.py` reste inchangé et en lecture seule.
Ce commit seul ne permet pas de bloquer un appareil réel.

## Comportement conservateur

- Seul un calendrier existant, activé et de structure reconnue est accepté.
- Réponse manquante, refusée ou contradictoire : état inconnu, refus.
- Blocage préparé : override `Disable`, ciblé sur une MAC unicast.
- Levée du blocage : override vide pour restaurer le calendrier, pas
  override `Enable` qui imposerait une autorisation permanente.
- Une restriction provenant du calendrier seul n'est pas supprimée.
- Confirmation obligatoire et refus des MAC protégées fournies par l'appelant.

Le rétablissement du calendrier peut laisser Internet interdit si le
calendrier le prévoit. Le futur résultat doit distinguer « forçage retiré »
et « accès autorisé ». Aucun historique de propriété du forçage n'est encore
géré : ce module ne sait pas qui l'a posé. Aucun calendrier n'est créé.

## Raccordements restant nécessaires

Session authentifiée séparée, identification modèle/firmware, périmètre réseau,
résolution de la cible depuis l'inventaire, identification obligatoire de la
passerelle et de l'appareil de gestion, liste de commandes autorisées,
lecture avant action et relecture après, erreurs expurgées et absence de
reprise automatique. Les paramètres préparés ne doivent jamais être exposés
comme une autorisation suffisante pour envoyer une commande.

## Source technique étudiée

LiveboxMonitor, `src/LiveboxMonitor/api/LmDeviceApi.py` :
https://github.com/p-dor/LiveboxMonitor/blob/main/src/LiveboxMonitor/api/LmDeviceApi.py

Identifiant du blob consulté : `4bf8ce93889105b27293d78e0d78fd5eb50ea1f2`.
Cet identifiant n'est pas un commit ; le lien de branche ci-dessus est
navigable mais son contenu peut évoluer.

Les méthodes de ce projet communautaire constituent une piste technique,
pas une garantie constructeur ni une validation sur la Livebox du propriétaire.
Le parseur exige volontairement une réponse plus stricte et doit être confronté
au format réel avant tout raccordement réseau. Aucun code tiers n'est copié.

## Tests et limites

Tests synthétiques ajoutés dans `tests/unit/test_livebox5_access.py`.
Non exécutés par l'assistant ; Ruff, mypy et pytest à vérifier en CI.
Aucun essai réseau, matériel ou navigateur. Le retrait d'un appareil de
l'inventaire et son expulsion Wi-Fi ne font pas partie de ce module.
