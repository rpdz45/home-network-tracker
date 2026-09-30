# AGENTS.md : Home Network Tracker

Brief de projet à lire **en premier** par tout agent IA (agent de code, assistant de chat, Perplexity, etc.) qui travaille sur ce dépôt.

Ces règles sont des consignes, pas un mécanisme de contrainte : c'est la CI GitHub (section 7) qui fait foi. Si une demande du propriétaire entre en conflit avec ce fichier, signale-le avant d'agir.

Langues : échanges avec le propriétaire et documentation utilisateur en français ; code, identifiants, commentaires et messages de commit en anglais.

---

## 0. Paramètres du propriétaire (à remplir avant de commencer)

| Paramètre | Valeur |
|---|---|
| OS de la machine qui fera tourner l'outil | Windows / Linux / Raspberry Pi OS (garder une seule option) |
| Sous-réseau à surveiller (CIDR) | ex. 192.168.1.0/24 |
| Routeur / box | marque, modèle, SNMP ou API disponible ? |
| Priorité | Sécurité (intrus) / Supervision (uptime, latence) / Les deux |
| Notifications | Discord / Telegram / E-mail / Aucune |
| Dashboard | Web FastAPI (défaut) / Grafana |

Si une valeur manque, applique le défaut de la section 3 et **dis-le explicitement** dans ta réponse.

---

## 1. Objectif

Outil local de suivi du réseau domestique :

