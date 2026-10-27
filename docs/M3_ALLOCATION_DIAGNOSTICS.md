# M3 — Diagnostic optionnel des allocations

## Utilisation après fusion et mise à jour du code

```powershell
.\.venv\Scripts\python.exe -m nettracker.resource_profile --cycles 1000 --warmup 1500 --allocation-details
```

Sans ce drapeau, aucun snapshot n'est pris et les champs JSON habituels restent
inchangés. Avec allocation_details=True dans l'API ou le drapeau CLI, chaque fenêtre
ajoute un objet allocations obtenu par comparaison des snapshots avant/après,
regroupée par ligne. Le scénario reste fictif, sans cible configurable ni réseau,
sur une base temporaire ; aucune configuration du propriétaire n'est chargée.

## Lecture et confidentialité

entries contient au plus dix lignes du paquet, triées par valeur absolue du delta
puis par source et ligne. Chaque entrée contient seulement source, line,
size_diff_bytes et count_diff. Un delta positif indique davantage d'octets/blocs
encore présents entre les captures, un delta négatif une diminution.

Les sources sont des noms relatifs nettracker/*.py à caractères ASCII sûrs.
Les chemins extérieurs au paquet, non sources ou non représentables sous cette
forme sont regroupés dans external_size_diff_bytes et external_count_diff, sans
nom de fichier. Les autres lignes du projet sont totalisées dans les champs
other_project_*. Les chemins absolus, piles complètes, lignes de code source et
contenus d'objets ne sont pas inclus dans le JSON. Aucun snapshot brut n'est exporté.
Le plafond de dix lignes concerne la sortie, pas la mémoire de collecte/comparaison.

## Limites

Les snapshots et leur traitement ajoutent des allocations et du temps. Les captures
encadrent la mesure chronométrée ; elles ne coïncident pas exactement avec les
relevés get_traced_memory. Ne pas exiger l'égalité entre les sommes des différences
et python_delta_bytes, ni comparer numériquement ce mode au profil simple.
Les lignes du profilage lui-même ne sont pas cachées : leurs allocations peuvent
apparaître. Les éléments externes sont agrégés et ne peuvent pas être localisés
par dépendance dans cette sortie. Ce diagnostic n'est ni RSS ni preuve de fuite,
ne distingue pas un cache légitime d'un objet indûment conservé et ne clôt pas M3.

## Vérifications

Six tests du module d'agrégation ont passé localement dans un paquet temporaire
isolé : masquage, bornes, totaux, tri signé, doublons et cas vides. La sérialisation
des modèles a été vérifiée séparément ; syntaxe, compilation et longueurs de ligne
des nouveaux brouillons également. Les trois tests de raccordement au profil,
préparés sur de petites phases avec backends réels bloqués, n'ont pas été exécutés
ici. Le paquet complet et Ruff ne sont pas installés ; CI Linux/Windows, mypy,
formatage et audits restent à vérifier. Aucun nouveau diagnostic exécuté chez le
propriétaire et aucune origine attribuée à la croissance de son premier rapport.

Commande ciblée : pytest tests/unit/test_allocation_diagnostics.py tests/integration/test_allocation_profile.py tests/unit/test_resource_profile.py -vv
