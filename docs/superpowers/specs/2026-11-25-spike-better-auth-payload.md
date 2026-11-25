# Spike: Better Auth next to Payload 3 in site-starter

Date: 2026-11-25. Throwaway spike, never merged. Clone kept at
`/private/tmp/claude-501/-Users-nayanchauveau-Documents-projets-perso-anki-deckdock/1905c080-ce51-46b2-87d0-07e9a5258f64/scratchpad/spike-auth`
(uncommitted changes on `main` of the clone; containers and volume removed with `docker compose -p spikeauth down -v`).

Stack: site-starter `main` at `394e47c` (Payload 3.90.2, Next 16.4.6, `@payloadcms/db-postgres`, `push: false`,
payload-totp 3.0.7), **better-auth 1.7.28**, pg 8.20.0, kysely 0.29.9 (the version better-auth already pulls in).

## Verdict

**Works, with caveats.** Better Auth lives in its own `auth` Postgres schema, Payload's migrations and schema diff
ignore that schema, a Payload custom strategy resolves `req.user` to a `customers` doc from the Better Auth session
(cookie or bearer), and the admin (`users`, TOTP) is unaffected. The caveats are all module-design work, not
blockers: CSRF parity in the strategy, typing of `req.user` in the core, the payload-totp redirect for customers,
`/me` with bearer tokens, cross-schema deletion, rate-limit storage.

## What was proven

| # | Check | Result |
| --- | --- | --- |
| 1 | Better Auth tables in a separate schema, created by its own migration | `database.schemaName: 'auth'` (new in 1.7). `getMigrations()` (`better-auth/db/migration`, same engine as the `auth migrate` CLI) emits `create schema if not exists "auth"` + `auth.user/session/account/verification/deviceCode`. |
| 2 | Payload migrations leave `auth` alone | `payload migrate:create add_customers` produced only `customers` + `payload_*_rels` columns; no mention of `auth`. `payload migrate` ran fine with `auth.*` present. drizzle-kit `pushSchema` (the dev push / migration test engine) proposed nothing for `auth` (only the 4 known `SET DEFAULT 0` quirks the starter test already filters). `tests/migrations.integration.ts` **passes** on a fresh `_test` DB with 3 migrations (initial, auth schema, customers). `migrate:fresh` only drops `public` (`drop schema public cascade`), so it does not reset `auth` either. |
| 3 | `customers` collection + custom strategy | `auth: { disableLocalStrategy: true, strategies: [betterAuthStrategy] }`, `access.admin: () => false`. Doc created lazily on first authenticated request. `/api/customers/me` returns the customer with `strategy: "better-auth"`. |
| 4 | Handler at `/api/auth/[...all]` | Route file under `src/app/(frontend)/api/auth/[...all]/route.ts` re-exporting the module handler; wins over Payload's `(payload)/api/[...slug]`. Architecture, CSP, modules tests pass. |
| 5 | E2E (curl) | sign-up / sign-in email+password OK; magic link (logged URL) OK, creates customer 2 on first use; sign-out invalidates. Admin login + `/admin` 200 (TOTP bypass) and 307 to `/admin/setup-totp` with TOTP on (unchanged behaviour). Customer cookie on `/admin` → 307 `/admin/unauthorized` (bypass on) or → `/admin/setup-totp` (TOTP on, see pitfalls). `/api/users/me` with customer cookie → `null`; `/api/customers/me` with admin cookie → `null`; customer cannot list `users` or `orders`. Both cookies at once → `req.user` is the admin (users strategies run first). |
| 6 | `deviceAuthorization` | `auth."deviceCode"` lands in the `auth` schema. Full RFC 8628 flow worked: `/device/code` → signed-in `GET /device?user_code=` (claim, required since 1.7) → `/device/approve` → `/device/token` returns a session token. With the `bearer` plugin that token authenticates Payload calls (`Authorization: Bearer`). Directly relevant for the Anki add-on login. |

## Config that worked

Better Auth instance (module-owned, own small pool on the same DB):

```ts
// src/modules/accounts/auth.ts
const pool = new pg.Pool({ connectionString: process.env.DATABASE_URL, max: 5 })
export const auth = betterAuth({
  baseURL: process.env.BETTER_AUTH_URL ?? process.env.APP_URL,
  secret: process.env.BETTER_AUTH_SECRET,
  basePath: '/api/auth',
  trustedOrigins: [process.env.APP_URL!],
  database: { dialect: new PostgresDialect({ pool }), type: 'postgres', schemaName: 'auth', transaction: true },
  emailAndPassword: { enabled: true, minPasswordLength: 12 },
  advanced: { cookiePrefix: 'customer' },          // cookie: customer.session_token (HttpOnly, Lax)
  plugins: [magicLink({ sendMagicLink }), deviceAuthorization({ verificationUri: '/device' }), bearer()],
})
```

