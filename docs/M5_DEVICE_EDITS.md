# M5 — Persistance des modifications d’appareils

Lié à l’issue #2. Le formulaire et la route HTTP sont maintenant décrits dans M5_DASHBOARD.md ; la présente note décrit uniquement la couche SQLite. Aucune migration supplémentaire : alias et device_type existent déjà.

`update_identity(conn, device_id, alias=..., device_type=...)` remplace les deux champs atomiquement. Un alias vide est enregistré à NULL pour conserver le repli nom d’hôte puis MAC ; limite de 120 caractères sans contrôles ASCII. Types : computer, phone, network, iot, tv, nas, camera, other, ou vide.

`mark_known(conn, device_id)` est idempotent. Il refuse les appareils ignorés ou fusionnés. Les événements historiques et règles de scan restent inchangés. Appareil absent : LookupError ; données invalides : ValueError ; erreur SQLite : DatabaseError générique. Les savepoints respectent les transactions englobantes.

Neuf tests SQLite isolés ont été exécutés lors du premier lot ; sa CI Linux/Windows a ensuite réussi. Cela ne valide pas automatiquement les nouvelles routes HTTP. Les nouveaux tests HTTP et toute la CI doivent être relancés pour le commit qui raccorde les formulaires. Aucun test matériel réel. Le statut connu est un classement manuel, jamais une authentification.
