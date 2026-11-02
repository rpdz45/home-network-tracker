# Garde-fous de confirmation du contrôle routeur

Ce module est un service préparatoire, pas une route web et pas une activation du contrôle.

## Contrat

- Une instance unique de `ControlGuards` doit être partagée par toutes les requêtes du processus.
- `prepare` reçoit un identifiant local et une action booléenne. Le résolveur injecté construit la MAC, l'IPv4 et le type de routeur côté serveur ; aucune IP/MAC du navigateur ne doit être transmise directement à l'adaptateur.
- Le jeton aléatoire expire après 60 secondes par défaut (maximum 300), lie la session, l'identifiant et la demande exacte, et ne peut servir qu'une fois.
- La confirmation relit l'inventaire et refuse une cible modifiée. Le jeton est consommé avant toute exécution, même en cas d'échec ou de résultat incertain.
- Un verrou non bloquant couvre résolution et exécution ; aucune relance automatique n'est faite. La capacité des confirmations est bornée.
- Les cibles protégées et les adresses hors sous-réseaux privés autorisés sont refusées.

## Raccordement restant et limites

Le résolveur SQLite concret reste à implémenter : rejeter appareil fusionné, observation périmée, IPv6 et association IP/MAC ambiguë, puis choisir le routeur depuis la configuration serveur. Le service injecté ne certifie pas ces propriétés à lui seul. La découverte fiable des MAC de gestion et de passerelle reste nécessaire.

L'exécuteur devra conserver les contrôles de modèle/firmware, la protection de l'adresse du routeur et la relecture de l'adaptateur Livebox. Une libération retire le forçage sans promettre un accès immédiat si le calendrier interdit encore l'accès.

La session doit provenir de l'authentification serveur, jamais d'un champ libre fourni par le navigateur. Le jeton n'est ni une authentification ni une protection CSRF complète : les futures routes devront imposer authentification, POST, contrôle d'origine/CSRF, limites de requêtes et affichage explicite de la cible et de l'action. Ne pas journaliser les jetons.

Le verrou et les jetons sont locaux au processus : plusieurs workers, plusieurs instances ou des appels directs à l'adaptateur contournent cette sérialisation. Aucun verrou distribué ni transaction couvrant inventaire et routeur ; une modification concurrente de l'inventaire après relecture reste possible. Un redémarrage invalide les confirmations.

## Validation

Tests synthétiques dans `tests/unit/test_control_guards.py` : session, usage unique, changement de cible, expiration, capacité, refus des cibles, échec et réentrance. Ces tests ne remplacent pas un test multithread ni la validation web.

Commande : `python -m pytest tests/unit/test_control_guards.py`.

Tests rédigés mais non exécutés par l'assistant. Ruff, formatage, mypy, couverture et sécurité restent à vérifier en CI Linux/Windows. Aucun test sur matériel ou réseau réel.
