# Hub DeckDock, étape A : plan d'implémentation

> **Pour les agents :** sous-compétence REQUISE : superpowers:subagent-driven-development (recommandé) ou superpowers:executing-plans, tâche par tâche. Les étapes sont des cases à cocher (`- [ ]`).

**Objectif :** un hub public où les auteurs publient leurs decks depuis leur CI avec un jeton, où un admin valide les nouveaux decks, et qui sert un catalogue ainsi que les fichiers au plugin Anki actuel.

**Architecture :** un nouveau site `deckdock-hub` créé depuis `site-starter`, avec le module `accounts` et un module propre `decks` (architecture hexagonale du starter). Les fichiers sont rangés par empreinte sur un volume du VPS, les informations dans Postgres. La vérification des envois passe par la bibliothèque Python `deckdock`, embarquée dans l'image. Le monorepo `deckdock` reçoit la vérification non stricte en JSON, la comparaison des types de cartes et la commande `publish` de l'Action.

**Pile :** Next.js 16.4, Payload 3.90.2, Postgres, Better Auth (module `accounts`), Python 3 en bibliothèque standard (`deckdock`), GitHub Actions composite, `node:test`, Playwright et axe, pytest.

**Spec :** `docs/superpowers/specs/2026-11-25-deckdock-hub-a-design.md` (avec ses « Précisions après relecture »). Contexte : `docs/superpowers/specs/2026-11-25-deckdock-hub-decisions.md`, `spec/deckdock-1.md` (sections « Publishing layout » et « Changing a published notetype »).

## Contraintes globales

- **Dépôts.** `NayanChauveau/deckdock` (monorepo : `cli/`, `action/`, `addon/`, `spec/`), `NayanChauveau/deckdock-template`, et le nouveau `NayanChauveau/deckdock-hub`, cloné dans `~/Documents/projets-perso/deckdock-hub`.
- **Commits et pushs.** Dans `deckdock-hub`, les règles d'`AGENTS.md` du starter s'appliquent : aucun commit sans accord explicite du propriétaire, et un accord séparé pour chaque push. Dans `deckdock` et `deckdock-template`, les commits locaux sont permis sur une branche de travail. Ne jamais pousser sans accord. Ne jamais toucher au VPS : la production ne change que par la CI.
- **Tests.** Boucle rapide pendant le travail (`AGENTS.md` du starter) : `pnpm test:unit` et les groupes concernés. La suite complète `pnpm test` seulement avant de demander à committer ou pousser.
- Le hub est un **consommateur** du format : il valide en mode **non strict**.
- **Adresse de service** d'un deck : `<base>` = `https://<domaine>/d/<pseudo>/<deck-id>`. On y sert `<base>/index.json` (`deckdock-index/1`), `<base>/<édition>/deck.json` et `<base>/<édition>/media/<fichier>`, identiques à la section « Publishing layout ». L'adresse à coller dans le plugin est `<base>/<édition>/`.
- **Jetons de publication :**
  - préfixe `ddk_` suivi de 32 octets aléatoires encodés en base64url ;
  - un jeton par deck, affiché une seule fois ;
  - stocké en sha256, comparé en temps constant.
- **Envois :**
  - archive `tar.gz` d'un dossier `dist/<édition>/` ;
  - limite de **100 Mo** compressés au démarrage, réglable par la variable `HUB_MAX_UPLOAD_BYTES` ;
  - taille décompressée au plus 524 288 000 octets (500 Mio) et 20 000 fichiers au plus ;
  - aucun chemin absolu, aucun `..`, aucun lien symbolique ou matériel, aucun fichier spécial.
- **Pseudo public :** `^[a-z0-9](?:[a-z0-9-]{1,28}[a-z0-9])$` (3 à 30 caractères), unique, non modifiable une fois qu'un deck est publié.
- **Statuts d'un deck :** `pending` → `approved` ↔ `hidden`, et aussi `pending` → `hidden`. Seul un admin qui a passé la double authentification change le statut.
- **La version `"dev"` est refusée** à la publication. Une même `deck.version` avec un contenu identique est acceptée sans rien créer ; avec un contenu différent, elle est refusée en 409.
- **Contenu des cartes et médias :** jamais exécutés dans le domaine du site. L'aperçu passe par un `iframe sandbox` sans `allow-same-origin`, et les médias sont servis avec `X-Content-Type-Options: nosniff` et une CSP `default-src 'none'; sandbox`.
- Textes visibles en français et en anglais. Code, commentaires et messages de commit en anglais.

