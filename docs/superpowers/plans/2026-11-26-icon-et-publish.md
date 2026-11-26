# Icône des decks, `deckdock publish` et `homepage` du template Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ajouter le champ facultatif `deck.icon` au format, une commande `deckdock publish` (publication sans CI GitHub) et un `homepage` rempli automatiquement par le template, puis recopier la bibliothèque dans le hub.

**Architecture:** La bibliothèque (`deckdock/cli`) gagne `icon` (spec, schéma, vérificateur) et un module `deckdock.publish` en bibliothèque standard seule, qui devient l'unique implémentation de la publication : la commande `deckdock publish` l'appelle, et `action/publish.py` n'est plus qu'un lanceur qui l'importe depuis le dépôt de l'Action (pas d'installation, comme aujourd'hui). Le template ajoute `icon` à `deckdock.yaml` et calcule `homepage` en CI. Le hub recopie la bibliothèque (`scripts/vendor-deckdock.mjs`).

**Tech Stack:** Python 3.13 (stdlib, pytest, ruff, basedpyright, uv), pydantic dans le template, Node pour le hub.

**Spec:** `docs/superpowers/specs/2026-11-26-deckdock-hub-refonte-ux-design.md` (sections « Icône des decks », « Lien Source », « Commande `deckdock publish` », « Décisions prises pendant la relecture »).

## Global Constraints

- `icon` est **facultatif** ; ajout rétrocompatible à `deckdock/1` (le numéro de format ne change pas). Le plugin (lecteur non strict) l'ignore déjà ; le vérificateur strict l'accepte.
- `icon` = **un seul emoji**, texte, au plus 64 octets UTF-8. Refusé dans les deux modes (strict et non strict) s'il est présent et invalide.
- Version de la bibliothèque : **0.3.0** (`cli/pyproject.toml`, `deckdock.__version__`).
- `deckdock publish` a le **même comportement** que l'étape `publish` de l'Action : https obligatoire sauf `localhost`/`127.0.0.1`/`::1` ; aucune redirection suivie ; messages du hub échappés ; limite d'archive (défaut 104857600 octets) ; délai 330 s ; arrêt à la première édition en échec ; jeton lu dans `DECKDOCK_TOKEN`, jamais affiché.
- `deckdock.publish` n'utilise que la bibliothèque standard (l'Action le lance sans installer la bibliothèque).
- `homepage` du template : la valeur de `deckdock.yaml` l'emporte ; sinon `${GITHUB_SERVER_URL}/${GITHUB_REPOSITORY}` si les deux variables existent ; sinon absent.
- Ordre de mise en circulation : bibliothèque poussée → tag `v2` de l'Action déplacé → seulement ensuite le template utilise `icon`. Chaque push et le déplacement du tag demandent un « oui » explicite du propriétaire.
- Branches : `feat/icon-publish` (deckdock), `feat/icon-homepage` (deckdock-template), `feat/vendor-0.3` (deckdock-hub), depuis `main` à jour. Commits locaux seulement après accord du propriétaire ; pas de push sans accord séparé.
- Les commits utilisent l'adresse noreply GitHub (déjà réglée dans les trois dépôts).

## Review Focus

1. Emoji composés : drapeau (🇫🇷), séquence ZWJ (👩‍💻, 👨‍👩‍👧‍👦), teinte de peau (👍🏽), touche (1️⃣), sélecteur de variante (❤️) — tous acceptés ; deux emoji côte à côte, un emoji suivi d'une espace, une lettre seule — refusés.
2. `deckdock publish` lancé hors CI sur un dossier sans édition, avec un jeton vide ou une URL `http://` distante : message clair, code de sortie non nul, rien n'est envoyé.
3. Sortie de `deckdock publish` dans un terminal : lisible, sans commandes de workflow `::error::` ; dans l'Action : les annotations GitHub restent identiques à aujourd'hui.
4. Template compilé hors CI (en local) : pas de `homepage` inventé ; en CI d'un dépôt créé depuis le template : l'URL de ce dépôt, pas celle du template.
5. Un `deck.json` avec `icon` passe le vérificateur du hub après re-vendoring ; un `icon` invalide y est refusé avec l'emplacement `deck.icon`.

---

### Task 1: Champ `icon` dans le format (deckdock)

