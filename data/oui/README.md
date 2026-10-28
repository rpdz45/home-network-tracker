# Base IEEE MA-L : installation et chargement local

## Source et limites

Source fixe : `https://standards-oui.ieee.org/oui/oui.csv`, registre public
de la Registration Authority IEEE. Les colonnes utiles sont `Registry`,
`Assignment` et `Organization Name`. Le résultat est un titulaire de préfixe
MA-L, pas une garantie de marque commerciale ni un modèle exact. Les MAC
locales/privées et multicast ne reçoivent pas d'attribution par la recherche.

Aucune base complète n'est redistribuée dans ce dépôt. Le fichier téléchargé
reste local et est ignoré par Git. Cette implémentation ne prétend pas
accorder de droits de redistribution sur les données IEEE.

## Installation et mise à jour explicites

Après installation d'une version contenant cet outil, depuis la racine du
projet, afficher d'abord l'aperçu (aucun réseau ni écriture) :

```powershell
.\.venv\Scripts\python.exe -m nettracker.discovery.oui_update
```

Pour autoriser le téléchargement HTTPS et l'installation locale :

```powershell
.\.venv\Scripts\python.exe -m nettracker.discovery.oui_update --apply
```

La même commande met à jour une base existante. `--output CHEMIN.csv` permet
un autre emplacement ; ce choix ne change pas le chemin d'autochargement.
Une destination personnalisée exige donc `scan-once --oui-file CHEMIN.csv`.

L'outil n'est appelé ni à l'ouverture du dashboard ni pendant une découverte.
Il ne lit pas l'inventaire du réseau, les identifiants de la box ou les
secrets de configuration ; il n'envoie ni MAC, ni nom d'appareil, ni jeton.
Comme toute requête HTTPS, le serveur reçoit les métadonnées normales de
connexion, notamment l'adresse IP publique du client.

## Protections

- HTTPS avec vérification TLS, URL fixe, aucune redirection ni authentification.
- Paramètres de proxy et certificats provenant de l'environnement ignorés.
- Réponse non compressée uniquement, statut 200 requis et lecture limitée
  à 8 Mio, avec vérification de Content-Length lorsqu'il est fourni.
- Délais HTTPX : connexion 5 s, lectures et autres attentes réseau 10 s.
  Budget de 30 s vérifié entre lectures : ce n'est pas une échéance stricte
  capable d'interrompre instantanément une attente système en cours.
- Validation UTF-8 avec ou sans BOM, CSV strict, colonnes et lignes cohérentes,
  au moins une entrée MA-L publiquement nommée avant toute écriture.
- Écriture temporaire voisine, fermeture et synchronisation du fichier,
  puis remplacement. En cas d'échec avant ce remplacement, l'ancien fichier
  reste intact. Aucun historique de versions ni sauvegarde séparée n'est créé.
- Destination .csv obligatoire ; liens symboliques et répertoires refusés.

Un échec de nettoyage peut laisser un temporaire local ; il est signalé et
les fichiers `.oui-*.tmp` sont ignorés par Git.

## Chargement après installation

La collecte lit `data/oui/oui.csv` depuis le dossier de lancement si aucune
table de fabricants n'est fournie explicitement. Le chemin est relatif au
répertoire courant, pas au dossier de configuration. Une lecture par collecte,
pas par appareil ; limite de 8 Mio et UTF-8 avec ou sans BOM.

`scan-once --oui-file CHEMIN` conserve sa priorité. Une table explicitement
fournie, même vide, désactive le recours au fichier par défaut. L'import
`nettracker.discovery.vendor.parse_ma_l_csv` reste compatible.

Une base absente ou inutilisable ne bloque pas la découverte ; elle ne
fournit simplement aucun enrichissement. Le chargement ne télécharge rien.
Installer la base ne modifie pas immédiatement les appareils stockés : une
nouvelle découverte est nécessaire pour enrichir les appareils observés.
Aucun ping, mDNS ou autre sondage actif n'est autorisé par cet outil.

## Validation

Les 29 cas de l'outil ont réussi dans un environnement isolé avec des fichiers
synthétiques et HTTPX MockTransport. Aucun téléchargement réel n'a eu lieu.
Les tests couvrent notamment erreurs HTTP, redirections, délais simulés,
limites de taille, CSV invalides, installation et conservation de l'ancien
fichier après un échec de remplacement.

La suite complète, les contrôles de qualité/sécurité et la CI Windows/Linux
restent à exécuter pour ce lot. Le téléchargement réel depuis IEEE, les
particularités du poste Windows et le réseau du propriétaire n'ont pas été
testés ici. Aucun test existant n'est désactivé.
