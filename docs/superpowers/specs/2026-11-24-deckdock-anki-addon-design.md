# Plugin Anki DeckDock (projet 3) : design du MVP

*24 novembre 2026. S'appuie sur le design général (`2026-11-24-deckdock-mvp-design.md`, §8 compris) et sur le format `spec/deckdock-1.md`.*

## 1. Intention

Le plugin est **le premier client** du format `deck.json`. Dans Anki Desktop, il s'abonne à un deck publié et l'installe directement depuis son `deck.json`, sans apkg ni boîte d'import. Il applique ensuite les mises à jour en gardant les révisions, et sans jamais écraser une modification locale sans prévenir.

Le MVP fait peu de choses, mais il les fait vraiment. Il se teste avec le deck Hello World de `deckdock-template`.

**Boussole long terme (Nayan).** Un jour viendront nos propres applications de révision, mobile et ordinateur : libres, gratuites, modernes, avec le hub intégré et extensibles par des plugins. Les extensions Anki ne fonctionnent que sur ordinateur, ce qui fait un mur pour les utilisateurs mobiles. Ce n'est pas un plan, mais ça impose trois règles dès maintenant :
1. le format et le futur hub restent indépendants d'Anki ;
2. le **moteur de décision** du plugin (qu'est-ce qui change, qu'est-ce qui est en conflit) est du Python pur, sur des données simples, sans import d'Anki : il pourra être réutilisé ou porté ;
3. seule une fine couche, l'**adaptateur Anki**, touche à la collection.

## 2. Objectifs, non-objectifs, anti-objectifs

**Objectifs du MVP**
- S'abonner à une **édition** d'un deck à partir de l'URL de son dépôt GitHub ou d'une **URL de base**.
- Vérifier les mises à jour au démarrage (au plus une fois toutes les 24 h) et à la demande.
- Montrer un **résumé avant d'appliquer**, puis appliquer en une seule opération Anki annulable.
- Créer et mettre à jour notetypes, decks, notes (par GUID) et médias. Les révisions ne sont jamais touchées.
- **Modifs locales, option 1** : une note modifiée localement depuis la dernière version reçue n'est pas mise à jour, et elle est signalée dans le résumé.
- Valider chaque `deck.json` avec `deckdock.format` (mode non strict) avant de toucher à la collection.