## Points de vigilance

1. **Archive piégée** (chemin `../`, lien symbolique, bombe de décompression) : refusée avant toute écriture hors du dossier temporaire. Test en Task 5.
2. **CI relancée deux fois pour le même commit** : la seconde publication répond 200 « déjà publiée » sans doublon. Test en Task 6.
3. **Jeton d'un deck utilisé pour publier un autre deck** (`deck.id` différent) : 409, rien n'est écrit. Test en Task 6.
4. **Template de carte qui contient `<script>` ou un média SVG avec du JavaScript** : ne s'exécute pas sur le domaine du hub. Tests en Task 7 (médias) et Task 9 (aperçu).
5. **Nouvelle version qui supprime un champ d'un type de carte publié** : 409, avec un message qui explique de créer un nouveau type de carte. Tests en Task 1 (bibliothèque) et Task 6 (API).

---

### Task 1 : `deckdock` — vérification non stricte en JSON et comparaison des types de cartes

**Fichiers :**
- Modifier : `cli/src/deckdock/cli.py`, `cli/src/deckdock/format/check.py` (si `check_dist` ne prend pas encore `strict`)
- Créer : `cli/src/deckdock/compat.py`
- Tests : `cli/tests/test_cli.py`, `cli/tests/test_compat.py`
- Recopier ensuite la copie embarquée du plugin avec `addon/scripts/vendor.py` (le test d'égalité l'exige)

**Interfaces :**
- Produit : `deckdock check [DIST] [--non-strict] [--json]`.
  - `--json` affiche `{"ok": bool, "issues": [{"path": str, "where": str, "message": str}]}` sur la sortie standard.
  - Le code de sortie reste 1 s'il y a des erreurs.
- Produit : `deckdock.compat.notetype_changes(previous: CompiledDeck, new: CompiledDeck) -> list[NotetypeChange]`, avec `NotetypeChange(notetype: str, kind: Literal["appended_fields", "breaking"], detail: str)`. Les types de cartes sont associés par `id`. Un type de carte nouveau ou disparu n'est pas un changement.
- Produit : `deckdock compat PREVIOUS_DECK_JSON NEW_DECK_JSON [--json]`. Le code de sortie vaut 1 s'il y a au moins un `breaking`.

- [ ] **Étape 1 : tests qui échouent :**
  - `test_check_non_strict_accepts_unknown_key` : un `deck.json` avec une clé inconnue est refusé sans `--non-strict` et accepté avec.
  - `test_check_json_output` : la sortie JSON est valide, et `ok` et `issues` sont exacts.
  - `test_compat_appended_field` : un champ ajouté à la fin donne un `appended_fields`.
  - `test_compat_breaking` : chaque cas du tableau « Changing a published notetype » donne un `breaking` : champ supprimé, renommé, réordonné, template ajouté ou supprimé, `kind` changé.
  - `test_compat_unchanged` : un texte de template ou un CSS modifié donne `[]`.
- [ ] **Étape 2 :** `cd cli && uv run pytest -q` → ÉCHEC.
- [ ] **Étape 3 : implémenter.** Reprendre la règle de structure déjà codée dans `addon/src/deckdock_addon/engine.py` (`_structure_problem`) pour que le hub et le plugin jugent de la même façon. Ne pas importer le plugin : la logique va dans la bibliothèque, puis la copie embarquée est régénérée.
- [ ] **Étape 4 :** `cd cli && uv run pytest -q && uv run ruff check . && uv run basedpyright`, puis `cd ../addon && uv run python scripts/vendor.py && uv run pytest -q`. Tout passe.
- [ ] **Étape 5 : commit** (`deckdock`) : `feat(cli): non-strict JSON check and notetype compatibility`.

### Task 2 : `deckdock` — commande `publish` de l'Action, et étape du template

**Fichiers :**
- Modifier : `action/action.yml`, `action/README.md`
- Créer : `action/publish.py`, en Python standard, appelé par l'Action
- Tests : `action/tests/test_publish.py`, avec un faux serveur `http.server` local
- Modifier dans `deckdock-template` : `.github/workflows/deck.yml`, `README.md`, `AGENTS.md` (une phrase)

