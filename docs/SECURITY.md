# Sécurité

## Avertissement légal

Cet outil ne doit être utilisé que sur **ton propre réseau**. Scanner un réseau qui ne t'appartient pas, ou un réseau professionnel sans accord écrit du service IT, peut enfreindre la loi et la politique de l'entreprise. Tu restes seul responsable de l'usage que tu en fais.

## Modèle de menace

| Menace | Mesure |
|---|---|
| Scan d'un réseau tiers ou d'Internet | `allowed_subnets` obligatoire ; refus de toute plage absente de la liste et de toute adresse publique (hors RFC 1918) |
| Accès non autorisé au dashboard | Écoute sur `127.0.0.1` par défaut ; jeton d'authentification exigé pour toute exposition sur le LAN |
| Fuite de secrets | Secrets uniquement dans `.env` (ignoré par Git) ; gitleaks en CI et en pre-commit ; secrets jamais écrits dans les logs |
| Fuite de données du foyer | MAC, IP et noms d'appareils stockés en local uniquement ; aucune télémétrie ; envoi externe limité aux notifications choisies |
| Dépendances vulnérables | `pip-audit` et `bandit` en CI |
| Commande injectée via nmap ou ping | Sous-processus avec liste d'arguments (jamais de shell) ; cible validée par le garde-fou avant l'appel |

## Droits nécessaires

- **Mode passif** (table ARP du système) : aucun privilège.
- **ARP brut (scapy)** : root ou `CAP_NET_RAW` sous Linux / Raspberry Pi OS, droits administrateur et Npcap sous Windows. Ce code est isolé dans un module dédié ; le reste de l'outil tourne sans privilèges.
- **Scan de ports** : désactivé par défaut, limité aux appareils listés, avec limitation de débit.

Sous Linux, préfère accorder la capacité `CAP_NET_RAW` à l'interpréteur ou au service plutôt que de tout lancer en root. La procédure détaillée sera documentée en M2 et M6.

## Secrets

Copie `.env.example` vers `.env`. Ne committe jamais `.env`. Si un secret est publié par erreur, révoque-le immédiatement (webhook, token) puis nettoie l'historique.

## Signaler un problème

Dépôt privé : ouvre une issue avec le label `role:securite`, sans y coller de secret ni de données du foyer.


## Repli nmap M2

Le repli est désactivé par défaut et exige `scan.nmap_fallback`, le mode actif, l’option CLI active et une cible explicite privée autorisée, limitée à 256 adresses. Les arguments sont fixes et passés sans shell ; aucun scan de ports, script ou détection de services n’est demandé. Le binaire doit provenir d’une installation de confiance : il est résolu dans le `PATH`, sans élévation automatique des droits.

Le délai du sous-processus est configurable entre 1 et 120 secondes. La sortie est contrôlée après capture (1 Mio de caractères), puis analysée avec `defusedxml` sans entités ni références externes. Les IP retournées hors cible provoquent une erreur et non un repli ; les MAC multicast, nulles ou mal formées ne sont pas persistées. Cette limite après capture ne constitue pas une protection contre la consommation de mémoire d’un binaire compromis. L’absence de nmap, les erreurs de droits et les délais dépassés sont signalés avant retour au cache passif. Aucun privilège n’est ajouté automatiquement ; pas de validation sur LAN ou matériel réel.

## Liste blanche known_devices

Une MAC explicitement listée ne donne jamais d’autorisation de scan supplémentaire. Le collecteur vérifie d’abord `allowed_subnets`, puis applique la confiance à un appareil observé ; aucune sonde ou précréation n’est déclenchée par la liste. Les entrées doivent être unicast non nulles et uniques après normalisation ; la vérification de configuration n’affiche que leur nombre.

Une MAC peut être usurpée : `known` est un classement local du propriétaire, pas une authentification ni une protection contre un intrus qui copie une MAC. Les MAC privées restent marquées comme telles même lorsqu’elles sont approuvées. Les décisions `ignored` et `merged_into` ne sont pas annulées. Retirer une MAC de la liste ne révoque pas le statut déjà persisté ; le reclassement reste manuel et n’a pas encore d’interface utilisateur. Les événements historiques restent présents, aucune notification n’est introduite.
