# Résolution locale des cibles de contrôle

`nettracker.db.control_inventory.resolve_control_target` construit une `AccessRequest` à partir d'un identifiant SQLite et d'une action. La sélection du routeur et le seuil de fraîcheur viennent exclusivement de la configuration serveur. Aucun accès réseau, aucune écriture et aucune route web ne sont ajoutés.

## Politique conservatrice

- Seules les observations `discovery` comptent, jamais les mesures `ping` ni une identification Fing.
- Le seuil de fraîcheur est explicite, strictement positif et limité à cinq minutes. L'horloge fournie doit être consciente de son fuseau.
- Appareil absent ou fusionné, absence de découverte récente, dernière découverte hors ligne, IPv6, date future ou non canonique : refus.
- Plusieurs IPv4 récentes pour le même appareil ou la même IPv4 observée récemment pour un autre appareil : refus, même si cet autre appareil a été fusionné. Après un renouvellement DHCP, attendre la fin de la fenêtre contradictoire et obtenir une découverte récente.
- Au-delà de 1024 lignes de preuves récentes, refus conservateur plutôt qu'une résolution partielle.
- Une seule requête SQL paramétrée réunit la cible et les preuves récentes ; aucune transaction d'écriture n'est ouverte.

## Intégration et limites

Le résolveur ne prouve pas l'identité physique : une observation locale peut être erronée ou usurpée. Il suppose les dates UTC canoniques produites par le repository ; les lignes trop anciennes selon leur texte ne sont pas inspectées. La borne limite les lignes retournées, pas le coût de lecture SQLite.

Il reste à injecter ce résolveur dans l'instance partagée de `ControlGuards`, puis à raccorder l'exécuteur et les routes authentifiées avec protections CSRF. Les sous-réseaux privés autorisés et les cibles protégées restent vérifiés par les garde-fous et l'adaptateur. Ce résolveur seul ne doit jamais autoriser une écriture routeur.

Aucune atomicité entre SQLite et le routeur ; une modification après résolution reste possible. Aucun secret ni inventaire réel n'est fourni dans ces tests.

## Validation

Tests en SQLite mémoire avec les migrations du projet : fraîcheur, date future, appareil absent/fusionné/hors ligne, changement d'IP, IP partagée, ping, IPv6 et erreur SQLite.

Commande : `python -m pytest tests/unit/test_control_inventory.py tests/unit/test_control_guards.py`.

Tests rédigés mais non exécutés par l'assistant. Ruff, formatage, mypy, couverture, suite complète et sécurité restent à vérifier en CI Linux/Windows. Aucun test sur réseau ou matériel réel.
