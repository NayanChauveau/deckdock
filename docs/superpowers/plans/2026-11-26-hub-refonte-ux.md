# Refonte de l'interface du hub Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Donner au site public de `deckdock-hub` une interface « SaaS clair et chaleureux », en clair et en sombre, avec navigation commune, accueil, catalogue, page de deck, espace auteur et guide refaits, sans toucher au service `/d/` ni à l'API de publication.

**Architecture:** On reprend d'abord du starter le mécanisme de thème (`src/core/ui/theme/`) et la 404 rendue côté serveur, puis on pose un socle visuel (tokens DeckDock dans `theme.css`, en-tête/pied de page, composants communs) et on reconstruit chaque page dessus. Les données changent peu : l'icône rejoint le `summary` JSON des versions (aucune migration), le catalogue gagne un tri. Le guide est en Markdown dans le dépôt, rendu côté serveur.

**Tech Stack:** Next 16, React 19, Payload 3, Tailwind 4, shadcn/ui (CLI `pnpm ui:add`), node:test + Testing Library, Playwright + axe, Lighthouse.

**Spec:** `docs/superpowers/specs/2026-11-26-deckdock-hub-refonte-ux-design.md` (maquettes : `docs/superpowers/specs/assets/2026-11-26-refonte-ux/*.html`).

**Dépôt de travail:** `/Users/nayanchauveau/Documents/projets-perso/deckdock-hub`, branche `feat/ux-redesign` créée depuis `main` à jour, sur laquelle on fusionne d'abord `feat/vendor-0.3` (bibliothèque 0.3.0).

## Global Constraints

