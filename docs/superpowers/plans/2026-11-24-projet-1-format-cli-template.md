# Projet 1 — Format deckdock/1, CLI `deckdock` et dépôt modèle : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal :** livrer la spec du format compilé `deckdock/1`, la CLI Python `deckdock` (`init`, `validate`, `build`, `check`), la GitHub Action qui l'enveloppe et le dépôt `deckdock-template`. On écrit des cartes en YAML, et la CI valide puis produit `dist/<édition>/deck.json` + `media/`.

**Architecture :**
- Monorepo `~/Documents/projets-perso/deckdock`, avec la CLI dans `cli/` (package `deckdock`, layout `src/`).
- Le module `deckdock.format` (vérification du format compilé) et `deckdock.guid` n'utilisent **que la bibliothèque standard**, pour pouvoir être embarqués plus tard dans l'extension Anki. Pydantic ne sert qu'aux modèles du YAML source.
- Le dépôt modèle `~/Documents/projets-perso/deckdock-template` est le résultat exact de `deckdock init`. Son workflow appelle l'Action du monorepo, qui installe la CLI depuis le même ref Git : pas besoin de PyPI pour le MVP.

**Tech Stack :** Python ≥ 3.13, uv, pydantic ≥ 2.9, PyYAML ≥ 6.0.2, markdown-it-py ≥ 3.0, pytest, jsonschema (dev uniquement), ruff, basedpyright, GitHub Actions (action composite).

**Spec :** `docs/superpowers/specs/2026-11-24-deckdock-mvp-design.md`, sections 4 et 5. Les exécutants lisent la spec **et** ce plan.

**Hors de ce plan :**
- **Migration des trois decks existants (§5.5).** Elle touche trois autres dépôts et fera l'objet d'un plan séparé, une fois ce plan livré. Elle consommera `deckdock.format` et `deckdock check`.
- `deckdock push`, qui appartient au projet 2.

## Global Constraints

- **Valeur de `format` :** `"deckdock/1"`, exactement.
- **Un fichier par édition :** `dist/<édition>/deck.json` + `dist/<édition>/media/<filename>`.
- **Clés du premier niveau de `deck.json` :** exactement `format`, `deck`, `notetypes`, `notes`, `media`. Toute clé inconnue, à n'importe quel niveau d'objet, fait échouer `check`.
- **Champs du format compilé :** HTML déjà rendu. Sous-deck : chemin `::` relatif à la racine, `""` désignant la racine.
- **Unicité des GUID :** dans un fichier seulement. `deck.language` est une liste non vide de codes BCP-47.
- **Champs facultatifs :** `deck.anki_id`, `notetypes[].anki_id` (entiers > 0), `deck.options` (`new_per_day`, `reviews_per_day`, entiers ≥ 0), `deck.description`, `deck.homepage`, `deck.license`, `deck.generator`.
- **Limites v1 :** 50 000 notes par édition, 10 Mo (10 485 760 octets) par média, 500 Mo (524 288 000 octets) de médias par édition.
- **`deck.version` :** valeur de la variable d'environnement `DECKDOCK_VERSION`, ou `"dev"` si elle est absente. C'est le seul champ non déterministe du build.
- **Id de carte :** regex `^[a-z0-9]+(?:-[a-z0-9]+)*$`, unique dans tout le projet. Id de deck : même regex.
- **Types de cartes du YAML :** `basic`, `reversed`, `cloze`, `mcq`. `status: draft` exclut la carte du build.
- **JSON écrit :** UTF-8, `ensure_ascii=False`, `indent=2`, clés dans l'ordre d'insertion, retour à la ligne final.
- **Format des erreurs :** `<chemin>:<ligne>: <message>`, ou `<chemin>: <message>` sans ligne. Code de sortie 1 en cas d'erreur, 0 sinon. Jamais de traceback pour une erreur utilisateur.
- **Hébergement :** `NayanChauveau/deckdock`, `NayanChauveau/deckdock-template`. Action : `uses: NayanChauveau/deckdock/action@v1`.
- **Licences :**
  - `spec/`, `cli/` et `action/` : MIT ;
  - `hub/` et `addon/` : AGPL-3.0-or-later (dossiers créés plus tard) ;
  - dépôt modèle : MIT pour l'outillage, CC0-1.0 pour le contenu d'exemple.
- **Commandes :** toutes depuis `cli/` : `uv run pytest`, `uv run ruff check .`, `uv run basedpyright`.

## Review Focus