- découvrir les appareils (IP, MAC, fabricant, nom d'hôte) ;
- suivre leur disponibilité (latence, perte de paquets, historique en ligne / hors ligne) ;
- détecter les appareils inconnus et notifier le propriétaire ;
- afficher le tout dans un dashboard web local ;
- stocker les données dans une base SQLite locale.

---

## 2. Règles non négociables

### 2.1 Périmètre et sécurité

1. L'outil ne scanne que le réseau du propriétaire. La config contient `allowed_subnets` ; le collecteur **refuse** de scanner toute plage absente de cette liste ainsi que toute adresse publique (hors plages privées RFC 1918). Aucun comportement par défaut du type « scanne tout ce que tu vois ».
2. Mode passif par défaut (table ARP locale, écoute). Les scans actifs (balayage ARP, ping) sont activés explicitement en config. Le scan de ports est désactivé par défaut, limité aux appareils listés, avec limitation de débit.
3. Aucun test ne doit émettre de paquets réels : tout accès réseau passe par des interfaces remplaçables (scapy, sous-processus nmap, ping).
4. Le dashboard et l'API écoutent sur `127.0.0.1` par défaut. Toute exposition sur le LAN exige un jeton d'authentification configuré.
5. Droits minimaux : documenter précisément ce qui exige root/admin (envoi ARP brut) et isoler ce code dans un module dédié. Le reste tourne sans privilèges.

### 2.2 Secrets et Git

6. Aucun secret dans le dépôt (webhooks Discord, tokens Telegram, mots de passe SMTP, clés API). Utiliser un fichier `.env` ignoré par Git et fournir un `.env.example` sans valeurs réelles.
7. Interdit : `git add .` et `git add -A`. Ajoute les fichiers explicitement, relis `git status` et `git diff --staged` avant chaque commit.
8. Interdit : push direct sur `main` (sauf le tout premier commit de ce fichier par le propriétaire), `--force` sur une branche partagée.

### 2.3 Honnêteté

9. Ne prétends jamais avoir testé sur un réseau réel si ce n'est pas le cas. Dans chaque PR, sépare « testé (tests unitaires / CI) » et « non testé sur matériel réel ».
10. Si tu ne peux pas exécuter quelque chose (pas de LAN, pas de droits), dis-le et donne la commande que le propriétaire doit lancer.
11. MAC, IP et noms d'appareils sont des données personnelles du foyer : stockage local uniquement, aucune télémétrie, aucun envoi externe hors notifications choisies par le propriétaire.

---

## 3. Stack par défaut (si non précisé en section 0)

- Python 3.11 ou plus, `pyproject.toml`, environnement virtuel `.venv`.
- Découverte : `scapy` (ARP) avec repli sur `nmap -sn` en sous-processus ; table ARP du système en mode passif.
- Fabricant : base OUI de l'IEEE embarquée dans `data/oui/` + script de mise à jour.
- Stockage : SQLite, schéma versionné, migrations simples.
- API + dashboard : FastAPI + uvicorn, pages HTML (Jinja2) avec graphiques légers. Grafana seulement si le propriétaire le demande.
- Notifications : webhooks Discord et Telegram via `httpx` ; SMTP en option.
- Config : fichier YAML ou TOML + variables d'environnement (`pydantic-settings`).
- Qualité : `pytest` + `pytest-cov`, `ruff` (lint et format), `mypy`, `bandit`, `pip-audit`, gitleaks, `pre-commit`.
- OS : sous Windows, Npcap est requis pour scapy ; sous Linux / Raspberry Pi, root ou la capacité `CAP_NET_RAW` est requis pour l'ARP brut. Le code doit fonctionner sur les trois, ou échouer proprement avec un message clair.

---

## 4. Structure cible du dépôt

```
home-network-tracker/
├─ AGENTS.md
├─ README.md
├─ pyproject.toml
├─ .env.example
├─ .gitignore                 # dont .env, *.db, .venv, __pycache__
├─ .github/workflows/ci.yml
├─ docs/
│  ├─ ARCHITECTURE.md
│  ├─ SECURITY.md
│  └─ TESTING.md
├─ data/oui/                  # base des fabricants (IEEE)
├─ src/nettracker/
│  ├─ config.py
│  ├─ cli.py
│  ├─ db/                     # schéma, repository, migrations
│  ├─ discovery/              # arp.py, nmap.py, vendor.py, names.py
│  ├─ monitor/                # ping.py, uptime.py
│  ├─ alerts/                 # rules.py, notifiers/
│  ├─ api/                    # app.py, routes
│  └─ web/                    # templates, static
└─ tests/
   ├─ unit/
   ├─ integration/
   └─ fixtures/
```

---

## 5. Les quatre rôles

Le travail avance par jalons (section 8). Pour chaque jalon, les quatre rôles passent l'un après l'autre. Un même agent peut tenir plusieurs rôles à la suite, mais il annonce le rôle en cours.

### 5.1 Architecte
- **Mission** : décisions techniques, interfaces, schéma de données.
- **Livrables** : `docs/ARCHITECTURE.md` (composants, flux de données, schéma SQLite : `devices`, `sightings`, `events`, `scans`, `notifications`), courtes ADR pour chaque choix structurant, découpage du jalon en issues GitHub.
- **Ne fait pas** : la logique métier.

### 5.2 Développeur
- **Mission** : implémenter le jalon en petites PR.
- **Exigences** : typage, erreurs explicites (jamais de `except: pass`), logs structurés, timeouts configurables, arrêt propre (SIGINT), écritures SQLite idempotentes.

### 5.3 QA
- **Mission** : tests.
- **Méthode** : tests unitaires avec réseau simulé ; tests d'intégration sur réseau simulé (conteneurs ou espaces de noms réseau) si faisable, sinon fixtures de captures enregistrées.
- **Cas à couvrir** : timeout, permission refusée, IP qui change après renouvellement DHCP, doublons de MAC, IPv6, appareil qui disparaît puis revient, base verrouillée ou corrompue, et **adresses MAC privées / aléatoires des téléphones** (un même téléphone peut apparaître comme un nouvel appareil : prévoir un statut « à confirmer » plutôt qu'une alerte critique).
- **Objectif** : couverture d'au moins 80 % sur la logique métier.

### 5.4 Sécurité et documentation
- **Mission** : `bandit`, `pip-audit`, gitleaks ; revue des permissions ; vérification des règles de la section 2.
- **Livrables** : `README.md` (installation par OS, configuration, exemples), `docs/SECURITY.md` (modèle de menace, droits nécessaires, avertissement légal : ne scanner que ses propres réseaux), `docs/TESTING.md`.

---

## 6. Workflow Git et coordination entre agents

- **Branches** : `feat/<jalon>-<sujet>`, `fix/<sujet>`, `docs/<sujet>`. Agents externes (ex. Perplexity) : `ext/<agent>-<sujet>`. Une branche = un seul agent à la fois.
- **Commits** : Conventional Commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- **Avant de commencer** : `git fetch`, puis rebase de ta branche sur `origin/main`. En cas de conflit, ne jamais écraser : résoudre à la main ou signaler.
- **Ordre de synchronisation** : commit, puis `git pull --rebase origin main`, puis push de la branche. Ne lance pas `pull --rebase` avec des modifications non commitées.
- **Pull requests** : description avec Quoi / Pourquoi / Comment testé / Limites connues / Risques. Fusion en squash, uniquement avec la CI verte.
- **Coordination** : via les Issues GitHub, avec les labels `role:architecte`, `role:dev`, `role:qa`, `role:securite`, `role:perplexity`. Pas de fichier de coordination à la racine.

---

## 7. CI (à créer au jalon M0 : `.github/workflows/ci.yml`)

Déclenchée sur chaque PR, sur Linux et Windows :

- `ruff check` et `ruff format --check`
- `mypy`
- `pytest --cov`
- `bandit -r src`
- `pip-audit`
- détection de secrets (gitleaks)

Si la CI est rouge, on ne fusionne pas. On ne désactive jamais un test pour faire passer la CI sans l'expliquer dans la PR.

---

## 8. Jalons et critères d'acceptation

| Jalon | Contenu | Critères d'acceptation |
|---|---|---|
| **M0** Fondations | Dépôt structuré, `pyproject.toml`, `.gitignore`, `.env.example`, CI, `docs/ARCHITECTURE.md` | CI verte sur une PR vide de logique ; aucun secret ; architecture relue par le propriétaire |
| **M1** Données et config | Schéma SQLite + repository, config validée (dont `allowed_subnets`), CLI `nettracker --help` | Tests de la couche données ; config invalide refusée avec un message clair |
| **M2** Découverte | ARP + repli nmap, fabricant OUI, nom d'hôte (DNS inverse / mDNS), liste blanche `known_devices`, garde-fou de sous-réseau | Refus de scanner hors périmètre (testé) ; découverte simulée cohérente ; échec propre sans droits |
| **M3** Suivi | Ping périodique (latence, perte), historique en ligne / hors ligne, détection des transitions, rétention configurable | Transitions correctes sur scénarios simulés ; pas de fuite mémoire sur exécution longue |
| **M4** Alertes | Règles (appareil inconnu, hors ligne depuis X min, latence anormale), anti-spam, notifiers Discord / Telegram / e-mail, mode `dry-run` | `dry-run` n'envoie rien ; dédoublonnage testé ; aucun secret dans les logs |
| **M5** API + dashboard | Liste et détail des appareils, graphiques latence / uptime, événements, action « marquer comme connu », jeton si exposé sur le LAN | Écoute sur `127.0.0.1` par défaut ; accès refusé sans jeton si exposé |
| **M6** Finition | Scan de ports (optionnel, désactivé par défaut), Dockerfile et/ou service systemd / tâche planifiée Windows, sauvegarde de la base, README complet | Installation reproductible par OS d'après le README ; tag `v0.1.0` |

---

## 9. Definition of Done (toute PR)

- CI verte.
- Tests ajoutés ou mis à jour.
- Documentation mise à jour.
- Aucune règle de la section 2 violée.
- Limites connues listées dans la PR.
- Aucun `TODO` sans issue associée.

---

## 10. Boucle de test chez le propriétaire

Le propriétaire teste sur **son** réseau. Jamais sur un réseau professionnel sans accord écrit du service IT. Un hotspot de téléphone ou un réseau de machines virtuelles convient pour un test isolé.

**Checklist de test terrain (à partir de M2)**

1. Lancer en `dry-run`.
2. Comparer la liste découverte avec la liste d'appareils de la box.
3. Éteindre puis rallumer un appareil : les transitions hors ligne / en ligne sont détectées.
4. Connecter un appareil inconnu : l'alerte (ou le statut « à confirmer ») apparaît.
5. Laisser tourner 24 h : surveiller CPU, mémoire, taille de la base.
6. Redémarrer la machine : le service reprend seul.

**Format d'un retour de bug** (à coller dans une issue `bug: ...`)

- OS et version, version de Python
- Commit (`git rev-parse --short HEAD`)
- Commande exacte lancée
- Extrait de config **sans secrets**
- Logs complets en niveau DEBUG
- Résultat attendu vs obtenu

L'agent reproduit d'abord le problème par un test (ou explique pourquoi c'est impossible), puis corrige dans une PR liée à l'issue.

---

## 11. Prompts prêts à coller

### 11.1 Prompt de démarrage (agent de code ou assistant de chat)

```text
Lis AGENTS.md en entier et applique-le strictement.
Rôle : Architecte. Jalon : M0.
1) Résume-moi en 10 lignes ce que tu as compris et liste les paramètres
   manquants de la section 0.
2) Propose docs/ARCHITECTURE.md (composants, schéma SQLite, arborescence)
   sans écrire de logique métier.
3) Prépare une PR depuis la branche feat/m0-foundations (structure,
   pyproject.toml, .gitignore, .env.example, CI).
Ne pousse jamais sur main. Ne lance aucun scan réseau.
```

### 11.2 Prompt pour Perplexity (recherche et PR limitées)

```text
Contexte : dépôt privé home-network-tracker (voir AGENTS.md).
Tu n'écris PAS de code applicatif. Chaque mission se fait sur une branche
ext/perplexity-<sujet> avec une PR :
- vérifier les versions et les vulnérabilités connues des dépendances de
  pyproject.toml (sources citées) ;
- mettre à jour data/oui/ depuis la source officielle de l'IEEE ;
- relire docs/SECURITY.md et signaler les manques (avec sources).
Règles : jamais de push sur main, aucun secret, toute affirmation sourcée.
Si une permission te manque, dis-le au lieu de la contourner.
```
