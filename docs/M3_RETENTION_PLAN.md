# M3 – Plan de rétention de l'historique (brouillon)

Statut : **plan uniquement, aucun code ni test n'est encore implémenté.**
Ce document sert de base à la PR brouillon ; l'implémentation suivra par commits successifs sur cette branche.

## Objectif

Permettre de purger l'historique de monitoring ancien (mesures de latence / perte de paquets issues du suivi ICMP) sans jamais toucher aux données d'identité ou d'état courant.

## Comportement prévu

- Nouvelle commande CLI `prune-history`.
- **Prévisualisation en lecture seule par défaut** : affiche ce qui serait supprimé, sans rien modifier.
- Suppression réelle uniquement si `retention.enabled = true` dans la configuration **et** option `--apply` passée explicitement.
- Suppression par lots bornés pour éviter les longs verrous SQLite.
- Défauts prudents : rétention désactivée tant qu'elle n'est pas activée explicitement.

## Données concernées / protégées

| Données | Action |
|---|---|
| Mesures de monitoring anciennes (au-delà de la durée de rétention) | Purgeables |
| Appareils | Conservés |
| Observations de découverte | Conservées |
| États courants | Conservés |
| Événements | Conservés |

## Points techniques à valider avant d'écrire le code

1. Lire le schéma SQLite et la couche d'accès aux données existants (M1/M3).
2. Définir la migration additive (index sur la date des mesures si utile).
3. Ajouter la section `[retention]` à la config avec validation.
4. Tests : prévisualisation sans écriture, refus sans `enabled`, refus sans `--apply`, lots bornés, tables protégées intactes.
5. Documentation : README, sécurité, guide de tests.

## Hors périmètre

- Planification périodique (cron / service) : lot ultérieur.
- Aucun accès réseau supplémentaire.
