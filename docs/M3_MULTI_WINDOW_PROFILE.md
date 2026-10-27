# M3 - Profil de ressources multi-fenetres

## Perimetre

`--windows N` (API : `window_count=N`) accepte un entier de 1 a 10.
Le defaut reste deux fenetres et conserve le schema JSON existant, avec ou sans
`--allocation-details`. `--cycles` et `--warmup` restent limites a 1-5000.
La serie partage un processus, une connexion et une base temporaire. Elle ne lit
pas la configuration du proprietaire et ne sollicite aucun backend reseau reel.
Au maximum : 5000 cycles d'echauffement puis 10 x 5000 cycles mesures.

## Commande apres revue, CI verte et mise a jour locale

```powershell
.\.venv\Scripts\python.exe -m nettracker.resource_profile --cycles 5000 --warmup 5000 --windows 10 --allocation-details
```

Ne pas lancer cette commande tant que cette option n'est pas disponible localement.
Une serie peut prendre plusieurs minutes, notamment avec les snapshots.

## Interpretation

Pour un nombre de fenetres different de deux, chaque fenetre ajoute
`python_between_windows_delta_bytes`. La premiere valeur est `null` ; les suivantes
sont exactement `python_before_bytes` courant moins `python_after_bytes` precedent.
Une valeur negative est valide. Ce champ separe les variations entre fenetres des
variations mesurees pendant les fenetres ; il ne mesure PAS le cout exact du
profileur et ne doit pas etre soustrait comme une correction de fuite.

La construction et la conservation des rapports, les comptages SQL, le GC et les
captures contribuent potentiellement aux variations entre fenetres. Les rapports
precedents restent volontairement conserves jusqu'a la fin. Aucun snapshot brut
n'est conserve dans le rapport. Une seule serie de snapshots avant/apres est
comparee a la fois ; le plafond de dix lignes borne la sortie, pas la memoire de
collecte. Les garanties de masquage de M3_ALLOCATION_DIAGNOSTICS.md restent en place.

Comparer les deltas successifs et leurs sites d'allocation : diminution, oscillation
ou persistance. Ne pas assimiler un delta persistant a une fuite prouvee, ni un
petit delta a une preuve d'absence de fuite. Pas d'extrapolation sur 24 heures,
pas de mesure RSS, pas d'endurance de production et pas de cloture automatique M3.
Ne pas comparer numeriquement le profil detaille au profil sans snapshots.

## Motivation et validation

Sur Windows / Python 3.11.9, le proprietaire a fourni des executions au commit
7cb5b0c40827cdec1adbce2ec57ccc0eeea5c9f1. Pour deux fenetres de 5000 cycles,
la seconde croissance Python etait +6030 octets avec 1500 cycles d'echauffement,
puis +6042 octets avec 5000. Ces observations ne prouvent aucune cause.
Les appels SQLite et la conversion des dates sont des sites d'allocation, pas
l'identification des references retenant les blocs.

Tests ajoutes : bornes avant effets de bord, continuite des cycles, formule du
champ inter-fenetres, mode detaille masque et borne, nettoyage, CLI et schema par
defaut. Aucun seuil de performance ni verdict de fuite n'est impose par les tests.
Leur execution dans le paquet complet, Ruff, mypy et les autres controles restent
a verifier en CI Linux/Windows ; aucun succes non execute n'est revendique ici.

Commande ciblee :

```text
pytest tests/unit/test_resource_profile.py tests/integration/test_allocation_profile.py tests/integration/test_multi_window_profile.py -vv
```
