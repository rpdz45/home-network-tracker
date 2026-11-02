# Session de contrôle Livebox : premier raccordement réseau

`routers.livebox5_control.change_schedule` effectue une action explicite
sur un calendrier existant reconnu. Aucun GET du dashboard ne l'appelle.
Le lecteur Livebox existant et sa liste de commandes restent inchangés.

## Parcours

Activation et confirmation, cible privée dans le périmètre, protection des
MAC de gestion et de passerelle fournies par l'appelant, contrôle du modèle
et du firmware attendu avant mot de passe, authentification, lecture,
une écriture au maximum puis relecture. TLS vérifié, redirections et
proxies d'environnement désactivés, délai de 5 secondes par opération,
réponse du planificateur bornée à 256 Kio. Aucun retry applicatif.

Les réponses HTTP, JSON et états ambigus sont refusés sans exposer leur
corps dans l'erreur. Après tentative d'écriture, une erreur est signalée
comme un résultat incertain, pas comme la preuve que rien n'a changé.

Le retrait du forçage restaure le calendrier. `ControlResult.state.blocked`
rapporte l'état de règle relu ; retirer le forçage peut laisser une
restriction horaire active. Cela ne prouve pas l'absence de trafic réseau.

## Limites avant utilisation dans le dashboard

- Aucun essai sur une box réelle : format de planificateur et service
  `sysbus.Scheduler` à valider sur le matériel.
- Une égalité de firmware attendu ne certifie pas sa compatibilité.
- La cible et les MAC protégées sont encore fournies par un appelant de
  confiance ; résolution depuis l'inventaire et découverte obligatoire
  des interfaces de gestion restent à raccorder.
- Pas de gestion de provenance des forçages, de création de calendrier,
  de bouton web, d'authentification dashboard ou de CSRF dans ce module.
- Pas de verrou/cooldown de contrôle concurrent dans ce premier raccordement.
- Les cookies et le contexte restent locaux au client temporaire, sans
  stockage sur disque ; sa fermeture ne prouve pas une révocation serveur.
- HTTP local exige une autorisation distincte et expose les secrets sur
  ce lien. L'identité déclarée par le routeur n'authentifie pas à elle seule
  le serveur ; la cible doit être préalablement de confiance.

Tests MockTransport ajoutés, non exécutés par l'assistant. Ruff, mypy et
suite complète à vérifier en CI. Aucun mot de passe réel, accès LAN ou
blocage réel utilisé pendant ce développement. Ne pas exposer cette
fonction directement comme une route web avant les raccordements ci-dessus.