**Interfaces :**
- Entrées de l'Action : `command` (`check` | `publish`), `path` (défaut `dist`), `hub-url` (obligatoire pour `publish`, sans valeur par défaut tant que le domaine n'existe pas), `deckdock-ref`.
- La variable d'environnement `DECKDOCK_TOKEN` est obligatoire pour `publish`.
- Pour chaque `<path>/<édition>/` : archive `tar.gz` du dossier, puis `POST <hub-url>/api/publish/<édition>` avec `Authorization: Bearer $DECKDOCK_TOKEN` et `Content-Type: application/gzip`.
- Réponse attendue : JSON `{"status": "published" | "already_published" | "pending_review", "version": str, "notes": int, "warnings": [str], "errors": [{"where": str, "message": str}]}`.
- Toute réponse ≥ 400 fait échouer l'étape et affiche chaque erreur avec `::error::`. Les `warnings` passent par `::warning::`.

- [ ] **Étape 1 : tests qui échouent :**
  - `test_publish_posts_each_edition` : deux éditions donnent deux requêtes, avec le bon chemin et l'en-tête `Authorization`.
  - `test_publish_fails_with_hub_errors` : un 422 avec deux erreurs donne une sortie non nulle et deux lignes `::error::`.
  - `test_publish_requires_token_and_hub_url`.
  - `test_publish_never_prints_token` : le jeton n'apparaît dans aucune sortie.
- [ ] **Étape 2 :** `uv run --with pytest pytest action/tests -q` → ÉCHEC.
- [ ] **Étape 3 : implémenter**, puis valider le YAML avec `uvx check-jsonschema --builtin-schema vendor.github-action action/action.yml`.
- [ ] **Étape 4 : template.**
  - Remplacer le bloc commenté « Publish to DeckDock hub » de `deck.yml` par une étape active.
  - Condition : `github.event_name == 'push' && github.ref == 'refs/heads/main'` et secret présent. Mettre le secret dans un `env` du job et tester `env.DECKDOCK_TOKEN != ''`, car `secrets` n'est pas lisible dans `if`.
  - Elle appelle `NayanChauveau/deckdock/action@v2` avec `command: publish`, `hub-url: ${{ vars.DECKDOCK_HUB_URL }}`, et ne tourne que si cette variable existe.
  - Valider avec `uvx check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/deck.yml`.
  - Documenter en une ligne : « Pour publier sur le hub, ajoutez le secret `DECKDOCK_TOKEN` et la variable `DECKDOCK_HUB_URL` ».
- [ ] **Étape 5 : commits** (`deckdock`, puis `deckdock-template`) : `feat(action): publish command`, puis `ci: publish to the DeckDock hub when a token is set`.

### Task 3 : `deckdock-hub` — création du site, module `accounts`, Python dans l'image

**Prérequis du propriétaire (étape 1 de `STARTER.md`) :** créer le dépôt avec `gh repo create NayanChauveau/deckdock-hub --private --template NayanChauveau/site-starter --clone`, privé ou public au choix. Il faut aussi choisir le domaine. S'il n'est pas encore choisi, initialiser avec `--domain deckdock-hub.invalid`, puis le changer dans `site.config.json` avant le déploiement.

**Fichiers :** générés par `init-site`. Ensuite, modifier :
- `Dockerfile` : Python et la bibliothèque `deckdock` dans `production` ;
- `docker-compose.prod.yml` : volume `hub-files` monté sur `/data/hub`, écriture autorisée seulement là ;
- `site.config.json` : section `modules.decks` ;
- un test de déploiement qui vérifie la présence de Python dans l'image.

**Interfaces :**
- `init-site --slug deckdock-hub --name "DeckDock" --domain <domaine> --port <port libre> --locales fr,en --modules accounts`.
- Dans l'image `production` :
  - `python3` est installé par `apt-get install --no-install-recommends python3-minimal`, sans pip ;
  - la bibliothèque est copiée dans `/opt/deckdock` depuis `cli/src/deckdock`, à un commit épinglé de `NayanChauveau/deckdock` (argument de build `DECKDOCK_REF`) ;
  - `PYTHONPATH=/opt/deckdock` ;
  - la commande `python3 -m deckdock check --non-strict --json <dir>` marche.
- Le chemin des fichiers vient de la variable `HUB_DATA_DIR` : `/data/hub` en production, un dossier temporaire dans les tests.

