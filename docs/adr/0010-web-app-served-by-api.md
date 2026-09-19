# ADR-0010 — The web app is served by the `api` function, from its image

- Status: proposed
- Date: 2026-09-19 · Deciders: Katlego

## Context

The agreed [infrastructure design](../design/infrastructure.md) hosts the React web app as
static files in a private S3 bucket behind CloudFront. Writing the web design showed three
problems with that.

- **The kit's release checks don't reach it.** The release pipeline runs pa11y (with axe) and
  ZAP only against services in `realm.toml` marked `ui = true`, at the service's own URL
  (`release.sh`, the accessibility and DAST steps). A site in S3 isn't a service, so NFR-009's
  measurement, and the DAST scan of the pages tenants actually use, would have to be rebuilt
  outside the kit.
- **It needs its own deploy path.** The bootstrap's release and promote roles push images and
  update functions. They can't write to a bucket or invalidate CloudFront. The site would need a
  build job, wider CI roles, and its own promotion from staging to production.
- **It escapes the release's guarantees.** The kit's images are built once, scanned, signed, and
  deployed by digest from staging to production. Files synced to a bucket are none of that.

The `api` already runs behind API Gateway on its own HTTPS URL.

## Options considered

1. **Do nothing: S3 and CloudFront**, as designed. There's a CDN near South Africa, but the three
   problems above remain.
2. **Amplify Hosting.** That's another service with its own build pipeline and bill, and the
   same three problems.
3. **The `api` function serves the web app** (proposed). The app is built in the `api` image's
   first stage (Node), and its files are copied into the Python stage.
   - The function answers `GET /` and any path outside `/api/` with those files.
   - The API moves under `/api/`, and `/health` stays for the kit.
   - The web app is then in the `api`'s image: built, scanned, signed and promoted with it. With
     `ui = true`, pa11y and ZAP check it on every release.

## Decision

Proposed: **the web app is served by the `api` function from its own image, at the root of the
HTTP API's URL. The API's routes move under `/api/`, and `realm.toml` marks the `api` service
`ui = true`.**

- **Hashed assets** are sent with `Cache-Control: public, max-age=31536000, immutable`.
- **`index.html`** is sent with `no-cache`.
- **Every HTML response** carries the security headers: a content security policy, HSTS,
  `X-Content-Type-Options` and `frame-ancestors 'none'`.
- **The per-environment settings** (the user pool and app client IDs) come from `GET
  /config.json`, which the function answers from its environment. That way one image serves
  both staging and production.

## Consequences

- **In `infrastructure.md`:** the web bucket and CloudFront go, and so do the HTTP API's CORS
  settings, because the app and the API share an origin. The documents bucket's CORS allows the
  API's own domain.
- **In `api.md`:** every endpoint moves from `/x` to `/api/x`. `/health` and `/config.json`
  stay at the root.
- **The `api` image grows** by the built app, a few hundred KB, and its Dockerfile gains a Node
  stage.
- **Static files cost Lambda invocations.** Browsers cache the hashed assets, so a returning
  visit costs about one request, well within the always-free allowance.
- **There's no CDN.** Pages come from Ireland, like the API (ADR-0001). The first load is slower
  from South Africa, and later ones hit the cache.
- **A later move to a CDN** is a new ADR, with its own deploy path in the kit.
