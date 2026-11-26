# Publish to the DeckDock hub

The DeckDock hub hosts decks in the `deckdock/1` format. Learners paste a deck's address into the
DeckDock Anki add-on, and the catalogue lists approved decks. This guide shows how to publish a deck
from a repository created with [deckdock-template](https://github.com/NayanChauveau/deckdock-template)
(or any repository whose CI produces `dist/<edition>/deck.json`).

## Before you start

- A deck repository that compiles to `dist/<edition>/deck.json` (and `dist/<edition>/media/`).
- The hub's address (`https://...`, no trailing path). The hub operator gives it to you. Plain
  `http` is accepted only for `localhost`, for local testing.
- The workflow's publish step uses the `publish` command of `NayanChauveau/deckdock/action@v2`. The
  step needs a version of action v2 that includes the `publish` command; the hub operator
  confirms it is available.

## One-time setup

1. **Create an account.** Open the hub, go to the account page and ask for a sign-in link: enter
   your email, then open the link you receive. It works once and expires after 15 minutes. There is
   no password.
2. **Choose a handle.** It appears in your decks' addresses (`/d/<handle>/<deck-id>/...`). It is
   3 to 30 characters, lowercase letters, digits and single dashes, and some names are reserved.
   **The handle cannot be changed once chosen**; if you made a typo, ask the hub admin.
3. **Create a deck.** In your decks page (`/compte/decks`), enter a deck id. It must be the same as
   `deck.id` in your `deckdock.yaml`: the hub refuses an upload whose `deck.id` differs from the
   token's deck.
4. **Copy the token.** It starts with `ddk_` and is shown **once**, right after the deck is created.
   Copy it before leaving the page; the hub keeps only its hash. If you lose it, regenerate it (see
   below).
5. **Configure your deck repository** (Settings, Secrets and variables, Actions):
   - secret `DECKDOCK_TOKEN`: the token;
   - variable `DECKDOCK_HUB_URL`: the hub's address, as shown on your deck's page.
6. **Push to `main`.** The template's `Deck` workflow runs the tests, compiles, checks, and then
   publishes each edition to the hub. The publish step only runs on pushes to `main`, and only when
   both the secret and the variable exist.

Without the secret and the variable, the workflow behaves as before and publishes nothing.

## What happens when you publish

For each folder `dist/<edition>/` that contains a `deck.json`, the action uploads a `tar.gz` to
`POST <hub>/api/publish/<edition>`, in alphabetical order, and stops at the first edition that fails.
The hub checks the upload with `deckdock check` and replies; errors show up in the workflow log as
`::error::<where>: <message>`, one per problem.

| Situation | Result |
| --- | --- |
| First version of a new deck | Accepted, then **waits for admin approval** (`pending_review`). The deck is not in the catalogue yet, but you can already test it with its address. |
| Later versions of an approved deck | Published directly. |
| Same edition and version, same files (a re-run of the workflow) | Nothing changes (`already_published`). |
| Same edition and version, different files | Refused (409). A new push generates a new version. |
| `deck.version` is `"dev"` | Refused (422). Only CI-generated versions are accepted, so publish from CI, not from a local build. |
| `deck.id` differs from the token's deck, or `deck.edition` from the address | Refused (409). |
| Unreadable archive, extra files, unsafe paths, a `deck.json` that fails `deckdock check` | Refused (422), with the checker's messages. |
| Removing, renaming or reordering a notetype's fields, adding or removing templates, changing `kind` | Refused (409): the structure of a published notetype is frozen. Create a new notetype (new `id`) instead. |
| Adding a field at the **end** of a notetype | Accepted with a warning: subscribers will need a full AnkiWeb sync. |
| Hidden deck | Refused (410). |

Text, tags, notes, template text and CSS can change freely. See "Changing a published notetype" in the
[format specification](../spec/deckdock-1.md).

### Limits

- 100 MB per upload (compressed). Decompressed: at most 500 MiB and 20 000 files; `deck.json` at most
  50 MiB. The archive contains only `deck.json` and `media/<file>`.
- At most 30 publishes per deck every 10 minutes. If the hub answers 429 or 503, wait for the
  `Retry-After` delay and re-run the workflow; re-runs are safe.
- Your token is checked before anything else, so a wrong or revoked token gives 401.

## Testing and sharing a deck

Once the first version is received, your deck's page in your account shows its address
(`<hub>/d/<handle>/<deck-id>/<edition>/`) with a copy button. Paste it in the add-on to test it
before approval. The page also shows the received versions and when the token was last used.

After approval the deck appears in the catalogue, with a page showing its description, editions and
a preview of up to five notes.

## Token: regenerate or revoke

On your deck's page, **Regenerate** gives a new token (shown once) and the old one stops working
immediately; update the `DECKDOCK_TOKEN` secret. **Revoke** disables the token until you regenerate
one. Both ask for a confirmation. If a token leaks, regenerate it.

## Hidden decks and deleted accounts

An admin can hide a deck, with a reason shown on its page. A hidden deck disappears from the
catalogue and its addresses answer 410; uploads are refused. If you delete your account, your decks
are hidden and their tokens revoked; they cannot be approved again, and your handle stays reserved.