- [ ] **Étape 1 : test qui échoue :** dans le smoke des images (`deploy/smoke.py` ou son test Python), `docker run … python3 -m deckdock --version` répond. Le conteneur est en lecture seule, sauf `/data/hub` et le tmpfs.
- [ ] **Étape 2 :** lancer ce test → ÉCHEC.
- [ ] **Étape 3 : implémenter.** Documenter dans le `README` du hub les écarts avec l'image durcie du starter : Python, et le volume en écriture.
- [ ] **Étape 4 :** `pnpm dev:setup`, puis `pnpm test --group=static,database` et le smoke des images. Tout passe.
- [ ] **Étape 5 : commit**, avec l'accord du propriétaire : `feat: DeckDock hub site from the starter, with Python checker in the image`.

### Task 4 : module `decks` — données, règles et jetons

**Fichiers :**
- Créer : `src/modules/decks/` (`module.ts`, `domain/`, `application/`, `adapters/payload/` : collections `authors`, `decks`, `editions`, `versions`)
- Créer : la migration générée et relue
- Tests : `tests/decks.domain.test.ts`, `tests/decks.integration.ts` (stage ajouté à `tests/run.mjs`)

**Interfaces :**
- Domaine (pur) :
  - `validateHandle(handle: string): Result<Handle, 'invalid' | 'reserved'>` (noms réservés : `admin`, `api`, `d`, `decks`, `compte`, `fr`, `en`) ;
  - `newPublishToken(random: (n: number) => Uint8Array): { token: string; hash: string }` ;
  - `hashToken(token: string): string` ;
  - `canTransition(from: DeckStatus, to: DeckStatus): boolean`.
- Collections :
  - `authors` : `customer` (relation `customers`, unique), `handle` (unique) ;
  - `decks` : `author`, `deckId` (unique par auteur), `status`, `approvedAt`, `hiddenReason`, `tokenHash`, `tokenLastUsedAt` ;
  - `editions` : `deck`, `code`, `latestVersion` ;
  - `versions` : `edition`, `version`, `receivedAt`, `summary` (json), `files` (json : nom → `{ sha256, size }`), `deckJsonSha256`.
- Accès :
  - un visiteur ne lit que ses propres `authors` et `decks`, et ne voit jamais `tokenHash` ;
  - écriture uniquement par les cas d'usage ;
  - statut modifiable seulement par un admin vérifié (`isVerifiedAdmin`) ;
  - `versions` est en écriture seule pour le système, sans mise à jour ni suppression par l'API.
- Cas d'usage :
  - `chooseHandle(customerId, handle)` ;
  - `createDeck(customerId, deckId) -> { deck, token }` ;
  - `regenerateToken(customerId, deckId) -> token` ;
  - `revokeToken(customerId, deckId)` ;
  - `deckForToken(token) -> Deck | null`, qui met à jour `tokenLastUsedAt`.

- [ ] **Étape 1 : tests qui échouent :**
  - domaine : pseudos valides et invalides, noms réservés, transitions de statut ;
  - jeton : préfixe `ddk_`, 47 caractères au moins, et le hash ne contient pas le jeton ;
  - intégration :
    - deux auteurs ne peuvent pas avoir le même pseudo ;
    - un même auteur ne peut pas avoir deux fois le même `deckId`, alors que deux auteurs le peuvent ;
    - `regenerateToken` invalide l'ancien jeton ;
    - un visiteur ne lit ni le deck d'un autre, ni `tokenHash` ;
    - une `versions` n'est pas modifiable par l'API.
- [ ] **Étape 2 :** lancer les tests → ÉCHEC.
- [ ] **Étape 3 : implémenter.** Ajouter le module à `src/modules/index.ts` et à `starter.json` (brique locale du site).
- [ ] **Étape 4 :** `pnpm test:unit` et `pnpm test --group=database`. Tout passe.
- [ ] **Étape 5 : commit**, avec accord : `feat(decks): authors, decks, editions, versions and publish tokens`.

### Task 5 : stockage par empreinte et décompression sûre

**Fichiers :** `src/modules/decks/adapters/files/blob-store.ts`, `src/modules/decks/adapters/files/extract.ts`. Tests : `tests/decks.files.test.ts`.

**Interfaces :**
- `putBlob(dataDir: string, source: string): Promise<{ sha256: string; size: number }>` : écriture atomique dans `blobs/<sha256[:2]>/<sha256>`, et rien n'est réécrit si le fichier existe déjà.
- `blobPath(dataDir, sha256): string`.
- `extractEdition(archive: Readable, dir: string, limits: { maxBytes: number; maxFiles: number }): Promise<void>` : n'accepte que des fichiers ordinaires et des dossiers, sous `dir`. La lecture est en flux, et le dépassement d'une limite arrête tout.