**Non-objectifs (feuille de route, dans l'ordre souhaité par Nayan)**
1. **La comparaison en trois versions** (version reçue avant, ma version, nouvelle version), avec trois choix : *garder ma version*, *prendre la nouvelle*, *garder ma version et ne plus jamais me demander* (ce qui protège la note). Le MVP stocke déjà la version reçue de chaque note pour que ça se branche sans rien refaire.
2. **Le compte sur le site du hub** : on s'abonne finement (decks, langues), et Anki télécharge tout automatiquement au démarrage.
3. **Propositions de modifications** depuis Anki, transformées en PR, et signalements transformés en issues.
4. **Mobile** : app compagnon Android via l'API d'AnkiDroid, ou nos propres applications (voir la boussole). La décision se prendra quand le hub aura des utilisateurs.
- Hors MVP également : publication sur AnkiWeb (installation par fichier `.ankiaddon`), migration des decks apkg de Nayan, changements cassants de notetype, déplacement de notes entre sous-decks, options de deck (`deck.options`).

**Anti-objectifs**
- Écraser une modification locale sans prévenir.
- Supprimer une note ou un historique de révision automatiquement.
- Dépendre de l'API GitHub, ce qui exposerait aux limites de débit et nous lierait à GitHub : le plugin ne lit que des fichiers servis par HTTPS.
- Toucher au Deck Manager existant : ce sont deux extensions séparées.

## 3. Approches

| Option | Verdict |
|---|---|
| **Extension Python qui applique le JSON via l'API de collection d'Anki** | **Retenue.** C'est la seule voie native, sans dépendance |
| Passer par AnkiConnect | Écartée : exige une autre extension et une API locale |
| Regénérer un apkg et l'importer | Écartée : ramène la boîte d'import et l'apkg, que le projet veut supprimer |

**Source des decks sans hub (décision de Nayan) : une branche `dist`.** La CI du dépôt de deck pousse `dist/` sur une branche `dist`. Le plugin s'abonne à une **URL de base d'édition**, qui contient `deck.json` et `media/<nom>`. Le jour où le hub existera, il fournira d'autres URLs de base, et le plugin ne changera pas.

## 4. Où vit le code

- **Code :** `deckdock/addon/` dans le monorepo, sous licence AGPL-3.0-or-later.
- **Python et Anki :** Python ≥ 3.13, Anki ≥ 26.09 (`min_point_version 260900`, comme le Deck Manager).
- **Bibliothèque embarquée.** La bibliothèque `deckdock` (`format/`, `guid.py`, `issues.py`, `__init__.py`) est **copiée dans le paquet au moment du build**, dans `deckdock_addon/vendor/deckdock/`. Ça marche parce qu'elle est stdlib-only. Un test vérifie que la copie embarquée est identique à `cli/src/deckdock`.
- **Code repris du Deck Manager** (adapté, jamais importé depuis `anki-deckdock`) :
  - téléchargement sécurisé : plafonds de taille, annulation, HTTPS uniquement ;
  - ouverture de l'import en arrière-plan avec `QueryOp` / `CollectionOp` ;
  - squelette de la fenêtre ;
  - chaînes FR/EN : l'interface suit la langue d'Anki, en français si Anki est en français, en anglais sinon.
- **Paquet :** `.ankiaddon` produit par la CI du monorepo. Nom affiché « DeckDock », paquet `deckdock_addon`.

**Découpage interne :**

```
addon/
  src/deckdock_addon/
    __init__.py          # point d'entrée Anki (n'importe aqt que si présent)
    vendor/deckdock/     # copie au build, pas commitée (ou commitée + test d'égalité ; au builder de choisir)
    sources.py           # URL → URL de base, lecture d'index.json et de deck.json (HTTP + ETag), médias
    store.py             # abonnements (config de collection) + empreintes reçues (dossier des médias) + versions reçues (fichiers du profil)
    engine.py            # MOTEUR PUR : (deck reçu, état local, versions reçues) → plan d'actions + résumé
    adapter.py           # ADAPTATEUR ANKI : lit l'état local, exécute un plan dans une opération annulable
    ui.py, strings.py    # fenêtre, dialogues, textes FR/EN
  tests/                 # moteur et sources sans Anki ; adaptateur avec le paquet PyPI `anki` (Collection temporaire)
```

## 5. Comportement détaillé

### 5.1 Publication côté dépôt de deck (modification de `deckdock-template`)

- **Déclenchement.** Sur un push vers `main` uniquement (jamais sur une PR), après `deckdock check`, la CI publie `dist/` sur la branche `dist`. C'est un **commit orphelin écrasé à chaque fois** : on ne garde pas d'historique des builds, pour que le dépôt ne gonfle pas avec les médias. Le job a la permission `contents: write`.
- **Index des éditions.** La CI ajoute à la racine de la branche un `index.json` :

  ```json
  {"format": "deckdock-index/1",
   "editions": [{"edition": "fr", "name": "…", "language": ["fr"], "version": "…"}]}
  ```

  Il est généré à partir des `*/deck.json`. `check_dist` ignore les fichiers à la racine. La spec `deckdock-1.md` gagne une courte section facultative, « Publishing layout », qui décrit `index.json` et la disposition `<base>/<edition>/deck.json` + `<base>/<edition>/media/<filename>`.
- **URL de base d'une édition GitHub :** `https://raw.githubusercontent.com/<owner>/<repo>/dist/<edition>/`.

### 5.2 S'abonner

- **Fenêtre Outils → DeckDock**, bouton **Ajouter**. On colle soit :
  - l'URL d'un dépôt GitHub (`https://github.com/<owner>/<repo>`) : le plugin lit `index.json` et propose les éditions dans une liste ;
  - une URL de base HTTPS d'édition (qui se termine par `/`) : le plugin lit directement `deck.json`.
- **Un abonnement = une édition.**
- **Refus :**
  - même `deck.id` et même édition déjà suivis ;
  - **une autre édition du même `deck.id` déjà suivie**, si les deux partagent des GUID. La spec l'interdit, puisqu'un GUID est unique dans toute une collection Anki. Le message propose de remplacer l'abonnement existant.
- Après l'ajout, on enchaîne immédiatement sur une vérification et le résumé d'installation.

### 5.3 Vérifier

- **Requête.** `GET <base>/deck.json`, avec `If-None-Match` si un ETag est connu. Une réponse 304 signifie qu'il n'y a rien de neuf.
- **Mise à jour disponible** si `deck.version` diffère de la version installée. La version est une chaîne opaque, on ne la trie pas.
- **Fréquence.** Au démarrage du profil, en arrière-plan, au plus une fois par 24 h et par abonnement. Le bouton **Vérifier** ignore ce délai.
- **Erreurs** (hors ligne, 404, JSON invalide, `check_deck` en échec, taille dépassée) : elles s'affichent dans la colonne d'état et ne bloquent jamais Anki.
- **Plafonds :**
  - `deck.json` : 64 Mio ;
  - médias : ceux du format (10 Mio par fichier, 500 Mio par édition) ;
  - redirections HTTPS seulement, sans changer de schéma.

### 5.4 Plan et résumé (moteur pur)

**Entrées du moteur :**
- le `deck.json` reçu, déjà validé ;
- l'état local des notes de l'abonnement (GUID → champs, tags, note existante ou non) ;
- les **versions reçues** de la dernière application (GUID → champs et tags tels que reçus) ;
- l'état local des notetypes de l'abonnement.

**Règles, par note du deck reçu :**

La détection repose sur l'**empreinte reçue** de chaque note : un hash court des champs tels que reçus, avec les noms de médias d'origine. Elle est **synchronisée** par un fichier du dossier des médias, que la synchronisation des médias d'AnkiWeb recopie (§5.6). Un second ordinateur sait donc lui aussi ce qui a été reçu.

| Situation | Action |
|---|---|
| GUID inconnu de l'abonnement et absent de la collection | **Créer** la note dans `<racine>::<deck>` |
| GUID connu de l'abonnement (empreinte reçue existante) mais absent de la collection | **Ne pas recréer** : l'utilisateur l'a supprimée. La signaler comme « supprimée par toi » |
| Présent, et l'empreinte des champs locaux est égale à l'empreinte reçue (pas de modif locale) | **Mettre à jour** les champs si la nouvelle version diffère, sinon rien |
| Présent, et l'empreinte des champs locaux diffère de l'empreinte reçue (modif locale) | **Ne rien toucher**, et signaler la note comme « modifiée par toi » |
| Présent, mais sans empreinte reçue (note déjà là avant l'abonnement, par exemple un ancien import apkg) | Si son notetype n'est pas celui que l'abonnement gère pour cette note : **conflit « note déjà présente ailleurs »**, la note n'est pas touchée. Sinon : si les champs locaux sont égaux aux nouveaux, rien, et on enregistre l'empreinte ; sinon conflit, la note n'est pas touchée et elle est signalée |
| GUID présent dans les empreintes reçues mais absent du nouveau deck | **Retirer** : ajouter le tag `DeckDock::Deleted`, sans jamais supprimer |

Les notes en conflit restent signalées à chaque mise à jour tant qu'elles diffèrent. Leur résolution (garder, prendre, ne plus demander) fait partie de la comparaison en trois versions de la feuille de route. Avant de créer une note, l'adaptateur **vérifie lui-même** que le GUID est libre, car `col.add_note` ne l'impose pas.

- **Tags.** On ne compare pas les tags pour détecter une modif locale. Les tags de l'utilisateur (`marked`, `leech`, les siens) ne comptent donc pas comme une modification. À la mise à jour, les tags venant du deck remplacent les tags *précédemment reçus*, et ceux ajoutés par l'utilisateur sont conservés.
- **Sous-decks.** Les nouvelles notes vont dans le chemin indiqué. Les notes existantes ne sont **pas déplacées**, l'utilisateur ayant pu ranger ses cartes autrement.

**Règles pour les notetypes**, par notetype utilisé :

| Situation | Action |
|---|---|
| Inconnu localement | **Créer** le notetype et mémoriser la correspondance `id` → id Anki dans l'abonnement. Avec `anki_id`, réutiliser ce notetype s'il existe, sinon le créer avec cet id (voir les notes d'API). Nom Anki : `<deck.name> (<édition>) · <notetype.name>`, car Anki renomme automatiquement les doublons de nom. Ensuite, on retrouve le notetype par son id mémorisé, jamais par son nom |
| Connu, **même structure** : mêmes champs dans le même ordre, même nombre de templates, même `kind` | **Mettre à jour** les templates (associés **par position** : noms, recto, verso) et le CSS si changés |
| **Champ(s) ajouté(s) à la fin**, le reste de la structure étant identique | **Accepté avec confirmation** (comme AnkiHub). Le résumé affiche un avertissement : « Cette mise à jour ajoute un champ au type de carte *X*. Anki demandera une synchronisation complète : synchronise d'abord tes autres appareils (téléphone, tablette), puis confirme. » Il propose deux boutons, **Confirmer et appliquer** et **Plus tard**. Sans confirmation, l'abonnement reste sur l'ancienne version. Les champs sont ajoutés, puis les templates et le CSS sont mis à jour |
| **Autre changement de structure** : champ supprimé, renommé ou réordonné ; template ajouté ou supprimé ; `kind` changé | **Refuser toute la mise à jour** de l'abonnement, avec un message clair (« changement de structure non pris en charge par cette version de DeckDock »). La suppression d'un template supprime ses cartes et leur historique, et un renommage est indiscernable d'une suppression suivie d'un ajout |

Si l'utilisateur a modifié lui-même les templates d'un notetype géré par DeckDock, le MVP **écrase** les templates et le CSS. Le résumé le dit, et la protection des templates fera partie de la feuille de route.

**Résumé affiché** : « *Nom du deck (fr)* — 3 nouvelles, 5 mises à jour, 1 retirée, 2 modifiées par toi (non mises à jour), notetypes : 1 mis à jour », suivi de la liste dépliable des notes modifiées localement (début du premier champ, avec un lien « Ouvrir dans le navigateur » ; Anki n'a pas de recherche sur le GUID, donc au clic le plugin retrouve les ids des notes par leur GUID et recherche `nid:…` ; les notes supprimées par l'utilisateur n'ont rien à montrer et sont ignorées). Les boutons sont **Appliquer** et **Plus tard**.

### 5.5 Appliquer (adaptateur Anki)

- **Médias en premier, hors de l'opération sur la collection.**
  - Le plugin **n'écrase jamais** un fichier du dossier média : un autre deck peut utiliser le même nom.
  - Chaque abonnement garde une **table des médias** (synchronisée, §5.6) : nom d'origine → (sha256 reçu, nom local dans Anki).
  - Seuls les médias absents de la table, ou dont le sha256 reçu a changé, sont téléchargés depuis `<base>/media/<nom encodé>`. Le sha256 et la taille sont vérifiés.
  - L'écriture passe par `col.media.write_data`. Anki renvoie le même nom si le contenu est identique, et un autre nom (`nom-<sha1>.ext`) si un fichier différent porte déjà ce nom. C'est **toujours** le cas quand une image change de contenu.
  - Le nom local renvoyé est enregistré dans la table, et les références sont réécrites (nom d'origine → nom local) dans **les champs, les templates et le CSS** que le plugin écrit pour cette édition.
  - Les empreintes reçues sont calculées sur les **noms d'origine**. Pour comparer, on remplace dans les champs locaux les noms locaux par les noms d'origine, ce qui évite qu'une note avec image paraisse « modifiée par toi ».
  - Si un téléchargement échoue, rien n'est appliqué.
- **Une seule opération annulable** (`CollectionOp`, entrée d'annulation « DeckDock : mise à jour de *nom* ») : notetypes, decks, puis notes. Les nouvelles notes reçoivent le GUID imposé.
- **Après succès :**
  - on enregistre les versions reçues des notes effectivement appliquées ou confirmées identiques ;
  - les notes en conflit gardent leur ancienne version reçue, pour pouvoir être résolues plus tard ;
  - on met à jour la version installée et l'ETag.
- **Rien n'est jamais supprimé**, ni note, ni carte, ni média.
- **Deck racine.** Il est créé avec `deck.name` et son id Anki est mémorisé. Si l'utilisateur le renomme, le plugin suit l'id. Avec `deck.anki_id`, on réutilise ce deck s'il existe. Sinon on le crée avec un nouvel id : Anki n'accepte pas d'id imposé pour un deck.

**Notes d'API, vérifiées sur `anki` 26.9.4 :**
- **Notetype avec id imposé :** `col.models.update(nt, preserve_usn=True)` après avoir fixé `nt["id"]`. `models.add` ou `add_dict` avec un id non nul font planter Anki.
- **GUID :** fixer `note.guid` avant `col.add_note` fonctionne. L'unicité n'est pas vérifiée par Anki, c'est à l'adaptateur de le faire.
- **Annulation :** une seule entrée d'annulation (`add_custom_undo_entry` + `merge_undo_entries`) couvrant notetypes, decks et notes est bien annulée en entier par `col.undo()`.
- **Sans changement de schéma :** modifier le texte d'un template ou le CSS ne change pas `col.scm`. Ajouter un champ ou un template le change, d'où le refus des changements de structure.

### 5.6 Stockage local

- **Abonnements (synchronisés).** Dans la config de la collection, clé `deckdock` (JSON versionné, comme le Deck Manager), ce qui les synchronise via AnkiWeb. Pour chaque abonnement :
  - identité et source : `id`, `source_url` (dépôt ou base), `base_url`, `deck_id`, `edition`, `name` ;
  - suivi : `installed_version`, `etag`, `last_checked_at`, `last_error` ;
  - correspondances : `root_deck_anki_id`, `notetype_ids` (slug → id Anki), `media` (nom d'origine → sha256 reçu et nom local).

  La config reste petite (quelques Ko) : Anki l'envoie en entier à chaque synchronisation.
- **Empreintes reçues (synchronisées).** Dans le dossier des médias de la collection : `_deckdock_<deck_id>_<edition>.json`, au format `deckdock-received/1`. Pour chaque version installée, on garde un instantané `received` (GUID → empreinte reçue : un hash court des champs reçus et la liste des tags reçus). `latest` désigne le dernier instantané écrit, et on n'en garde que deux : celui qui vient d'être écrit et celui de la version installée juste avant (la base de la mise à jour). La synchronisation des médias d'AnkiWeb recopie ce fichier, et « Vérifier les médias » le garde parce que son nom commence par `_`. C'est de l'ordre de quelques centaines de Ko pour 10 000 notes. Un second ordinateur reconnaît donc les modifs locales, les suppressions et les retraits exactement comme le premier.
  - Le fichier est lu avant chaque plan, avec l'instantané de `installed_version` (à défaut `latest`). Un abonnement pas encore installé (`installed_version` vide) prend l'instantané `latest` du fichier s'il existe : c'est la base laissée par un abonnement retiré de la même édition. Sans fichier, il n'a rien reçu. Exception : si le fichier indique (`first_install`) que c'est cet abonnement-là qui a fait la première installation, c'est que cette installation a été annulée, et il repart de l'instantané dont elle était partie (ou de rien). Si un abonnement installé n'a pas de fichier utilisable (absent, illisible, d'un autre deck, ou sans instantané), la synchronisation des médias ne l'a sans doute pas encore apporté : le plan est bloqué avec le message « Les données de suivi de ce deck ne sont pas encore arrivées sur cet ordinateur. Synchronise Anki (médias compris), puis réessaie. » Planifier sans base recréerait les notes supprimées par l'utilisateur. Il est écrit après une application réussie, hors de l'étape d'annulation, et seulement si son contenu change. Si l'écriture échoue, la mise à jour reste faite et l'erreur est journalisée.
  - **Tolérance au catalogue en retard.** Si l'empreinte d'une note locale diffère de celle de l'instantané installé mais égale celle de l'instantané `latest`, la note est considérée comme non modifiée, avec l'entrée de `latest` comme base. Cela couvre un catalogue synchronisé qui indique une version plus ancienne que celle appliquée sur un autre ordinateur.
  - Annuler une mise à jour rétablit `installed_version` dans la config mais pas le fichier ; l'instantané de la version précédente sert alors de base, d'où une clé par version. Garder la base (et non le `latest` précédent) couvre aussi deux annulations successives.
  - Le fichier est rattaché au deck et à l'édition, pas à l'abonnement : retirer puis rajouter la même édition retrouve sa base (les notes supprimées par l'utilisateur ne sont pas recréées, ses notes modifiées restent « modifiées par toi »). Retirer un abonnement ne le supprime pas. Une première installation enregistre `first_install` (id de l'abonnement et version de départ, gardée comme base), pour qu'annuler cette installation puis la refaire recrée bien les notes.
- **Versions reçues complètes (locales).** Dans le dossier du profil : `<profil>/deckdock/<abonnement>.json` (GUID → champs reçus en entier). Elles ne servent qu'à la future comparaison en trois versions, et leur absence ne gêne jamais le MVP.
- **Retirer un abonnement** : on arrête le suivi et on supprime le fichier de versions reçues. Le deck et les notes restent dans Anki.

### 5.7 Interface

**Fenêtre principale (Outils → DeckDock) :**

```
 Deck              Édition  Version              État                 [Ajouter]
 Mon premier deck  fr       2026-11-24T…+a094cc5  À jour               [Vérifier]
 Mon premier deck* en       …                     Mise à jour dispo.   [Appliquer]
                                                                       [Ouvrir la source]
                                                                       [Retirer]
```

- **Dialogue d'ajout** : un champ URL, puis une liste des éditions.
- **Dialogue de résumé** : voir §5.4.
- **Au démarrage**, si des mises à jour sont disponibles, le dialogue de résumé s'ouvre (une section par abonnement), avec **Appliquer** ou **Plus tard**.

## 6. Tests et critère de réussite

- **Moteur :** tests unitaires purs pour toutes les lignes des tableaux du §5.4, plus les tags et le cas « aucune version reçue ».
- **Adaptateur :** tests d'intégration avec le paquet PyPI `anki` (26.9.x) sur une collection temporaire. On installe le Hello World, on applique une mise à jour qui modifie, ajoute et retire des notes, on vérifie que les révisions d'une carte sont intactes, qu'une note modifiée localement n'est pas touchée et que l'opération est annulable.
- **Sources :** HTTP simulé (ETag, 304, erreurs, tailles, redirections).
- **Critère de réussite (manuel, dans Anki Desktop 26.09) :**
  1. on installe le `.ankiaddon` ;
  2. on colle `https://github.com/NayanChauveau/deckdock-template` et on choisit `fr` : les 3 cartes apparaissent ;
  3. on révise une carte, on modifie une autre carte dans Anki, puis on pousse une modification des deux dans le template ;
  4. on clique **Vérifier** puis **Appliquer** : la carte révisée est mise à jour et garde son historique, la carte modifiée localement est signalée et n'est pas touchée.

## 7. Laissé au builder

- Structure exacte des classes et fonctions, dans le respect du découpage moteur pur / adaptateur.
- Copie de la bibliothèque embarquée : commitée avec un test d'égalité, ou générée au build.
- Détails visuels des dialogues.
- Méthode exacte pour créer un notetype avec un id imposé (API backend d'Anki).

## 8. Décisions prises par l'auteur du design, à vérifier

1. Une extension **séparée** du Deck Manager, dans `deckdock/addon/`, installée par fichier (pas encore sur AnkiWeb).
2. La branche `dist` est un **commit orphelin écrasé** à chaque push sur `main`, avec un `index.json` des éditions.
3. Les **tags ne comptent pas** comme modif locale, et les tags de l'utilisateur sont conservés.
4. Les **notes existantes ne sont pas déplacées** de sous-deck.
5. Les **templates et le CSS sont écrasés** à la mise à jour, même s'ils ont été modifiés localement (et c'est signalé). Les templates sont associés par position.
6. *(décidé avec Nayan)* **L'ajout de champs à la fin est accepté après confirmation explicite** de la synchronisation complète, comme chez AnkiHub. **Tout autre changement de structure est refusé** (champ supprimé, renommé ou réordonné, template ajouté ou supprimé, `kind` changé), pour ne jamais supprimer de cartes ni perdre de contenu. Les règles sont documentées pour les auteurs et leurs agents dans `spec/deckdock-1.md` (« Changing a published notetype ») et dans l'AGENTS.md du template.
7. **Une empreinte synchronisée** de chaque note reçue (dans un fichier du dossier des médias) permet de fonctionner proprement sur plusieurs ordinateurs. Les versions complètes, réservées à la future comparaison en trois versions, restent locales.
8. Une **note supprimée par l'utilisateur n'est jamais recréée**.
9. Une **note déjà présente avec le même GUID** mais hors de l'abonnement est mise en conflit, jamais adoptée de force.
10. **Les médias ne sont jamais écrasés.** Une image qui change reçoit un nouveau nom local, et les références sont réécrites dans les champs, les templates et le CSS.
11. Les **notetypes portent le nom du deck et de l'édition**, et sont toujours retrouvés par leur id.