Payload strategy and collection:

```ts
export const betterAuthStrategy: AuthStrategy = {
  name: 'better-auth',
  authenticate: async ({ headers, payload }) => {
    const session = await auth.api.getSession({ headers })
    if (!session) return { user: null }
    const { docs } = await payload.find({ collection: 'customers',
      where: { authUserId: { equals: session.user.id } }, limit: 1, depth: 0, overrideAccess: true })
    const customer = docs[0] ?? await payload.create({ collection: 'customers', overrideAccess: true,
      data: { authUserId: session.user.id, email: session.user.email, name: session.user.name } })
    return { user: { ...customer, collection: 'customers', _strategy: 'better-auth' } }
  },
}
export const Customers: CollectionConfig = {
  slug: 'customers',
  auth: { disableLocalStrategy: true, strategies: [betterAuthStrategy] },
  access: { admin: () => false, read: adminOrSelf, update: adminOrSelf, create: admin, delete: admin },
  fields: [{ name: 'authUserId', type: 'text', required: true, unique: true, index: true },
           { name: 'email', type: 'email', required: true }, { name: 'name', type: 'text' }],
}
```

Route (architecture rule: `(frontend)/api` routes only re-export a module handler and are listed in its `routes`):

```ts
// src/app/(frontend)/api/auth/[...all]/route.ts
export { GET, POST } from '@/modules/accounts/http/auth-route'   // = toNextJsHandler(auth)
```

Core change needed for bearer tokens (`src/core/payload/config.ts`):

```ts
auth: { jwtOrder: ['JWT', 'cookie'] },   // Payload must not try to decode 'Authorization: Bearer'
```

Better Auth DDL inside a Payload migration (single ops step, proven on a fresh DB):

```ts
// src/migrations/20261125_092000_auth_schema.ts — SQL from getMigrations().compileMigrations()
export async function up({ db }: MigrateUpArgs) { await db.execute(sql.raw(`create schema if not exists "auth"; ...`)) }
export async function down({ db }: MigrateDownArgs) { await db.execute(sql`DROP SCHEMA IF EXISTS "auth" CASCADE;`) }
```

After it ran, Better Auth's own `getMigrations()` reported nothing to create or add: the two agree.

## Pitfalls hit

1. **CSRF parity.** Payload's cookie extraction refuses a cookie unless `Origin` is in `csrf` or `Sec-Fetch-Site`
   is same-origin/same-site/none. The custom strategy has no such check: a `PATCH /api/customers/1` with
   `Origin: https://evil.test` and the customer cookie succeeded. `SameSite=Lax` blocks this in real browsers for
   cross-site fetch, but the strategy must replicate Payload's rule when it reads the cookie (bearer is fine).
2. **Field access.** The customer could PATCH its own `authUserId` and `email`. Those fields need `update: () => false`
   (email changes go through Better Auth).
3. **`req.user` becomes `User | Customer`.** `tsc` fails in the core: `src/core/payload/access.ts` (`isAdmin`) and
   `src/core/http/maintenance.ts` read `req.user.role`. Runtime is safe (customers have no role) but the core must
   narrow on `req.user.collection === 'users'`.
4. **payload-totp redirects customers.** With TOTP on, a customer opening `/admin` is sent to
   `/admin/setup-totp` (200, form rendered) instead of `/admin/unauthorized`. The setup endpoint refuses other
   collections (`user.collection !== pluginOptions.collection`), so no secret can be written, but it is confusing
   and must be covered by a test. Access wrappers are fine: `totpAccess` passes users of other collections through.
5. **Bearer + `/me`.** Payload's `jwtOrder` includes `Bearer`, so `/api/customers/me` with a Better Auth bearer
   token threw `JWTInvalid` (500) even though the strategy had resolved the user; list endpoints worked. Fixed by
   `auth.jwtOrder: ['JWT', 'cookie']` (admin unaffected: it uses the cookie).
6. **Dev HMR does not reload the Payload config.** After editing the Better Auth options, the strategy kept the
   old `auth` instance until `next dev` was restarted.
7. **Generated migration did not load.** `migrate:create` wrote `import { MigrateUpArgs, MigrateDownArgs, sql }`;
   under `--disable-transpile` Node failed (`does not provide an export named 'MigrateDownArgs'`). It needed
   `type` imports like the initial migration. This comes from the starter, not from Better Auth.
8. **Cross-schema FK is not allowed.** A `customers.auth_user_id → auth.user(id) ON DELETE CASCADE` FK makes
   drizzle propose `ALTER TABLE "customers" DROP CONSTRAINT ...`: the starter migration test fails, and a dev push
   would drop it.