**Files:**
- Modify: `spec/deckdock-1.md` (table `deck` : ligne `icon` après `description` ; règle « un seul emoji, au plus 64 octets UTF-8 »), `spec/deckdock-1.schema.json` (`"icon": { "type": "string", "minLength": 1 }`), un exemple de `spec/examples/` avec `icon`
- Modify: `cli/src/deckdock/format/types.py` (`icon: NotRequired[str]`), `cli/src/deckdock/format/check.py` (`_DECK_OPTIONAL` + validation)
- Create: `cli/src/deckdock/format/emoji.py`
- Modify: `cli/pyproject.toml` et `cli/src/deckdock/__init__.py` (0.3.0) ; la copie embarquée du plugin via `addon/scripts/vendor.py`
- Test: `cli/tests/test_emoji.py`, `cli/tests/test_format_check.py`

**Interfaces:**
- Produces: `def is_single_emoji(value: str) -> bool` dans `deckdock.format.emoji`. Une suite d'éléments séparés par U+200D (ZWJ), où un élément est : un code pictographique (plages ci-dessous) suivi au plus d'un U+FE0F et au plus d'une teinte U+1F3FB–1F3FF ; **ou** exactement deux indicateurs régionaux U+1F1E6–1F1FF (drapeau, seul, sans ZWJ) ; **ou** une touche `[0-9#*]` U+FE0F? U+20E3 (seule) ; **ou** U+1F3F4 suivi de caractères d'étiquette U+E0020–E007E puis U+E007F (drapeaux de régions, seul). Plages pictographiques : U+00A9, U+00AE, U+203C, U+2049, U+2122, U+2139, U+2194–21AA, U+231A–23FF, U+24C2, U+25AA–25FE, U+2600–27BF, U+2934–2935, U+2B05–2B55, U+3030, U+303D, U+3297, U+3299, U+1F000–1FAFF (hors indicateurs régionaux et teintes). Au plus 64 octets UTF-8.

- [ ] **Step 1: Write the failing tests**

```python
# cli/tests/test_emoji.py
import pytest
from deckdock.format.emoji import is_single_emoji

@pytest.mark.parametrize("value", ["📚", "🇫🇷", "👩‍💻", "👨‍👩‍👧‍👦", "👍🏽", "1️⃣", "❤️", "🏴󠁧󠁢󠁳󠁣󠁴󠁿", "🗺️"])
def test_single_emoji_accepted(value): assert is_single_emoji(value)

@pytest.mark.parametrize("value", ["", "a", "📚📚", "📚 ", " 📚", "🇫", "🇫🇷🇩🇪", "📚a", "‍📚", "📚‍", "🏽", "1", "️"])
def test_not_a_single_emoji_refused(value): assert not is_single_emoji(value)

def test_longer_than_64_bytes_refused(): assert not is_single_emoji("‍".join(["👩"] * 20))
```

```python
# cli/tests/test_format_check.py (ajouts) — avec la fabrique de deck valide déjà utilisée par ce fichier
def test_icon_is_optional_and_accepted_strict(): ...      # deck sans icon → aucune issue ; avec "📚" → aucune issue
def test_invalid_icon_refused_in_both_modes(): ...        # "📚📚" → une issue where == "deck.icon", strict=True et strict=False
def test_icon_must_be_a_string(): ...                     # 5 → issue deck.icon
```

