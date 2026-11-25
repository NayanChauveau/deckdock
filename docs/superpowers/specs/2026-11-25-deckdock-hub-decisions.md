# DeckDock hub: decisions so far (2026-11-25)

Not a design yet. These are the decisions taken with the user before the hub design. The hub
design comes after the starter `accounts` module.

## Target

- Accounts for **authors and learners**. A learner browses the hub, picks decks and editions
  (languages) on the website, and the Anki add-on, linked to the account, installs and updates
  them by itself.
- It is delivered in two milestones:
  - **A**: accounts plus author side (register a GitHub repo, catalogue, versions pushed by CI).
  - **B**: learner subscriptions plus add-on linking.

  A must be a strict part of B: one account system and a data model designed for B from day one,
  with nothing thrown away.
- The subscription and sync API stays independent of Anki: it is the API a future DeckDock app
  will use.

## Deck intake

- **MVP**: decks arrive only from their GitHub repo's CI. The hub **stores a copy of every
  version** itself, instead of pointing at the repo's `dist` branch, so later intake paths share
  the same storage.
- Next version: upload of a compiled `deck.json` plus media from the website.
- Later: upload of an `.apkg`, which the hub converts to `deckdock/1`.

## Authentication

- One account system for authors and learners. Sign-in methods: GitHub, Google, email magic
  link, and possibly email + password.
- CI publishing proves the repo identity with a GitHub Actions OIDC token, so authors need no
  stored secret. The repo must be registered by a signed-in owner.
- The add-on links to an account with a device-code flow ("enter this code on the website").
- Library: **Better Auth**, self-hosted inside the app, with accounts stored in the site's
  Postgres. It is free at any size, and the data stays on the user's servers. External services
  (Clerk, Auth0...) and a separate auth server (Keycloak...) were rejected.

## Platform

- The hub is built from **site-starter** (Next.js + Payload + Postgres) and deployed on
  **infra-traefik**. Hub uploads are checked with the reference Python `deckdock check`, run
  inside the container.
- The public accounts are first built **into site-starter as an optional `accounts` module**
  (also wanted for manon-karsenti, matching infra-traefik TODO P3). The hub is then created
  from the updated starter.
- Hub-specific auth (CI OIDC, add-on device flow) lives in the hub, not in the starter.

## Idea for later

- The Better Auth ↔ Payload bridge built for the starter `accounts` module could become a
  standalone, published Payload plugin (user idea, 2026-11-25). Not planned; keep the bridge
  self-contained so it can be extracted.
