# Hub DeckDock, refonte de l'interface : design

Date : 2026-11-26. Statut : à valider par le propriétaire.
Contexte : [2026-11-25-deckdock-hub-a-design.md](2026-11-25-deckdock-hub-a-design.md) (le hub tel
qu'il est construit), [`spec/deckdock-1.md`](../../../spec/deckdock-1.md) (format). Maquettes validées
pendant la discussion : [`assets/2026-11-26-refonte-ux/`](assets/2026-11-26-refonte-ux/) (fichiers HTML
à ouvrir dans un navigateur ; les decks montrés sont fictifs).

## Intention

Le hub fonctionne (étape A), mais il a l'air d'un squelette : l'accueil est encore le contenu de
démonstration du starter (« Bienvenue », style éditorial serif sur beige), seules certaines pages ont
un en-tête, rien ne mène au catalogue, et l'espace auteur est un bloc de texte. Le propriétaire veut
un site dont il soit fier, qui « fait vraiment SaaS moderne », et qui accueille aussi des auteurs
qui ne sont pas développeurs.

## Objectifs

### Identité visuelle

- Direction **« clair et chaleureux »** (maquette `direction-c-clair-sombre.html`) : accent indigo
  (`#4f46e5` en clair, `#6366f1` en sombre), dégradé discret indigo → rose sur le mot clé du titre,
  fond très légèrement teinté (`#fbfaff` / `#0f0e1a`), cartes blanches à ombre douce en clair et à
  bordure fine en sombre, coins ronds (cartes ~14 px, boutons en pilule), police sans empattement
  (Inter ou la police système équivalente).
- **Clair et sombre** : le mécanisme vient du starter (spec `site-starter`
  `docs/superpowers/specs/2026-11-26-mode-sombre-design.md`), le hub n'apporte que sa palette.
  Défaut = réglage du système, bouton ☀/☾ dans la barre, choix mémorisé.
- Le style éditorial du starter (serif, beige, `site.css` de présentation, contenu « site
  d'exemple ») disparaît du site public du hub.

### Navigation commune

- Un en-tête et un pied de page sur **toutes** les pages publiques (accueil, catalogue, deck,
  guide, connexion, compte, espace auteur, pages légales, erreurs).
- En-tête : logo « ● DeckDock » ; liens Catalogue, Publier un deck, Guide ; sélecteur **FR · EN** ;
  bouton ☀/☾ ; « Connexion » pour un visiteur, ou un menu au pseudo une fois connecté (Mes decks,
  Compte, Déconnexion). Sur mobile, les liens passent dans un menu.
- Pied de page : « DeckDock · open source », liens GitHub (dépôts deckdock et deckdock-hub),
  Guide, Mentions légales, Confidentialité.

### Accueil (maquette `accueil-structure.html`)

1. Haut de page : pastille « Gratuit et open source », titre « Vos decks Anki, toujours à jour. »
   (fin du titre en dégradé), une phrase, boutons « Parcourir les decks » et « Publier un deck ».
2. **Comment ça marche** (apprenants) : trouver un deck, coller son adresse dans le plugin Anki,
   recevoir les mises à jour sans perdre sa progression.
3. **Decks récents** : les vrais decks validés, les plus récemment mis à jour (3 à 6), lien
   « Tout le catalogue ». Si aucun deck n'est validé, la section invite à publier le premier.
4. **Pour les auteurs** : « votre deck vit dans un dépôt GitHub », extrait du workflow, boutons
   « Publier un deck » et « Le template ».

Les textes sont rédigés en français et en anglais ; le contenu de démonstration du starter est
remplacé.

### Catalogue (maquette `catalogue-et-deck.html`, haut)

- Titre, phrase d'explication, grande barre de recherche (la recherche actuelle : nom et
  description, sans accents ni casse), filtres de langue en pastilles, **tri** : mis à jour
  récemment (défaut), nom, nombre de cartes.
- Grille de cartes de deck, chaque carte cliquable en entier : icône ou initiale, nom, description
  courte, pastilles (langues, nombre de cartes, mise à jour relative « il y a 2 j »), auteur.
- 20 par page avec pagination, comme aujourd'hui ; état vide soigné (aucun résultat, aucun deck).

### Page d'un deck (même maquette, bas)

- Fil d'Ariane, grande icône ou initiale, nom, auteur, licence, mise à jour relative.
- Colonne principale : **aperçu** en carrousel (une carte à la fois, recto et verso côte à côte,
  carte suivante/précédente), description, historique des versions.
- Colonne latérale : bloc **« Suivre ce deck dans Anki »**, l'action principale (onglet par
  édition, adresse en police mono avec bouton Copier, consigne « Outils › DeckDock › Ajouter », lien
  « Installer le plugin ») ; puis « En bref » : cartes, langues, licence, **Source** (le champ
  `homepage` du deck, affiché s'il est rempli).
- Sur mobile, le bloc « Suivre dans Anki » passe juste sous l'en-tête du deck.
- L'aperçu garde l'isolation actuelle (iframe sandbox, CSP de `/preview/`, pas de script de carte).
  Pendant la discussion, l'aperçu est resté vide dans le navigateur intégré de l'outil
  (`ERR_BLOCKED_BY_CLIENT`, blocage du navigateur lui-même, le serveur répondait correctement) :
  le constructeur vérifie le rendu et les images dans un vrai navigateur (Chromium de Playwright) et
  corrige si le hub est en cause.

### Icône des decks

- Nouveau champ **facultatif** `icon` dans le format : un seul emoji, écrit par l'auteur dans
  `deckdock.yaml` (template) et présent dans `deck.json` (`deck.icon`). Ajout rétrocompatible à
  `deckdock/1` : les consommateurs non stricts (plugin) l'ignorent déjà ; la spec, le schéma JSON et le
  vérificateur strict l'acceptent ; le vérificateur refuse tout ce qui n'est pas un seul graphème
  emoji.
- Le hub enregistre l'icône de la dernière version reçue et l'affiche partout où un deck apparaît.
- **Repli** sans icône : pastille avec l'initiale du nom, sur une couleur choisie de façon stable à
  partir de l'identifiant du deck, dans une petite palette lisible en clair comme en sombre.

### Lien Source

- Le template remplit `homepage` avec l'adresse de son dépôt GitHub (le hub l'affiche comme
  « Source »). Le hub n'affiche `homepage` que si c'est une URL `https`.