1. **Fichier YAML invalide ou de forme inattendue** (erreur de syntaxe, liste à la place d'un mapping, `cards:` absent) : erreur `fichier:ligne: …`, sans traceback. Testé à la Task 4.
2. **Même id de carte dans deux fichiers :** une erreur qui cite les deux emplacements. Testé à la Task 4.
3. **Accents et caractères HTML spéciaux** (`é`, `<`, `&`, `’`) : texte conservé à l'identique dans `deck.json`, écrit en UTF-8 sans échappement `\u`. Testé à la Task 7.
4. **Image hors de `media/`, absente, ou dont le nom contient des espaces :** erreur au `validate` pour les deux premiers cas ; le nom avec espaces est accepté et correctement référencé. Testé aux Tasks 4 et 5.
5. **Carte présente dans une seule langue, ou édition sans aucune carte :** la carte est omise de l'autre édition ; une édition vide fait échouer le build avec `edition '<code>' has no cards`. Testé à la Task 7.

---

## File Structure

```
deckdock/
  README.md                                  # présentation du monorepo
  LICENSE-MIT                                # spec/, cli/, action/
  .gitignore
  .github/workflows/cli.yml                  # lint + types + tests + e2e de l'Action
  spec/
    deckdock-1.md                            # spec lisible du format compilé
    deckdock-1.schema.json                   # JSON Schema (écrit à la main)
    deckdock-source-1.schema.json            # JSON Schema du YAML source (généré depuis pydantic, commité)
    examples/valid/*.json, examples/invalid/*.json
  action/action.yml                          # action composite
  cli/
    pyproject.toml
    src/deckdock/
      __init__.py                            # __version__ = "0.1.0"
      issues.py                              # Issue + format des erreurs
      guid.py                                # guid_for, card_guid (stdlib)
      format/__init__.py                     # réexporte check_deck, check_dist, FORMAT, limites
      format/check.py                        # vérification du format compilé (stdlib)
      source/models.py                       # modèles pydantic du YAML source
      source/load.py                         # lecture YAML avec numéros de ligne
      source/validate.py                     # règles métier des sources
      build/markdown.py                      # Markdown → HTML + réécriture des médias
      build/notetypes.py                     # les 4 notetypes + libellés traduits
      build/notetypes/*.html, *.css, *.js    # fichiers des templates (package data)
      build/builder.py                       # sources → dict compilé par édition → dist/
      scaffold/                              # fichiers du projet Hello World (package data)
      init.py                                # deckdock init
      cli.py                                 # argparse, point d'entrée
    tests/
      conftest.py                            # fixture make_project(tmp_path, files: dict[str, str|bytes])
      test_*.py
deckdock-template/                           # sortie de `deckdock init`, commitée
```

---

### Task 1 : squelette du monorepo et CLI minimale

**Files :**
- Create: `README.md`, `LICENSE-MIT`, `.gitignore`, `.github/workflows/cli.yml`, `cli/pyproject.toml`, `cli/src/deckdock/__init__.py`, `cli/src/deckdock/cli.py`, `cli/src/deckdock/issues.py`
- Test: `cli/tests/test_cli.py`, `cli/tests/test_issues.py`

**Interfaces :**
- Produces :
  - `deckdock.__version__: str = "0.1.0"` ;
  - `deckdock.cli.main(argv: list[str] | None = None) -> int` ;
  - script `deckdock = "deckdock.cli:main"` ;
  - `@dataclass(frozen=True) class Issue(path: str, message: str, line: int | None = None)`, dont `__str__` produit le format des Global Constraints ;
  - `print_issues(issues: list[Issue]) -> int`, qui écrit sur stderr et renvoie 1 s'il y a des issues, 0 sinon.

- [ ] **Step 1 : écrire les tests qui échouent**

```python
# cli/tests/test_cli.py
from deckdock import __version__
from deckdock.cli import main

def test_version_flag(capsys):
    assert main(["--version"]) == 0
    assert capsys.readouterr().out.strip() == f"deckdock {__version__}"

def test_unknown_command_exits_2():
    import pytest
    with pytest.raises(SystemExit) as exc:
        main(["frobnicate"])
    assert exc.value.code == 2

# cli/tests/test_issues.py
from deckdock.issues import Issue, print_issues

def test_issue_format_with_and_without_line():
    assert str(Issue("cards/a.yaml", "boom", 12)) == "cards/a.yaml:12: boom"
    assert str(Issue("deckdock.yaml", "boom")) == "deckdock.yaml: boom"

def test_print_issues_returns_exit_code(capsys):
    assert print_issues([]) == 0
    assert print_issues([Issue("a", "b", 1)]) == 1
    assert "a:1: b" in capsys.readouterr().err
```

- [ ] **Step 2 : lancer les tests et vérifier qu'ils échouent**

Run : `cd cli && uv run pytest -q`. Attendu : échec à l'import (`ModuleNotFoundError: deckdock`).

- [ ] **Step 3 : implémenter**
  - **`pyproject.toml` :**
    - projet `deckdock` 0.1.0, licence MIT, `requires-python = ">=3.13"` ;
    - dépendances `pydantic>=2.9`, `pyyaml>=6.0.2`, `markdown-it-py>=3.0` ;
    - groupe dev `pytest`, `jsonschema`, `ruff`, `basedpyright` ;
    - build hatchling, package data `build/notetypes/*` et `scaffold/**` ;
    - `[tool.pytest.ini_options] testpaths = ["tests"]`.
  - **`main` :** argparse avec `--version` et des sous-commandes vides (`init`, `validate`, `build`, `check`), complétées par les tâches suivantes.
  - **`.gitignore` :** `.venv/`, `__pycache__/`, `dist/`, `*.egg-info/`.
  - **`README.md` :** un paragraphe sur le projet, la disposition des dossiers, et un lien vers la spec.
- [ ] **Step 4 : écrire la CI** `.github/workflows/cli.yml`
  - déclenchement : `push` et `pull_request` avec `paths: [cli/**, spec/**, action/**, .github/workflows/cli.yml]` ;
  - job `test` : `astral-sh/setup-uv`, puis `uv run ruff check .`, `uv run basedpyright` et `uv run pytest -q` dans `cli/`. Le job `e2e` sera ajouté à la Task 9.
- [ ] **Step 5 : lancer les tests et vérifier qu'ils passent.** `cd cli && uv run pytest -q && uv run ruff check . && uv run basedpyright` : tout PASS.
- [ ] **Step 6 : commit.** `git add -A && git commit -m "chore: scaffold deckdock monorepo and CLI entry point"`

---

### Task 2 : GUID déterministes

**Files :**
- Create: `cli/src/deckdock/guid.py`
- Test: `cli/tests/test_guid.py`

**Interfaces :**
- Produces :
  - `guid_for(*values: str) -> str`, compatible avec `genanki.guid_for` ;
  - `card_guid(deck_id: str, card_id: str, edition: str) -> str`, qui vaut `guid_for("deckdock", deck_id, card_id, edition)`.

- [ ] **Step 1 : écrire le test qui échoue**

```python
from deckdock.guid import card_guid, guid_for

def test_pinned_vectors():
    assert card_guid("hello-deck", "hello-001", "fr") == "x^#+V>S%em"
    assert card_guid("hello-deck", "hello-001", "en") == "kCwaq3>(Jd"

def test_guid_is_deterministic_and_anki_safe():
    g = guid_for("a", "b")
    assert g == guid_for("a", "b") and g != guid_for("a", "c")
    assert g and not any(ch.isspace() or ch in "\"'\\" for ch in g)
```

- [ ] **Step 2 : lancer et vérifier l'échec.** `uv run pytest tests/test_guid.py -q` : FAIL (import).
- [ ] **Step 3 : implémenter.** C'est l'algorithme de genanki, à reproduire exactement :

```python
import hashlib, string
_TABLE = string.ascii_letters + string.digits + "!#$%&()*+,-./:;<=>?@[]^_`{|}~"  # 91 caractères

def guid_for(*values: str) -> str:
    digest = hashlib.sha256("__".join(values).encode("utf-8")).digest()[:8]
    number = int.from_bytes(digest, "big")
    out = []
    while number > 0:
        number, rest = divmod(number, len(_TABLE))
        out.append(_TABLE[rest])
    return "".join(reversed(out))
```

- [ ] **Step 4 : lancer et vérifier le succès.** PASS.
- [ ] **Step 5 : commit.** `git commit -am "feat: deterministic Anki GUIDs"` (ajouter les nouveaux fichiers avec `git add`).

---

### Task 3 : vérificateur du format compilé, spec, schéma et `deckdock check`

**Files :**
- Create: `cli/src/deckdock/format/__init__.py`, `cli/src/deckdock/format/check.py`, `spec/deckdock-1.md`, `spec/deckdock-1.schema.json`, `spec/examples/valid/minimal.json`, `spec/examples/valid/full.json`, un fichier par cas d'invalidité sous `spec/examples/invalid/`
- Modify: `cli/src/deckdock/cli.py` (sous-commande `check`)
- Test: `cli/tests/test_format_check.py`, `cli/tests/test_spec_examples.py`

**Interfaces :**
- Consumes : `Issue` (Task 1).
- Produces :
  - `FORMAT = "deckdock/1"`, `MAX_NOTES = 50_000`, `MAX_MEDIA_BYTES = 10_485_760`, `MAX_TOTAL_MEDIA_BYTES = 524_288_000` ;
  - `check_deck(data: object, *, path: str = "deck.json") -> list[Issue]`, pour la structure seule, sans accès disque ;
  - `check_dist(dist_dir: Path) -> list[Issue]`, qui vérifie chaque `<dist>/<édition>/deck.json` : structure, médias sur disque (présence, taille, sha256), fichiers listés et présents, références ;
  - CLI : `deckdock check [DIST]` (par défaut `dist`) imprime les issues et renvoie le code de sortie.

**Règles à implémenter** (chaque règle correspond à un exemple invalide et à un test) :
- **Clés.**
  - Premier niveau : exactement les cinq clés, avec `format == "deckdock/1"`.
  - Objets `deck`, notetype, template, note et média : clés requises présentes, clés inconnues refusées.
  - `deck` requiert `id`, `edition`, `name`, `language` et `version`.
- **`deck`.**
  - `id` respecte la regex des ids. `edition` est non vide et sans `/`.
  - `language` est une liste non vide de chaînes.
  - `anki_id` est un entier > 0. `options` ne contient que `new_per_day` et `reviews_per_day`, des entiers ≥ 0.
- **Notetypes.**
  - `id` unique. `kind` vaut `standard` ou `cloze`.
  - `fields` est non vide, ses noms uniques et non vides.
  - `templates` est non vide, et un notetype `cloze` en a exactement un.
  - `name`, `front`, `back` et `css` sont des chaînes. `anki_id` est un entier > 0 s'il est présent.
- **Notes.**
  - `guid` non vide et unique dans le fichier. `notetype` existe.
  - L'ensemble des clés de `fields` est égal à celui des champs du notetype, et les valeurs sont des chaînes.
  - `tags` est une liste de chaînes non vides sans espaces.
  - `deck` vaut `""` ou des segments non vides séparés par `::`.
  - Au plus `MAX_NOTES` notes.
- **Médias.**
  - `filename` non vide, sans `/`, sans `\`, différent de `.` et `..`, et unique.
  - `sha256` contient 64 caractères hexadécimaux en minuscules. `size` est un entier ≥ 0, au plus `MAX_MEDIA_BYTES`, et le total est au plus `MAX_TOTAL_MEDIA_BYTES`.
- **Références** (`check_dist` uniquement) : tout nom trouvé dans les champs, les templates ou le CSS par les motifs `src="X"`, `src='X'`, `[sound:X]` et `url(X)` (guillemets facultatifs) doit être listé, à condition que X ne contienne ni `://` ni `/` et ne commence pas par `data:`. Un fichier de `media/` absent de la liste, ou l'inverse, est une erreur.
- **Messages.** Ils citent le chemin JSON, par exemple `deck.json: notes[3].fields: missing field 'Back'`.

- [ ] **Step 1 : écrire les tests qui échouent**

```python
# cli/tests/test_spec_examples.py
import json, pathlib, pytest, jsonschema
from deckdock.format import check_deck
SPEC = pathlib.Path(__file__).parents[2] / "spec"
SCHEMA = json.loads((SPEC / "deckdock-1.schema.json").read_text())

@pytest.mark.parametrize("p", sorted((SPEC / "examples/valid").glob("*.json")), ids=lambda p: p.name)
def test_valid_examples_pass_checker_and_schema(p):
    data = json.loads(p.read_text())
    assert check_deck(data) == []
    jsonschema.validate(data, SCHEMA)

@pytest.mark.parametrize("p", sorted((SPEC / "examples/invalid").glob("*.json")), ids=lambda p: p.name)
def test_invalid_examples_fail_checker(p):
    assert check_deck(json.loads(p.read_text())) != []
```

Le reste dans `test_format_check.py`. Chaque test part du dict de `valid/minimal.json`, le modifie et vérifie qu'un message contient le fragment indiqué :
  - `test_unknown_top_level_key` → `unknown key 'extra'` ;
  - `test_wrong_format_version` → `format must be 'deckdock/1'` ;
  - `test_duplicate_guid` → `duplicate guid` ;
  - `test_note_fields_must_match_notetype` → `missing field 'Back'` et `unknown field 'Verso'` ;
  - `test_cloze_notetype_has_one_template` → `exactly one template` ;
  - `test_language_must_be_non_empty_list` → `language` ;
  - `test_options_keys_and_values` → `options` ;
  - `test_deck_path_segments` (`"A::::B"`) → `deck path` ;
  - `test_media_filename_with_slash` → `filename` ;
  - `test_too_many_notes` (monkeypatch de `MAX_NOTES` à 1) → `too many notes` ;
  - `test_check_dist_media_sha_mismatch` (tmp_path) → `sha256 mismatch` ;
  - `test_check_dist_unlisted_and_missing_media` → `not listed` et `missing file` ;
  - `test_check_dist_unlisted_reference` (`<img src="x.png">` sans entrée média) → `references unlisted media 'x.png'` ;
  - `test_external_and_data_urls_ignored` (`src="https://…"`, `src="data:…"`) → aucune issue ;
  - `test_cli_check_exit_codes` : `main(["check", str(dist)])` vaut 0 sur un dist valide et 1 sur un dist invalide.

- [ ] **Step 2 : lancer et vérifier l'échec.** `uv run pytest tests/test_format_check.py tests/test_spec_examples.py -q` : FAIL.
- [ ] **Step 3 : écrire les exemples et le schéma.**
  - `minimal.json` : un notetype `basic` (champs `Front`, `Back`), une note, aucun média.
  - `full.json` : les quatre types, des sous-decks, `anki_id`, `options`, un média.
  - `deckdock-1.schema.json` : JSON Schema 2020-12 qui encode les règles **structurelles** ci-dessus (clés, types, `additionalProperties: false`, regex). Les règles croisées (unicité, correspondance des champs, références) restent du ressort de `check_deck`, et la spec le dit.
- [ ] **Step 4 : implémenter `check_deck`, `check_dist` et la sous-commande `check`** (stdlib uniquement, aucun import de pydantic ni de yaml dans `deckdock.format` et `deckdock.guid`).
- [ ] **Step 5 : écrire `spec/deckdock-1.md`.** Structure du dossier, tableau de chaque objet et de chaque clé (type, requise ou non, règle), identité et unicité, médias et références, limites, compatibilité (`deckdock/1` puis `deckdock/2`), exemple. Contenu repris des §5.1 de la spec de design et des règles ci-dessus.
- [ ] **Step 6 : lancer et vérifier le succès.** `uv run pytest -q` : PASS. Ajouter le test garde-fou `test_format_module_is_stdlib_only` : parcourir l'AST de `format/*.py` et de `guid.py`, et vérifier qu'aucun import ne commence par `pydantic`, `yaml` ou `markdown_it`.
- [ ] **Step 7 : commit.** `git add -A && git commit -m "feat: deckdock/1 format spec, schema and checker"`

---

### Task 4 : modèles du YAML source, chargement et `deckdock validate`

**Files :**
- Create: `cli/src/deckdock/source/{__init__,models,load,validate}.py`, `spec/deckdock-source-1.schema.json`
- Modify: `cli/src/deckdock/cli.py` (sous-commande `validate`)
- Test: `cli/tests/conftest.py`, `cli/tests/test_source_load.py`, `cli/tests/test_validate.py`

**Interfaces :**
- Consumes : `Issue`, `print_issues` (Task 1).
- Produces :
  - `class ProjectConfig(BaseModel)` avec :
    - `id: str` ;
    - `name: str | dict[str, str]`, `description: str | dict[str, str] | None` ;
    - `editions: list[str]` (au moins une, codes uniques) ;
    - `license: str | None`, `homepage: str | None`, `options: DeckOptions | None`.
  - `class Card(BaseModel)` avec :
    - `id: str`, `type: Literal["basic","reversed","cloze","mcq"]` ;
    - `deck: str = ""`, `tags: list[str] = []`, `status: Literal["draft","reviewed"] = "reviewed"` ;
    - un contenu soit **direct** (identique pour toutes les éditions), soit **par édition** (clé = code d'édition).
  - Contenu par type :
    - `basic` et `reversed` : `front: str`, `back: str` ;
    - `cloze` : `text: str`, `extra: str = ""` ;
    - `mcq` : `question: str`, `choices: list[Choice]` (`text: str`, `correct: bool = False`), `explanation: str = ""`.
  - Tous les modèles ont `extra="forbid"`, sauf `Card`. Ses clés inconnues sont traitées comme des blocs par édition : un validateur `model_validator(mode="before")` les déplace dans `editions: dict[str, Content]`, validées selon le modèle de contenu du `type`. Les champs de contenu direct sont regroupés dans `direct: Content | None`.
  - `@dataclass(frozen=True) class LoadedCard(card: Card, path: str, line: int)`.
  - `@dataclass(frozen=True) class Project(root: Path, config: ProjectConfig, cards: list[LoadedCard])`.
  - `load_project(root: Path) -> tuple[Project | None, list[Issue]]` lit `deckdock.yaml` et `cards/**/*.yaml` et `*.yml`, triés par chemin relatif.
  - `validate_project(project: Project) -> list[Issue]`.
  - `Card.content_for(edition: str) -> BasicContent | ClozeContent | McqContent | None` renvoie le contenu direct ou le bloc de l'édition, `None` s'il est absent.
  - CLI : `deckdock validate [ROOT]` (par défaut `.`).
  - Fixture `make_project(files: dict[str, str | bytes]) -> Path`, qui écrit les fichiers dans `tmp_path`. Elle fournit un `deckdock.yaml` minimal valide par défaut (`id: test-deck`, `name: Test`, `editions: [fr, en]`) si la clé est absente.

**Règles de `validate_project`** (message → test) :
- ids de carte conformes à la regex → `invalid card id` ;
- id en double → `duplicate card id 'x' (also at cards/a.yaml:3)` ;
- clé de langue qui n'est pas une édition déclarée → `unknown edition 'de'` ;
- carte sans contenu pour aucune édition → `no content for any edition` ;
- mélange de contenu direct et par édition → `mix of direct and per-edition content` (à refuser dans le modèle) ;
- cloze sans `{{cN::…}}` → `cloze text has no deletion` ;
- QCM avec moins de 2 choix ou un nombre de bonnes réponses différent de 1 → `exactly one correct choice` ;
- image Markdown ou `src=` local ne commençant pas par `media/` → `media must live in media/` ;
- fichier média absent → `missing media file 'media/x.png'` ;
- segment de sous-deck vide → `deck path` ;
- `name` ou `description` en dict sans valeur pour chaque édition → `missing name for edition 'en'`.

**Chargement :**
- Utiliser `yaml.compose` pour récupérer la ligne (1-based) de chaque élément de `cards`, puis `yaml.safe_load` pour les valeurs.
- Erreur de syntaxe YAML → `Issue(path, "invalid YAML: <problème>", ligne)`.
- Racine qui n'est pas un mapping ou `cards` absent ou pas une liste → issue avec ligne.
- Erreurs pydantic → une issue par erreur, avec la ligne de la carte et le chemin du champ (`hello-001.fr.front: Field required`).

- [ ] **Step 1 : écrire les tests qui échouent.** Un test par règle ci-dessus, plus les tests de chargement suivants :

```python
def test_yaml_syntax_error_reports_file_and_line(make_project):
    root = make_project({"cards/a.yaml": "cards:\n  - id: a\n    type: [basic\n"})
    project, issues = load_project(root)
    assert project is None and str(issues[0]).startswith("cards/a.yaml:3: invalid YAML")

def test_card_line_numbers(make_project):
    root = make_project({"cards/a.yaml": "cards:\n  - id: a-1\n    type: basic\n    front: x\n    back: y\n\n  - id: a-2\n    type: basic\n    front: x\n    back: y\n"})
    project, _ = load_project(root)
    assert [c.line for c in project.cards] == [2, 7]

def test_non_mapping_root(make_project):
    root = make_project({"cards/a.yaml": "- 1\n- 2\n"})
    _, issues = load_project(root)
    assert "cards/a.yaml:1:" in str(issues[0])

def test_duplicate_id_across_files_names_both(make_project): ...
def test_cli_validate_exit_codes(make_project): ...   # 0 sur un projet valide, 1 avec la sortie stderr attendue
```

- [ ] **Step 2 : lancer et vérifier l'échec.** FAIL.
- [ ] **Step 3 : implémenter** les modèles, `load_project`, `validate_project` et la sous-commande.
- [ ] **Step 4 : générer le schéma source.** Un test `test_source_schema_up_to_date` compare `spec/deckdock-source-1.schema.json` à la sortie de `deckdock.source.models.source_json_schema() -> dict`. Ce schéma réunit `ProjectConfig` et un fichier de cartes `{cards: list[Card]}` sous `$defs`. Écrire le fichier une première fois avec `uv run python -c "…"`, pour que le test passe.
- [ ] **Step 5 : lancer et vérifier le succès.** `uv run pytest -q` : PASS.
- [ ] **Step 6 : commit.** `git add -A && git commit -m "feat: source YAML models and deckdock validate"`

---

### Task 5 : rendu Markdown et réécriture des médias

**Files :**
- Create: `cli/src/deckdock/build/__init__.py`, `cli/src/deckdock/build/markdown.py`
- Test: `cli/tests/test_markdown.py`

**Interfaces :**
- Produces : `render(text: str) -> tuple[str, set[str]]`, qui renvoie le HTML et l'ensemble des fichiers `media/…` référencés (chemins relatifs à la racine, par exemple `"media/a b.png"`).
  - Rendu avec `MarkdownIt("commonmark", {"html": True})`.
  - Si la sortie est exactement un paragraphe, on retire le `<p>…</p>` englobant.
  - Les `src` d'images qui commencent par `media/` sont réécrits vers le nom de fichier seul.
  - Le texte n'est jamais modifié autrement.

- [ ] **Step 1 : écrire les tests qui échouent**

```python
from deckdock.build.markdown import render

def test_single_paragraph_is_unwrapped():
    assert render("**Hello**") == ("<strong>Hello</strong>", set())

def test_multi_paragraph_kept():
    assert render("a\n\nb")[0] == "<p>a</p>\n<p>b</p>"

def test_image_rewritten_to_basename_and_collected():
    html, media = render("![carte](media/carte%20bordeaux.png)")
    assert 'src="carte bordeaux.png"' in html and media == {"media/carte bordeaux.png"}

def test_inline_html_img_rewritten():
    html, media = render('<img src="media/x.png">')
    assert 'src="x.png"' in html and media == {"media/x.png"}

def test_cloze_and_accents_survive():
    assert render("La {{c1::Côte-d’Or}} & <b>Beaune</b>")[0] == "La {{c1::Côte-d’Or}} &amp; <b>Beaune</b>"
```

  Si markdown-it échappe `&` différemment de ce qu'attend le dernier test, aligner le test sur le comportement CommonMark réel (`&amp;`) et garder l'assertion sur les accents et le cloze.
- [ ] **Step 2 : lancer et vérifier l'échec.** FAIL.
- [ ] **Step 3 : implémenter `render`.** Réécrire les images via une règle de rendu markdown-it pour `image`, et les `<img src>` en HTML brut via une regex sur `src=["']media/([^"']+)["']`. Décoder les `%20` des URL Markdown avec `urllib.parse.unquote`.
- [ ] **Step 4 : lancer et vérifier le succès.** PASS.
- [ ] **Step 5 : commit.** `git add -A && git commit -m "feat: markdown rendering with media rewriting"`

---

### Task 6 : les quatre notetypes DeckDock

**Files :**
- Create: `cli/src/deckdock/build/notetypes.py`, `cli/src/deckdock/build/notetypes/{base.css,basic.front.html,basic.back.html,reversed.front2.html,reversed.back2.html,cloze.front.html,cloze.back.html,mcq.front.html,mcq.back.html,mcq.js}`
- Test: `cli/tests/test_notetypes.py`

**Interfaces :**
- Produces : `notetype_for(card_type: str, edition: str) -> dict`, qui renvoie un notetype au format compilé (`id`, `name`, `kind`, `fields`, `templates`, `css`, sans `anki_id`).

| type | `id` | `name` | `kind` | `fields` | templates |
|---|---|---|---|---|---|
| basic | `basic` | `DeckDock Basic` | standard | `Front`, `Back` | 1 |
| reversed | `reversed` | `DeckDock Basic (and reversed)` | standard | `Front`, `Back` | 2 |
| cloze | `cloze` | `DeckDock Cloze` | cloze | `Text`, `Extra` | 1 |
| mcq | `mcq` | `DeckDock MCQ` | standard | `Question`, `Choices`, `Explanation` | 1 |

- **Champ `Choices` du QCM :** HTML produit par le builder, de la forme `<ol class="dd-choices"><li data-correct="1">…</li><li>…</li></ol>`. `mcq.js` est inclus dans les deux faces.
  - **Recto :** mélange les `li` avec un ordre stocké dans `sessionStorage` sous la clé `deckdock-mcq:<texte de la question>`.
  - **Verso :** réapplique le même ordre et ajoute la classe `dd-correct` sur la bonne réponse.
  - Si `sessionStorage` est indisponible, on garde l'ordre d'origine (mobile).
- **Libellés traduits** par un dict `LABELS = {"en": {"explanation": "Explanation"}, "fr": {"explanation": "Explication"}}`, avec repli sur `en` pour une autre langue. Ils sont injectés dans le HTML au moment de `notetype_for`.
- **CSS commun :** sobre, avec mode sombre via `.nightMode`.

- [ ] **Step 1 : écrire les tests qui échouent**
  - `test_table_values` : pour chaque ligne du tableau, `id`, `name`, `kind`, `fields` et le nombre de templates.
  - `test_templates_reference_only_declared_fields` : extraire `{{X}}` et `{{cloze:X}}` hors `FrontSide`, et vérifier que chaque X appartient à `fields`.
  - `test_mcq_includes_shuffle_script_on_both_sides`.
  - `test_labels_localised` : `"Explication"` apparaît dans le notetype `mcq` pour `fr`, `"Explanation"` pour `en` et pour `de`.
  - `test_output_passes_check_deck` : un deck minimal construit à la main avec chaque notetype passe `check_deck`.
- [ ] **Step 2 : lancer et vérifier l'échec.** FAIL.
- [ ] **Step 3 : implémenter** les fichiers de templates (lus avec `importlib.resources`) et `notetype_for`.
- [ ] **Step 4 : lancer et vérifier le succès.** PASS.
- [ ] **Step 5 : commit.** `git add -A && git commit -m "feat: built-in DeckDock notetypes"`

---

### Task 7 : le builder et `deckdock build`

**Files :**
- Create: `cli/src/deckdock/build/builder.py`
- Modify: `cli/src/deckdock/cli.py` (sous-commande `build`)
- Test: `cli/tests/test_builder.py`

**Interfaces :**
- Consumes :
  - `load_project`, `validate_project`, `Project`, `Card.content_for` (Task 4) ;
  - `render` (Task 5), `notetype_for` (Task 6), `card_guid` (Task 2) ;
  - `check_dist`, `FORMAT` (Task 3).
- Produces :
  - `compile_edition(project: Project, edition: str, version: str) -> tuple[dict, set[str]]`, qui renvoie le deck compilé et les médias référencés ;
  - `build(root: Path, out: Path, version: str) -> list[Issue]`, qui fait `validate`, vide `out` puis écrit chaque édition, lance `check_dist(out)` et renvoie toutes les issues ;
  - CLI : `deckdock build [ROOT] [--out DIST]`, avec `--out` par défaut `ROOT/dist` et une version lue dans `DECKDOCK_VERSION`, `"dev"` par défaut.

**Règles :**
- **`deck`** : `id`, `edition`, `name` et `description` pour l'édition (une chaîne s'applique à toutes), `language: [edition]`, `license`, `homepage`, `options` s'ils sont présents, `version`, `generator: "deckdock <__version__>"`. Les clés absentes sont omises.
- **Notes.**
  - Ordre : celui de `project.cards` (fichiers triés, puis ordre dans le fichier). Cartes `draft` et cartes sans contenu pour l'édition exclues.
  - Champs : chaque champ texte passe par `render`. `Choices` est construit à partir des choix rendus.
  - `guid = card_guid(config.id, card.id, edition)`, `deck = card.deck`, `tags = card.tags`.
- **Notetypes** : seulement ceux qui sont utilisés, dans l'ordre de première utilisation.
- **Médias** : copiés depuis `ROOT/media/…` vers `out/<édition>/media/<basename>`, avec `filename`, `sha256` et `size` calculés, triés par `filename`. Deux chemins sources différents avec le même basename donnent l'erreur `media name collision 'x.png'`.
- **Édition sans aucune note** → `Issue("deckdock.yaml", "edition '<code>' has no cards")`.
- **Écriture JSON** selon les Global Constraints.

- [ ] **Step 1 : écrire les tests qui échouent**
  - `test_build_two_editions_layout` : `dist/fr/deck.json` et `dist/en/deck.json` existent, et `check_dist` renvoie `[]`.
  - `test_guid_matches_card_guid` : pour `hello-001` en `fr`, `guid == card_guid("test-deck","hello-001","fr")`.
  - `test_card_missing_language_is_omitted_from_that_edition`.
  - `test_empty_edition_fails`.
  - `test_drafts_excluded`.
  - `test_accents_and_html_preserved_utf8` : le fichier brut contient `Côte-d’Or` littéralement et pas de `ô`.
  - `test_media_copied_with_sha_and_size`, et `test_media_with_space_in_name`.
  - `test_deterministic_output` : deux builds avec la même `DECKDOCK_VERSION` produisent des octets identiques.
  - `test_version_from_env_or_dev`.
  - `test_cli_build_exit_codes` : 0 sur un projet valide, 1 sur un projet invalide, sans traceback.
  - `test_mcq_choices_html` : `data-correct="1"` exactement une fois.
- [ ] **Step 2 : lancer et vérifier l'échec.** FAIL.
- [ ] **Step 3 : implémenter `compile_edition`, `build` et la sous-commande.**
- [ ] **Step 4 : lancer et vérifier le succès.** `uv run pytest -q` : PASS.
- [ ] **Step 5 : commit.** `git add -A && git commit -m "feat: deckdock build"`

---

### Task 8 : `deckdock init` et le projet Hello World

**Files :**
- Create: `cli/src/deckdock/init.py`, et sous `cli/src/deckdock/scaffold/` :
  - `deckdock.yaml`, `cards/hello.yaml`, `media/hello.png` ;
  - `AGENTS.md`, `CONTENT_GUIDELINES.md`, `README.md` ;
  - `LICENSE`, `LICENSE-CONTENT` ;
  - `gitignore` (renommé en `.gitignore` à la copie), `editorconfig` (→ `.editorconfig`), `pre-commit-config.yaml` (→ `.pre-commit-config.yaml`) ;
  - `github/workflows/deck.yml`, `github/ISSUE_TEMPLATE/card-problem.yml`, `github/PULL_REQUEST_TEMPLATE.md` (→ `.github/…`).
- Modify: `cli/src/deckdock/cli.py` (sous-commande `init`)
- Test: `cli/tests/test_init.py`

**Interfaces :**
- Consumes : `build` (Task 7).
- Produces : `init_project(target: Path, *, deck_id: str | None = None) -> None`, qui refuse un dossier non vide (`FileExistsError`, message CLI `target is not empty`). `deck_id` vaut par défaut le nom du dossier, normalisé selon la regex des ids. La fonction crée le lien `CLAUDE.md → AGENTS.md` (copie si le lien échoue). CLI : `deckdock init [TARGET]` (par défaut `.`).

**Contenu fixé :**
- **`deckdock.yaml`** : en première ligne `# yaml-language-server: $schema=https://raw.githubusercontent.com/NayanChauveau/deckdock/v1/spec/deckdock-source-1.schema.json` ; `id` (remplacé), `name` et `description` en `fr` et `en`, `editions: [fr, en]`, `license: CC0-1.0`.
- **`cards/hello.yaml`** : même ligne `$schema`, puis trois cartes, `hello-001` basic, `hello-002` cloze et `hello-003` QCM, en FR et EN. `hello-001` affiche `media/hello.png`.
- **`media/hello.png`** : PNG valide de moins de 5 Ko.
- **`deck.yml`** (workflow) :
  - déclenchement : `pull_request` et `push` sur `main` ;
  - étapes : `actions/checkout@v4`, puis un step shell `echo "DECKDOCK_VERSION=$(date -u +%Y-%m-%dT%H:%M:%SZ)+${GITHUB_SHA::7}" >> "$GITHUB_ENV"`, puis `NayanChauveau/deckdock/action@v1` avec `command: build` ;
  - puis `actions/upload-artifact@v4` avec le nom `deck` et le chemin `dist/` ;
  - un step `Publish to DeckDock hub` commenté, avec la note « disponible au projet 2 : ajouter le secret DECKDOCK_TOKEN ».
- **`.pre-commit-config.yaml`** : un hook local `deckdock validate` lancé via `uvx --from git+https://github.com/NayanChauveau/deckdock@v1#subdirectory=cli deckdock validate`.
- **`AGENTS.md`** : comment ajouter des cartes (formats des quatre types avec exemples, règles d'id permanents, médias dans `media/`, `status: draft`), commandes à lancer (`deckdock validate`, `deckdock build`), et rappel de lire `CONTENT_GUIDELINES.md`. On peut partir de `AGENTS.md` et `CONTENT_GUIDELINES.md` de `wine-theory-anki`, en retirant tout ce qui est propre au vin.
- **`README.md`** : démarrage en trois étapes (Use this template, éditer `deckdock.yaml`, ajouter des cartes et pousser), où trouver le JSON (artefact `deck`), et un lien vers la spec.

- [ ] **Step 1 : écrire les tests qui échouent**
  - `test_init_then_build_is_valid` : `init_project(tmp/"mon-deck")`, puis `build` renvoie `[]`. Deux éditions, trois notes chacune, un média.
  - `test_init_sets_deck_id_from_folder` : `id: mon-deck`.
  - `test_init_refuses_non_empty_dir`.
  - `test_dotfiles_renamed` : `.github/workflows/deck.yml`, `.gitignore`, `.editorconfig` et `.pre-commit-config.yaml` existent, et aucun `github/` sans point.
  - `test_claude_md_points_to_agents`.
  - `test_workflow_uses_pinned_action` : `deck.yml` contient `NayanChauveau/deckdock/action@v1`.
- [ ] **Step 2 : lancer et vérifier l'échec.** FAIL.
- [ ] **Step 3 : écrire le scaffold et `init_project`.**
- [ ] **Step 4 : lancer et vérifier le succès.** PASS.
- [ ] **Step 5 : commit.** `git add -A && git commit -m "feat: deckdock init with hello-world scaffold"`

---

### Task 9 : GitHub Action et test de bout en bout en CI

**Files :**
- Create: `action/action.yml`, `action/README.md`
- Modify: `.github/workflows/cli.yml` (job `e2e`)

**Interfaces :**
- Produces : une action composite.
  - **Entrées :** `command` (`validate` | `build` | `check`, défaut `build`), `path` (défaut `.`), `deckdock-ref` (défaut vide, ce qui signifie `${{ github.action_ref }}`).
  - **Étapes :** `astral-sh/setup-uv@v5`, puis `uvx --from "git+https://github.com/NayanChauveau/deckdock@${REF}#subdirectory=cli" deckdock <command> <path>`, où `REF` vaut `inputs.deckdock-ref` ou, à défaut, `github.action_ref`.
  - **Variante locale** (CI du monorepo, où `action_ref` est vide) : si `deckdock-ref` vaut `local`, l'action lance `uvx --from "${{ github.action_path }}/../cli" deckdock …`.

- [ ] **Step 1 : ajouter le job `e2e`** à `cli.yml` :
  1. checkout ;
  2. `uvx --from ./cli deckdock init /tmp/hello` ;
  3. `uses: ./action` avec `path: /tmp/hello`, `command: build`, `deckdock-ref: local` ;
  4. `uvx --from ./cli deckdock check /tmp/hello/dist`.
- [ ] **Step 2 : vérifier en local** ce que le job exécute : `cd cli && uv run deckdock init /tmp/dd-e2e && uv run deckdock build /tmp/dd-e2e && uv run deckdock check /tmp/dd-e2e/dist`. Attendu : code 0 à chaque commande. Valider la syntaxe de l'action avec `uvx check-jsonschema --builtin-schema vendor.github-actions action/action.yml` et du workflow avec `--builtin-schema vendor.github-workflows .github/workflows/cli.yml`.
- [ ] **Step 3 : écrire `action/README.md`** : exemple d'utilisation, entrées, épinglage `@v1`.
- [ ] **Step 4 : commit.** `git add -A && git commit -m "feat: GitHub Action wrapping the deckdock CLI"`

---

### Task 10 : le dépôt `deckdock-template`

**Files :**
- Create : tout `~/Documents/projets-perso/deckdock-template/`, comme sortie de `deckdock init`.
- Create: `cli/tests/test_template_repo_in_sync.py` (dans le monorepo)

**Interfaces :**
- Consumes : `init_project` (Task 8).

- [ ] **Step 1 : écrire le test de synchronisation**, ignoré si le dépôt voisin est absent :

```python
TEMPLATE = Path(__file__).parents[3] / "deckdock-template"

@pytest.mark.skipif(not TEMPLATE.exists(), reason="template repo not checked out next to deckdock")
def test_template_repo_matches_init(tmp_path):
    init_project(tmp_path / "deckdock-template")
    # comparer tous les fichiers sauf .git/ ; même liste, mêmes octets
```

- [ ] **Step 2 : générer le dépôt.** `cd ~/Documents/projets-perso/deckdock/cli && uv run deckdock init ../../deckdock-template`. Le dossier ne contient que `.git/` : adapter `init_project` pour ignorer `.git` dans le contrôle « dossier non vide », avec le test `test_init_allows_existing_git_dir`.
- [ ] **Step 3 : vérifier.** `uv run pytest -q` : PASS (sync compris). `uv run deckdock build ../../deckdock-template` : code 0.
- [ ] **Step 4 : commit dans les deux dépôts.**
  - deckdock : `git commit -am "test: keep deckdock-template in sync with init"`.
  - deckdock-template : `git add -A && git commit -m "Initial hello-world deck from deckdock init"`.

---

### Task 11 : publication sur GitHub (point d'arrêt, accord explicite requis)

Cette tâche est **visible publiquement** : ne pas l'exécuter sans un « oui » de Nayan dans la conversation.

- [ ] **Step 1 : demander l'accord**, en listant ce qui va se passer :
  - création des dépôts publics `NayanChauveau/deckdock` et `NayanChauveau/deckdock-template` ;
  - push ;
  - tag mobile `v1` sur `deckdock` ;
  - marquage de `deckdock-template` comme dépôt modèle.
- [ ] **Step 2 : publier.**
  - `gh repo create NayanChauveau/deckdock --public --source ~/Documents/projets-perso/deckdock --push`
  - `git -C ~/Documents/projets-perso/deckdock tag v1 && git -C ~/Documents/projets-perso/deckdock push origin v1`
  - `gh repo create NayanChauveau/deckdock-template --public --source ~/Documents/projets-perso/deckdock-template --push`
  - `gh repo edit NayanChauveau/deckdock-template --template`
- [ ] **Step 3 : vérifier.** La CI `cli.yml` (test + e2e) est verte sur `deckdock`. Le workflow `deck.yml` est vert sur `deckdock-template`, et l'artefact `deck` contient `fr/deck.json`, `en/deck.json` et `media/hello.png`. Si c'est rouge, ouvrir les logs avec `gh run view --log-failed` et corriger.
