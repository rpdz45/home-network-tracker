# Identification avec Fing : client local et rapprochement

## État de ce lot

Le module `nettracker.discovery.fing` lit une API réelle documentée, sans
inventer de fabricant ou modèle. Ce lot fournit le client et le rapprochement,
pas encore un bouton du dashboard, une commande CLI ou une persistance SQLite.
Aucun appel automatique au démarrage et aucun remplacement du mode existant.
Le raccordement à l'écran et l'enrichissement de l'inventaire restent à réaliser.
Aucun contrôle d'accès ou blocage d'appareil n'est ajouté.

## Source et prérequis

Documentation officielle consultée : https://www.fing.com/integrations/local-api/
API locale v1.1.0 : GET `/1/devices` sur le port 49090 ; clé dans le paramètre
auth. Fing Desktop doit être installé, configuré et actif par le propriétaire.
L'API exige une clé obtenue dans ses paramètres. Aucune clé réelle à fournir
à un assistant, à Git ou aux tests. Ce module n'installe ni ne lance Fing.

La réponse documentée contient networkId et devices ; chaque appareil possède
mac, ip (liste) et state (UP/DOWN). name, make, model et type sont facultatifs.
Le client ne réinterprète pas un préfixe MAC comme un modèle et ne remplit pas
un champ absent. Une reconnaissance Fing n'est pas une identification garantie.
La provenance `fing_local_api` est conservée dans le résultat.

## Sécurité et périmètre

Appel Python : `read_inventory(api_key, allowed_subnets, enabled=True,
confirmed=True)` ; api_key est un SecretStr local. Ces accords ne remplacent
pas les protections d'une future route web. Pas de secret lu implicitement dans
l'environnement, pas de clé hardcodée, pas d'URL cible fournie par le navigateur.

Un seul GET vers `http://127.0.0.1:49090/1/devices`, aucun DNS explicite,
proxy d'environnement, suivi de redirection, réessai ou appel cloud dans notre
connecteur. Le transport HTTP standard a son mode debug désactivé et n'utilise
pas les journaux d'URL HTTPX : le paramètre secret n'y est pas exposé. Les erreurs
ne reprennent ni URL authentifiée ni corps brut. Timeout de 5 secondes pour les
opérations socket, pas une échéance globale. Corps limité à 2 Mio, compression
refusée, maximum 1024 appareils et 16 adresses par appareil.

Le mode HTTP est réservé à la boucle locale ; la clé n'est pas chiffrée sur ce
transport. Un logiciel local malveillant n'est pas neutralisé par ce client.
Les règles, le compte, les traitements et la confidentialité propres à Fing
restent à examiner par le propriétaire avant activation : une API locale ne
prouve pas que tout Fing est sans cloud. Aucun service cloud Fing ajouté ici.

Les réseaux autorisés sont validés par le garde-fou RFC1918 existant avant
l'appel. Seules les IPv4 appartenant à allowed_subnets sont retenues ; les IPv6
et adresses hors périmètre sont écartées. Les appareils sans IPv4 admissible
sont comptés dans excluded_devices. Aucun scan n'est lancé sur ces adresses.
Une IP malformée, une MAC invalide, nulle ou multicast fait échouer la lecture.
Les MAC locales restent admissibles : l'information vient de Fing, pas d'une
inférence OUI. MAC répétée ou IP revendiquée par plusieurs entrées admissibles :
lecture refusée, y compris en présence d'anciennes attributions DHCP ambiguës.

## Identités et ancienneté

`match_identity(inventory, mac, ip)` exige une correspondance exacte MAC + IPv4.
Aucune fusion par IP seule, nom ou marque. Cela ne constitue pas une preuve
cryptographique d'identité et ne résout pas les changements de MAC privée.
Le module ne modifie aucun alias, fabricant existant ou statut de confiance.

Les textes sont bornés, les répétitions de la clé masquées dans ces textes et
les contacts/personnes ignorés. Aucun journal d'inventaire, stockage de réponse
brute ou transmission externe. Les données retournées restent personnelles.
Le futur écran devra utiliser l'échappement HTML et afficher leur provenance.

retrieved_at est la date UTC de récupération, pas une date de dernier scan.
reported_state est l'état annoncé par Fing, pas une sonde effectuée par notre
outil. first_seen et last_changed ne sont pas assimilés à une présence récente.
Le client ne demande pas de nouveau scan ; Fing peut collecter de son côté.

## Vérifications

14 tests unittest avec réponses synthétiques et connexion HTTP remplacée,
sans paquet réel. Ils ont passé dans un environnement isolé avec normalize_mac
et les contrôles de périmètre extraits du code existant, et une classe de base
d'erreur minimale. Cela ne remplace pas la suite du dépôt ni la CI.
Ruff et mypy non exécutés ici. Aucun test Fing Desktop réel sur Windows.

```text
python -m pytest tests/unit/test_fing.py
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest --cov
```

Avant fusion : CI Linux/Windows verte et revue de sécurité. Avant activation :
validation locale de l'API et de sa confidentialité. Aucun accès à la Bbox requis.
