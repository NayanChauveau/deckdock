# DeckDock : design du MVP

*24 novembre 2026. Contexte et études concurrentielles (AnkiHub, AnkiCollab) : [docs/research/2026-11-24-analyse-ankihub-ankicollab.md](../../research/2026-11-24-analyse-ankihub-ankicollab.md).*

## 1. Intention

Amener à Anki l'efficacité du développement logiciel, et en particulier du développement agentique : les cartes sont du code (YAML, générateurs, données), relues et produites avec des agents, buildées et publiées par la CI GitHub. Un **hub central gratuit et ouvert** recense les decks et les distribue. Une **extension Anki** applique les mises à jour automatiquement, sans apkg ni boîte d'import.

C'est plus simple qu'AnkiHub (gratuit, pas d'abonnement pour partager, publication depuis la CI) et plus efficace qu'AnkiCollab, où relecture, rôles et historique sont faits maison au lieu de s'appuyer sur Git et GitHub.

**Premier utilisateur : le porteur du projet lui-même**, avec ses decks existants. Le MVP doit d'abord résoudre son flux réel :

| Deck | Dépôt | Construction actuelle |
|---|---|---|
| Vin, WSET 3 | `wine-theory-anki` | QCM, basic et cloze bilingues en YAML |
| Géographie française | `anki-deck-french-geography` | règles de génération appliquées à du GeoJSON |
| Plongée | `diving-anki` | YAML à schéma propre |

Les trois produisent aujourd'hui des apkg avec genanki, et leurs GUID sont stables (`genanki.guid_for(namespace, card_id, lang)`).

## 2. Objectifs, non-objectifs, anti-objectifs

**Objectifs du MVP (projets 1 à 3)**
- Un **format JSON de deck compilé**, versionné et spécifié par un JSON Schema : le contrat entre toutes les pièces.
- Un **dépôt modèle** qu'on clone avec « Use this template » : on écrit des cartes en YAML simple, et la validation, le build et la publication sont automatiques.
- Un **hub** qui reçoit les decks compilés poussés par la CI (token dans les secrets GitHub), tient l'annuaire public et sert les mises à jour.
- Une **extension Anki** connectée au hub, qui crée et met à jour les notes directement depuis le JSON, préserve la planification et ne détruit jamais une modification locale sans prévenir.

**Non-objectifs (après le MVP, de façon itérative)**
- Propositions de modifications depuis Anki transformées en PR, signalements transformés en issues.
- Champs protégés gérés par le mainteneur, groupes de tags optionnels, overlays, forks avec suivi de l'amont.
- Publication sans GitHub (upload web, publication depuis Anki), decks privés, organisations.
- IA (recherche, bot de relecture), statistiques.
- Mobile natif : comme AnkiHub et AnkiCollab, on passe par la synchro AnkiWeb.

**Anti-objectifs (le projet est raté s'il en arrive là, même s'il « marche »)**
- Imposer un format source unique, ce qui casserait les générateurs comme celui de la géographie.
- Écraser une modification locale de l'utilisateur sans prévenir (l'erreur d'AnkiCollab).
- Réinventer ce que GitHub donne gratuitement : relecture, discussion, rôles, historique.
- Exiger un compte pour simplement s'abonner à un deck public.
- Retomber dans « télécharger un apkg et passer par la boîte d'import ».

## 3. Architecture d'ensemble

```
 Dépôt d'un deck (GitHub)                    Hub DeckDock                     Anki (extension)
 ───────────────────────                     ────────────                     ────────────────
 sources libres (YAML, règles, données)
   └─ générateur (le builder DeckDock
      ou un générateur maison)
        └─ dist/<édition>/deck.json + media/
             └─ CI : deckdock push ──token──▶ API de publication
                                              stockage des versions          ◀── synchro
                                              annuaire public ────────────────▶ application
                                                                                note par note
```

**Quatre pièces :**
0. **Spec** du format compilé (`deckdock/1`) et son JSON Schema.
1. **Outil `deckdock`** (CLI Python) : `init`, `validate`, `build`, `check`, puis `push` au projet 2. La **GitHub Action** est une fine enveloppe autour de cet outil.
2. **Hub** : API de publication, annuaire, synchro, site.
3. **Extension Anki** v2, qui remplace le Deck Manager actuel (code dans `anki-deckdock`, publié sur AnkiWeb sous l'id 932198090).

**Ordre de livraison :**
- **Projet 1** : spec + outil + dépôt modèle. C'est le sujet de ce document, détaillé en section 5.
- **Projet 2** : le hub v1.
- **Projet 3** : l'extension v2.

Les projets 2 et 3 auront chacun leur propre design, construit sur ce contrat.

## 4. Approches retenues

### 4.1 Ce que reçoit le hub

| Option | Résumé | Verdict |
|---|---|---|
| **A. Deck compilé en JSON** | Chaque dépôt garde son générateur et produit un JSON standard. Un format YAML simple de référence est fourni dans le dépôt modèle | **Retenue.** C'est la seule option qui garde intacts les générateurs comme celui de la géographie tout en supprimant l'apkg |
| B. YAML universel lu par le hub | Le plus simple pour un débutant | Écartée : tue les générateurs et devient une usine à gaz |
| C. apkg comme format d'échange | Compatible avec l'existant | Écartée : binaire, garde la boîte d'import |

L'apkg n'est **pas** produit, même pendant la transition.

### 4.2 Organisation des dépôts

| Option | Verdict |
|---|---|
| **A. Monorepo `deckdock` + dépôt `deckdock-template` à part** | **Retenue.** Un changement de format touche la spec, le builder, le hub et l'extension en un seul commit. Le code partagé s'embarque facilement dans l'extension, qui ne peut pas installer de dépendances pip. Le dépôt modèle doit être un dépôt entier pour le bouton « Use this template », et il sert de test de bout en bout de ce qui est publié |
| B. Un dépôt par pièce | Écartée : versions croisées ingérables en solo |
| C. Un seul dépôt avec `deckdock init` à la place du modèle | Écartée comme seule voie, mais `deckdock init` existe *en plus* |

Les deux dépôts sont créés en local à côté de `anki-deckdock` :
- `~/Documents/projets-perso/deckdock`
- `~/Documents/projets-perso/deckdock-template`

L'ancien dépôt `anki-deck-manager` sera archivé avec un lien vers le nouveau quand l'extension v2 sera publiée.

**Disposition du monorepo :**

```
deckdock/
  spec/          # format deckdock/1 : doc + JSON Schema + exemples valides et invalides
  cli/           # package Python « deckdock » (modèles, validation, builder YAML, CLI)
  action/        # GitHub Action composite (action.yml) qui appelle la CLI
  hub/           # projet 2
  addon/         # projet 3 (migration du code d'anki-deckdock)
  docs/          # specs, recherches, doc utilisateur
```

**Licences par dossier :**
- `spec/`, `cli/` et `action/` : MIT ;
- `hub/` et `addon/` : AGPL-3.0-or-later ;
- `deckdock-template` : MIT pour l'outillage, et un contenu d'exemple en CC0.

## 5. Projet 1 en détail : spec, outil et dépôt modèle

### 5.1 Format compilé `deckdock/1`

**Un fichier par édition** (une édition = une langue ou une variante d'un même deck), avec ses médias à côté :

```
dist/
  fr/
    deck.json
    media/
      carte-bordeaux.png
  en/
    deck.json
    media/…
```

**Exemple de `deck.json` :**

```json
{
  "format": "deckdock/1",
  "deck": {
    "id": "wine-theory",
    "edition": "fr",
    "name": "Théorie du vin (WSET 3)",
    "description": "Markdown court",
    "language": "fr",
    "homepage": "https://github.com/…",
    "license": "CC-BY-SA-4.0",
    "version": "2026-11-24T10:12:00Z+3f2a9c1",
    "generator": "deckdock 0.1.0"
  },
  "notetypes": [
    {
      "id": "mcq",
      "name": "DeckDock QCM",
      "kind": "standard",
      "fields": ["Question", "Choix", "Explication"],
      "templates": [
        { "name": "Carte 1", "front": "<html…>", "back": "<html…>" }
      ],
      "css": "…"
    }
  ],
  "notes": [
    {
      "guid": "a1B2c3D4e5",
      "notetype": "mcq",
      "deck": "France::Bordeaux",
      "fields": { "Question": "<p>…</p>", "Choix": "…", "Explication": "…" },
      "tags": ["france", "bordeaux"]
    }
  ],
  "media": [
    { "filename": "carte-bordeaux.png", "sha256": "…", "size": 48213 }
  ]
}
```

**Règles du format :**

- **Identité.**
  - `deck.id` est un slug choisi par l'auteur, stable pour toujours. Le couple (`deck.id`, `deck.edition`) identifie un flux de mises à jour. L'unicité globale (préfixe propriétaire, etc.) sera attribuée par le hub au projet 2.
  - `notes[].guid` est le GUID Anki : chaîne non vide, unique dans le fichier, **stable entre versions**. C'est la clé de mise à jour, et la conserver préserve la planification.
  - `notetypes[].id` est un slug stable propre au deck. Les ids numériques Anki seront dérivés côté extension (projet 3).
- **Champs.**
  - `fields` est un objet dont les clés sont exactement les champs du notetype.
  - Les valeurs sont du **HTML** : Markdown et autres sources sont déjà rendus au build.
  - L'ordre des champs est celui de `notetypes[].fields`.
- **Notetypes.**
  - `kind` vaut `standard` ou `cloze`.
  - Les templates utilisent la syntaxe Anki (`{{Champ}}`, `{{cloze:Texte}}`, `{{FrontSide}}`).
  - Le JS est autorisé dans les templates, ce que le QCM mélangé exige.
- **Sous-decks.** `deck` est le chemin relatif au deck racine, avec `::` comme séparateur. Il peut être vide (`""`), ce qui désigne la racine. Le nom affiché de la racine est `deck.name`.
- **Médias.**
  - Chaque fichier référencé dans un champ, un template ou le CSS doit être listé dans `media`, et chaque fichier listé doit exister dans `media/`.
  - Les noms sont uniques dans l'édition et sans chemin.
  - `sha256` sert à la déduplication et à la vérification.
- **Version.** `deck.version` est une chaîne opaque générée par la CI (date ISO + sha court du commit). Aucun tag manuel. Le tri des versions est l'affaire du hub (ordre de réception).
- **Compatibilité.** `format` porte la version majeure. Un ajout de champ facultatif reste en `deckdock/1`, un changement cassant passe en `deckdock/2`. `deckdock check` refuse les clés inconnues au premier niveau de chaque objet, pour attraper les fautes de frappe.
- **Unicité des GUID.** Un GUID est unique **dans un fichier**. Le même GUID peut apparaître dans plusieurs éditions du même deck, comme le deck plongée, où un niveau combiné reprend les notes des niveaux N2 et N3. Dans une collection Anki, un GUID est unique globalement, donc l'extension (projet 3) empêchera de s'abonner à deux éditions qui partagent des GUID, ou proposera de basculer de l'une à l'autre.
- **Langues.** `deck.language` est une **liste** de codes BCP-47 : `["fr"]`, ou `["fr", "en"]` pour une édition bilingue. `deck.edition` est un slug libre (`fr`, `en`, `bilingual`, `n2`…).
- **Rattachement à l'existant (`anki_id`).** `notetypes[].anki_id` et `deck.anki_id` sont des entiers **facultatifs**. Quand ils sont fournis, l'extension réutilise exactement ce notetype et ce deck racine Anki. Ça permet aux decks déjà installés par apkg (ids genanki fixes) d'être repris sans changer de notetype. Sans eux, l'extension dérive les ids de façon déterministe. `notetypes[].name` et les noms de champs doivent alors rester identiques à l'existant.
- **Options de deck.** `deck.options` est **facultatif** et contient un preset d'étude (`new_per_day`, `reviews_per_day` ; d'autres clés pourront s'ajouter). L'extension l'applique seulement à la première installation et ne l'écrase jamais ensuite. C'est nécessaire pour le deck plongée, qui embarque aujourd'hui un preset.
- **Limites v1.** 50 000 notes par édition, 10 Mo par média, 500 Mo de médias par édition. Ces chiffres sont des garde-fous initiaux, ajustables.

La spec vit dans `spec/deckdock-1.md`, avec `spec/deckdock-1.schema.json` (généré depuis les modèles pydantic de `cli/` et commité) et `spec/examples/`.

### 5.2 Format YAML simple (dépôt modèle)

**`deckdock.yaml` à la racine :**

```yaml
# yaml-language-server: $schema=https://…/deckdock-source.schema.json
id: hello-deck
name:
  fr: Mon premier deck
  en: My first deck
description:
  fr: Un exemple.
  en: An example.
editions: [fr, en]        # une seule langue → editions: [fr]
license: CC0-1.0
```

**`cards/*.yaml`, un fichier par thème :**

```yaml
cards:
  - id: hello-001                 # permanent, kebab-case, jamais renommé
    type: basic                   # basic | reversed | cloze | mcq
    deck: Bases                   # sous-deck facultatif, "A::B"
    tags: [exemple]
    fr: { front: "Bonjour ?", back: "**Hello**" }
    en: { front: "Hello?", back: "**Bonjour**" }

  - id: hello-002
    type: cloze
    fr: { text: "La capitale de la France est {{c1::Paris}}." }

  - id: hello-003
    type: mcq
    fr:
      question: "2 + 2 ?"
      choices:
        - { text: "3" }
        - { text: "4", correct: true }
      explanation: "Arithmétique."
```

**Règles du format YAML :**
- **Édition mono-langue.** Les blocs de contenu peuvent être écrits directement sans clé de langue (`front:` / `back:` au niveau de la carte).
- **Carte absente d'une édition.** Une carte sans bloc pour une langue est omise de cette édition (comportement actuel du deck vin).
- **Contenu.**
  - Le contenu est en **Markdown** (CommonMark, HTML en ligne autorisé), rendu en HTML au build.
  - Les images s'écrivent `![](media/fichier.png)` et sont réécrites vers le nom de fichier Anki.
- **GUID.** Le GUID est dérivé de façon déterministe de (`deckdock.yaml:id`, `card.id`, édition), avec un algorithme documenté dans la spec du YAML.
- **Brouillons.** `status: draft` exclut une carte du build.
- **Notetypes fournis.** Ce sont les quatre notetypes DeckDock (basic, reversed, cloze, QCM avec choix mélangés), avec un style sobre, un mode sombre et des libellés traduits par édition.
- **Schéma.** Un JSON Schema du YAML source (`deckdock-source.schema.json`) assure l'autocomplétion et la validation dans l'éditeur.

### 5.3 CLI `deckdock`

| Commande | Rôle |
|---|---|
| `deckdock init [dossier]` | Génère un projet Hello World identique au dépôt modèle |
| `deckdock validate` | Valide les sources YAML : schéma, ids uniques et au bon format, médias présents, cloze bien formées, QCM avec exactement une bonne réponse. Messages avec fichier:ligne |
| `deckdock build [--out dist]` | YAML vers `dist/<édition>/deck.json` + `media/`. Build déterministe : mêmes sources, même sortie (hors `version`) |
| `deckdock check <dist>` | Valide n'importe quel deck compilé contre la spec, **quel que soit le générateur**. C'est la commande que les générateurs maison (vin, géographie, plongée) appellent dans leur CI |
| `deckdock push` | Projet 2 : envoie `dist/` au hub avec `DECKDOCK_TOKEN` |

- **Technique.** Python ≥ 3.13, `uv`, pydantic v2 (modèles, d'où sortent les JSON Schemas), PyYAML, une bibliothèque Markdown (choix du builder), pytest. Distribution : PyPI sous le nom `deckdock`, utilisable via `uvx deckdock`.
- **Bibliothèque réutilisable.** Les modèles du format compilé et `check` forment un module Python qu'on peut importer sans dépendances lourdes, pour qu'un générateur maison puisse construire le JSON avec ces modèles. L'extension (projet 3) embarquera ce même module.

### 5.4 Dépôt `deckdock-template`

```
deckdock.yaml
cards/hello.yaml               # 3 cartes : basic, cloze, QCM, en FR et EN
media/hello.png
AGENTS.md (+ CLAUDE.md → lien)  # comment ajouter et relire des cartes avec un agent
CONTENT_GUIDELINES.md          # règles de qualité des cartes
README.md                      # démarrage en 3 étapes, badge « Disponible sur DeckDock » (plus tard)
.github/
  workflows/deck.yml           # PR : validate + build + check + artefact ; main : idem + push (inactif tant que le hub n'existe pas)
  ISSUE_TEMPLATE/card-problem.yml
  PULL_REQUEST_TEMPLATE.md
.editorconfig
.pre-commit-config.yaml        # deckdock validate en local
```

- **Parcours cible.** « Use this template », éditer `deckdock.yaml`, ajouter des cartes, pousser. La CI est verte, et le JSON est disponible en artefact. Au projet 2, il suffit d'ajouter le secret `DECKDOCK_TOKEN` pour publier.
- **Version de l'outil.** Le workflow utilise une version **épinglée** de l'outil, via l'Action `uses: NayanChauveau/deckdock/action@v1` qui installe `deckdock`.

### 5.5 Migration des decks existants (fin du projet 1)

Les trois générateurs **ajoutent** une sortie `deckdock/1` (construite avec les modèles du module partagé) **à côté** de leur sortie genanki, puis lancent `deckdock check` en CI. Ils gardent :
- leurs GUID actuels ;
- leurs notetypes actuels, déclarés avec `anki_id` ;
- les ids de leur deck racine ;
- le preset d'options du deck plongée.

Les apkg et les releases GitHub continuent d'être publiés jusqu'à la sortie de l'extension v2, pour ne pas couper les mises à jour des abonnés actuels. genanki sera retiré au projet 3. Ce choix ne contredit pas la règle « pas d'apkg » : le builder YAML et le dépôt modèle n'en produisent jamais.

**Critère de réussite :** pour chaque deck et chaque édition, un script compare le JSON à l'apkg actuel. Il doit retrouver les mêmes GUID, les mêmes ids et noms de notetypes, les mêmes noms et le même ordre de champs, et les mêmes ids de deck racine.

## 6. Ce qui est laissé au builder

- Choix de la bibliothèque Markdown, structure interne du package, outils de lint et de typage (ruff et basedpyright, comme dans les decks existants).
- Algorithme exact de dérivation du GUID dans le builder YAML, tant qu'il est déterministe, documenté et produit des GUID compatibles Anki.
- Design visuel des quatre notetypes.
- Contenu exact de `AGENTS.md` et `CONTENT_GUIDELINES.md` (on peut partir de ceux des decks existants).
- Découpage des workflows CI du monorepo (lancement par dossier modifié).

## 7. Décisions de l'auteur du design, à vérifier en lisant

1. Un `deck.json` **par édition**, plutôt qu'un fichier multi-langues.
2. Champs en **HTML déjà rendu** dans le format compilé, avec le Markdown réservé au YAML source.
3. Sous-decks exprimés par un **chemin `::` sur chaque note**, plutôt qu'un arbre séparé.
4. **Version générée par la CI** (date + sha), sans tag manuel.
5. **Quatre types de cartes** dans le YAML simple : basic, reversed, cloze, QCM.
6. Licences : MIT pour la spec, l'outil et l'Action, AGPL pour le hub et l'extension, MIT/CC0 pour le dépôt modèle.
7. GUID unique par fichier, et pas entre éditions ; `deck.language` est une liste.
8. `anki_id` facultatifs sur les notetypes et le deck racine, pour reprendre les decks déjà installés par apkg.
9. `deck.options` facultatif, appliqué seulement à la première installation.
10. Les decks existants gardent leurs apkg à côté du JSON jusqu'à l'extension v2.
11. Hébergement : compte GitHub perso `NayanChauveau` (`NayanChauveau/deckdock`, `NayanChauveau/deckdock-template`). Le nom `deckdock` est libre sur PyPI.
