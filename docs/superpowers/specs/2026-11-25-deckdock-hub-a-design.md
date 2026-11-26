# Hub DeckDock, étape A : design

Date : 2026-11-25. Statut : brouillon à valider par le propriétaire.
Contexte : [2026-11-25-deckdock-hub-decisions.md](2026-11-25-deckdock-hub-decisions.md) (décisions de
cadrage), [2026-11-24-deckdock-mvp-design.md](2026-11-24-deckdock-mvp-design.md) (vision d'ensemble),
[`spec/deckdock-1.md`](../../../spec/deckdock-1.md) (format, dont la section « Publishing layout »).

## Intention

Aujourd'hui, un deck DeckDock vit dans son dépôt : la CI publie une branche `dist`, et un apprenant
colle l'adresse du dépôt dans le plugin Anki. Personne ne peut découvrir les decks des autres, et un
dépôt supprimé casse ses abonnés.

Le hub est un **site public et gratuit**. On y découvre les decks dans un catalogue. Les auteurs y
publient leurs versions depuis leur CI, et le hub les garde et les sert au plugin. C'est la première
moitié du hub. L'étape B ajoutera les comptes apprenants : abonnements choisis sur le site,
installation et mises à jour automatiques par le plugin relié au compte. **Tout ce qui est construit
ici reste dans B**, et rien n'est jetable.

Le premier utilisateur est le propriétaire, avec ses propres decks. Le hub doit rester simple pour un
auteur qui n'est pas développeur : il crée un compte, colle un jeton dans son dépôt, et c'est tout.

## Objectifs (étape A)

1. **Comptes.** Tout le monde peut créer un compte avec le module `accounts` du starter (lien
   magique). Chaque compte choisit un **pseudo public** (`handle`) à sa première publication.
2. **Decks et jetons de publication.**
   - Un auteur connecté crée un deck dans son espace : il donne l'identifiant du deck (le `deck.id` de
     son `deckdock.yaml`) et reçoit un **jeton de publication propre à ce deck**.
   - Le jeton s'affiche une seule fois. Le hub n'en garde qu'une empreinte et affiche sa date de
     dernière utilisation.
   - L'auteur peut **régénérer** le jeton (l'ancien est invalidé) ou le **révoquer**.
3. **Publication par la CI.**
   - La CI du dépôt envoie chaque édition compilée (`dist/<édition>/`, avec `deck.json` et les
     médias) au hub, avec le jeton dans `DECKDOCK_TOKEN`.
   - Le hub vérifie l'envoi avec le vérificateur officiel `deckdock check`, en mode **non strict**
     comme tout consommateur (le format l'exige : une clé optionnelle ajoutée plus tard ne doit pas
     bloquer la publication), et le refuse avec des erreurs lisibles s'il est invalide.
   - S'il est valide, le hub enregistre une **nouvelle version** de cette édition.
   - L'Action `NayanChauveau/deckdock/action` gagne une commande `publish`, et le template active
     l'étape déjà prévue en commentaire dans `deck.yml`.
4. **Modération.**
   - Un nouveau deck est **en attente** tant qu'un admin ne l'a pas validé. En attente, il n'apparaît
     pas dans le catalogue, mais l'auteur le voit dans son espace et peut le tester par son adresse
     directe.
   - Une fois le deck validé, toutes ses mises à jour sont publiées sans nouvelle validation, et une
     nouvelle édition d'un deck validé est validée d'office.
   - Un admin peut **masquer** un deck à tout moment. Il disparaît alors du catalogue, et son adresse
     de service répond « retiré ». Le masquage se fait depuis l'admin Payload, à côté de la validation.
5. **Catalogue public.**
   - Une liste des decks validés, avec une recherche sur le nom et la description et un filtre par
     langue.
   - Pour chaque deck, une page qui affiche : nom, auteur (pseudo), licence, lien vers le dépôt ou
     page d'accueil, éditions, nombre de cartes, date de la dernière version, description (Markdown
     rendu en HTML sûr), aperçu de 5 cartes (recto et verso rendus), historique des versions.
   - Tout vient du `deck.json` reçu. L'auteur n'a rien de plus à remplir sur le site.
6. **Service au plugin.**
   - Le hub sert chaque deck dans la structure « Publishing layout » du format :
     `<base>/index.json`, `<base>/<édition>/deck.json`, `<base>/<édition>/media/<fichier>`, avec
     `<base>` = `https://<domaine>/d/<pseudo>/<deck-id>`.
   - La page du deck donne l'adresse à coller dans le plugin, une par édition
     (`<base>/<édition>/`). Le plugin actuel l'accepte déjà telle quelle (source « base »).
   - Le service gère `ETag` et `If-None-Match`, comme le plugin l'attend.

## Hors périmètre (étape B ou plus tard)