- [ ] **Étape 1 : tests qui échouent** (archives construites dans le test) :
  - `rejects parent traversal` ;
  - `rejects absolute paths` ;
  - `rejects symlinks and hardlinks` ;
  - `rejects too many files` ;
  - `rejects a decompression bomb before writing it all` ;
  - `extracts a valid edition` ;
  - `putBlob is idempotent and content-addressed`.
- [ ] **Étape 2 :** ÉCHEC.
- [ ] **Étape 3 : implémenter.** Utiliser un lecteur tar en flux (paquet `tar-stream`, version exacte épinglée), ou un lecteur minimal maison si l'ajout d'un paquet est refusé. Pas de commande `tar` du système.
- [ ] **Étape 4 :** `pnpm test:unit`. Tout passe.
- [ ] **Étape 5 : commit**, avec accord : `feat(decks): content-addressed storage and safe archive extraction`.

### Task 6 : API de publication

**Fichiers :**
- `src/modules/decks/application/publish.ts`
- `src/modules/decks/adapters/http/publish-route.ts`
- `src/app/(frontend)/api/publish/[edition]/route.ts` (réexport)
- `src/modules/decks/adapters/python/checker.ts` (appel de `python3 -m deckdock`)
- Tests : `tests/decks.http.ts` (stage HTTP du build de production)

**Interfaces :**
- `publishEdition({ token, edition, archive }): Promise<PublishResult>`. Ordre des contrôles :
  1. jeton (401) ;
  2. deck masqué (410) ;
  3. taille (413) ;
  4. décompression sûre (422) ;
  5. `check --non-strict --json` (422, erreurs détaillées) ;
  6. `deck.id` et `deck.edition` égaux au deck du jeton et à l'URL (409) ;
  7. `deck.version` différente de `"dev"` (422) ;
  8. version existante : même empreinte de `deck.json` et des médias → 200 `already_published`, sinon 409 ;
  9. `compat` contre la dernière version de l'édition : un `breaking` donne 409 ; un `appended_fields` donne un avertissement ;
  10. fichiers dans le stockage, puis `versions`, `editions` et `latestVersion` dans une seule transaction.
- Réponse : le contrat JSON de la Task 2, avec le statut `pending_review` si le deck est `pending`.
- Le dossier temporaire est sous `HUB_DATA_DIR/tmp` et toujours supprimé, même en cas d'erreur.
- Limite de débit par jeton (application). Le chemin `/api/publish/*` est ajouté au routeur `-auth` de Traefik (`docker-compose.prod.yml`).

- [ ] **Étape 1 : tests qui échouent** (HTTP, build de production, jetons et archives créés par le test) :
  - publication valide → 200 `pending_review`, puis `published` après validation par un admin ;
  - jeton faux → 401 ; jeton révoqué → 401 ;
  - archive piégée → 422 ;
  - `deck.json` invalide → 422, erreurs détaillées ;
  - autre `deck.id` → 409 (point de vigilance 3) ;
  - `"dev"` → 422 ;
  - même version et même contenu → 200 `already_published` (point 2) ; même version avec un autre contenu → 409 ;
  - champ supprimé dans un type de carte → 409 (point 5) ; champ ajouté à la fin → 200 avec avertissement ;
  - deck masqué → 410 ;
  - corps de plus de `HUB_MAX_UPLOAD_BYTES` → 413.
- [ ] **Étape 2 :** ÉCHEC.
- [ ] **Étape 3 : implémenter.**
- [ ] **Étape 4 :** `pnpm test --group=web`. Tout passe.
- [ ] **Étape 5 : commit**, avec accord : `feat(decks): publish API`.

### Task 7 : service au plugin

**Fichiers :** `src/modules/decks/adapters/http/serve-route.ts`, `src/app/(frontend)/d/[handle]/[deck]/[...path]/route.ts`. Tests : `tests/decks.http.ts`, `tests/decks.addon.test.py` (ou un stage qui lance pytest).

