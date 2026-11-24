# Plugin Anki DeckDock (MVP) : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** une extension Anki Desktop « DeckDock » qui s'abonne à une édition d'un deck publié (URL de base contenant `deck.json` et `media/`), l'installe et applique ses mises à jour note par note. Elle garde les révisions, ne supprime jamais rien, et n'écrase jamais une modification locale.

**Architecture :**
- Le code vit dans `deckdock/addon/` (monorepo).
- **Moteur pur** (`engine.py`, sans import d'Anki) : il reçoit le deck, l'état local et les empreintes reçues, et produit un plan d'actions et un résumé.
- **Adaptateur** (`adapter.py`) : il lit l'état d'une `Collection` et exécute un plan en une seule entrée d'annulation.
- `sources.py` (HTTP), `store.py` (persistance), `ui.py` (Qt).
- La bibliothèque `deckdock` (stdlib) est **copiée** dans `src/deckdock_addon/vendor/deckdock`, puis rendue importable en ajoutant `vendor/` au `sys.path` au chargement.

**Tech Stack :** Python ≥ 3.13, uv, pytest, ruff, basedpyright ; en développement, `anki==26.9.4` (PyPI, pour les tests d'intégration sur une vraie `Collection`) ; Qt via `aqt.qt` à l'exécution uniquement.

**Spec :** `docs/superpowers/specs/2026-11-24-deckdock-anki-addon-design.md` (à lire en entier, en particulier les §5.4 à 5.6 et les notes d'API) et `spec/deckdock-1.md`.

## Global Constraints

- **Version minimale :** Anki ≥ 26.09, `manifest.json` → `"min_point_version": 260900`. Nom affiché `DeckDock`, paquet `deckdock_addon`. Licence AGPL-3.0-or-later (`addon/LICENSE`).
- **Pas d'Anki dans le moteur :** `engine.py`, `store.py` (sauf les deux fonctions de lecture et d'écriture de la config) et `sources.py` n'importent **ni `anki` ni `aqt`**. Un test AST le vérifie, sur le modèle du garde-fou stdlib de `cli/`.
- **Validation :** chaque `deck.json` est validé avec `check_deck(data, strict=False)` avant toute action. Une issue bloque l'abonnement entier.
- **Ce qu'on ne fait jamais :** supprimer une note, une carte ou un média ; recréer une note supprimée par l'utilisateur ; écraser une note dont l'empreinte locale diffère de l'empreinte reçue.
- **Tag de retrait :** `DeckDock::Deleted`. Les tags commençant par `DeckDock::` sont gérés par le plugin.
- **Config de collection :** clé `deckdock`, `{"version": 1, "subscriptions": [...]}` (§5.6). Versions complètes locales : `<profil>/deckdock/<subscription_id>.json`.
- **Empreinte :** `fingerprint(fields: dict[str, str]) -> str` = les 16 premiers caractères hexadécimaux du sha256 de `json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":"))`. Les champs sont pris avec les **noms de médias d'origine**.
- **Nom Anki d'un notetype :** `f"{deck['name']} ({deck['edition']}) · {notetype['name']}"`. On le retrouve ensuite toujours par l'id mémorisé.
- **Plafonds :**
  - `deck.json` ≤ 67 108 864 octets, `index.json` ≤ 1 048 576 ;
  - médias : `MAX_MEDIA_BYTES` et `MAX_TOTAL_MEDIA_BYTES` de `deckdock.format` ;
  - HTTPS uniquement, redirections incluses ;
  - 5 redirections au plus.
- **Vérification automatique :** au plus une fois toutes les 24 h par abonnement (`check_interval_hours` dans `config.json`, défaut 24).
- **Interface :** FR si la langue d'Anki commence par `fr`, EN sinon (même règle que `anki-deckdock/src/strings.py`). L'entrée d'annulation s'appelle `DeckDock: update {name}` / `DeckDock : mise à jour de {name}`.
- **Commandes,** depuis `addon/` : `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .`, `uv run basedpyright` (0/0). Le message de commit se termine par la ligne `Co-Authored-By` du projet.
- **Rien n'est poussé ni publié** sans l'accord explicite de Nayan (Task 8).

## Review Focus

1. **Coupure réseau au milieu des médias :** rien n'est appliqué à la collection, l'erreur est affichée et un nouvel essai fonctionne. Testé dans la Task 5.
2. **Racine du deck renommée ou supprimée par l'utilisateur :** si elle est renommée, on la suit par son id. Si elle est supprimée, on recrée `deck.name` et on mémorise le nouvel id, sans planter. Testé dans la Task 5.
3. **Gros deck (5 000 notes) :** la lecture de l'état local et l'application se font en lot (une requête SQL pour lire, pas une recherche par note). Le test d'intégration à 5 000 notes doit passer en moins de 30 s. Testé dans la Task 5.
4. **Profil fermé pendant une vérification en arrière-plan :** pas d'exception ni d'écriture dans la mauvaise collection. On utilise un compteur d'époque, comme `anki-deckdock/src/ui.py`. Vérifié dans la Task 6.
5. **`deck.json` modifié côté serveur pendant l'application** (une nouvelle version arrive entre la vérification et l'application) : l'application relit `deck.json` et recalcule le plan avant d'agir. Testé dans la Task 5.

---

## File Structure

```
addon/
  pyproject.toml            # projet uv « deckdock-addon » ; dev : pytest, ruff, basedpyright, anki==26.9.4, deckdock (path ../cli)
  uv.lock
  LICENSE                   # AGPL-3.0-or-later
  scripts/vendor.py         # copie cli/src/deckdock → src/deckdock_addon/vendor/deckdock
  scripts/package.py        # construit dist/deckdock-<version>.ankiaddon
  src/deckdock_addon/
    __init__.py             # ajoute vendor/ au sys.path ; si aqt est importable : ui.register()
    manifest.json, config.json
    vendor/deckdock/…       # copie commitée (test d'égalité)
    sources.py              # URLs, HTTP (ETag), index.json, deck.json, médias
    store.py                # Subscription, Catalog, (dé)sérialisation, empreinte, versions complètes
    engine.py               # moteur pur : plan + résumé
    adapter.py              # lecture de l'état local + exécution du plan sur une Collection
    strings.py              # textes FR/EN
    ui.py                   # fenêtre, dialogues, démarrage
  tests/
    conftest.py             # fixtures : decks deckdock/1 d'exemple, Collection temporaire
    test_vendor.py, test_sources.py, test_store.py, test_engine.py, test_adapter.py, test_strings.py, test_package.py
.github/workflows/addon.yml # tests + package (artefact .ankiaddon)
```

---

### Task 1 : squelette de l'extension et bibliothèque embarquée

**Files :** Create `addon/pyproject.toml`, `addon/LICENSE`, `addon/scripts/vendor.py`, `addon/src/deckdock_addon/{__init__.py,manifest.json,config.json}`, `addon/src/deckdock_addon/vendor/deckdock/**`, `addon/tests/test_vendor.py`, `.github/workflows/addon.yml`. Modify : `README.md` (racine, une ligne sur `addon/`).

**Interfaces :**
- Produces :
  - `deckdock_addon.VENDOR_DIR: Path`.
  - Après `import deckdock_addon`, `import deckdock` charge **la copie embarquée** quand le paquet `deckdock` du monorepo n'est pas installé. En développement, le paquet installé et la copie sont identiques (test).
  - `scripts/vendor.py` : `vendor(src: Path, dest: Path) -> None` remplace intégralement `dest` par les fichiers `.py` et `py.typed` de `src`, sans `__pycache__`.
- `manifest.json` : `{"package": "deckdock_addon", "name": "DeckDock", "min_point_version": 260900}`.
- `config.json` : `{"check_interval_hours": 24}`.

- [ ] **Step 1 : écrire les tests qui échouent** (`tests/test_vendor.py`)
  - `test_vendored_copy_matches_library` : tous les fichiers de `../cli/src/deckdock` (`.py`, `py.typed`) existent sous `src/deckdock_addon/vendor/deckdock`, avec le même contenu octet par octet, et il n'y a pas de fichier en trop.
  - `test_import_does_not_require_aqt` : `import deckdock_addon` réussit dans un environnement sans `aqt` (Anki absent du `sys.modules`) et n'appelle pas `ui.register`.
  - `test_engine_modules_do_not_import_anki` : l'AST de `engine.py` et de `sources.py` n'importe ni `anki` ni `aqt`. Ignoré tant que les fichiers n'existent pas ; ce garde-fou servira aux Tasks 2 à 4.
- [ ] **Step 2 : lancer.** `cd addon && uv run pytest -q` : FAIL.
- [ ] **Step 3 : implémenter.** `pyproject.toml` (sans dépendances d'exécution ; build hatchling, `packages = ["src/deckdock_addon"]` ; `[tool.uv.sources] deckdock = { path = "../cli", editable = true }` pour le dev), `vendor.py`, lancer `uv run python scripts/vendor.py`, `__init__.py`, `manifest.json`, `config.json`, et `LICENSE` (texte AGPL-3.0 officiel).
- [ ] **Step 4 : CI** `.github/workflows/addon.yml`.
  - Déclenchement : `paths: [addon/**, cli/src/**, .github/workflows/addon.yml]`.
  - `working-directory: addon` ; `setup-uv@v5` ; `uv sync --locked` ; `ruff check` ; `ruff format --check` ; `basedpyright` ; `pytest -q`.
  - Le test d'égalité attrape tout oubli de `vendor.py` après une modification de `cli/`.
- [ ] **Step 5 : vérifier** (les quatre commandes vertes) **et commiter.**

---

### Task 2 : sources : URLs, HTTP, index, deck, médias

**Files :** Create `addon/src/deckdock_addon/sources.py`, `addon/tests/test_sources.py`.

**Interfaces :**
- Produces :
  - `class SourceError(Exception)` avec `.code: str`, l'un de `"https_required"`, `"not_found"`, `"http_error"`, `"too_large"`, `"invalid_json"`, `"invalid_deck"`, `"sha_mismatch"`, `"redirect_rejected"`, `"cancelled"`, `"invalid_url"`.
  - `@dataclass(frozen=True) class Response(status: int, headers: dict[str, str], body: bytes)` ; `Transport = Callable[[str, dict[str, str], int], Response]` (url, en-têtes, nombre maximal d'octets). `urllib_transport` en est l'implémentation par défaut : HTTPS seulement, au plus 5 redirections, toutes en HTTPS, lecture plafonnée.
  - `parse_source(text: str) -> Source`, où `@dataclass(frozen=True) class Source(kind: Literal["github", "base"], url: str, index_url: str | None, owner: str | None, repo: str | None)`.
    - Une URL `https://github.com/<owner>/<repo>` (avec ou sans `/`, `.git` ou `www.`) donne `index_url = https://raw.githubusercontent.com/<owner>/<repo>/dist/index.json`.
    - Une URL HTTPS qui se termine par `/` donne `kind="base"`.
    - Sinon, `SourceError("invalid_url")`.
  - `edition_base_url(source: Source, edition: str) -> str`. Cas github : `https://raw.githubusercontent.com/<owner>/<repo>/dist/<edition>/`. Cas base : `source.url`.
  - `fetch_index(source, *, transport=urllib_transport) -> list[IndexEdition]`, avec `@dataclass(frozen=True) class IndexEdition(edition: str, name: str, language: list[str], version: str)`. Le format attendu est `"deckdock-index/1"`, sinon `invalid_json`.
  - `fetch_deck(base_url: str, *, etag: str | None, transport=...) -> FetchedDeck | None`, avec `@dataclass(frozen=True) class FetchedDeck(deck: CompiledDeck, etag: str | None)`. Une réponse 304 renvoie `None`. Une issue de `check_deck(strict=False)` lève `SourceError("invalid_deck")`, avec un message qui contient la première issue.
  - `fetch_media(base_url: str, entry: MediaEntry, *, transport=..., cancelled: Callable[[], bool] = lambda: False) -> bytes` lit `base_url + "media/" + quote(filename)`, puis vérifie la taille et le sha256 (sinon `sha_mismatch`).

- [ ] **Step 1 : écrire les tests qui échouent,** avec un transport factice défini dans le test :
  - `test_parse_github_repo_variants` (4 formes donnent la même `index_url`) ;
  - `test_parse_base_url_requires_trailing_slash_and_https` ;
  - `test_edition_base_url` ;
  - `test_fetch_index_parses_editions` et `test_fetch_index_rejects_unknown_format` ;
  - `test_fetch_deck_sends_if_none_match_and_handles_304` ;
  - `test_fetch_deck_rejects_invalid_deck` (un deck sans `notes`) ;
  - `test_fetch_deck_accepts_unknown_keys` (une clé `future` à la racine passe, car le mode est non strict) ;
  - `test_fetch_deck_too_large` (le transport reçoit le plafond 67 108 864 et lève `too_large`) ;
  - `test_fetch_media_checks_sha_and_size` et `test_fetch_media_quotes_name` (`"a b.png"` → `media/a%20b.png`) ;
  - `test_404_maps_to_not_found` ;
  - `test_redirect_to_http_rejected` (via `urllib_transport`, avec un opener simulé, sur le modèle de `anki-deckdock/src/download.py`).
- [ ] **Step 2 : lancer.** FAIL.
- [ ] **Step 3 : implémenter `sources.py`,** en reprenant les techniques de `anki-deckdock/src/download.py` et `github.py` (gestionnaire de redirection, lecture par blocs plafonnée), sans liste d'hôtes autorisés, mais en HTTPS strict.
- [ ] **Step 4 : vérifier et commiter.**

---

### Task 3 : store : abonnements, empreintes, versions complètes

**Files :** Create `addon/src/deckdock_addon/store.py`, `addon/tests/test_store.py`.

**Interfaces :**
- Produces :
  - `@dataclass(frozen=True) class MediaRecord(sha256: str, local_name: str)`.
  - `@dataclass(frozen=True) class Received(fingerprint: str, tags: tuple[str, ...])`.
  - `@dataclass(frozen=True) class Subscription` avec :
    - identité : `id: str`, `source_url: str`, `base_url: str`, `deck_id: str`, `edition: str`, `name: str` ;
    - suivi : `installed_version: str | None = None`, `etag: str | None = None`, `last_checked_at: str | None = None`, `last_error: str | None = None` ;
    - mise à jour en attente : `available_version: str | None = None` ;
    - correspondances : `root_deck_anki_id: int | None = None`, `notetype_ids: dict[str, int]` (vide par défaut), `media: dict[str, MediaRecord]` (vide par défaut), `received: dict[str, Received]` (vide par défaut).
  - `@dataclass(frozen=True) class Catalog(subscriptions: tuple[Subscription, ...] = ())`.
  - `CONFIG_KEY = "deckdock"`, `SCHEMA_VERSION = 1`.
  - `dump_catalog(c) -> dict[str, object]` et `load_catalog(payload: object) -> Catalog`. `None` donne un catalogue vide. Une version inconnue, une forme invalide ou une clé inconnue dans un abonnement lèvent `ValueError`.
  - `add`, `replace` et `remove` (`Catalog`, `Subscription` ou id → `Catalog`). `add` refuse avec `DuplicateSubscription(ValueError)` le même `(deck_id, edition)`, et avec `ConflictingEdition(ValueError)` le même `deck_id` sous une autre édition (§5.2).
  - `fingerprint(fields: dict[str, str]) -> str`, selon la définition des Global Constraints.
  - `full_versions_path(profile_dir: Path, subscription_id: str) -> Path` ; `write_full_versions(path, versions: dict[str, dict[str, str]]) -> None` (écriture atomique : fichier temporaire puis `replace`) ; `read_full_versions(path) -> dict[str, dict[str, str]]` (fichier absent ou corrompu → `{}`).
  - `read_catalog(col) -> Catalog` et `write_catalog(col, c) -> None` : les **deux seules** fonctions qui touchent Anki, via `col.get_config(CONFIG_KEY, None)` et `col.set_config`.
  - `check_is_due(last_checked_at: str | None, now: datetime, interval_hours: int) -> bool` (repris du Deck Manager).

- [ ] **Step 1 : écrire les tests qui échouent :**
  - `test_round_trip_with_media_and_received` ;
  - `test_load_none_is_empty` ;
  - `test_load_rejects_unknown_version_and_keys` ;
  - `test_add_rejects_duplicate_and_other_edition_of_same_deck` ;
  - `test_fingerprint_is_order_independent_and_pinned`, avec la valeur fixée `fingerprint({"Front": "a", "Back": "b"}) == "<calculée>"`. La valeur est calculée une fois à l'implémentation selon la définition, puis figée dans le test ;
  - `test_full_versions_atomic_and_tolerant` ;
  - `test_check_is_due`.
- [ ] **Step 2 : lancer.** FAIL.
- [ ] **Step 3 : implémenter.**
- [ ] **Step 4 : vérifier et commiter.**

---

### Task 4 : moteur pur : plan et résumé

**Files :** Create `addon/src/deckdock_addon/engine.py`, `addon/tests/test_engine.py`.

**Interfaces :**
- Consumes : `Subscription`, `Received`, `MediaRecord`, `fingerprint` (Task 3) ; `CompiledDeck` et les TypedDicts de `deckdock.format`.
- Produces :
  - **Entrées.**
    - `@dataclass(frozen=True) class LocalNote(note_id: int, guid: str, notetype_anki_id: int, fields: dict[str, str], tags: tuple[str, ...])`, avec les noms de médias **locaux**.
    - `@dataclass(frozen=True) class LocalNotetype(anki_id: int, field_names: tuple[str, ...], template_count: int, is_cloze: bool)`.
    - `@dataclass(frozen=True) class LocalState(notes_by_guid: dict[str, LocalNote], notetypes: dict[int, LocalNotetype], root_deck_exists: bool)`.
  - **Actions et plan.**
    - `NotetypeChange = Literal["create", "update", "append_fields", "unchanged"]`.
    - `@dataclass(frozen=True) class NotetypeAction(slug: str, change: NotetypeChange, anki_id: int | None, appended_fields: tuple[str, ...])`.
    - `@dataclass(frozen=True) class NoteAction(kind: Literal["create", "update", "retire", "record"], guid: str, note_id: int | None, fields: dict[str, str] | None, tags: tuple[str, ...] | None, deck_path: str | None, notetype_slug: str | None)`. Les champs sont avec les noms **d'origine**, et l'adaptateur les réécrit en noms locaux. `record` signifie « identique : enregistrer seulement l'empreinte ».
    - `@dataclass(frozen=True) class Skipped(guid: str, reason: Literal["modified_locally", "deleted_locally", "foreign_note", "no_base_conflict"], preview: str)`. `preview` contient les 60 premiers caractères du premier champ local, sans HTML (ou du premier champ reçu si la note est absente).
    - `@dataclass(frozen=True) class Plan` avec :
      - `blocked: str | None` (message s'il y a un changement de structure non pris en charge ; dans ce cas, aucune action) ;
      - `needs_full_sync_confirmation: bool` (vrai si au moins un `append_fields`) ;
      - les listes `notetype_actions`, `note_actions`, `skipped` ;
      - `media_to_download: tuple[MediaEntry, ...]` ;
      - `new_received: dict[str, Received]` (l'état `received` complet après application, conflits gardés à leur ancienne valeur) ;
      - `counts: Counts`.
    - `@dataclass(frozen=True) class Counts(created: int, updated: int, retired: int, skipped: int, notetypes_updated: int)`.
  - **Fonctions.**
    - `make_plan(deck: CompiledDeck, sub: Subscription, local: LocalState) -> Plan` applique **exactement** les tableaux du design §5.4 : la règle des notes, les tags (on remplace les tags reçus précédents, on garde ceux de l'utilisateur, on ignore les tags `DeckDock::*` dans la comparaison) et la règle des notetypes (association par position ; ajout en fin → `append_fields` ; tout autre changement → `blocked`).
    - Média à télécharger : absent de `sub.media`, ou sha256 reçu différent.
    - `to_origin_names(text: str, media: dict[str, MediaRecord]) -> str` et `to_local_names(text: str, media: dict[str, MediaRecord]) -> str` réécrivent les références `src="…"`, `src='…'`, `[sound:…]` et `url(…)` (insensible à la casse pour `src` et `url`, mêmes motifs que `deckdock.format.check`). Les noms comparés sont décodés (HTML puis pourcentage).
    - L'empreinte locale vaut `fingerprint({k: to_origin_names(v, sub.media) for k, v in local.fields.items()})`.
    - `summary_lines(plan: Plan, name: str, edition: str, lang: str) -> list[str]` produit le texte du résumé (FR/EN), dont la phrase d'avertissement de synchro complète du design §5.4.

- [ ] **Step 1 : écrire les tests qui échouent.** Un test par ligne de chaque tableau du §5.4, en données pures :
  - notes : `test_create_unknown_guid`, `test_update_unmodified_note`, `test_skip_modified_locally`, `test_do_not_recreate_deleted_locally`, `test_retire_missing_from_deck_adds_tag`, `test_no_base_equal_records_fingerprint`, `test_no_base_different_is_conflict`, `test_foreign_note_other_notetype_is_conflict`, `test_unchanged_note_no_action` ;
  - tags : `test_tags_user_tags_kept_and_received_replaced`, `test_deckdock_tags_ignored_in_comparison` ;
  - notetypes : `test_notetype_create_and_update_by_position`, `test_append_fields_needs_confirmation`, `test_removed_renamed_reordered_field_blocks`, `test_template_count_change_blocks`, `test_kind_change_blocks`, `test_blocked_plan_has_no_actions` ;
  - médias : `test_media_to_download_new_or_changed_sha`, `test_local_media_names_do_not_look_modified` (le champ local contient `h-ad78.png` et la table associe `h.png` → `h-ad78.png` : pas de modif locale), `test_to_local_names_rewrites_src_sound_url` ;
  - résumé : `test_counts_and_summary_fr_en`.
- [ ] **Step 2 : lancer.** FAIL.
- [ ] **Step 3 : implémenter `engine.py`** (dataclasses et fonctions pures).
- [ ] **Step 4 : vérifier** (le garde-fou AST de la Task 1 couvre maintenant `engine.py`) **et commiter.**

---

### Task 5 : adaptateur Anki : lecture et application

**Files :** Create `addon/src/deckdock_addon/adapter.py`, `addon/tests/conftest.py`, `addon/tests/test_adapter.py`.

**Interfaces :**
- Consumes : Tasks 2 à 4.
- Produces :
  - `read_local_state(col, deck: CompiledDeck, sub: Subscription) -> LocalState` lit les notes en **une requête SQL** (`select id, guid, mid, flds, tags from notes where guid in (…)`, découpée par lots de 500), avec les champs nommés via le notetype.
  - `write_media(col, entries: list[tuple[MediaEntry, bytes]], media: dict[str, MediaRecord]) -> dict[str, MediaRecord]` passe par `col.media.write_data(filename, data)` et enregistre le nom renvoyé. Il ne touche **jamais** à un fichier existant.
  - `apply_plan(col, deck: CompiledDeck, sub: Subscription, plan: Plan, *, undo_label: str) -> Subscription` :
    - une seule entrée d'annulation (`col.add_custom_undo_entry(undo_label)`, puis `col.merge_undo_entries(pos)` après chaque étape) ;
    - **notetypes** : `create` construit le notetype avec le nom des Global Constraints, ses champs, ses templates, son CSS et `kind` (cloze : `type = 1`). Avec `anki_id` fourni et absent, on fixe `nt["id"]` puis `col.models.update(nt, preserve_usn=True)`. Sinon `col.models.add`. `update` met à jour `qfmt`, `afmt` et `name` des templates par position, ainsi que le CSS. `append_fields` ajoute les champs avec `col.models.add_field` puis met à jour comme `update` ;
    - **deck racine** : on cherche `sub.root_deck_anki_id`, puis `deck.anki_id`. S'il est absent, on le crée (`col.decks.id(deck["name"])`). Les sous-decks se nomment `"<nom actuel de la racine>::<deck_path>"` ;
    - **notes** : `create` fixe `note.guid`, remplit les champs (réécrits en noms locaux), les tags et le deck, puis vérifie que le GUID est libre (sinon on le passe en `Skipped` et on ne crée rien) ; `update` touche les champs et les tags seulement ; `retire` ajoute le tag `DeckDock::Deleted` ;
    - `record` et les actions mises à jour donnent `received` = `plan.new_received` ;
    - la fonction renvoie la `Subscription` mise à jour (`installed_version`, `available_version=None`, `notetype_ids`, `root_deck_anki_id`, `received`).
  - `update_subscription(col, sub: Subscription, *, transport, profile_dir: Path, confirmed_full_sync: bool, undo_label: str) -> tuple[Subscription, Plan]` est le **pipeline complet** pour un abonnement :
    1. relire `deck.json` sans ETag ;
    2. `read_local_state`, puis `make_plan` ;
    3. si `blocked`, ou si une confirmation est nécessaire alors que `confirmed_full_sync` vaut `False`, ne rien appliquer et renvoyer le plan ;
    4. télécharger tous les médias du plan (un échec lève `SourceError`, et la collection n'est pas touchée) ;
    5. `write_media` ;
    6. `apply_plan` ;
    7. écrire les versions complètes.

- [ ] **Step 1 : écrire les tests qui échouent,** sur une vraie collection temporaire.
  - Fixture `col` : `anki.collection.Collection(str(tmp_path / "c.anki2"))`, fermée en fin de test. Les decks d'exemple sont construits avec les notetypes du Hello World (copier `deckdock-template/dist/en/deck.json` dans `tests/data/` après un `uv run compile` du template, avec un PNG), et le transport factice sert ces fichiers.
  - `test_install_creates_notetypes_deck_notes_media` : 3 notes, des GUID identiques au deck, le nom du notetype selon les Global Constraints, et le média présent.
  - `test_update_keeps_review_history` : on révise une carte (`col.sched.answer_card`), on modifie son champ côté deck et on met à jour. Le champ change, et `revlog` ainsi que `card.ivl` restent intacts.
  - `test_locally_modified_note_untouched` et `test_user_deleted_note_not_recreated`.
  - `test_retired_note_tagged_not_deleted`.
  - `test_changed_image_gets_new_local_name_and_references` : `h.png` change de contenu, ce qui donne un nom `h-…png`. Les champs **et** les templates référencent le nouveau nom, et la note n'apparaît pas comme modifiée localement à la mise à jour suivante.
  - `test_append_field_requires_confirmation_then_applies`, avec vérification que `col.scm` change seulement après confirmation.
  - `test_blocked_structure_change_applies_nothing` : `col.mod`, le nombre de notes et `col.scm` sont inchangés.
  - `test_whole_update_is_one_undo_step` : après `col.undo()`, les notes ajoutées et les champs mis à jour ont disparu.
  - `test_existing_guid_from_other_source_is_conflict` : une note insérée à la main avec le même GUID et un autre notetype n'est pas touchée.
  - `test_network_failure_during_media_changes_nothing` (Review Focus 1).
  - `test_root_deck_renamed_is_followed_and_deleted_is_recreated` (Review Focus 2).
  - `test_5000_notes_install_and_update_under_30s` (Review Focus 3 ; deck généré dans le test).
  - `test_refetches_deck_before_apply` (Review Focus 5) : le transport sert la version A à la vérification et la version B à l'application, et c'est B qui est appliquée.
- [ ] **Step 2 : lancer.** FAIL.
- [ ] **Step 3 : implémenter `adapter.py`.**
- [ ] **Step 4 : vérifier et commiter.**

---

### Task 6 : interface : fenêtre, ajout, résumé, démarrage

**Files :** Create `addon/src/deckdock_addon/strings.py`, `addon/src/deckdock_addon/ui.py`, `addon/tests/test_strings.py`. Modify `__init__.py` (`register()`).

**Interfaces :**
- Consumes : Tasks 2 à 5.
- Produces :
  - `register() -> None` branche `gui_hooks.main_window_did_init` (menu **Outils → DeckDock**), `profile_did_open` (vérification au démarrage, différée de 1,5 s) et `profile_will_close` (on ferme les dialogues et on incrémente l'époque).
  - **Fenêtre** : un tableau Deck, Édition, Version, État, et les boutons **Ajouter**, **Vérifier**, **Appliquer**, **Ouvrir la source**, **Retirer** (§5.7). La suppression demande confirmation (« le deck reste dans Anki »).
  - **Ajouter** : un champ URL, puis `fetch_index` pour une source GitHub (liste des éditions) ou `fetch_deck` pour une base. On refuse un doublon ou une autre édition du même deck avec le message du §5.2, puis on enchaîne sur la vérification et le résumé.
  - **Vérifier** : en arrière-plan (`QueryOp` sans collection) avec `fetch_deck(etag)`. On met à jour `available_version` et l'état, sans rien appliquer.
  - **Résumé et application** : `make_plan` est calculé en arrière-plan avec lecture de la collection. Le dialogue montre `summary_lines`, la liste dépliable des notes ignorées et un bouton « Ouvrir dans le navigateur » (`guid:<guid>`). Les boutons sont **Appliquer** et **Plus tard**, ou **Confirmer et appliquer** si une synchro complète est nécessaire. L'application passe par `CollectionOp` et `update_subscription`. Un plan bloqué affiche son message et un seul bouton **OK**.
  - **Démarrage** : on vérifie les abonnements dus (24 h). S'il y a des mises à jour, un dialogue de résumé s'ouvre avec une section par abonnement.
  - Toutes les erreurs de `SourceError` s'affichent dans la colonne État via `strings.error_text(code)`.
- [ ] **Step 1 : écrire les tests qui échouent** (`test_strings.py`) :
  - chaque code de `SourceError` et chaque `Skipped.reason` a un texte FR et un texte EN non vides ;
  - le choix de la langue suit la langue d'Anki (`fr_FR` → FR, `de` → EN), comme `anki-deckdock/tests/test_strings.py`.
- [ ] **Step 2 : lancer.** FAIL.
- [ ] **Step 3 : implémenter `strings.py` et `ui.py`** en reprenant la structure de `anki-deckdock/src/ui.py` (époque, `_busy`, lecture et écriture du catalogue sur le thread principal, `QueryOp` / `CollectionOp`).
- [ ] **Step 4 : vérifier** les tests, ruff et basedpyright. Le comportement de l'interface se vérifie à la main à la Task 8.
- [ ] **Step 5 : commiter.**

---

### Task 7 : publication `dist` du template, index et spec

**Files :**
- Modify `deckdock-template/.github/workflows/deck.yml`, `deckdock-template/README.md`, `deckdock-template/AGENTS.md` (une phrase).
- Create `deckdock-template/scripts/make_index.py` et `deckdock-template/tests/test_make_index.py`.
- Modify `deckdock/spec/deckdock-1.md` (section « Publishing layout »).

**Interfaces :**
- Produces :
  - `make_index(dist: Path) -> dict[str, object]`, qui renvoie `{"format": "deckdock-index/1", "editions": [{edition, name, language, version}, …]}` trié par édition, à partir de `dist/*/deck.json`.
  - `uv run python scripts/make_index.py dist` écrit `dist/index.json`.
  - **Workflow :** après `deckdock check` et l'upload de l'artefact, un job ou une étape `publish-dist` ne s'exécute que si `github.event_name == 'push' && github.ref == 'refs/heads/main'`, avec `permissions: contents: write`. Il :
    1. génère `index.json` ;
    2. crée un dépôt temporaire dans `dist/` (`git init`, commit orphelin « Publish <DECKDOCK_VERSION> » au nom de `github-actions[bot]`) ;
    3. le pousse en force vers `refs/heads/dist` avec `${{ github.token }}`.
  - **Spec :** une section « Publishing layout (optional) » : `<base>/index.json` (format `deckdock-index/1`, ses champs), `<base>/<edition>/deck.json` et `<base>/<edition>/media/<filename>`. Les clients lisent les médias par nom de fichier encodé en pourcentage.
- [ ] **Step 1 : écrire le test qui échoue** `test_make_index_lists_editions_sorted` (dans le template), à partir du `dist/` produit par `compile` dans un dossier temporaire.
- [ ] **Step 2 : implémenter**, puis valider le workflow avec `uvx check-jsonschema --builtin-schema vendor.github-workflows .github/workflows/deck.yml`.
- [ ] **Step 3 : documenter.** README du template : « Après chaque push sur `main`, la branche `dist` contient le deck compilé : abonnez-vous dans DeckDock avec l'URL du dépôt. » Mettre aussi à jour la spec.
- [ ] **Step 4 : vérifier.** Template : pytest, ruff et basedpyright. Monorepo : pytest de `cli/`. Commiter dans les deux dépôts, sans rien pousser.

---

### Task 8 : paquet `.ankiaddon`, recette dans Anki et publication (point d'arrêt)

**Files :** Create `addon/scripts/package.py` et `addon/tests/test_package.py`. Modify `.github/workflows/addon.yml` (job `package` qui produit l'artefact `deckdock-addon`).

- [ ] **Step 1 : test qui échoue** `test_package_contains_addon_files_only`. Le zip produit contient `__init__.py`, `manifest.json`, `config.json`, tous les modules et `vendor/deckdock/**`, mais pas de `__pycache__`, de `tests/`, de `.venv`. Son nom est `deckdock-<version>.ankiaddon`, où la version vient de `pyproject.toml`.
- [ ] **Step 2 : implémenter `package.py`** et le job CI (artefact uniquement, pas de release).
- [ ] **Step 3 : point d'arrêt.** Demander à Nayan l'accord pour pousser `deckdock` (branche fusionnée dans `main`) et `deckdock-template` (avec la publication `dist`), puis vérifier que la CI est verte et que la branche `dist` du template contient `index.json`, `fr/deck.json`, `en/deck.json` et les médias.
- [ ] **Step 4 : recette manuelle par Nayan** dans Anki Desktop 26.09, selon le critère du design §6 :
  1. installer le `.ankiaddon` ;
  2. coller `https://github.com/NayanChauveau/deckdock-template`, choisir `fr` : 3 cartes ;
  3. réviser une carte, en modifier une autre dans Anki, puis pousser une modification des deux dans le template ;
  4. **Vérifier** puis **Appliquer** : la carte révisée est mise à jour et garde son historique, la carte modifiée localement est signalée et n'est pas touchée.

  Les retours de cette recette deviennent des correctifs.