- Comptes apprenants, abonnements sur le site, liaison du plugin au compte par code, installation
  automatique (étape B).
- Envoi manuel d'un `deck.json` puis d'un `.apkg` depuis le site (versions suivantes).
- Notation et commentaires par la communauté.
- Connexion GitHub ou Google, et preuve GitHub signée (OIDC) en alternative au jeton.
- Stockage chez Backblaze B2 (si le disque du VPS devient un sujet).

## Anti-objectifs

- Un jeton qui fuit et permet d'écrire sur les decks d'un autre auteur, ou de son propre compte
  au-delà du deck visé.
- Un contenu publié qui exécute du code sur le site du hub. Les templates de cartes contiennent du
  HTML et du JavaScript : le catalogue ne doit jamais les exécuter dans la page du site.
- Une version publiée qu'on ne peut plus servir à l'identique à un abonné.
- Un hub payant à faire tourner, ou qui dépend d'un service externe.

## Approches considérées (stockage)

1. **Fichiers sur un volume du VPS, informations dans Postgres.** Retenue par le propriétaire.
   - Gratuit, et couvert par la sauvegarde chiffrée nocturne existante.
   - Le plugin marche sans changement.
   - La limite est le disque du VPS : un deck pèse au plus 500 Mo par édition, mais les decks
     actuels pèsent quelques Mo. Un graphe Grafana de disque par conteneur est en cours, à part.
2. **Fichiers chez Backblaze B2.** Gardée pour plus tard : un service de plus, un coût au-delà de
   l'offre gratuite, et des téléchargements à faire passer par le hub ou par des liens signés.
3. **Pointer vers la branche `dist` de GitHub sans rien stocker.** Rejetée : un dépôt supprimé
   casse les abonnés, et les futurs envois manuels n'auraient pas de place.

## Design

### Plateforme

- Nouveau dépôt **`NayanChauveau/deckdock-hub`** (privé ou public, au choix du propriétaire), créé
  avec les outils du starter (`init-site`, modules `accounts`, sans `orders`, `payments-stripe`,
  `customer-uploads` ni `addresses`), et déployé sur `infra-traefik` selon la procédure « Ajouter un
  site ». (Choix de Claude : un dépôt à part profite de `starter:update` et du kit de déploiement ;
  le monorepo `deckdock` garde le format, la bibliothèque et le plugin.)
- Le code propre au hub vit dans un module du site, **`decks`**, qui dépend d'`accounts`, et suit
  l'architecture du starter (domaine, application, adaptateurs).
- **Vérification des envois.** L'image du conteneur embarque Python et la bibliothèque `deckdock`
  (stdlib seulement), installée depuis le monorepo à une version épinglée. La route d'envoi appelle
  `deckdock check` sur le dossier décompressé et récupère ses erreurs.

### Données (Postgres, collections Payload du module `decks`)

- **`authors`** : le pseudo public d'un compte (`customer` → `handle`, unique, slug de 3 à
  30 caractères, non modifiable après la première publication pour ne pas casser les adresses).
  Choix de Claude : une collection à part plutôt qu'un champ ajouté à `customers`, pour ne pas
  modifier le module `accounts`.
- **`decks`** : auteur, `deckId` (le `deck.id` du format, unique **par auteur**), statut
  (`pending`, `approved`, `hidden`), date de validation, raison du masquage, empreinte du jeton
  (et date de dernière utilisation).
