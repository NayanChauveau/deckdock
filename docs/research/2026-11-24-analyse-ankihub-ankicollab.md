# DeckDock face à AnkiHub : analyse et stratégie

*Analyse du 24 novembre 2026, faite à partir du code de ce dépôt et du code public de l'add-on AnkiHub (`AnkiHubSoftware/ankihub_addon`), de sa documentation communautaire et des forums Anki.*

---

## 1. En bref

- **Aujourd'hui, DeckDock est un « installateur d'apkg avec détection de version ».** Chaque client interroge lui-même l'API GitHub Releases, puis réimporte le paquet entier via la boîte d'import native d'Anki. Il n'y a ni serveur, ni compte, ni synchronisation au niveau des notes.
- **AnkiHub est une plateforme complète.** Elle offre une synchro incrémentale au niveau des notes, des champs protégés, des propositions de modifications depuis Anki avec une file de relecture, des tags optionnels, la gestion des suppressions, un catalogue web et des fonctions IA payantes. En revanche, elle est **fermée** : pas d'API publique, pas de webhooks, pas de Git, un abonnement payant même pour partager un deck entre camarades, et un verrouillage des gros decks (AnKing).
- **Ton intuition est la bonne.** Il faut un **hub central**, alimenté par **webhooks GitHub** (pas besoin de scraper GitHub chaque nuit). Les clients interrogent ce hub, plus GitHub directement. Le hub calcule des **deltas au niveau des notes**, et c'est ce qui débloque presque toutes les fonctions qui manquent.
- **Ce qui ferait gagner DeckDock :** **Git comme couche de collaboration**. Une proposition faite dans Anki devient une Pull Request, un merge déclenche une release, et la release est poussée aux abonnés. Ajoute à ça l'historique, le blame, les forks et la CI, que GitHub donne gratuitement. Et le tout ouvert et gratuit, avec une API publique : c'est exactement ce qu'AnkiHub ne fait pas et ce que la communauté réclame (cf. le fil « open interface for collaboration platforms » sur forums.ankiweb.net).

> ⚠️ **Contexte important.** D'après les forums Anki, AnkiHub reprend depuis février 2026 la gestion opérationnelle d'Anki : AnkiMobile 26.10 est présenté comme leur première release, et Anki a un « Sign in with AnkiHub » natif. Le concurrent est donc très bien placé. Le seul positionnement tenable est celui de **l'alternative ouverte, gratuite et branchée sur Git**, pas une copie.

---

## 2. Ce que fait DeckDock aujourd'hui

| Aspect | Implémentation actuelle |
|---|---|
| Source | URL `github.com/{owner}/{repo}/releases/download/{vX.Y.Z}/{file}.apkg` uniquement ([domain.py](../src/domain.py)) |
| Détection de MAJ | `GET /repos/{o}/{r}/releases/latest` par dépôt, au plus une fois par 24 h, avec ETag ([github.py](../src/github.py), [manager.py](../src/manager.py)). Mise à jour = tag différent, sans tri de versions |
| Livraison | Téléchargement de l'apkg **complet** (plafonné à 512 Mo), puis la boîte d'import native d'Anki ([runner.py](../src/runner.py), [importer.py](../src/importer.py)) |
| Fusion | Déléguée à l'importeur d'Anki : correspondance par GUID, options « mettre à jour les notes si plus récentes / toujours / jamais » |
| Suppressions | Aucune : les notes retirées du paquet restent chez l'utilisateur |
| Modifs locales | Écrasées si l'utilisateur choisit « toujours mettre à jour », sinon c'est la date de modification qui tranche. Pas de champ protégé |
| État | JSON dans la config de la collection ([store.py](../src/store.py)) |
| Comptes / serveur | Aucun |
| Qualité | Code propre, logique pure séparée de Qt, bien testée, sécurité réseau soignée (hôtes de redirection en liste blanche, taille plafonnée) |

**Limites structurelles du modèle « apkg + client direct » :**

1. **Rate limit GitHub.** Sans token, l'API autorise 60 requêtes par heure et par IP : ça tient pour 10 decks, mais ça casse dans une résidence étudiante ou derrière un NAT d'université.
2. **Tout retélécharger à chaque version** : un deck de 300 Mo de médias pour une faute de frappe corrigée.
3. **L'apkg est binaire**, donc impossible à diff ou à relire dans une PR. Git ne sert aujourd'hui que d'hébergeur de fichiers.
4. **Aucun canal retour** : l'utilisateur ne peut ni proposer une correction, ni signaler une erreur depuis Anki.
5. La boîte d'import et ses options laissent l'utilisateur **choisir mal** et écraser ses propres modifications.

