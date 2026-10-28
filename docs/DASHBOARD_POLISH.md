# Refonte du dashboard domestique

## Contexte et périmètre

Application locale utilisée sous Windows, interface en français et heures de
Paris. Le propriétaire dispose d'une Livebox 5 Orange. L'accès éventuel à
cette box n'est pas implémenté ni activé par ce lot. Aucun identifiant réel
ou inventaire du foyer ne doit être ajouté au dépôt.

## Lot 1A : socle des dates

- Fonction `paris_datetime` dans `nettracker.web.formatting`.
- Affichage prévu : `15:07 · 28/10/2026`, fuseau `Europe/Paris`.
- Stockage UTC conservé sans modification ni migration.
- `tzdata` ajouté aux dépendances pour les systèmes sans base IANA, notamment
  Windows.
- Valeur absente : « Non renseigné ».
- Valeur invalide : « Date invalide ».
- Date sans fuseau : « Fuseau non renseigné » ; aucun fuseau n'est inventé.

Ce lot ajoute une fonction et ses tests. Il ne l'enregistre pas encore comme
filtre Jinja et ne modifie pas encore les pages du dashboard. Aucun changement
visuel n'est donc attendu à ce stade.

## Validation

Les 16 cas ont été exécutés avec pytest dans un environnement isolé contenant
une copie exacte du module et des tests, sans accès réseau. Ils couvrent les
changements d'heure, le passage au lendemain et les données incomplètes.
La suite complète du dépôt, les outils de qualité et la CI Windows/Linux
restent à exécuter : ces tests isolés ne les remplacent pas.

Commande à exécuter dans un environnement du projet à jour :

```powershell
.\.venv\Scripts\python.exe -m pytest tests/unit/test_web_formatting.py -q
```

Aucun test sur le réseau ou le matériel du propriétaire n'a été effectué.
Aucune sonde, notification ou rétention n'est activée par ce lot.

## Suite du périmètre convenu

1. Raccorder le formateur aux pages et ajouter des tests de rendu.
2. Remplacer les codes internes par des libellés français compréhensibles,
   sans confondre validation personnelle et disponibilité réseau.
3. Améliorer la liste et le détail, avec états sans données explicites et
   indicateurs d'activité uniquement fondés sur des données réelles.
4. Enrichir l'identification en distinguant marque, fabricant de l'interface,
   modèle, source et niveau de certitude ; permettre les corrections locales.
5. Préparer le lancement Windows et les icônes.

L'enrichissement Livebox reste à étudier. Il ne doit pas conditionner le
fonctionnement du logiciel ni activer silencieusement une collecte réseau.