### Connexion et espace auteur (maquette `espace-auteur.html`)

- Connexion : carte centrée, champ e-mail, « Recevoir le lien », mention « le compte est créé à la
  première connexion ». Même traitement pour les écrans « lien envoyé », « lien expiré ».
- Espace auteur : barre latérale (Mes decks, Compte, Guide auteur) ; sur mobile, onglets en haut.
- **Mes decks** : choix du pseudo au premier passage (inchangé sur le fond), liste des decks avec
  icône ou initiale, identifiant, éditions, dernière version et statut en pastille (Publié, En
  attente, Masqué avec motif), bouton « + Nouveau deck ».
- **Détail d'un deck** : tant qu'aucune version n'est reçue, un **guide en 3 étapes** (secret
  `DECKDOCK_TOKEN`, variable `DECKDOCK_HUB_URL` avec l'adresse du hub pré-remplie et copiable, push sur
  main ; la première version attend la validation d'un administrateur), avec lien vers le guide
  complet. Ensuite : versions reçues, éditions et leurs adresses, jeton (affiché une seule fois à la
  création, régénérer, révoquer), retrait du deck. Toutes les fonctions existantes restent.

### Guide (nouveau)

- Une section « Guide » du site, en **fichiers Markdown dans le dépôt du hub**, en français et en
  anglais, mis en forme par le site (titres, encadrés, blocs de code avec bouton Copier, images,
  sommaire des pages du guide en barre latérale).
- Écrit pour quelqu'un qui n'a jamais codé. Pages :
  1. **Comment ça marche** : ce qu'est un deck DeckDock, pourquoi il vit dans un dépôt, ce que
     reçoivent les apprenants, la validation par un administrateur.
  2. **Publier avec GitHub, pas à pas** : ce qu'est GitHub et pourquoi on s'en sert ; créer un
     compte ; créer son deck depuis le template (« Use this template ») ; modifier ses cartes
     directement sur le site de GitHub sans rien installer ; créer le deck sur le hub et ajouter le
     secret et la variable ; suivre la publication dans l'onglet Actions ; corriger une erreur de
     vérification.
  3. **Publier sans GitHub (API)** : le jeton ; la commande `deckdock publish` ; l'appel HTTP brut
     (`curl`, `POST /api/publish/<édition>`, archive tar.gz) ; les réponses possibles du hub et leur
     sens (statuts et codes de l'étape A).
  4. **Le format en détail** : `deckdock.yaml` (dont `icon` et `homepage`), éditions, médias,
     versions, ce qui casse la compatibilité.
- Les captures d'écran de GitHub ne peuvent pas être prises par le constructeur : il écrit des
  étapes qui se suffisent en texte et laisse des emplacements marqués pour les captures, que le
  propriétaire ajoutera.

### Commande `deckdock publish`

- Nouvelle commande de la bibliothèque : `deckdock publish PATH --hub URL`, jeton lu dans
  `DECKDOCK_TOKEN`. Même comportement que l'étape `publish` de l'Action (https obligatoire sauf
  localhost, pas de redirection suivie, messages du hub échappés, limite `--max-bytes`, délai, arrêt
  à la première édition en échec, sortie lisible et `--json`).

## Non-objectifs

- Déposer un deck depuis le navigateur (`.apkg` ou `deck.json` téléversé) : projet à part, plus tard.
- Changer l'API de publication, les règles de validation, les quotas ou le format au-delà de `icon`.
- Refaire l'admin Payload (il garde son thème ; seuls ses écrans de validation existants restent).
- Comptes, statistiques de téléchargement, notes ou commentaires sur les decks.

## Anti-objectifs

- Un site joli mais lent ou inaccessible : le budget Lighthouse et les tests d'accessibilité
  existants restent verts, dans les deux thèmes, sur mobile comme sur ordinateur.
- Affaiblir la sécurité de l'étape A (CSP, isolation de l'aperçu, `/d/` inchangé pour le plugin).
- Casser le plugin Anki : les adresses `/d/<pseudo>/<deck>/<édition>/` et leurs réponses ne changent
  pas, et un `deck.json` avec `icon` reste lisible par le plugin actuel.
