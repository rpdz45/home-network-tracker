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