- **`editions`** : deck, code d'édition, dernière version publiée.
- **`versions`** : édition, chaîne `deck.version` reçue, date de réception, résumé (nom,
  description, langues, licence, page d'accueil, nombre de notes, taille), et la liste des fichiers
  (nom → empreinte sha256, taille). Une version est **immuable** une fois enregistrée.
- Le **catalogue** lit la dernière version de chaque édition des decks `approved`.

### Fichiers (volume du VPS)

- Les fichiers sont rangés par empreinte : `blobs/<sha256[:2]>/<sha256>`, pour les `deck.json`
  comme pour les médias. Un fichier identique n'est stocké qu'une fois, même d'une version à
  l'autre, ou d'un deck à l'autre.
- Une version référence ses fichiers par empreinte. Rien n'est jamais réécrit en place.
- Le volume est déclaré dans `infra-traefik` (`sites.json`) pour la sauvegarde nocturne, comme le
  volume média d'un site existant.
- Les fichiers qu'aucune version ne référence plus ne sont pas supprimés dans l'étape A.

### Publication

- `POST /api/publish/<édition>`, avec `Authorization: Bearer <jeton>`. Le corps est une archive
  `tar.gz` du dossier `dist/<édition>/`.
- Ordre des contrôles :
  1. jeton valide et non révoqué, sinon 401 ;
  2. deck non masqué ;
  3. taille de l'archive dans les limites du format (500 Mo par édition au plus), sinon 413 ;
  4. décompression sûre : aucun chemin qui sort du dossier, aucun lien symbolique, nombre de
     fichiers borné, taille décompressée bornée ;
  5. `deckdock check` en mode non strict ;
  6. le `deck.id` et l'édition du `deck.json` correspondent au deck du jeton et à l'URL, sinon 409.
- Si une version avec la même chaîne `deck.version` existe déjà pour cette édition, l'envoi est
  accepté sans rien créer (réponse 200 « déjà publiée »). Une CI relancée ne crée donc pas de
  doublon.
- Réponse en JSON, lisible par l'Action : statut, version, nombre de notes, et le statut du deck
  (« en attente de validation » ou « publié »), plus les erreurs de vérification ligne par ligne.
- Limite de débit par jeton (Traefik et application), car c'est l'opération la plus coûteuse.
- **Action `publish`** (monorepo `deckdock`) : elle envoie chaque `dist/<édition>/` au hub, avec
  `DECKDOCK_TOKEN` et l'adresse du hub (une valeur par défaut, modifiable par entrée). Elle échoue
  avec les erreurs du hub si un envoi est refusé.
- **Template** : l'étape « Publish to DeckDock hub » de `deck.yml` est activée, sur `main`
  uniquement. Elle ne tourne que si le secret `DECKDOCK_TOKEN` existe, pour qu'un dépôt sans jeton
  garde une CI verte.

### Service au plugin

- Routes publiques en lecture, sous `/d/<pseudo>/<deck-id>/` :
  - `index.json` : construit à partir des dernières versions, au format `deckdock-index/1` ;
  - `<édition>/deck.json` et `<édition>/media/<fichier>` : servis depuis les fichiers de la
    dernière version.
- En-têtes :
  - `ETag` = empreinte du fichier, avec réponse 304 sur `If-None-Match` ;
  - `Cache-Control` court sur `index.json` et `deck.json`, long sur les médias (désignés par leur
    empreinte côté stockage) ;
  - `Content-Type` correct, et `X-Content-Type-Options: nosniff`.
- Un deck en attente est servi à son adresse directe (pour que l'auteur teste), mais il n'est ni
  listé ni indexé (`noindex`). Un deck masqué répond 410.
- Les médias sont servis en téléchargement pur (`Content-Disposition` sûr, CSP stricte sur ces
  routes) : un SVG ou un HTML déposé comme média ne s'exécute jamais dans le domaine du hub.

### Pages

- **Catalogue** `/{locale}/decks` : recherche et filtre de langue, liste paginée.
- **Page de deck** `/{locale}/d/<pseudo>/<deck-id>`.
  - La description Markdown est rendue en HTML assaini.
  - L'**aperçu** de 5 cartes rend le recto et le verso dans un `iframe` `sandbox` sans
    `allow-same-origin`, servi depuis une route de prévisualisation à CSP stricte, pour que le
    HTML, le CSS et le JavaScript des cartes ne touchent jamais au site. (Choix de Claude : c'est
    la seule façon sûre de montrer des cartes qui contiennent du JavaScript.)
  - Pour chaque édition : l'adresse à copier dans le plugin, avec un bouton « Copier ».
- **Espace auteur** `/{locale}/compte/decks`, réservé aux comptes connectés :
  - choisir son pseudo ;
  - créer un deck (son `deck.id`) et obtenir le jeton ;
  - régénérer ou révoquer le jeton ;
  - voir le statut (en attente, publié, masqué), les éditions et les versions reçues ;
  - voir la marche à suivre pour la CI (le secret `DECKDOCK_TOKEN` et la ligne du workflow).
- **Admin Payload** : listes des decks en attente, validation, masquage avec raison. La validation
  et le masquage sont réservés aux admins qui ont passé la double authentification, comme le reste
  de l'admin.
- Pages en français et en anglais, comme le starter.

### Comptes

- Le module `accounts` du starter tel quel : lien magique, « Mon compte », suppression.
- **Suppression d'un compte auteur.** Ses decks passent à l'état masqué et ne sont plus servis,
  son pseudo reste réservé, et ses jetons sont révoqués. (Choix de Claude : le RGPD porte sur ses
  données personnelles ; le contenu publié sous licence ouverte peut être transmis plus tard à un
  autre auteur, mais l'étape A se contente de le retirer.) Les apprenants qui l'utilisaient
  gardent leurs cartes dans Anki.

### Sécurité (résumé)

- Jetons : longs (au moins 32 octets aléatoires), avec un préfixe reconnaissable (`ddk_`) pour les
  scanners de secrets. Stockés en empreinte (sha256), comparés en temps constant, propres à un
  seul deck.
- Archives : décompression sûre, limites de taille et de nombre, aucun lien.
- Contenu des cartes : jamais exécuté dans le domaine du site (iframe isolé pour l'aperçu, médias
  servis en téléchargement, CSP stricte).
- Les règles du starter s'appliquent : maintenance, CSRF, séparation admin et visiteurs.

### Tests

- Domaine et cas d'usage : jetons, statuts et transitions, idempotence de la publication.
- Intégration Postgres : collections, unicité des pseudos et des decks, versions immuables.
- HTTP :
  - publication valide et invalide (jeton faux ou révoqué, archive piégée, `deck.json` invalide,
    mauvais deck, doublon de version) ;
  - service au plugin (index, deck, média, ETag et 304, deck en attente, deck masqué 410) ;
  - catalogue et page de deck.
- Test de bout en bout réel : la bibliothèque du plugin (`deckdock_addon.sources`) récupère un
  deck publié sur un hub de test, avec l'adresse donnée par la page du deck.
- Navigateur : catalogue, page de deck avec aperçu isolé, espace auteur, avec axe pour
  l'accessibilité.
- Monorepo `deckdock` : tests de l'Action `publish` contre un faux serveur.

## Précisions après relecture (choix de Claude, à vérifier par le propriétaire)

1. **Même version, contenu différent.** La publication compare l'empreinte de chaque fichier.
   - Même `deck.version` et même contenu : 200 « déjà publiée », rien n'est créé.
   - Même `deck.version` avec un contenu différent : 409 « cette version existe déjà avec un autre
     contenu ».
   - La version `"dev"` est refusée à la publication (422), car elle n'identifie rien. Le template
     tamponne déjà date + commit.
2. **Compatibilité des types de cartes.** Le hub compare la structure de chaque type de carte avec
   la dernière version publiée de la même édition, selon les règles de « Changing a published
   notetype » du format :
   - un champ ajouté à la fin est accepté, et la réponse le signale (synchronisation complète chez
     les abonnés) ;
   - toute autre modification de structure est refusée (409), avec un message qui explique de créer
     un nouveau type de carte.

   Sinon, l'auteur bloquerait ses abonnés sur l'ancienne version sans le savoir. Le message répète
   la règle déjà écrite dans l'`AGENTS.md` du template.
3. **Aperçu des cartes.** Un rendu « au mieux », pas une copie exacte d'Anki. Il gère
   `{{Champ}}`, `{{cloze:Champ}}` (première suppression masquée au recto, révélée au verso),
   `{{FrontSide}}`, les sections conditionnelles `{{#Champ}}…{{/Champ}}` et
   `{{^Champ}}…{{/Champ}}`, et ignore les autres filtres.
   - Les cartes montrées sont les 5 premières notes de l'édition affichée, avec au plus une par type
     de carte en premier pour montrer la variété.
   - Le rendu se fait côté serveur, puis s'affiche dans l'`iframe` isolé.
4. **Vérification Python.** `python3` (sans pip) est ajouté à l'image de production du hub, et la
   bibliothèque `deckdock`, en Python standard seulement, est copiée dans l'image à une version
   épinglée. Pas de service en plus.
   - L'archive est décompressée dans un dossier temporaire du **volume de données**, pas en
     mémoire, puis supprimée.
   - Limite pratique d'un envoi : **100 Mo** compressés au démarrage, réglable, sous les 500 Mo du
     format.
   - Ces écarts avec l'image durcie du starter sont documentés dans le dépôt du hub.
5. **Version de l'Action.** La commande `publish` arrive dans l'Action sous l'étiquette `v2`
   existante : c'est un ajout compatible, rien ne change pour qui ne l'appelle pas. L'entrée
   `hub-url` est obligatoire tant que le domaine n'est pas choisi ; elle aura ensuite le domaine
   pour valeur par défaut.
6. **Deck à plusieurs éditions dans le catalogue.** Une seule ligne par deck dans la liste. Le
   nom, la description et les langues affichés sont ceux de l'édition qui correspond à la langue
   du visiteur, sinon de la première édition par ordre alphabétique. La page du deck permet de
   choisir l'édition affichée.
7. **Retrait d'une édition.** Il n'existe pas dans l'étape A : seul le deck entier peut être
   masqué. Il viendra avec les envois manuels.

## Laissé au constructeur

- Les noms exacts des fichiers, des routes internes et des champs, dans le respect des conventions
  du starter.
- La présentation des pages, avec le design system du starter.
- Le mécanisme exact de recherche (`LIKE` simple ou plein texte Postgres) tant qu'il cherche dans
  le nom et la description.
- Le format exact des erreurs JSON de la publication, tant que l'Action peut les afficher ligne par
  ligne.

## À fournir par le propriétaire au moment du déploiement

- Le nom de domaine du hub et son enregistrement DNS.
- Les secrets du site (le kit du starter les liste), et le choix privé ou public du dépôt.
- Le règlement de la facturation GitHub Actions, sans quoi la CI ne tourne pas.