- Un guide qui suppose que le lecteur sait ce qu'est un terminal, Git ou YAML sans l'expliquer.

## Contraintes

- Le hub reste construit sur sa copie du starter (Next 16, Payload, shadcn/ui, Tailwind 4). Les
  fichiers du starter modifiés sont listés dans le README du hub, comme aujourd'hui.
- Ordre des chantiers : (1) mode sombre dans `site-starter` ; (2) `icon`, `deckdock publish` et
  `homepage` du template dans `deckdock` et `deckdock-template`, puis re-vendoring de la bibliothèque
  dans le hub ; (3) la refonte du hub, qui reprend le mécanisme de thème du starter.
- Bilingue fr/en partout, y compris le guide.
- Aucune dépendance nouvelle sans raison ; les composants shadcn passent par la CLI (`pnpm ui:add`).

## Approches

- **Où vit le guide** — retenu : **fichiers Markdown dans le dépôt** (versionnés, relus en pull
  request, corrigeables par la communauté, cohérents avec « decks as code »). Écarté : pages dans
  l'admin Payload (modifiables sans déploiement, mais pénibles pour le code et les captures, non
  versionnées, fermées aux contributions).
- **Icône** — retenu : champ `icon` dans le format, écrit dans le dépôt (versionné, relu). Écarté :
  sélecteur d'emoji dans l'espace auteur (seule donnée du deck hors du dépôt).
- **Mode sombre** — retenu : dans le starter, repris par le hub. Écarté : uniquement dans le hub
  (chaque futur site le referait).
- **Construction de la refonte** — un socle commun d'abord (thème, en-tête, pied de page,
  composants : carte de deck, icône/initiale, pastille de statut, bloc d'adresse copiable, mise en
  page du guide), puis les pages reconstruites dessus.

## Décisions prises pendant la relecture (appels du concepteur, à vérifier par le propriétaire)

- **Mise en circulation de `icon`** : la bibliothèque passe en 0.3.0 et accepte `icon` ; on déplace
  le tag `v2` de l'Action sur ce commit (comme pour `publish`) ; seulement ensuite, le template
  utilise `icon`. Le template livre une icône d'exemple (📚) que l'auteur remplace ; une note de
  migration dans le README du template indique que les copies existantes n'ont rien à faire.
- **`homepage` du template** : le compilateur la remplit en CI depuis `GITHUB_SERVER_URL` et
  `GITHUB_REPOSITORY` ; une valeur écrite dans `deckdock.yaml` l'emporte. Rien à faire pour l'auteur.
- **Arrivée du mode sombre dans le hub** : pas de `starter:update` complet (le starter a avancé
  avec d'autres travaux) ; le mécanisme est recopié à la main dans les fichiers du site
  (`src/styles/**`, `src/site/**`, script de démarrage dans le layout), et la liste des fichiers du
  starter modifiés est mise à jour dans le README du hub. Dans le starter, le travail part d'une
  branche issue de `main`.
- **Plusieurs éditions** : le nom, la description et l'icône affichés sont ceux de l'édition dans la
  langue du visiteur, sinon de la première édition ; le tri par nom suit la même règle. Le hub compte
  des **notes**, pas des cartes générées : l'interface dit « notes » (et non « cartes ») et le tri
  « taille » prend l'édition qui en a le plus. Le constructeur peut ajouter des colonnes dénormalisées
  au niveau du deck (nom, icône, nombre de notes) avec une migration.
- **Textes de l'accueil** (décidé par le propriétaire) : dans le code, en fr et en en, comme le
  guide ; les globals Payload `site-content` (accueil) ne servent plus au hub. Les pages légales
  restent dans l'admin (`legal-pages`).
- **Le starter avance avec le site** (décidé par le propriétaire) : tout ce que ce chantier ajoute
  de générique (fonctionnement, pas design) va d'abord dans `site-starter`, puis dans le hub. Ici,
  seul le mode sombre est concerné.
- **Test de déploiement** : la chaîne « Le site ouvre très bientôt » cherchée sur `/fr` par le smoke
  test est remplacée par un texte de la nouvelle page d'accueil.

## Laissé au constructeur

- Le détail des tokens (nuances, ombres, rayons) dans l'esprit des maquettes, et les contrastes.
- La bibliothèque de rendu Markdown (sans HTML brut dans le contenu) et la coloration du code.
- La structure des fichiers du guide et des composants, les textes exacts (dans le ton des maquettes).
- Le comportement exact du carrousel (clavier, nombre de cartes montrées : jusqu'à 3 aujourd'hui).
- La palette de repli des initiales et la validation exacte d'un « seul emoji ».
- Le partage de code entre `deckdock publish` et le script de l'Action.