**Interfaces :**
- `GET /d/<pseudo>/<deck-id>/index.json` : `deckdock-index/1` construit à partir des `latestVersion` des éditions, trié par édition.
- `GET /d/<pseudo>/<deck-id>/<édition>/deck.json` et `GET /d/<pseudo>/<deck-id>/<édition>/media/<fichier>` (fichier en encodage pourcentage).
- `ETag: "<sha256>"`, réponse 304 si `If-None-Match` correspond.
- `Cache-Control: public, max-age=300` pour `index.json` et `deck.json`, `public, max-age=31536000, immutable` pour les médias.
- Un deck `pending` est servi, avec `X-Robots-Tag: noindex`. Un deck `hidden` répond 410. Un deck ou un fichier inconnu répond 404.
- Sur les médias, la CSP est `default-src 'none'; sandbox`, avec `X-Content-Type-Options: nosniff` et `Content-Disposition: inline; filename*=UTF-8''…`, et le type MIME déduit de l'extension, sans jamais de `text/html` pour un fichier non listé.

- [ ] **Étape 1 : tests qui échouent :**
  - index, deck et média servis à l'identique, octet pour octet, de ce qui a été publié ;
  - ETag et 304 ;
  - `pending` → `noindex` ; `hidden` → 410 ;
  - un média `.svg` est servi avec la CSP `sandbox` (point de vigilance 4) ;
  - **test réel du plugin** : le code de `deckdock/addon/src/deckdock_addon/sources.py` (`parse_source`, `fetch_deck`, `fetch_media`), lancé par Python contre le serveur de test avec l'adresse `<base>/<édition>/`, récupère et valide le deck. Le test réutilise la copie embarquée de la bibliothèque, sans installer le plugin.
- [ ] **Étape 2 :** ÉCHEC.
- [ ] **Étape 3 : implémenter.**
- [ ] **Étape 4 :** `pnpm test --group=web`. Tout passe.
- [ ] **Étape 5 : commit**, avec accord : `feat(decks): serve published decks in the publishing layout`.

### Task 8 : espace auteur et admin

