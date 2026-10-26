# M5 — Dashboard local : état livré et validation

## Démarrage

Après installation et configuration d’allowed_subnets : nettracker init-db --config config.toml puis nettracker serve --config config.toml. Adresse par défaut : http://127.0.0.1:8080. Le serveur n’effectue aucune collecte ; scan-once, monitor-once, health-check et process-alerts sont des commandes séparées. Aucun rafraîchissement automatique.

## Pages et modifications

/ affiche jusqu’à 500 appareils non fusionnés et la santé du collecteur. /devices/{id} affiche la fiche, les 25 dernières observations et événements, le formulaire et le graphique temporel. /events liste les 100 événements récents. /login accepte le jeton partagé.

Sans jeton configuré, les pages restent consultables sur loopback mais les écritures sont refusées (403). Avec NETTRACKER_API_TOKEN configuré, les pages exigent Bearer ou le cookie HttpOnly/SameSite=Strict de /login. Sans identifiants : redirection /login ; Bearer incorrect : 401. Une exposition hors loopback est refusée par la configuration sans jeton.

POST /devices/{id}/edit permet alias/type et marquage comme connu, dans une transaction unique. Alias limité à 120 caractères sans contrôles ASCII ; vide signifie repli nom d’hôte puis MAC. Les appareils fusionnés ne sont pas modifiables ; les ignorés ne sont pas approuvés implicitement. Aucune révocation du statut connu ni suppression d’événements historiques. Connu n’est pas une authentification.

## Historique temporel

window=24h (défaut) ou window=7d sélectionne 96 créneaux de 15 ou 105 minutes. Les autres valeurs sont invalides. La requête source=ping porte sur toute la fenêtre, indépendamment de la limite du tableau ; elle exclut les autres appareils et les découvertes. Horloge injectée, dates UTC, fin tronquée à la seconde et exclue. Moyenne/maximum de latence et nombres de réponses/sondes sont consultables dans le tableau dépliable.

Sans sonde, disponibilité inconnue et ratio absent. Le ratio réponses/sondes n’est ni un uptime temporel ni un taux de paquets reçus. Aucun prolongement d’état entre les sondes, aucune interpolation. Une non-réponse ICMP ne prouve pas une déconnexion. Détails et politique de lacunes dans M5_HISTORY_CHARTS.md.

## Sécurité et limites

GET utilise query_only ; les écritures passent par une connexion dédiée après authentification, contrôle Origin/Sec-Fetch-Site et jeton CSRF HMAC par appareil. Formulaires URL-encodés limités à 4096 octets/quatre champs ; champs inconnus, répétés et invalides refusés. Le jeton d’authentification n’est pas injecté dans le HTML. Jinja échappe les valeurs. CSP, nosniff, no-referrer et no-store sont conservés ; /docs et /openapi.json désactivés.

Un seul jeton partagé, cookie contenant ce jeton, durée de 8 heures et aucune limitation des essais de connexion. HTTP reste en clair : réseau de confiance ou proxy TLS géré par le propriétaire. Un redémarrage invalide les formulaires CSRF ouverts ; pas de coordination des clés multi-worker. Les proxys réécrivant origine/préfixe peuvent nécessiter une adaptation. Le résultat temporel est borné à 96 agrégats, sans benchmark SQL sur gros historique. Pas de pagination des listes ni de validation navigateur/mobile ou LAN annoncée.

## Tests

Le lot de consolidation ajoute tests/unit/test_web_time_windows.py : TestClient en processus, base temporaire avec migrate, observations créées par MonitoringRepository, aucune sonde réseau. Dix fonctions, dont cinq valeurs invalides paramétrées : fenêtres 24 h/7 jours, plus de 25 sondes malgré des découvertes plus récentes, isolation d’appareils, fenêtre vide, ratio distinct d’un uptime, authentification Bearer/cookie, en-têtes de sécurité, appareil absent et comparaison du contenu SQLite avant/après les GET.

Syntaxe Python et limite de 100 caractères vérifiées pendant la préparation ; tests non exécutés dans cet environnement, FastAPI et Ruff indisponibles. La CI des lots précédents ne valide pas ces nouveaux tests. Commande ciblée : pytest tests/unit/test_web_time_windows.py tests/unit/test_web.py tests/unit/test_web_edits.py tests/unit/test_history_charts.py -vv. Puis exécuter toute la CI. Aucun test sur matériel réel. Le jalon M5 complet n’est pas déclaré terminé par ce document.
