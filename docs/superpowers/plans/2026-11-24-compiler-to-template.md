# Le compilateur déménage dans le dépôt modèle : plan d'implémentation

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`) syntax.

**Goal :** appliquer la révision §8 du design. `deckdock` ne garde que le format (spec, schéma, bibliothèque stdlib-only, `deckdock check`). Le compilateur YAML → `deck.json` part dans `deckdock-template`, comme exemple modifiable avec ses tests.

**Architecture :** le code et les tests existants sont **déplacés**, pas réécrits. Le template devient un projet uv (`pyproject.toml` + `uv.lock`) qui dépend de la bibliothèque `deckdock`. Pendant le développement, cette dépendance est un chemin local (`../deckdock/cli`). À la publication, elle devient `git` au tag `v2`.

**Spec :** `docs/superpowers/specs/2026-11-24-deckdock-mvp-design.md` §8 (et §5.1 pour le format, inchangé).

## Global Constraints

- **Format inchangé :** `deckdock/1`, avec le même schéma, les mêmes règles et le même `check`. Aucun octet de `dist/` du Hello World ne doit changer, `version` excepté.
- **Bibliothèque `deckdock` (cli/src/deckdock) :** stdlib uniquement, **sans aucune dépendance tierce**. La CLI ne contient que `deckdock --version` et `deckdock check [DIST]`. Version du package : `0.2.0`.
- **Le compilateur du template importe** `deckdock.format` (types, `check_dist`, `SLUG_RE`), `deckdock.guid` et `deckdock.issues`. Il ne duplique jamais ce code.
- **Le parcours du template se fait en 3 commandes**, avec une sortie identique à aujourd'hui :
  - `uv run compile`, qui valide puis écrit `dist/` ;
  - `uv run compile --validate-only` ;
  - `uv run compile --out DIR`.

  Le code de sortie, le format des erreurs `fichier:ligne: message` et la règle « jamais de traceback » restent ceux d'aujourd'hui.
- **Action `NayanChauveau/deckdock/action` :** la seule commande est `check`. L'entrée `path` vaut `dist` par défaut et lance `deckdock check <path>`. Le template l'utilise à `@v2`.
- **Toujours avant de rendre :** ruff check, ruff format --check, basedpyright 0/0 et pytest verts **dans chaque dépôt touché**.
- **Rien n'est poussé ni publié** avant la Task 4, qui demande l'accord explicite de Nayan.

## Review Focus

1. Après le déménagement, le template compile exactement le même `dist/` qu'avant (comparaison octet par octet avec `DECKDOCK_VERSION` fixé).
2. Les protections de sécurité (traversée de chemins pour les médias et les éditions, liens symboliques) et leurs tests survivent au déménagement.
3. `deckdock check` fonctionne toujours seul, sans pydantic, yaml ni markdown-it installés.
4. Les docs (template README, AGENTS.md, spec) ne mentionnent plus `deckdock init`, `deckdock build` ou `deckdock validate`.

---

### Task 1 : le compilateur d'exemple dans `deckdock-template`

**Repo :** `~/Documents/projets-perso/deckdock-template` (branche `main`, commits locaux).

**Layout cible :**

```
pyproject.toml          # name "deck-compiler", private ; requires-python >=3.13
                        # deps : deckdock, pydantic>=2.9, pyyaml>=6.0.2, markdown-it-py>=3.0
                        # dev : pytest, ruff, basedpyright
                        # [project.scripts] compile = "compiler.cli:main"
                        # [tool.uv.sources] deckdock = { path = "../deckdock/cli", editable = true }   (provisoire, Task 4)