**Fichiers :** `src/modules/decks/ui/` (pages de l'espace auteur), `src/app/(frontend)/[locale]/compte/decks/...` (réexports), les composants admin et les champs `status` et `hiddenReason` de la collection `decks`. Tests : `tests/decks.ui.test.tsx`, `tests/e2e/decks-author.spec.ts`.

**Interfaces :**
- `/{locale}/compte/decks` (connexion obligatoire, sinon redirection vers la connexion du module `accounts`) :
  - choisir son pseudo s'il n'existe pas encore ;
  - liste de ses decks avec leur statut ;
  - « Nouveau deck » (`deck.id`).
- `/{locale}/compte/decks/<deck-id>` :
  - statut, éditions, versions reçues (date, version, nombre de notes) ;
  - jeton : « Régénérer » (affiche le nouveau jeton une seule fois, avec un bouton « Copier ») et « Révoquer » ;
  - la marche à suivre pour la CI (secret `DECKDOCK_TOKEN`, variable `DECKDOCK_HUB_URL` = l'origine du hub) ;
  - l'adresse de test `<base>/<édition>/`.
- Admin Payload :
  - vue des decks `pending` ;
  - actions « Valider » (vers `approved`) et « Masquer » (vers `hidden`, raison obligatoire), réservées aux admins vérifiés.
- **Suppression du compte** (crochet sur la suppression d'un `customer`) : ses decks passent à `hidden` avec la raison « compte supprimé », leurs jetons sont révoqués, et l'entrée `authors` reste, pour réserver le pseudo.

- [ ] **Étape 1 : tests qui échouent :**
  - en React Testing Library : formulaire du pseudo (erreurs invalide ou pris) ; jeton affiché une seule fois puis masqué ;
  - en Playwright :
    - connexion par lien magique avec la boîte aux lettres de test ;
    - choix du pseudo, création d'un deck, copie du jeton, publication par l'API ;
    - le deck apparaît en attente ;
    - validation dans l'admin ;
    - le statut passe à publié ;
    - axe sur les pages ;
  - en intégration : la suppression d'un compte masque ses decks et révoque ses jetons.
- [ ] **Étape 2 :** ÉCHEC.
- [ ] **Étape 3 : implémenter.**
- [ ] **Étape 4 :** les groupes `static`, `database`, `web` et `browser`. Tout passe.
- [ ] **Étape 5 : commit**, avec accord : `feat(decks): author space and admin review`.

### Task 9 : catalogue, page de deck et aperçu isolé

**Fichiers :**
- `src/modules/decks/ui/catalogue/`, `src/modules/decks/ui/deck-page/`
- `src/modules/decks/application/preview.ts` (rendu des templates)
- `src/app/(frontend)/[locale]/decks/page.tsx`, `src/app/(frontend)/[locale]/d/[handle]/[deck]/page.tsx`
- la route `src/app/(frontend)/preview/[handle]/[deck]/[edition]/[note]/[side]/route.ts`

Tests : `tests/decks.preview.test.ts`, `tests/e2e/decks-catalogue.spec.ts`.

**Interfaces :**
- **Catalogue** `/{locale}/decks?q=&lang=&page=` :
  - decks `approved` seulement, 20 par page ;
  - recherche insensible à la casse et aux accents sur le nom et la description ;
  - filtre de langue sur `language` des éditions.
- **Page de deck** `/{locale}/d/<pseudo>/<deck-id>?edition=` :
  - édition par défaut : celle qui correspond à la langue du visiteur, sinon la première par ordre alphabétique ;
  - affiche pseudo, licence, page d'accueil, éditions, nombre de notes, date de dernière version, description Markdown assainie, historique des versions, et l'adresse `<base>/<édition>/` avec un bouton « Copier » ;
  - `pending` → 404 pour les autres que l'auteur ; `hidden` → 410.
- **Aperçu.**
  - `renderCard(notetype: Notetype, note: Note, templateIndex: number, side: 'front' | 'back', media: (name: string) => string): string`. Il gère `{{Champ}}`, `{{cloze:Champ}}` (suppression `c1` masquée au recto, révélée au verso), `{{FrontSide}}`, `{{#Champ}}…{{/Champ}}` et `{{^Champ}}…{{/Champ}}`, et retire les autres filtres sans erreur.
  - Les références de médias sont réécrites vers les URL de service.
  - Notes montrées : 5 au plus, une par type de carte d'abord, puis dans l'ordre du fichier.
  - Le document de la route de prévisualisation contient le CSS du type de carte et le HTML rendu. Il est servi avec la CSP `default-src 'none'; img-src <origine du hub>; media-src <origine du hub>; style-src 'unsafe-inline'; sandbox allow-scripts`, sans `allow-same-origin`.
  - La page de deck l'affiche dans `<iframe sandbox="allow-scripts">`.

- [ ] **Étape 1 : tests qui échouent :**
  - rendu : champ simple ; cloze recto et verso ; `FrontSide` ; sections conditionnelles vide et pleine ; filtre inconnu ignoré ; média réécrit ;
  - HTTP : la route de prévisualisation porte la CSP `sandbox` sans `allow-same-origin` (point de vigilance 4) ;
  - Playwright :
    - recherche et filtre de langue ;
    - page de deck en français et en anglais ;
    - un deck en attente est absent du catalogue ;
    - un `<script>` de template ne peut lire ni `document.cookie` ni `parent.document` du site ;
    - axe, et aucun débordement à 390 px.
- [ ] **Étape 2 :** ÉCHEC.
- [ ] **Étape 3 : implémenter.**
- [ ] **Étape 4 :** les groupes `static`, `web` et `browser`, puis la suite complète `pnpm test` (dernière tâche de code). Tout passe.
- [ ] **Étape 5 : commit**, avec accord : `feat(decks): catalogue, deck page and isolated card preview`.

### Task 10 : documentation et préparation du déploiement

**Fichiers :**
- `README.md` et `deploy/OPERATIONS.md` du hub : modération, masquage, volume `hub-files`, limites, écarts avec le starter
- `docs/` du monorepo `deckdock` : guide auteur « Publier sur le hub »

Hors de ce plan, sans l'accord du propriétaire : l'entrée de `infra-traefik/sites.json` (avec le volume `hub-files` déclaré pour la sauvegarde), le DNS, les secrets et le premier déploiement. La procédure « Ajouter un site » les décrit.

- [ ] **Étape 1 :** écrire la documentation et vérifier que chaque commande citée existe.
- [ ] **Étape 2 :** `pnpm test --group=static` dans le hub. Tout passe.
- [ ] **Étape 3 : commits**, avec accord : `docs: operating the DeckDock hub` (hub) et `docs: publish to the DeckDock hub` (`deckdock`).
- [ ] **Étape 4 : point d'arrêt.** Présenter au propriétaire ce qui reste de son côté : création du dépôt si ce n'est pas fait, domaine et DNS, secrets avec `scripts/github-secrets.sh`, entrée dans le registre d'`infra-traefik`, facturation GitHub Actions, premier déploiement.