9. **Lazy creation race.** Two parallel first requests can both try to create the customer; the unique index
   protects data, but one request would fail. Use an upsert/retry, or create in a Better Auth hook.
10. **Release age.** pnpm 11 added `minimumReleaseAgeExclude` entries for `better-auth@1.7.28` (released the day
    before). Pin a patch older than the policy in the real module.
11. Payload's `migrate:create` with no change waits for an interactive prompt (hung a scripted run).
12. Better Auth accepts requests **without** an `Origin` header (curl sign-up worked); a wrong `Origin` gets
    403 `INVALID_ORIGIN`. This differs from the starter's `sameOrigin()` guard, which requires `Origin`.

## What the real `accounts` module needs

- **Migrations ordering (CI + Docker ops image).** Commit Better Auth's DDL as a hand-written Payload migration
  (generated by `getMigrations().compileMigrations()`, reviewed), named before any migration that relies on it.
  Then the existing one-off `migrate` service (`payload migrate`) stays the only step; nothing new in the ops
  image or `release.py`. Add a test that `getMigrations()` reports nothing to do on a migrated DB (drift check,
  next to `tests/migrations.integration.ts`). Plugin upgrades (new columns) mean a new migration from the diff.
  `migrate:fresh` does not touch `auth`: tests that reset the DB must drop it too.
- **Module removal.** `pnpm module:remove accounts` must also handle the `auth` schema migration and the
  `jwtOrder`/typing changes in the core. Register the module in `starter.json` (`tests/starter-coverage.test.ts`
  failed with `piece accounts`).
- **CSP / proxy.** No conflict: `src/proxy.ts` only matches `/fr`, `/en`, `/admin`; `/api/*` gets the API header
  set from `next.config.mjs` (`default-src 'none'; sandbox`), fine for JSON and redirects. The magic-link verify
  is a 302 to the site. Login/sign-up pages under `/fr|/en` post to `/api/auth` (`connect-src 'self'`, OK). OAuth
  later: redirects are top-level navigations, so no CSP change, but `form-action 'self'` blocks a form POST that
  redirects to a provider; use links or fetch + `window.location`.
- **Request guards.** Better Auth does its own origin check (`trustedOrigins`); add the starter's body size limit
  and `privateHeaders` (no-store) around the handler if wanted. Make the strategy enforce Payload's CSRF rule.
- **Rate limiting.** The Traefik `-auth` router only lists Payload paths; add `/api/auth/sign-in/*`,
  `/sign-up/*`, `/forget-password`, `/magic-link/*`, `/device/*` (device token polling needs a looser limit).
  Better Auth's own limiter is on only in production, with `memory` storage by default (per process, lost on
  deploy, fine for one web container); `storage: 'database'` adds a `rateLimit` table to `auth`. Set
  `advanced.ipAddress.ipAddressHeaders: ['x-real-ip']` to match `requestIdentity()` behind Traefik.
- **Cookie names.** `customer.session_token` (and `customer.session_data` if cookie cache is turned on) next to
  Payload's `payload-token`; both `HttpOnly; SameSite=Lax`, Better Auth sets `Secure` itself on https. Keep a
  distinct prefix so a site never confuses the two.
- **Deletion cascade.** Inside `auth`, FKs cascade (sessions, accounts). For `public.customers` and the customer's
  Payload data, use `user.deleteUser` with a `beforeDelete`/`databaseHooks.user.delete` hook that deletes through
  Payload (orders keep their own data or get anonymised), or a trigger on `auth.user` (drizzle ignores triggers).
  Not an FK (pitfall 8). Admin-side deletion of a `customers` doc must also delete the Better Auth user.
- **Creation.** Either keep lazy creation in the strategy (proven, add upsert) or a `databaseHooks.user.create.after`
  hook; the hook needs `getPayload` through a dynamic import to avoid the config ↔ auth import cycle (not tested).
- **Secrets / env.** `BETTER_AUTH_SECRET` (32+ chars) and `BETTER_AUTH_URL` (= `APP_URL`) in deploy secrets and
  config validation; real email sending via the starter's email adapter (verification, reset, magic link).
- **Tests.** HTTP tests for: customer cannot reach `/admin` (both TOTP modes), admin is not a customer, CSRF
  refusal, bearer `/me`, device flow, removal of the module.

## Rough effort

About **3 to 5 days** for a production-grade module: 1 day for the module skeleton, migration and typing
changes in the core; 1 day for the strategy hardening (CSRF, upsert, field access, deletion hooks); 1 day for the
public pages (sign-up/in, reset, magic link, device verify page) and emails; 1 to 2 days for tests (HTTP,
integration, architecture/module removal), the Traefik limits and deploy secrets. OAuth providers add about half
a day each once credentials exist.