- [ ] **Step 2: Run** `cd cli && uv run pytest -q tests/test_emoji.py tests/test_format_check.py` — Expected: FAIL (module absent, `icon` inconnu en strict).
- [ ] **Step 3: Implement** `emoji.py`, la clé `icon` dans `check.py` (chaîne puis `is_single_emoji`, message « must be a single emoji »), la spec, le schéma, un exemple, la version 0.3.0 ; relancer `addon/scripts/vendor.py`.
- [ ] **Step 4: Run** `cd cli && uv run ruff check . && uv run ruff format --check . && uv run basedpyright && uv run pytest -q` puis les tests du plugin (`cd addon && uv run pytest -q`) — Expected: PASS (dont `test_spec_examples.py` sur l'exemple modifié).
- [ ] **Step 5: Commit** (après accord) `feat(format): optional deck.icon, a single emoji`

### Task 2: `deckdock publish` (deckdock)

**Files:**
- Create: `cli/src/deckdock/publish.py` (logique déplacée depuis `action/publish.py`, typée pour basedpyright, bibliothèque standard seule)
- Modify: `cli/src/deckdock/cli.py` (sous-commande `publish`), `action/publish.py` (lanceur), `action/action.yml` si le chemin change, `docs/publish-to-the-hub.md` (section « Publier sans GitHub »)
- Test: `cli/tests/test_publish.py` (nouveau), `action/tests/test_publish.py` (inchangé, doit passer)

**Interfaces:**
- Consumes: rien des autres tâches.
- Produces:
  - `def publish_dist(dist: Path, hub_url: str, token: str, *, max_bytes: int = DEFAULT_MAX_BYTES, reporter: Reporter) -> int` (0 si toutes les éditions sont publiées, 1 sinon)
  - `class Reporter(Protocol)`: `error(message: str) -> None`, `warning(edition: str, message: str) -> None`, `published(edition: str, status: str, version: str, notes: str) -> None`
  - `GithubReporter` (sortie actuelle de l'Action, `::error::` / `::warning::`, valeurs échappées par `esc`) et `TextReporter` (texte simple sur stdout/stderr) ; `--json` imprime `{"ok": bool, "editions": [{"edition", "status", "version", "notes", "warnings", "error"}]}`
  - `def main_from_env(env: Mapping[str, str]) -> int` — comportement exact de l'actuel `action/publish.py:main` (variables `DECKDOCK_HUB_URL`, `DECKDOCK_TOKEN`, `DECKDOCK_PATH`, `DECKDOCK_MAX_BYTES`), avec `GithubReporter`.
  - CLI : `deckdock publish [DIST] --hub URL [--max-bytes N] [--json]` ; `DIST` défaut `dist` ; `--hub` défaut `DECKDOCK_HUB_URL` ; jeton dans `DECKDOCK_TOKEN`.
  - `action/publish.py` : ajoute `Path(__file__).resolve().parent.parent / "cli" / "src"` en tête de `sys.path`, importe `deckdock.publish`, appelle `main_from_env(os.environ)` ; réexporte `DEFAULT_MAX_BYTES` et `POST_TIMEOUT` pour ses tests.

- [ ] **Step 1: Write the failing tests** (`cli/tests/test_publish.py`, avec un faux hub `http.server` sur 127.0.0.1 comme `action/tests/test_publish.py`)

```python
def test_cli_publishes_each_edition_and_prints_plain_text(tmp_path, hub): ...   # 2 éditions → 2 POST, sortie sans "::"
def test_cli_json_report(tmp_path, hub): ...                                       # --json → ok true, 2 entrées
def test_cli_requires_token(tmp_path, monkeypatch): ...                            # DECKDOCK_TOKEN absent → code 1, message, aucun POST
def test_cli_refuses_remote_http(tmp_path): ...                                    # --hub http://example.com → code 1
def test_cli_no_edition(tmp_path): ...                                             # dossier vide → code 1 « No edition found »
def test_cli_stops_at_first_failed_edition(tmp_path, hub_failing_first): ...      # 1 seul POST
def test_token_never_printed(tmp_path, hub, capsys): ...                           # le jeton n'apparaît ni sur stdout ni sur stderr
```

- [ ] **Step 2: Run** `cd cli && uv run pytest -q tests/test_publish.py` — Expected: FAIL (module absent).
- [ ] **Step 3: Implement** le module, la sous-commande et le lanceur ; documenter la commande dans `docs/publish-to-the-hub.md`.
- [ ] **Step 4: Run** `cd cli && uv run ruff check . && uv run basedpyright && uv run pytest -q` puis `uv run --project cli pytest -q action/tests` — Expected: PASS ; les tests existants de l'Action passent sans modification.
- [ ] **Step 5: Commit** (après accord) `feat(cli): deckdock publish, shared with the Action`

### Task 3: `icon` et `homepage` dans le template (deckdock-template)

**Files:**
- Modify: `compiler/source/models.py` (`icon: str | None = None`), `schema/source.schema.json` (régénéré comme le dépôt le fait déjà), `compiler/builder.py` (`deck["icon"]` après `description` ; `homepage` calculé), `compiler/cli.py` (passe l'environnement au calcul de `homepage`)
- Modify: `deckdock.yaml` (`icon: 📚` avec un commentaire « un seul emoji, facultatif »), `README.md` (le champ `icon` et une note : les dépôts créés avant n'ont rien à faire), `CONTENT_GUIDELINES.md` si les champs y sont listés
- Test: `tests/test_builder.py`, `tests/test_validate.py`

**Interfaces:**
- Produces: `def deck_homepage(configured: str | None, env: Mapping[str, str]) -> str | None` dans `compiler/builder.py`.

- [ ] **Step 1: Write the failing tests**

```python
def test_icon_copied_to_every_edition(): ...                  # icon "📚" → deck["icon"] == "📚" en fr et en
def test_no_icon_no_key(): ...                                # pas de clé "icon"
def test_homepage_from_github_env():
    assert deck_homepage(None, {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "alice/geo"}) == "https://github.com/alice/geo"
def test_configured_homepage_wins():
    assert deck_homepage("https://example.org", {"GITHUB_SERVER_URL": "https://github.com", "GITHUB_REPOSITORY": "a/b"}) == "https://example.org"
def test_no_homepage_outside_ci():
    assert deck_homepage(None, {}) is None
def test_invalid_icon_rejected_by_validation(): ...           # "📚📚" → erreur de validation du projet sur icon
```

- [ ] **Step 2: Run** `uv run --locked pytest -q tests/test_builder.py tests/test_validate.py` — Expected: FAIL.
- [ ] **Step 3: Implement** ; la validation de `icon` réutilise la règle de la Task 1 (copie de `is_single_emoji` dans le compilateur, le template ne dépend pas de la bibliothèque à la compilation ; un test vérifie que les deux copies acceptent et refusent les mêmes cas de la Review Focus 1).
- [ ] **Step 4: Run** `uv run --locked pytest -q && uv run --locked compile` puis la vérification stricte avec la bibliothèque 0.3.0 locale : `uv run --project ../deckdock/cli deckdock check dist` — Expected: PASS, `dist/*/deck.json` contient `"icon": "📚"`, et pas de `homepage` en local.
- [ ] **Step 5: Commit** (après accord) `feat: deck icon and homepage from the repository`

### Task 4: Re-vendoring dans le hub (deckdock-hub)

**Files:**
- Modify: `vendor/deckdock/**` et `vendor/deckdock/SOURCE` via `node scripts/vendor-deckdock.mjs`
- Test: le test existant du vérificateur Python du hub (fichier qui couvre `pythonChecker`) — ajout de deux cas

- [ ] **Step 1: Write the failing tests**: un `deck.json` valide avec `"icon": "📚"` passe `check` ; avec `"icon": "📚📚"` il échoue avec une issue `where: "deck.icon"`.
- [ ] **Step 2: Run** le test (Python du hub via `HUB_PYTHON` si `python3` < 3.13) — Expected: FAIL (`icon` inconnu de la bibliothèque 0.2.0).
- [ ] **Step 3: Run** `node scripts/vendor-deckdock.mjs` (depuis `../deckdock` à jour sur `feat/icon-publish`) ; `SOURCE` nomme le commit.
- [ ] **Step 4: Run** `pnpm test:unit` et `pnpm test --group=web` — Expected: PASS.
- [ ] **Step 5: Commit** (après accord) `chore(vendor): deckdock 0.3.0 (deck.icon)`

### Mise en circulation (après accord du propriétaire à chaque étape)

Ordre corrigé après la relecture finale : le hub actuel (bibliothèque 0.2.0, vérification stricte) refuse `icon`, et le template ne compile plus avec une bibliothèque 0.2.0 puisqu'il importe `deckdock.format.emoji`.

1. Pousser `feat/icon-publish` de deckdock, fusionner dans `main`, puis déplacer le tag `v2` sur ce `main`.
2. Pousser et fusionner `feat/vendor-0.3` du hub, puis le **déployer** (sans quoi un deck avec `icon` est refusé par le hub).
3. Dans le template : `uv lock --upgrade-package deckdock` (le verrou passe au nouveau `v2`), commit, puis pousser et fusionner `feat/icon-homepage`.
