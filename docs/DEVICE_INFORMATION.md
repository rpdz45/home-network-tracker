# Comprendre les informations des appareils

## Changement de présentation uniquement

La liste et la fiche distinguent identité, validation personnelle, observations
et mesures. Aucun changement de schéma, statut, collecte, seuil, permission,
authentification ou contrôle réseau. Aucun appel Fing ou Bbox ajouté.
Le mode local sans administration de la box reste disponible.

## Fraîcheur de la découverte

« Collecteur : périmé » est remplacé par :

- « Découverte : aucune collecte réussie » si aucune date n'est disponible ;
- « Découverte : collecte récente » selon la santé déjà calculée par le serveur ;
- « Découverte : à actualiser » si le seuil configuré est dépassé ;
- « Découverte : horodatage à vérifier » si l'âge est négatif ;
- « Découverte : ancienneté inconnue » si le contexte ne fournit pas l'âge ou l'état.

La date reste affichée à l'heure de Paris, et les données UTC ne sont pas
modifiées. L'âge est affiché en minutes complètes, puis heures et jours ;
moins d'une minute est explicite. Le seuil exact reste calculé par le backend,
indépendamment de cet arrondi d'affichage. Aucune date de collecte inventée.
Une collecte réussie peut relire un cache contenant des observations anciennes.
Elle ne démontre ni la présence de tous les appareils ni l'exécution actuelle
d'une boucle de suivi. Actualiser la page ne déclenche pas de nouvelle collecte.

## Identité et confiance

Le libellé « MAC privée / locale » devient « Adresse MAC locale (privée
possible) ». Le bit local ne prouve pas une rotation aléatoire, un fabricant,
un appareil reconnu ou une intrusion. Une adresse locale peut aussi être
virtuelle ou configurée manuellement.

Le fabricant réseau reste un indice sur l'interface, pas une garantie de marque
commerciale ou de modèle. Le nom personnalisé reste prioritaire ; un nom réseau
annoncé n'est pas une identité vérifiée. Les modèles fournis par Fing sont dans
la page optionnelle correspondante et ne sont pas persistés dans la fiche locale.
Aucun modèle fictif ou reconnaissance automatique supplémentaire n'est ajouté.

« Reconnu », « À valider », « À confirmer » et « Ignoré » gardent exactement
leurs valeurs et règles existantes. Le guide explique qu'il s'agit d'un
classement personnel et qu'ignorer une fiche ne bloque aucun accès réseau.

## Mesures

Les résultats ICMP sont des mesures enregistrées, pas nécessairement actuelles.
Une absence de réponse ne prouve pas une déconnexion ; une réponse ne prouve pas
l'identité. Sans mesure, l'état est inconnu. La latence est un délai de réponse
en millisecondes, et la perte décrit les sondes sans réponse pendant un test.
Aucune disponibilité continue déduite. Les formulaires existants, l'historique
et leurs protections sont conservés.

## Vérification

15 cas de rendu hors réseau ont passé dans l'environnement isolé : dates,
ancienneté, absence de collecte, futur, MAC locale, informations inconnues,
échappement HTML et conservation du formulaire de modification. Le gabarit de
base y est réduit ; les macros de date et l'historique existants sont utilisés.
Cela ne remplace pas la suite complète du dépôt. Le test web historique sur
les deux libellés de santé est adapté, sans supprimer de contrôle.

```text
python -m pytest tests/unit/test_device_information.py
python -m pytest tests/unit/test_web.py tests/unit/test_web_list_presentation.py
python -m ruff check .
python -m ruff format --check .
python -m mypy
python -m pytest --cov
```

Tests FastAPI complets non exécutés ici, cette dépendance étant absente.
Ruff, mypy et CI Linux/Windows restent à vérifier avant fusion. Aucun test sur
le réseau réel, aucune prétention d'identification ou de blocage matériel.