---

## 3. Inventaire des écarts

Légende de priorité : **P0** = indispensable pour être crédible, **P1** = pour égaler AnkiHub, **P2** = pour le dépasser.

### 3.1 Synchronisation

| Fonctionnalité | AnkiHub | DeckDock | Prio |
|---|---|---|---|
| Synchro **incrémentale** au niveau des notes (`/updates?since=`) | ✅ JSON compressé et découpé, snapshot complet seulement au premier import | ❌ apkg complet | **P0** |
| IDs stables (note id, GUID, notetype id conservés à l'identique) | ✅ plus un UUID dans un champ `ankihub_id` | ⚠️ GUID via l'apkg uniquement | **P0** |
| **Champs protégés** (par note via des tags `…_Protect::Champ`, par deck via le web) | ✅ | ❌ | **P0** |
| **Tags protégés** (tags perso jamais retirés) | ✅ | ❌ | **P0** |
| Synchro silencieuse, sans boîte d'import | ✅ | ❌ boîte native à chaque fois | **P0** |
| Synchro auto au démarrage ou avant la synchro AnkiWeb | ✅ | ⚠️ vérification au démarrage, import manuel | P1 |
| Suppressions (tag `Deleted`, suppression seulement si la note n'a jamais été révisée) | ✅ | ❌ | P1 |
| Évolution des notetypes (templates, CSS, ajout ou renommage de champs) | ✅ | ⚠️ via l'importeur Anki (« merge notetypes ») | P1 |
| Médias incrémentaux, hashés, sur CDN | ✅ S3, conversion webp | ❌ dans l'apkg | P1 |
| « Réinitialiser mes modifs locales » | ✅ | ❌ | P1 |
| Sous-decks optionnels construits à partir de tags | ✅ | ❌ (structure de l'apkg imposée) | P2 |
| Presets de deck et FSRS gérés par le mainteneur | ✅ | ❌ | P2 |

### 3.2 Collaboration

| Fonctionnalité | AnkiHub | DeckDock | Prio |
|---|---|---|---|
| **Proposer une modification depuis l'éditeur Anki** (avec un type et une justification) | ✅ | ❌ | **P0** pour le pitch |
| Proposer une nouvelle note, ou une suppression | ✅ | ❌ | P1 |
| Propositions en masse depuis le navigateur | ✅ (avec des bugs signalés) | ❌ | P1 |
| File de relecture pour les mainteneurs (fusionner, rejeter avec motif, éditer, co-auteur) | ✅ web | ❌ → **ce sera une PR GitHub** | **P0** |
| Discussion par proposition | ✅ Discourse | ❌ → commentaires de PR | gratuit avec Git |
| Historique d'une note, attribution | ✅ par note | ❌ → `git log`, `git blame` | gratuit avec Git |
| Changelog de deck | ❌ (posts écrits à la main) | ⚠️ notes de release GitHub | P1, à générer automatiquement |
| Signaler une erreur sans la corriger | ⚠️ via « Content error » | ❌ → Issue GitHub | P1 |

### 3.3 Personnalisation

| Fonctionnalité | AnkiHub | DeckDock | Prio |
|---|---|---|---|
| **Groupes de tags optionnels** (tags de cours, de ressources tierces, maintenus par d'autres) | ✅ « deck extensions » | ❌ | P1 |
| Choix des sous-decks à installer | ✅ | ❌ | P2 |
| Désactiver les médias sur certains champs | ✅ | ❌ | P2 |

### 3.4 Découverte et web

| Fonctionnalité | AnkiHub | DeckDock | Prio |
|---|---|---|---|
| Catalogue web avec recherche | ✅ mais **derrière une connexion** | ❌ | **P0** (le site web) |
| Page de deck (description, aperçu des notes, stats) | ⚠️ connexion requise | ❌ | P0 |
| Notes, abonnés, popularité | ? (non vérifiable) | ❌ | P1 |
| Recherche plein texte dans les notes de tous les decks | ⚠️ par deck | ❌ | P2, différenciant |
| Ajouter depuis le web en un clic (`deckdock://` ou code à coller) | ✅ via l'add-on | ❌ URL longue et stricte | P0 |
| Notes et avis | ❌ apparemment | ❌ | P2 |

### 3.5 Créateurs et organisations

| Fonctionnalité | AnkiHub | DeckDock | Prio |
|---|---|---|---|
| Créer et publier un deck depuis Anki | ✅ | ❌ (il faut savoir faire une release GitHub) | **P0** |
| Decks privés | ✅ | ❌ (dépôts publics seulement) | P1 (dépôt privé + GitHub App) |
| Rôles propriétaire / mainteneur | ✅ | ⚠️ ce sont les droits GitHub | gratuit avec Git |
| Organisations (places payées, abonnement automatique) | ✅ | ❌ → organisations GitHub | P2 |
| Statistiques pour les créateurs | ❓ (données collectées mais non exposées) | ❌ | P2, opt-in |

### 3.6 IA et mobile

| Fonctionnalité | AnkiHub | DeckDock | Prio |
|---|---|---|---|
| Smart Search : un cours ou un PDF en entrée, les cartes correspondantes en sortie | ✅ Premium | ❌ | P2 |
| Chatbot sur le deck | ✅ Premium | ❌ | P2 |
| Mobile natif | ❌ (passe par la synchro AnkiWeb) | ❌ (pareil) | match nul |

### 3.7 Ce qu'AnkiHub **n'a pas**, et où DeckDock gagne

| Fonctionnalité | AnkiHub | DeckDock (cible) |
|---|---|---|
| API publique documentée | ❌ promise depuis des années | ✅ |
| Webhooks entrants et sortants | ❌ | ✅ |
| Git, PR, historique diffable, forks | ❌ | ✅ |
| Format source texte et export non verrouillé | ❌ | ✅ |
| Gratuit pour partager entre camarades | ❌ abonnement Core nécessaire | ✅ |
| Open source (serveur et client) | ❌ add-on sans licence, serveur fermé | ✅ AGPL |
| CI sur le contenu (lint de cartes, médias cassés, doublons, cloze mal formées) | ❌ | ✅ GitHub Actions |
| Forks avec suivi de l'amont (« mon deck = AnKing + mes ajouts ») | ❌ | ✅ |
| Éditions multilingues liées | ❌ | ✅ |
| Pas de télémétrie de révisions par défaut | ❌ (envoie des résumés de révisions) | ✅ argument de confidentialité |

---

## 4. Le cœur technique : passer de « apkg » à « notes »

Presque toutes les fonctions P0 et P1 (champs protégés, deltas, suppressions, propositions, catalogue avec aperçu, recherche) supposent la **même chose** : que quelqu'un, quelque part, connaisse le deck **note par note**, avec des identifiants stables. Aujourd'hui personne ne le fait : l'apkg passe en boîte noire de GitHub jusqu'à l'importeur d'Anki.

**Il y a deux façons d'y arriver, et il faut les deux :**

### A. Format source texte dans le dépôt (le vrai mode « Git »)

- **Contenu.** Un format de deck lisible et diffable dans le dépôt :
  - `deck.yaml` : métadonnées, notetypes, options ;
  - `notes/*.yaml`, ou un CSV/JSONL par notetype, une note par ligne avec son `guid` ;
  - `media/`.
- **Inspirations.** CrowdAnki (JSON) et Brain Brew (CSV + YAML) existent déjà. Il vaut mieux être compatible avec CrowdAnki à l'import que réinventer.
- **CI.** Une GitHub Action fournie par DeckDock (`deckdock/build-action`) :
  - valide le contenu (lint) ;
  - construit l'apkg ;
  - génère le changelog ;
  - publie la release.
- **Bénéfice :** les PR deviennent lisibles (« champ `Back` de la note X : *mitochondrie* → *mitochondries* »).

### B. Ingestion d'apkg (compatibilité, et le mode sans GitHub)

- **Fonctionnement.** Le hub ouvre l'apkg (c'est du SQLite plus des médias), en extrait les notes et les indexe par GUID. Il calcule ensuite le diff avec la version précédente.
- **Usage.** Ça couvre les decks existants publiés en apkg, et les créateurs qui ne veulent pas entendre parler de Git.

Dans les deux cas, le hub stocke la même chose : **un snapshot normalisé par version, plus un journal de changements note par note.**

### Côté add-on : remplacer la boîte d'import par un moteur de synchro

- **Application directe.** Les notes sont créées ou mises à jour par l'API de collection (`col.add_note`, `col.update_note`), avec les IDs et GUID imposés par le hub.
- **Règles de fusion explicites** (c'est là que DeckDock peut être *meilleur* qu'AnkiHub, qui écrase tout ce qui n'est pas protégé) :
  - un champ jamais modifié localement est mis à jour ;
  - un champ protégé n'est jamais touché ;
  - un champ modifié localement et non protégé : **c'est un conflit**. On montre un diff à 3 voies (amont précédent / local / amont nouveau) et on propose « garder le mien », « prendre l'amont » ou « proposer le mien en PR ».
  - AnkiHub ne fait pas de 3-way merge. C'est un vrai argument.
- **Base de fusion.** On stocke localement le dernier état amont de chaque note (dans une table annexe ou la config) pour servir de base au 3-way.
- **Suppressions.** On applique le tag `DeckDock::Deleted`, et on supprime seulement si la note n'a jamais été révisée et que l'utilisateur l'a accepté.
- **Planification.** On ne touche jamais aux révisions (même règle qu'AnkiHub).

---

## 5. Architecture du hub central

### 5.1 Webhooks plutôt que scraping nocturne

Tu hésitais entre un calcul nocturne qui parcourt tout GitHub et un hub qu'on « tape » depuis GitHub. **C'est la seconde option qu'il faut.** Le scraping coûte cher, se fait limiter par GitHub et arrive en retard. Les webhooks sont instantanés et quasi gratuits.

**Recommandation : une GitHub App « DeckDock ».**

1. **Installation.** Le créateur installe l'App sur son dépôt (un clic, avec un choix fin des dépôts concernés). Ça marche aussi pour les **dépôts privés**.
2. **Événements reçus.** GitHub envoie au hub `release.published`, `push` (pour le mode source texte) et `pull_request` (pour l'état des propositions).
3. **Ingestion.** Le hub télécharge l'asset ou le contenu source, le normalise et calcule le diff, puis publie la nouvelle version dans son index.
4. **Filet de sécurité.** Une **réconciliation nocturne légère** passe sur les seuls dépôts installés pour rattraper un webhook perdu. C'est là que le « une fois par nuit » a sa place, mais en secours, pas comme mécanisme principal.
5. **Sans App.** Pour les dépôts tiers qui n'installent pas l'App, une URL de webhook générique (`POST /hooks/github/{deck_id}` signée par secret) suffit, ou alors le hub interroge ces dépôts en arrière-plan avec son propre token (5 000 requêtes par heure, contre 60 côté client).

### 5.2 Les flux

```
 Créateur                         Hub DeckDock                       Abonnés (add-on Anki)
 ────────                         ────────────                       ─────────────────────
 git push / release ──webhook──▶  ingestion → snapshot v42
                                  diff v41→v42 (notes, médias)
                                  index de recherche, page web
                                                       ◀── GET /sync?since=<curseur>  (1 requête
                                                            pour TOUS les decks suivis)
                                  ── deltas JSON + URLs médias ──▶  application note par note
                                                                    (champs protégés, 3-way)

 Abonné: « Proposer une modif » ── POST /suggestions ──▶ hub (GitHub App) ouvre une PR
                                                          sur le dépôt, avec l'utilisateur en co-auteur
 Mainteneur: merge sur GitHub ──webhook──▶ nouvelle version ──▶ tous les abonnés
```

**Point clé : le client ne parle plus jamais directement à GitHub**, sauf peut-être pour télécharger les médias depuis les assets de release, qui servent alors de CDN gratuit. Le rate limit disparaît, la synchro tient en une seule requête, et le hub peut aussi servir des decks qui ne viennent pas de GitHub.

### 5.3 Sans GitHub (mode secondaire, mais nécessaire)

- **Publication.** Le créateur publie depuis l'add-on : « Publier ce deck sur DeckDock » envoie le deck en apkg ou au format source. Il peut aussi passer par le site, avec un glisser-déposer d'apkg.
- **Stockage.** En interne, le hub peut quand même versionner ces decks dans un **dépôt Git qu'il héberge** (sur un Gitea ou Forgejo embarqué, ou simplement dans le stockage objet avec le même modèle de versions). Le même code sert les deux modes, et le créateur peut plus tard « exporter vers GitHub » sans rien perdre.
- **Propositions.** Pour ces decks, elles arrivent dans une file de relecture sur le site, une mini-UI de PR. C'est le seul cas où il faut construire la relecture soi-même.

### 5.4 Stack suggérée (pour un projet solo, peu cher)

| Brique | Choix |
|---|---|
| API et webhooks | Python (FastAPI) : réutilise le code de parsing et de domaine de l'add-on, et le module `anki` de PyPI pour lire les apkg |
| BDD | Postgres : decks, versions, notes (JSONB), changements, utilisateurs, propositions. Recherche plein texte avec `tsvector` dès le départ, embeddings (`pgvector`) plus tard pour la recherche « IA » |
| Stockage | Médias en stockage objet S3-compatible (Cloudflare R2 : pas de frais de sortie) avec des noms hashés, ou les assets de release GitHub en proxy |
| Jobs | File de tâches simple (Postgres + worker) pour l'ingestion et la réconciliation |
| Site | Next.js ou SvelteKit, pages de deck **publiques et indexables** (SEO = acquisition), connexion GitHub OAuth |
| Auth add-on | « Device flow » (un code affiché dans Anki, validé sur le site), sans mot de passe dans Anki |

### 5.5 API publique (le différenciateur)

- `GET /decks?q=` : recherche dans le catalogue ;
- `GET /decks/{id}`, `GET /decks/{id}/versions`, `GET /decks/{id}/notes?q=` ;
- `GET /sync?since=` (authentifié ou anonyme) : les deltas de tous les abonnements ;
- `POST /suggestions`, `GET /suggestions/{id}` ;
- **Webhooks sortants** : « nouvelle version », « proposition fusionnée ». Ils permettent des intégrations Discord, Slack ou de classe, et des bots ;
- tout documenté en OpenAPI. C'est littéralement ce qu'AnkiHub promet depuis des années sans le livrer.

---

## 6. Idées pour aller plus loin qu'AnkiHub

1. **Forks avec suivi de l'amont.** « Je pars du deck X et j'ajoute mes cartes. » Le hub sait que ton deck dérive de X et te propose les nouveautés de l'amont, toujours avec le 3-way merge. AnkiHub ne permet que de protéger des champs.
2. **Overlays au lieu de « tags optionnels ».** Un dépôt séparé contient uniquement des tags, des champs supplémentaires (par exemple « Notes de mon prof ») ou des traductions, rattachés par GUID au deck de base. Chaque fac ou chaque prof maintient son overlay. C'est la généralisation des « deck extensions » d'AnkiHub, qui ne portent que des tags.
3. **CI de contenu prête à l'emploi** : cloze cassées, médias manquants ou orphelins, doublons quasi identiques, champs vides, HTML sale. Les rapports s'affichent directement dans la PR.
4. **Changelog automatique lisible** dans Anki avant d'appliquer une mise à jour : « 132 notes modifiées, 12 ajoutées, 3 supprimées », avec un aperçu du diff.
5. **Bot IA sur les PR**, à la place d'un chatbot payant : relecture des propositions (« cette correction contredit la note Y »), détection de doublons, suggestion de tags. Plus tard, un « Smart Search » ouvert : tu colles ton cours et tu obtiens les cartes correspondantes, cette fois sur *tous* les decks publics.
6. **Badges et intégrations** : badge « Disponible sur DeckDock » pour les README, lien profond `deckdock://add/{deck}` ou code court à coller dans Anki.
7. **Éditions liées.** Les versions FR et EN d'un même deck partagent des GUID de « concept » : une correction de fond sur l'une ouvre une issue sur l'autre.
8. **Confidentialité par défaut.** Aucune télémétrie de révision. Les statistiques pour les créateurs restent opt-in et agrégées.

---

## 7. Feuille de route proposée

| Phase | Objectif | Contenu | Effort indicatif |
|---|---|---|---|
| **0. Fondations** (sans serveur) | Rendre l'outil actuel plus facile à adopter | Accepter l'URL de dépôt (choisir l'asset dans une liste), ajout par code court, import « silencieux » avec options imposées (mettre à jour les notes si plus récentes + fusionner les notetypes), changelog depuis les notes de release | 1–2 sem. |
| **1. Hub v1 : catalogue + synchro centralisée** | Remplacer le polling GitHub | GitHub App + webhooks, ingestion apkg → snapshot de notes, `GET /sync`, site avec catalogue public, pages de deck et aperçu des notes. L'add-on parle au hub (repli sur GitHub si le hub est en panne) | 4–6 sem. |
| **2. Moteur de synchro note par note** | Égaler AnkiHub sur l'essentiel | Deltas, application directe sans boîte d'import, champs et tags protégés, suppressions, médias incrémentaux, réinitialisation des modifs locales, 3-way merge | 4–6 sem. (le plus délicat) |
| **3. Collaboration Git** | Le pitch | Format source texte + build-action, « Proposer une modif » dans l'éditeur → PR (puis en masse, nouvelles notes, suppressions), « Signaler » → Issue, comptes via GitHub OAuth + device flow | 4 sem. |
| **4. Sans GitHub + créateurs** | Élargir le public | Publier depuis Anki, decks hébergés par le hub, file de relecture web, decks privés, organisations | 4 sem. |
| **5. Au-delà** | Différenciation | Overlays, forks avec amont, CI de contenu, API publique et webhooks sortants documentés, recherche plein texte globale, bot IA | continu |

**Le MVP qui fait déjà mieux qu'AnkiHub sur un axe :** phases 1 et 3 *partielle*, c'est-à-dire catalogue public + webhook GitHub + synchro par le hub + « Proposer une modif » → PR. On peut le livrer avant le moteur de deltas complet en gardant l'import apkg comme mécanisme d'application.

---

## 8. AnkiCollab : le concurrent gratuit

*Étude du code source (Plugin, Backend et Website, sous licence GPL-3.0, github.com/CravingCrates) et du forum de support, au 24/11/2026.*

### Ce qu'est le projet

- **Modèle.** Gratuit, sans paywall, avec un compte obligatoire. Il est hébergé et soutenu par la fédération des étudiants en médecine allemands (bvmd) et la communauté Ankizin.
- **Bus factor ≈ 1.** Un seul développeur principal écrit environ 90 % des commits, mais le projet est très actif : derniers pushs les 21–23/11/2026.
- **Utilisation.** Plusieurs centaines de decks publics. Le plus gros est **« Anki EDN » (ECN/EDN française) : 17 000 notes et environ 1 360 abonnés.** Une partie de la cible francophone est donc déjà chez eux.
- **Stack.** Backend Rust (axum) avec Postgres et du stockage S3 pour les médias, site web Rust/Tera. L'add-on est un fork de CrowdAnki (payloads JSON).

### Comment marche la synchro

- **Abonnement.** On s'abonne avec une clé de six mots (`pip-item-hawaii-…`).
- **Récupération.** `/pullChanges` reçoit un timestamp par deck et renvoie les **notes entières** modifiées depuis, ainsi que les GUID supprimés, les champs protégés, les groupes de tags optionnels et le changelog.
- **Premier téléchargement.** Il passe par un bundle zip pré-construit sur S3. Ce bundle n'est construit qu'après 24 h, et le téléchargement ne reprend pas en cas de coupure : les decks de plus de 200 Mo échouent.
- **Identité et planification.** Les notes sont identifiées par GUID et mises à jour sur place, donc les révisions sont préservées.
- **Protection.** Tags `AnkiCollab_Protect::Champ` et `AnkiCollab_Personal::`, champs protégés par le mainteneur, et un marqueur `USER_CUSTOMISATION` dans le CSS et les templates.
- **Suppressions.** Le serveur fait une suppression douce, puis le client demande confirmation à l'utilisateur.
- **Conflits.** Le dernier changement approuvé l'emporte : **les modifs locales non protégées sont écrasées sans prévenir.** Une PR qui ajoutait un diff avant application a été refusée.
- **Limites.** La structure des sous-decks est imposée et ne peut pas être allégée. Les notetypes ne s'éditent que sur le web. Les options de deck ne sont pas partagées.

### Collaboration

- **Propositions depuis Anki.** On peut proposer depuis l'éditeur ou en masse depuis le navigateur, avec un motif et un message. Les suppressions et les déplacements de notes sont aussi des propositions.
- **Relecture.** File de relecture web avec un diff HTML, et acceptation ou refus champ par champ. Les mainteneurs peuvent s'auto-approuver.
- **Rôles.** Ils sont grossiers : un seul propriétaire, et la FAQ conseille de partager ses identifiants pour partager la propriété.
- **Historique.** Il existe un historique par note avec restauration, un changelog affiché en popup et des notifications dans Anki. En revanche, **il n'y a pas de discussion** sur les propositions.
- **Decks liés.** Un deck peut hériter des champs d'un deck de base, et les propositions faites sur ces champs remontent vers l'amont. C'est une sorte de fork avec suivi de l'amont.
- **Découverte.** Une liste plate : nom, nombre de notes (par tranche), nombre d'abonnés et un bouton « copier la clé ». Pas de catégories. Les decks sont privés par défaut (case à décocher).
- **Pas de Git, pas d'API publique, pas de webhooks.**

### Plaintes récurrentes

- **Gros decks :** téléchargements qui échouent, timeouts sur les médias, blocages par CrowdSec.
- **Validation invisible :** l'utilisateur ne comprend pas pourquoi sa modif n'arrive pas, faute de voir qu'elle attend une approbation.
- **Comptes :** pas de réinitialisation de mot de passe, et une objection de confidentialité au fait de devoir créer un compte.
- **Gouvernance :** rôles rigides, et les PR externes sont fermées avec « discutez-en d'abord sur Discord ».

### Ce qu'on reprend, ce qu'on évite

| On reprend | On évite |
|---|---|
| Mise à jour sur place par GUID, liste de GUID supprimés et confirmation de suppression par l'utilisateur | Écraser les modifs locales sans prévenir → résumé ou diff avant application, notes modifiées localement mises de côté |
| Protection par tags (`…_Protect::`, `…_Personal::`) et marqueur de personnalisation dans le CSS | Structure de sous-decks imposée, notetypes éditables seulement sur le web |
| Motif + message sur chaque proposition (→ libellé et titre de PR) | Validation interne invisible → lien vers la PR et statut affichés dans Anki |
| Snapshot initial, puis deltas | Bundle construit après 24 h, sans reprise → construit dès la publication, avec reprise par HTTP Range |
| Connexion par appairage d'appareil (code dans Anki, validation dans le navigateur) | Comptes avec mot de passe maison → GitHub OAuth, ou aucun compte pour simplement s'abonner |
| Popup de changelog, notification « ta proposition a été acceptée » | UI de relecture, de diff et d'historique faite à la main → GitHub PR |
| Decks liés avec remontée vers l'amont (après le MVP) | Découverte sans catégories ni recherche |

**Conclusion.** AnkiCollab prouve que le modèle « gratuit + propositions + synchro par GUID » attire les utilisateurs, la cible francophone comprise. Ses faiblesses sont précisément celles que Git et GitHub règlent gratuitement : relecture, discussion, rôles, historique, gouvernance et facteur bus. Notre MVP doit donc être **plus simple à utiliser** (pas de compte pour s'abonner, statut visible) et **plus sûr** (ne jamais écraser une modif locale sans prévenir).

---

## 9. Risques et questions ouvertes

- **Contenu sous droits.** Des gens vont republier AnKing ou des contenus de First Aid / Boards & Beyond. Il faut une procédure de retrait (DMCA) et des CGU dès le catalogue public.
- **Coût des médias.** C'est le seul vrai poste de coût. Il faut s'appuyer au maximum sur les assets de release GitHub, et sur R2 (sans frais de sortie) pour les decks hébergés.
- **Concurrence existante.** **AnkiCollab** (gratuit, open source, collaboratif) occupe déjà une partie de ce créneau, sans Git. À étudier de près avant de construire : son modèle de propositions et de fusion, et ce que ses utilisateurs lui reprochent.
- **Position d'AnkiHub dans Anki.** S'ils pilotent désormais Anki, une intégration native concurrente est peu probable. Rester un add-on et miser sur la compatibilité (AnkiWeb pour le mobile) est la voie réaliste.
- **Mobile.** Comme AnkiHub, on dépend de la synchro AnkiWeb : on synchronise sur desktop, puis AnkiWeb prend le relais vers le téléphone. Pas pire que le concurrent, mais pas mieux non plus.
- **Nom.** Le dépôt s'appelle `anki-deckdock`, l'add-on « Deck Manager » et la release `anki-deck-manager`. Pour un hub public avec un site, il faut un nom unique (DeckDock ?) et un domaine.
- **Gouvernance de la GitHub App.** Elle demande des droits en écriture (ouvrir des PR, publier des releases) : il faut des permissions minimales et une communication claire.
