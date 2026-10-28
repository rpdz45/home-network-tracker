# Livebox 5 : premier client de lecture

## Périmètre réel

La fonction `nettracker.routers.livebox5.read_snapshot` prépare la lecture
de l'identité de la box puis de sa liste d'appareils. Elle est désactivée
par défaut (`enabled=False`). Aucun appel n'est effectué à l'import ni au
démarrage du dashboard. Ce premier lot ne modifie ni la configuration TOML,
ni la base SQLite, ni les routes ou pages. Il n'est pas encore raccordé
à une commande utilisateur ou à l'interface graphique.

Il ne livre aucun blocage Internet, filtrage Wi-Fi, déblocage ou effacement
d'appareil. Aucun support UniFi n'est ajouté. Les appareils renvoyés sont
des données brutes de la box, conservées en mémoire ; leur normalisation,
leur provenance et leur affichage restent à implémenter. Aucun modèle
exact d'appareil connecté n'est garanti.

## Protocole étudié

Les échanges ont été vérifiés dans les références publiques MIT du projet
non officiel LiveboxMonitor de Pierre Dor :

- https://github.com/p-dor/LiveboxMonitor/blob/main/src/LiveboxMonitor/api/LmSession.py
- https://github.com/p-dor/LiveboxMonitor/blob/main/src/LiveboxMonitor/api/LmDeviceApi.py
- https://github.com/p-dor/LiveboxMonitor/blob/main/src/LiveboxMonitor/api/LmLiveboxInfoApi.py

Le présent client est une implémentation originale, sans import de
LiveboxMonitor et sans garantie de stabilité d'API officielle Orange.
Les noms bruts `Livebox Fibre` et `Livebox 5` sont les seules identités
acceptées ici. Une identité inconnue est refusée, sans modèle de repli.

## Protections

- Activation explicite, adresse IPv4 littérale privée comprise dans les
  sous-réseaux autorisés, ports standards et aucun nom DNS à résoudre.
- Pas d'identifiants, chemin personnalisé, paramètres ou fragment dans l'URL.
- HTTPS avec vérification TLS ; aucun contournement de certificat.
- HTTP local uniquement avec `allow_http=True` explicitement fourni :
  le mot de passe et le trafic seraient alors non chiffrés et pourraient
  être observés depuis un point de capture approprié. Ce n'est pas un
  mode invisible. Le précontrôle de modèle n'est pas une authentification
  cryptographique de la box, notamment en HTTP.
- Identification avant envoi du mot de passe administrateur.
- Aucune redirection, proxy d'environnement ou sauvegarde de cookies sur disque.
- Réponses non compressées, taille limitée à 2 Mio chacune, au plus 512 appareils.
- Timeout réseau de 5 s par attente ; aucune échéance globale stricte annoncée.
- Liste fermée d'appels : identification, création de contexte et lecture
  des appareils uniquement. Aucun appel de modification de configuration.
- Erreurs rendues génériques ; le client ne journalise pas les corps des
  requêtes/réponses ni les identifiants. Le mot de passe est reçu via SecretStr
  et transmis uniquement à la cible validée lors de l'authentification.

L'authentification crée un contexte côté Livebox. La connexion HTTP est
fermée après la lecture, mais ce prototype ne libère pas explicitement le
contexte serveur ; il peut persister jusqu'à expiration. Aucun rafraîchissement
périodique ni réutilisation de session n'est activé dans ce lot.

## Validation et limites

Les 37 cas ciblés ont réussi dans un environnement isolé avec SecretStr,
HTTPX MockTransport et réponses synthétiques. Aucun accès réseau réel,
identifiant réel ou inventaire du foyer n'a été utilisé.

Restent à exécuter : suite complète du dépôt, Ruff et formatage, mypy,
contrôles de sécurité et CI Windows/Linux. Aucun test existant n'est désactivé.
Aucun test sur une Livebox ou sur le poste du propriétaire n'a été effectué.
La compatibilité réelle de son firmware et la disponibilité de l'identité
sans authentification devront être vérifiées avant de rendre le client utilisable.
Les identifiants devront être renseignés localement, jamais publiés dans Git
ou transmis dans une conversation.