- Palette (spec) : accent `#4f46e5` en clair, `#6366f1` en sombre ; dégradé du mot clé indigo → rose (`#4f46e5`→`#db2777` en clair, `#818cf8`→`#f472b6` en sombre) ; fond `#fbfaff` / `#0f0e1a` ; cartes blanches à ombre douce en clair, bordure fine en sombre ; cartes ~14 px de rayon, boutons en pilule ; police sans empattement (pile système, sans chargement de police externe).
- Thème : défaut = système, bouton ☀/☾ (Système → Clair → Sombre), choix mémorisé, aucun flash — mécanisme repris **tel quel** du starter (`src/core/ui/theme/*`, `ThemeScript` dans `<head>`, `ThemeSync` dans le layout) ; le hub ne fournit que la palette.
- Toutes les pages publiques ont l'en-tête et le pied de page communs ; FR · EN pointe vers la même page dans l'autre langue.
- Bilingue fr/en partout (textes, guide). L'interface dit « notes » (pas « cartes »).
- Pas d'affaiblissement de l'étape A : CSP à nonce, isolation de l'aperçu (`/preview/`, iframe `sandbox="allow-scripts"`, pas de script de carte), `/d/` et `/api/publish/` inchangés.
- Accessibilité WCAG 2.1 AA (axe sans violation) en clair **et** en sombre, sur ordinateur et à 390 px sans débordement horizontal ; budget Lighthouse existant vert.
- `homepage` n'est affichée (« Source ») que si c'est une URL `https`. L'icône affichée est celle de l'édition dans la langue du visiteur, sinon de la première ; sans icône : initiale du nom sur une couleur stable tirée de l'identifiant du deck (palette lisible dans les deux thèmes).
- Pas de dépendance nouvelle sans raison écrite dans le commit ; composants shadcn par `pnpm ui:add`.
- Respecter `tests/architecture.test.ts` (le socle n'importe pas les modules).
- Le README du hub tient à jour la liste des fichiers du starter modifiés.
- Commits locaux seulement après accord du propriétaire ; aucun push sans accord séparé. Commits avec l'adresse noreply (déjà réglée).
- Boucle rapide : `pnpm test:unit` et `pnpm test --group=<groupe>` ; `HUB_PYTHON=/opt/homebrew/bin/python3.14` en local pour les tests du vérificateur réel.

## Review Focus

1. Deck dont l'édition dans la langue du visiteur n'existe pas (deck seulement `en`, visiteur `fr`) : carte, page et icône prennent la première édition, sans trou ni texte vide.
2. Textes longs : nom de deck de 80 caractères, description d'une seule ligne de 2 000 caractères, pseudo long, adresse d'édition longue — rien ne déborde à 390 px, en clair comme en sombre.
3. Catalogue vide, recherche sans résultat, page de pagination au-delà de la dernière : états vides soignés, pas d'erreur.
4. Visiteur connecté sans pseudo, connecté avec pseudo, non connecté, administrateur : l'en-tête montre le bon état (Connexion, menu au pseudo) sans flash ni erreur d'hydratation.
5. Maintenance active (visiteur bloqué, admin connecté avec bannière) et page 404 : en-tête/pied cohérents, thème sombre sans flash.

---

### Task 1: Base de la branche, thème et 404 du starter

**Files:**
- Copy from `site-starter` (main `38f71fe` pour le thème ; commit local `e1a8f4d` de `fix/not-found-in-layout` pour la 404) : `src/core/ui/theme/{preference.ts,ThemeScript.tsx,ThemeToggle.tsx}`, `tests/theme.test.ts`, `tests/theme.ui.test.tsx`, `tests/theme-contrast.test.ts`, `src/core/i18n/messages.ts` (libellés `theme`), les changements de `src/app/(frontend)/[locale]/layout.tsx`, `next.config.mjs` (`experimental.globalNotFound`), `global-not-found.tsx`, le dossier `(legal)/` avec ses stubs, et les tests de la 404.
- Delete: `src/app/(frontend)/[locale]/[...slug]/page.tsx` (remplacé par `(legal)/legal-page.tsx` du hub, qui reprend le contenu actuel de la page légale du hub, pas celui du starter).
- Lire avant : la note `~/Library/Application Support/Claude/side-session-notes/local_b04a039f-81c4-4654-980a-5abcac3589f9/404-server-render.md`.

- [ ] **Step 1:** `git switch -c feat/ux-redesign main && git merge --no-ff feat/vendor-0.3`.
- [ ] **Step 2: Tests d'abord** : copier les tests du starter (thème, contraste, 404) ; `pnpm test:unit` — Expected: FAIL (modules absents ; `.dark` absent de `theme.css`).
- [ ] **Step 3:** copier le mécanisme et la 404 ; dans `theme.css`, ajouter un bloc `.dark` provisoire (valeurs neutres) pour que le test de contraste passe — la palette DeckDock arrive en Task 2.
- [ ] **Step 4: Run** `pnpm test:unit` puis `pnpm test --group=browser` — Expected: PASS ; `/fr/page-inexistante` n'est plus l'error shell et est sombre au chargement pour un système sombre.
- [ ] **Step 5: Commit** `feat: dark mode and server-rendered 404 from the starter`

### Task 2: Palette et typographie DeckDock

**Files:** Modify `src/styles/theme.css` (`:root` et `.dark` aux valeurs de la spec ; `--radius` ~0.875rem ; polices système ; ombre de carte), `src/styles/base.css` si besoin ; Delete du site public les styles éditoriaux du starter devenus inutiles (`site.css` : hero, art, about) au fil des tâches suivantes ; Test `tests/theme-contrast.test.ts` (paires de la palette DeckDock, y compris `primary-foreground` sur `primary`, texte du dégradé non requis car décoratif doublé du texte).

- [ ] **Step 1:** ajouter au test de contraste les valeurs attendues (`--primary` = `#4f46e5` en clair, `#6366f1` en sombre ; `--background` = `#fbfaff` / `#0f0e1a`) — Expected: FAIL.
- [ ] **Step 2:** écrire la palette complète (tous les tokens de couleur dans les deux blocs), tokens additionnels `--gradient-from`, `--gradient-to`, `--shadow-card`.
- [ ] **Step 3: Run** `pnpm test:unit` — Expected: PASS (contrastes AA dans les deux thèmes).
- [ ] **Step 4: Commit** `feat(theme): DeckDock palette, light and dark`

### Task 3: Coquille du site (en-tête, pied de page, états)

**Files:** Modify `src/site/SiteChrome.tsx` (refonte), `src/site/messages.ts` (textes DeckDock : plus de « Site d'exemple ») ; Create `src/site/PublicShell.tsx` (en-tête + `<main>` + pied, prop `paths` pour FR · EN) ; Modify toutes les pages publiques pour l'utiliser (`decks`, `d/...`, `compte/*`, `(legal)`, `not-found`, `error`, `MaintenancePage`) ; Test `tests/site-chrome.ui.test.tsx` (nouveau), e2e.

**Interfaces:**
- Produces: `PublicShell({ locale, paths?, children })` (serveur) ; `SiteHeader({ locale, paths, viewer })` avec `viewer: { signedIn: false } | { signedIn: true; handle: string | null }` ; liens Catalogue `/{l}/decks`, Publier un deck `/{l}/guide/publier-avec-github` (ou l'équivalent en), Guide `/{l}/guide`, sélecteur FR · EN, `ThemeToggle`, Connexion ou menu au pseudo (Mes decks, Compte, Déconnexion) ; menu mobile (bouton `aria-expanded`, liens en colonne) sous 768 px. Le pied : « ● DeckDock · open source », liens GitHub (`NayanChauveau/deckdock`, `NayanChauveau/deckdock-hub`), Guide, mentions légales, confidentialité.
- Comment l'en-tête connaît le visiteur : par un point d'extension existant du module accounts (session) ou une lecture de session dans `src/site`, sans import des modules par le socle.

- [ ] **Step 1: Write the failing tests** : rendu de `SiteHeader` non connecté (lien « Connexion »), connecté sans pseudo (menu « Compte »), avec pseudo (menu « demo ») ; liens FR · EN vers `paths` ; e2e : toutes les pages publiques listées ont `header` et `footer`, un lien « Catalogue » mène au catalogue, axe clair+sombre sans violation, 390 px sans débordement, menu mobile ouvrable au clavier.
- [ ] **Step 2: Run** — Expected: FAIL.
- [ ] **Step 3: Implement**.
- [ ] **Step 4: Run** `pnpm test:unit` et `pnpm test --group=browser` — Expected: PASS.
- [ ] **Step 5: Commit** `feat(site): shared header and footer on every public page`

### Task 4: Composants communs et icône des decks

**Files:** Create `src/modules/decks/ui/components/{DeckIcon,DeckCard,StatusBadge,CopyField,Section}.tsx` ; Modify `src/modules/decks/application/publish.ts` (le `summary` garde `icon` quand `deck.icon` est présent), `domain/edition.ts` (`deckFacts` lit `icon`), `application/catalogue.ts` et `server.ts` (`CatalogueCard.icon`, `PublicEdition.icon`) ; Test `tests/decks.components.ui.test.tsx`, `tests/decks.publish.test.ts` (ou le fichier qui couvre `publish`).

**Interfaces:**
- Produces: `DeckIcon({ icon?: string | null, name: string, deckId: string, size?: 'sm' | 'md' | 'lg' })` — emoji si présent, sinon initiale (premier graphème du nom, majuscule) sur `initialColor(deckId)` ; `initialColor(deckId: string): string` (indice stable dans une palette de 8 tokens `--initial-1..8`, définis en clair et en sombre dans `theme.css`) ; `CopyField({ label, value, testId? })` (police mono, bouton Copier, annonce `aria-live`) ; `StatusBadge({ status: 'approved' | 'pending' | 'hidden' })`.

- [ ] **Step 1: Write the failing tests** : `initialColor` stable (même id → même couleur ; ids différents répartis) ; `DeckIcon` emoji vs initiale (« é » pour « écologie », emoji de nom ignoré) ; publication d'un `deck.json` avec `icon` → `summary.icon` ; catalogue et `deckPage` renvoient `icon` de l'édition de la langue du visiteur, sinon de la première (Review Focus 1).
- [ ] **Step 2–4:** FAIL → implement → `pnpm test:unit` PASS.
- [ ] **Step 5: Commit** `feat(decks): deck icon and shared components`

### Task 5: Accueil en code

**Files:** Rewrite `src/app/(frontend)/[locale]/page.tsx` (4 blocs de la maquette `accueil-structure.html`) ; Create `src/site/home-content.ts` (textes fr/en) ; la section « Decks récents » appelle le catalogue (3 à 6 decks validés les plus récents) ; Modify `site.config.json` (`contains` du test de déploiement → une phrase de la nouvelle accueil), `tests/test_site_config.py`, `tests/smoke_harness.py`, `tests/accounts.http.ts` si concernés ; le global Payload `site-content` n'est plus lu par l'accueil (laisser la collection en place, la retirer est hors périmètre) ; métadonnées SEO de l'accueil dans le code.

- [ ] **Step 1: Write the failing tests** (HTTP/e2e) : `/fr` contient « Vos decks Anki, toujours à jour. », les 3 étapes, la section auteurs avec `NayanChauveau/deckdock/action@v0` ; « Decks récents » montre un deck validé et pas un deck en attente ; sans deck validé, l'invitation à publier ; `/en` en anglais.
- [ ] **Step 2–4:** FAIL → implement → PASS (`pnpm test --group=web,browser`).
- [ ] **Step 5: Commit** `feat(home): DeckDock home page`

### Task 6: Catalogue

**Files:** Rewrite `src/modules/decks/ui/CataloguePage.tsx` ; Modify `application/catalogue.ts` + `adapters/payload/catalogue-store.ts` (paramètre `sort`: `'updated'` défaut | `'name'` | `'notes'` ; `name` = nom de l'édition retenue, `notes` = maximum des éditions ; tri en SQL) ; messages ; Test `tests/decks.catalogue.http.ts`, `tests/e2e/decks-catalogue.spec.ts`, test unitaire de `catalogue`.

- [ ] **Step 1: Write the failing tests** : `sort=name` ordonne par nom, `sort=notes` par taille, valeur inconnue → `updated` ; pastilles de langue = liens (pas de bouton requis), état « Aucun deck trouvé » et page au-delà de la dernière (Review Focus 3) ; carte entière cliquable (un seul lien par carte, nom accessible = nom du deck) ; pastilles langues / notes / « il y a … » ; mettre à jour les assertions existantes (rôles, `data-testid="catalogue-total"`).
- [ ] **Step 2–4:** FAIL → implement → PASS.
- [ ] **Step 5: Commit** `feat(catalogue): search, language pills, sort and deck cards`

### Task 7: Page d'un deck

**Files:** Rewrite `src/modules/decks/ui/DeckPage.tsx` (et `DeckNotFound.tsx`) ; Create `src/modules/decks/ui/PreviewCarousel.tsx` (client) ; Test `tests/decks.catalogue.http.ts`, `tests/e2e/decks-catalogue.spec.ts`.

- [ ] **Step 1: Write the failing tests** : en-tête (icône, nom, auteur, licence, mise à jour relative) ; bloc « Suivre ce deck dans Anki » avec un onglet par édition (liens `?edition=`), `CopyField` avec `data-testid="address-<code>"`, lien « Installer le plugin » ; « En bref » : notes, langues, licence, « Source » seulement si `homepage` est https (`http://…` et `javascript:` non affichés) ; carrousel : une note à la fois, recto/verso côte à côte, boutons précédent/suivant accessibles, iframes inchangées (`sandbox="allow-scripts"`, `src="/preview/..."`) ; sur mobile le bloc « Suivre » vient juste après l'en-tête du deck ; historique conservé.
- [ ] **Step 2:** FAIL. **Step 3:** implement ; vérifier dans Chromium (Playwright) que les cartes de l'aperçu et leurs images s'affichent (dans le navigateur intégré de l'outil elles étaient bloquées côté client) et corriger si le hub est en cause.
- [ ] **Step 4:** PASS. **Step 5: Commit** `feat(deck-page): follow block, preview carousel and facts`

### Task 8: Connexion, compte et espace auteur

**Files:** Modify `src/modules/accounts/ui/{SignInPage,SignInForm,AccountPage,AccountView,DeletedPage}.tsx` (carte centrée, états « lien envoyé », « lien expiré ») ; Create `src/modules/decks/ui/AuthorShell.tsx` (barre latérale Mes decks / Compte / Guide auteur ; onglets sous 768 px) ; Rewrite `AuthorDecksPage.tsx`, `AuthorDeckPage.tsx` (guide en 3 étapes tant qu'aucune version n'est reçue, avec `DECKDOCK_HUB_URL` pré-rempli = URL publique du hub et copiable ; puis versions, éditions et adresses, jeton, retrait) ; Test `tests/decks.ui.test.tsx`, `tests/accounts.ui.test.tsx`, `tests/e2e/decks-author.spec.ts`, `tests/e2e/accounts.spec.ts`.

- [ ] **Step 1: Write the failing tests** : liste des decks avec `DeckIcon`, identifiant, éditions, dernière version et `StatusBadge` (motif affiché pour « Masqué ») ; le guide en 3 étapes n'apparaît que sans version reçue ; toutes les actions existantes restent (pseudo, création, régénérer/révoquer le jeton, maintenance) — adapter les tests existants sans perdre de cas.
- [ ] **Step 2–4:** FAIL → implement → PASS (`pnpm test:unit`, `--group=browser`).
- [ ] **Step 5: Commit** `feat(author): author space with sidebar and first-publish guide`

### Task 9: Guide

**Files:** Create `content/guide/{fr,en}/{comment-ca-marche|how-it-works,publier-avec-github|publish-with-github,publier-sans-github|publish-without-github,format}.md` ; Create `src/site/guide/{load.ts,GuidePage.tsx,render.ts}` et la route `src/app/(frontend)/[locale]/guide/[[...slug]]/page.tsx` ; sitemap ; Test `tests/guide.test.ts`, `tests/e2e/guide.spec.ts`.

**Interfaces:**
- Produces: `guidePages(locale): { slug: string; title: string }[]` (ordre du sommaire) ; `guidePage(locale, slug): { title: string; html: string; other: string } | null` (`other` = slug de la même page dans l'autre langue, pour FR · EN) ; rendu Markdown **sans HTML brut** (titres, listes, liens, code avec bouton Copier, encadrés `> **Note**`, images de `public/guide/`), titres avec ancres.
- Bibliothèque de rendu : au choix du constructeur (justifiée dans le commit), HTML brut désactivé, liens externes `rel="noopener"`.

- [ ] **Step 1: Write the failing tests** : chaque page existe en fr et en, `other` pointe sur l'équivalent ; un `<script>` ou `<img onerror>` écrit dans un `.md` de test ressort échappé ; slug inconnu → 404 ; sommaire dans l'ordre ; la page « Publier sans GitHub » contient `deckdock publish` et l'exemple `curl` (`POST /api/publish/<edition>`) ; la page « Publier avec GitHub » contient les emplacements de captures marqués `<!-- capture: ... -->` (non rendus).
- [ ] **Step 2:** FAIL. **Step 3:** écrire le contenu (pour quelqu'un qui n'a jamais codé : ce qu'est GitHub, « Use this template », modifier un fichier sur github.com, secret et variable, onglet Actions, lire une erreur de vérification ; API : jeton, `deckdock publish`, `curl`, réponses et statuts de l'étape A ; format : `deckdock.yaml` dont `icon` et `homepage`, éditions, médias, versions, compatibilité) et le rendu.
- [ ] **Step 4:** PASS. **Step 5: Commit** `feat(guide): author guide in fr and en`

### Task 10: Finitions, accessibilité et documentation

**Files:** e2e transverses ; `README.md` (fichiers du starter modifiés, guide), `DESIGN_SYSTEM.md` du hub (palette, composants) ; nettoyage des styles devenus morts (`site.css`, `commerce.css` du starter) ; budget Lighthouse.

- [ ] **Step 1: Write the failing tests** : axe WCAG 2.1 AA en clair **et** en sombre sur `/fr`, `/en`, `/fr/decks`, une page de deck, `/fr/guide`, une page du guide, `/fr/compte/connexion`, l'espace auteur (connecté), `/fr/mentions-legales`, `/fr/page-inexistante` ; 390 px sans débordement sur les mêmes, avec les données longues de la Review Focus 2 ; Review Focus 4 et 5 couverts par un test chacun.
- [ ] **Step 2–3:** FAIL → corriger.
- [ ] **Step 4: Run** `pnpm test` (tous les groupes, dont performance) — Expected: « Tous les tests sont passés ».
- [ ] **Step 5: Commit** `test: accessibility and layout across the redesigned site; docs`