uv.lock
compiler/               # package plat (pas de src/)
  __init__.py
  cli.py                # main(argv) -> int : [--validate-only] [--out DIR] ; racine = dossier courant
  source/{__init__,models,load,validate}.py     # depuis deckdock/source
  render/{__init__,markdown}.py                 # depuis deckdock/build/markdown.py
  media.py, notetypes.py, builder.py            # depuis deckdock/build
  notetypes/*.html|css|js                       # depuis deckdock/build/notetypes
tests/                  # tests déplacés et adaptés (builder, markdown, notetypes, source_load, validate, + exemples de doc)
docs/source-format.md   # depuis deckdock/spec/deckdock-source-1.md, adapté (« format du compilateur d'exemple »)
schema/source.schema.json  # depuis spec/deckdock-source-1.schema.json ; test « à jour » déplacé ici
```

- [ ] **Step 1 : copier le code et les tests** depuis `~/Documents/projets-perso/deckdock/cli` (le monorepo n'est pas modifié dans cette tâche).
  - Renommer les imports `deckdock.source` → `compiler.source`, `deckdock.build.*` → `compiler.*`.
  - Garder `deckdock.format`, `deckdock.guid` et `deckdock.issues` importés depuis la bibliothèque.
  - Le `generator` du deck devient `"deck-compiler (deckdock-template)"`.
- [ ] **Step 2 : `compiler/cli.py`.** Il réutilise `build()` et `load_project` / `validate_project`. Le code de sortie et l'impression des issues passent par `deckdock.issues.print_issues`. Il lit `DECKDOCK_VERSION`, `"dev"` par défaut.
- [ ] **Step 3 : lignes `$schema` relatives.** `deckdock.yaml` : `# yaml-language-server: $schema=./schema/source.schema.json`. `cards/*.yaml` : `# yaml-language-server: $schema=../schema/source.schema.json`. Elles survivent à « Use this template ».
- [ ] **Step 4 : CI `.github/workflows/deck.yml`.**
  - Déclenchement : `pull_request` et `push` sur `main`.
  - Étapes : checkout → `astral-sh/setup-uv@v5` → `uv sync --locked` → `uv run --locked pytest -q` → step version (`echo "DECKDOCK_VERSION=$(date -u +%Y-%m-%dT%H:%M:%SZ)+${GITHUB_SHA::7}" >> "$GITHUB_ENV"`) → `uv run --locked compile` → `uses: NayanChauveau/deckdock/action@v2` avec `command: check` et `path: dist` → `actions/upload-artifact@v4` (`deck`, `dist/`).
  - Le step de publication commenté reste en place.
- [ ] **Step 5 : `.pre-commit-config.yaml`.** Hook local `uv run compile --validate-only`.
- [ ] **Step 6 : docs.**
  - **README :** démarrage (Use this template → éditer `deckdock.yaml` → ajouter des cartes → `uv run compile` en local, facultatif → pousser), « Ce dépôt contient son propre compilateur : modifiez-le librement », lien vers la spec `deckdock-1.md` du monorepo.
  - **AGENTS.md :** une section **« Changing the compiler »** (où vit chaque morceau, comment ajouter un type de carte : un notetype + un modèle de contenu + des tests ; la seule obligation est que `deckdock check` passe), et les commandes `uv run compile`, `uv run pytest`.
  - Toute mention de `deckdock init`, `build` ou `validate` est retirée.
  - Le `.gitignore` ajoute `.venv/`, `__pycache__/` et `.pytest_cache/`.
- [ ] **Step 7 : vérifier.**
  - `uv run pytest -q`, `uv run ruff check .`, `uv run ruff format --check .` et `uv run basedpyright` (0/0) sont verts.
  - **Non-régression :** avec `DECKDOCK_VERSION=fixed`, le `dist/` produit par `uv run compile` est identique octet par octet à `cd ../deckdock/cli && DECKDOCK_VERSION=fixed uv run deckdock build ../../deckdock-template --out <tmp>`. Lancer cette commande **avant** la Task 2, qui supprime `build` ; seul le champ `generator` peut différer.
  - Puis `uv run --project ../deckdock/cli deckdock check dist` doit passer.
- [ ] **Step 8 : commit(s)** sur `main` du template.

### Task 2 : alléger `deckdock` (format + check seulement)

**Repo :** `~/Documents/projets-perso/deckdock`, nouvelle branche `feat/format-only` depuis `main`.

- [ ] **Step 1 : supprimer** `cli/src/deckdock/{init.py,build/,source/,scaffold/}`, `spec/deckdock-source-1.md`, `spec/deckdock-source-1.schema.json`, et les tests qui ne concernent plus que le compilateur : `test_builder`, `test_markdown`, `test_notetypes`, `test_source_load`, `test_validate`, `test_init`, `test_template_repo_in_sync`, et dans `conftest` la fixture `make_project` si elle n'est plus utilisée.
- [ ] **Step 2 : `cli.py`.** Il ne garde que `--version` et `check [DIST]`. `pyproject.toml` : `dependencies = []`, version `0.2.0`, description « Reference checker and Python library for the deckdock/1 Anki deck format », sans `include` de package data. `uv lock` relancé.
- [ ] **Step 3 : garde-fou.** Ajouter le test `test_package_has_no_third_party_imports` : l'AST de **tous** les fichiers de `cli/src/deckdock` n'importe que la stdlib et `deckdock`. Garder `test_format_module_is_stdlib_only`, ou le remplacer.
- [ ] **Step 4 : Action.** La seule commande acceptée est `check`, et `path` vaut `dist` par défaut, ce qui lance `deckdock check "$path"`. Une autre commande provoque `::error::`. Mettre à jour `action/README.md`.
- [ ] **Step 5 : CI `cli.yml` e2e.**
  - Construire un dist depuis `spec/examples/valid/minimal.json` (`mkdir -p /tmp/dist/<edition>` puis y copier le fichier sous le nom `deck.json`, l'édition étant lue dans le fichier).
  - Lancer `uses: ./action` avec `path: /tmp/dist` et `deckdock-ref: local`.
  - Ajouter un second cas qui **doit échouer** sur un exemple invalide (`continue-on-error` + vérification de l'échec).
- [ ] **Step 6 : spec `deckdock-1.md`.**
  - Ajouter une section **« Writing your own compiler »** :
    - n'importe quel langage ou outil convient ;
    - obligations : GUID stables et uniques par fichier ; `deck.id`, codes d'édition et ids de notes permanents (les changer réinitialise l'historique des utilisateurs) ; noms de médias à plat ; `deckdock check` doit passer en strict ;
    - recommandation : en Python, utiliser `deckdock.format` (TypedDicts), `deckdock.guid.guid_for` (compatible genanki) et `check_dist` ;
    - lien vers `deckdock-template` comme compilateur d'exemple.
  - Retirer les renvois à `deckdock-source-1.md`.
- [ ] **Step 7 : README racine.** Le présenter comme « format + vérificateur », avec les commandes `check`, l'usage de l'Action, et le lien vers le template pour compiler.
- [ ] **Step 8 : vérifier.**
  - pytest, ruff check, ruff format --check et basedpyright 0/0 sont verts.
  - `uv run --isolated --no-dev --project cli deckdock check <dist valide>` passe.
  - Le template (Task 1) passe toujours tests et compilation avec la bibliothèque allégée, via la dépendance par chemin.
- [ ] **Step 9 : commit(s)** sur `feat/format-only`.

### Task 3 : revue finale des deux dépôts et correctifs

Revue de toute la branche (modèle le plus capable), suivie d'une seule vague de correctifs et d'une re-revue ciblée.

### Task 4 : publication `v2` (point d'arrêt, accord explicite de Nayan requis)

1. `deckdock` : fusionner `feat/format-only` dans `main`, pousser, poser le tag `v2` et le pousser. `v1` reste intact.
2. Template : remplacer la source uv par `deckdock = { git = "https://github.com/NayanChauveau/deckdock", tag = "v2", subdirectory = "cli" }`, lancer `uv lock`, vérifier les tests et la compilation, commiter, pousser.
3. Vérifier que la CI est verte des deux côtés, et que l'artefact `deck` du template contient `fr/deck.json`, `en/deck.json` et le média.
