# M5 — Historique temporel ICMP 24 h / 7 jours

## Utilisation et périmètre

La fiche /devices/{id} propose maintenant une période 24 heures (défaut) ou 7 jours via le paramètre window=24h ou window=7d. Les autres valeurs sont refusées par la validation FastAPI. Le tableau des dernières observations reste limité à 25 lignes, mais le graphique ne dépend plus de cette limite : toutes les sondes source=ping de la fenêtre sont agrégées par une requête dédiée en lecture seule.

Le graphique présente exactement 96 créneaux chronologiques de même durée : 15 minutes sur 24 h, 105 minutes sur 7 jours. L’origine de l’axe est le début de la fenêtre, pas le rang d’une mesure. Les données sont exprimées en UTC, avec début inclus et fin exclue. La fin est l’horloge injectée, convertie en UTC et tronquée à la seconde ; les mesures de la seconde en cours ne sont donc pas encore affichées.

Chaque barre représente la moyenne des latences des réponses dans son créneau. L’échelle verticale utilise le maximum de latence observé, avec un minimum de 1 ms. Le tableau dépliable indique début, fin, nombre de mesures, nombre de réponses, état observé, moyenne et maximum pour les 96 créneaux. Les valeurs nulles ne deviennent jamais des zéros ; une réponse valide à 0 ms reste comptée comme réponse.

## Lacunes et disponibilité

Un créneau sans mesure est explicitement inconnu (?). Un créneau sans latence de réponse affiche ×. Le tableau distingue réponses seules, non-réponses seules, mixte et sans mesure. Même un créneau comportant une réponse ne prouve pas une disponibilité continue entre les sondes. Aucune interpolation ou liaison de courbe entre créneaux.

Le ratio global est la somme des réponses divisée par la somme des sondes, sans moyenne de pourcentages de créneaux. Ce n’est pas un uptime temporel ni un taux de paquets reçus. Aucune mesure donne un ratio absent, pas 0 % ni 100 %. Une absence de réponse ICMP ne prouve pas une déconnexion. Le calcul d’un uptime temporel reste hors périmètre tant qu’une politique de couverture n’est pas définie.

## Décision technique et sécurité

Agrégation SQL dans web/timeseries.py et objets Bucket/TimeSeries immuables ; pas de migration ou nouvelle dépendance. L’index existant sightings(device_id, seen_at) sert au filtrage par appareil et fenêtre. Le résultat chargé en Python est borné à 96 agrégats ; le travail SQL dépend néanmoins du volume de sondes dans les sept jours, sans benchmark de charge réalisé. Les horodatages attendus sont le format canonique UTC avec microsecondes produit par le repository. La conversion en secondes utilise les 19 premiers caractères pour éviter l’arrondi SQLite des fractions proches de la seconde suivante ; le filtrage des bornes conserve les microsecondes.

HTML/CSS serveur uniquement : aucun JavaScript, CDN, scan, télémétrie ou connexion sortante. Authentification, CSRF, query_only et CSP conservés. Les sept anciens tests du composant compact sont remplacés par quinze tests portant sur le composant temporel et sa requête ; l’ancien contrat limité à 25 observations est volontairement supprimé.

## Validation et limites

Quinze tests SQLite/Jinja ont réussi dans l’environnement de préparation avec un schéma SQLite minimal compatible avec les colonnes utilisées et le template exact chargé via DictLoader. Les définitions des exceptions nécessaires ont été recréées en mémoire ; les imports du paquet installé et le chargeur de fichiers réel n’ont pas été validés par cette exécution. Deux attentes initiales de fixtures ont été corrigées : leurs mesures tombaient de part et d’autre d’une frontière de créneau et ne devaient pas être moyennées ensemble. Le test distinct des frontières temporelles reste présent.

Cas vérifiés : fenêtres et durées, 96 créneaux, absence de données, bornes incluses/exclues, microsecondes, découverte et autres appareils exclus, plus de 25 mesures, moyenne/maximum, créneau mixte, ratio pondéré par sondes, non-réponse, latence nulle, fuseaux horaires, paramètres invalides, erreur SQLite et connexion query_only. Syntaxe et longueur des lignes des trois fichiers Python vérifiées. Tests HTTP, migrations réelles, Ruff, mypy, audits, couverture et CI complète restent à exécuter pour ce commit. Aucun test navigateur, mobile, réseau ou matériel réel.

Commande ciblée : pytest tests/unit/test_history_charts.py tests/unit/test_web.py tests/unit/test_web_edits.py -vv. Vérifier ensuite toute la CI avant fusion. Test manuel : choisir les deux périodes, comparer les agrégats au tableau dépliable et vérifier qu’une fenêtre sans sondes reste inconnue. Le README historique et les notes des lots précédents peuvent encore décrire l’ancien aperçu ; cette page décrit le comportement de ce lot temporel.
