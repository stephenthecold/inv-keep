# Changelog

All notable changes to Inv-Keep are recorded here. Versions are tagged in git
(`vX.Y.Z`) and the running version is shown in the app footer and Settings.

## [1.35.0] — 2026-06-07
- **Order note / reason is now visible where orders are reviewed.** The mobile
  app sends a required note as the justification for a $0 warranty / no-charge
  order. The web **History** page (and the scan page's "Recent activity") now
  shows that note under the part name — tinted like a warning callout when the
  line is $0, so warranty/NCR cases jump out, and neutral otherwise. (This app
  has no separate per-order detail page; History is where orders are reviewed.)
- **Mobile responses carry the note.** `GET /mobile/orders/recent` and
  `GET /mobile/orders/zero-total` now include a `note` field per order (the
  device-supplied reason, with the internal `| custom` marker stripped), so the
  Android Recent-orders screen can badge annotated rows.

## [1.34.0] — 2026-06-07
- **Mobile app: catalog items now show their real icon, not a generic glyph.**
  The web "Edit item" dropdown sets a preset icon (`svg:network-cable`, …) for
  the vast majority of items, but the mobile API only ever exposed *uploaded*
  icons, so every preset item returned `icon_url: null` and the Android app
  fell back to a placeholder. Added `GET /mobile/icons/{slug}` that serves the
  built-in preset SVGs (public, sandboxed, year-long immutable cache, keeps
  `stroke="currentColor"` so the client tints to the theme), and `ItemDto.icon_url`
  now falls back upload → preset → null. Per-item uploads still take priority.

## [1.33.1] — 2026-06-07
- **Items → Manage mode: the category buttons actually work now.** "+ Add
  sub-category", "Rename / move", and the per-card Rename / + Sub buttons did
  nothing when clicked. Their inline `onclick` passed the category name through
  the `tojson` filter, which emits double quotes — and those collided with the
  double-quoted `onclick="…"` attribute, producing a malformed handler. Rewired
  them as data-attribute buttons with event listeners (the pattern the rest of
  the app uses), so they open the add/rename dialogs reliably regardless of
  characters in the category name. (The v1.33.0 redirect fix was real but
  unrelated — these buttons were never opening their dialogs to begin with.)

## [1.33.0] — 2026-06-07
Items "Manage mode" + category readability fixes.

- **Manage mode actions now keep you in the items browser.** Rename / + Sub /
  Delete on `/parts` (manage mode) worked, but redirected to the separate
  `/categories` page afterwards — so it looked like nothing happened and you
  lost your place. They now return to the same manage view (a same-app `next`,
  open-redirect-guarded; the dedicated `/categories` page still stays put).
- **Category hierarchy is easier to read.** On `/categories`, nested categories
  now show a `└` branch marker and deeper indent, and top-level names are bold,
  so parent → child nesting is obvious at a glance instead of relying on
  whitespace alone.
- **Buttons aren't crammed together.** The Save / Delete clusters on the
  Categories and Kiosk-PINs rows, and the Rename / + Sub / Delete buttons on the
  manage-mode category cards, now have proper spacing.
- **Kiosk PINs table fits without side-scrolling.** Trimmed the input/select
  widths so the row fits its card on a normal screen (the `.table-scroll`
  wrapper from v1.32.2 stays as the safety net for very narrow viewports), so
  you don't have to scroll back and forth.

## [1.32.2] — 2026-06-07
- **Settings → Kiosk PINs:** the PINs table overflowed its card once the new
  "Inv admin" column widened the row — it now sits in a `.table-scroll`
  wrapper so it scrolls inside the card instead of bleeding over the edge.

## [1.32.1] — 2026-06-07
- **Settings → Kiosk PINs:** the new "Inventory admin" checkbox's help text on
  the *Add a kiosk PIN* form rendered inline (it sat in a flex-row `.check`
  label), crowding the row against the Add PIN button. It now sits on its own
  line under the checkbox.

## [1.32.0] — 2026-06-07
Mobile companion app v3 — six additive capabilities on the `/mobile/*` API.
No breaking changes to existing endpoints.

- **Category browse.** `GET /mobile/items/categories` returns each category
  with an active-item count (count desc, name asc); `GET /mobile/items/search`
  takes an optional `?category=` exact-match filter, combinable with `?q=`.
- **Per-item icons.** `ItemDto` gains a nullable `icon_url`. Icons upload via
  `POST /mobile/items/{id}/icon` and serve from `GET /mobile/items/{id}/icon`.
  SVG is supported — but, unlike the web favicon/logo uploads, only because the
  serving route is hardened (sandbox CSP + `nosniff`, `<img>`-only) so an
  embedded script can't execute. Long immutable cache headers.
- **White-labeling.** `GET /mobile/whitelabel` (public — usable before login)
  returns `brand_name` / `logo_url` / `primary_color_hex` / `accent_color_hex`
  from the install's branding settings; the logo serves publicly via
  `GET /mobile/brand/logo` so the login screen can show it.
- **Inventory management (admin-only).** A new per-PIN **Inventory admin** flag
  (set in Settings → Kiosk PINs, surfaced as `TechDto.is_inventory_admin`)
  gates `POST /mobile/items`, `PATCH /mobile/items/{id}`, and
  `POST /mobile/items/{id}/stock-adjust` (ledgered to the audit log with the
  reason + acting tech). Non-admins get 403.
- **Reject $0 orders.** `POST /mobile/orders` now refuses a $0 total or a $0
  client-supplied line with `400 {"error":"zero_total"}` — with an
  `allow_zero_total:true` escape hatch for deliberate no-charge orders.
- **$0 audit list.** `GET /mobile/orders/zero-total` lists historical $0
  orders (same shape + pagination as `/orders/recent`) for review.
- **GPS (confirmation):** mobile orders already persist `geo_lat`/`geo_lon`
  per line and surface them in the web UI on **History** (per-row map pin) and
  the **Map** page — no change needed.

## [1.31.0] — 2026-06-07
UI / accessibility polish (review batch 4).

- **Wide tables scroll on phones instead of being clipped.** History,
  Audit, Categories, Jobs, the Report tables, and the scan page's "Recent
  activity" are now wrapped so their right-most columns (Charge, Void, …)
  stay reachable on a narrow screen instead of being cut off by the page's
  `overflow-x: hidden`.
- **The scan-page search suggestions are keyboard-accessible.** Each
  suggestion is now a real button (reachable by Tab, activatable with
  Enter/Space, announced to screen readers); Arrow keys move through the
  list and Escape closes it — previously the list was mouse-only.
- **Map popups round money the same way as everything else.** The Leaflet
  popups on History and the full-page Map showed the line charge with
  plain rounding; they now use the app's ceiling-to-cent value so a pin
  never disagrees with the table by a cent.
- **Smaller fixes:** the kiosk-PINs table now uses the app's table style
  (it was rendering unstyled); icon-only links (map pin, label print) and
  the inline edit fields on Categories / Jobs got accessible labels; and a
  stray `<span>` inside an `<option>` on the transfer form (invalid HTML)
  was removed.

## [1.30.0] — 2026-06-07
Performance (review batch 3) — faster history, reports, and listings as the
data grows. No behaviour change; same pages, fewer/cheaper queries.

- **Indexes on the hot, unbounded tables.** Added indexes on
  `transactions.created_at` (every history / report / map / home query orders
  by or range-filters on it), `transactions.customer_id` + `part_id` (delete /
  void history checks), `audit_log.created_at` + `action` (the `/audit` page),
  and `jobs.client_id`. They're created on fresh databases and back-filled onto
  existing ones at startup.
- **Killed the N+1 query fan-outs.** `/transactions` and `/map` now eager-load
  the order link they render per row; the monthly **report builder** eager-loads
  part/client/job/location (previously ~4 lazy queries per line); `/clients`
  eager-loads each client's jobs; and the mobile **recent-orders** endpoint
  batches every order's lines into one query and eager-loads the customer
  (was ~2 queries per order).
- **Less per-request work.** Role seeding no longer issues a write transaction
  on every authenticated request — it only commits when a role actually changed.
  `/transactions` and `/map` reuse the settings dict they already loaded instead
  of reading the whole settings table twice.

## [1.29.0] — 2026-06-07
Correctness hardening (review batch 2).

- **Mobile orders can no longer double-charge under a retry race.** The
  device's `client_action_id` idempotency was a check-then-insert that two
  simultaneous retries (flaky signal) could both pass. A
  `UNIQUE(client_action_id, created_by)` index now backs it, and the submit
  handler returns the already-saved order as an idempotent replay if the race
  is lost. The migration that adds the index is guarded so a pre-existing
  duplicate can't crash startup.
- **Deleting a kiosk PIN now revokes its mobile tokens.** Previously a deleted
  station's bearer token kept working until its 12-hour expiry; the delete now
  drops the matching `mobile_sessions` rows.
- **Item creation rejects negative / non-finite money and quantity.** A
  tampered `/parts/add` could seed a negative price (which would credit the
  client) or a NaN cost; these are now refused.
- **Plumbing:** the emailed monthly report now uses the same ceiling-to-cent
  helper as the CSV and on-screen report (consistency with the currency
  convention), and the NaN/Infinity geo guard is now a single shared helper
  (`app/util.py`) instead of being duplicated across the web and mobile code.

## [1.28.0] — 2026-06-07
Security & critical-correctness hardening (review batch 1).

- **Charge-out now actually requires the `checkout` permission.** The real cart
  endpoints (`POST /api/cart/*`) were gated only by `view`, so a read-only
  Viewer role could scan, decrement stock, and submit orders. They now require
  `checkout` like the permission's description always implied.
- **Our cost / margin no longer leak to client-price-only sessions.** The cart
  payload and `/api/search` shipped `unit_cost`/`cost`/`margin` to every
  session — readable in DevTools on a shared Kiosk device even though the column
  was hidden. These fields are now zeroed unless the session has `see_cost`.
  `/report` and `/report.csv` likewise hide the cost/margin columns from roles
  (e.g. Operator) that lack `see_cost`.
- **Mobile PIN login is brute-force throttled.** `POST /mobile/auth/token` had
  no lockout (the web kiosk login did), leaving short PINs guessable. Both now
  share a per-IP throttle **plus a global backstop** so rotating
  `X-Forwarded-For` can't bypass the lockout.
- **Fixed a startup crash / history loss on upgrades from pre-v1.9 databases.**
  The `transactions` table rebuild omitted `location_id` + `receipt_id`, so the
  copy-back referenced columns the new table lacked. It now declares them and
  copies only the columns common to both tables.
- **Stock-integrity & input guards.** Restock now rejects zero/negative
  amounts; moving a category under its own descendant (a tree cycle) is
  rejected; and non-numeric `category_id` / `parent_id` / threshold form values
  no longer 500. Backup-restore extraction is hardened (`filter="data"`,
  symlink/special-file rejection).

## [1.27.0] — 2026-06-05
- **Scan-page polish for the charge-out flow.**
  - The search/scan box now sits **above** the location · client · job
    pickers — it's the first thing the operator reaches, so scanning can
    start immediately and the destination pickers fall below it. The
    box is also a touch thinner so it takes less vertical space at the
    top of the page.
  - **Create a job mid-checkout.** A new "+ New job for this client"
    button under the Job picker spins up a job for the currently-selected
    client and attaches it to the open cart without leaving the scan
    page — no more bouncing to `/jobs` and back. Backed by
    `POST /api/cart/job/new`; requires a real (non walk-in) client on the
    cart first.
- **Bigger stock-modal dropdowns.** The per-item Stock pop-up's
  location / from / to selects were tiny, fiddly tap targets. They now
  render at a comfortable ~44px touch height with more padding, so
  picking a location during a stock add / move / stocktake is far
  easier on a touchscreen.

## [1.26.2] — 2026-06-05
- **Mobile API surface, round two — match the kiosk's scan-pick-charge
  flow on a phone.** v1.26.0 covered auth + barcode scan + order submit;
  the field-tech UX needed the rest of the in-store flow. New routes:
  - `GET /mobile/items/lookup?q=…` — fuzzy scan-or-type lookup that
    returns `{exact, candidates}`. SKU/barcode exact match wins; falls
    through to case-insensitive, name-prefix, then contains. A single
    hit is promoted to `exact` so the Android UI can drop straight
    into the cart instead of re-prompting.
  - `GET /mobile/items/search?q=&limit=&offset=` — paginated catalog
    browse with name / SKU / category-name match.
  - `GET /mobile/customers/search?q=&limit=&offset=` — paginated
    customer browse, archived (walk-in) clients excluded.
  - `GET /mobile/customers/{id}/jobs` and `POST
    /mobile/customers/{id}/jobs` — list chargeable jobs under a
    client, plus the "start a job in the field" create.
  - `GET /mobile/locations` — every active location with the tech's
    `default_location_id` flagged so the device pre-selects the right
    source.
  - `POST /mobile/receipts` (multipart) — upload a paper-receipt
    image for a store-bought item. JPEG / PNG only (matches the
    favicon allowlist that excludes SVG to avoid stored XSS via
    `/uploads/`), 5 MB cap. Returns `{receipt_id, url}` for the
    custom-line reference. Scoped per-tech.
  - `POST /mobile/orders` (updated, backwards-compatible) — now
    accepts an optional top-level `job_id` (422 if it doesn't belong
    to the order's `customer_id`) and a `type: "custom"` line shape
    `{name, qty, unit_price_cents, receipt_id?}` for store-bought
    items. Custom lines reuse the web-UI's archived-Part pattern
    (`CUSTOM-…` barcode, `archived=True`) so they still flow through
    reports, audit, and voids exactly like a catalog line.
- **`/mobile/items/by-barcode/{code}` falls through to case-insensitive
  match** before 404'ing, matching the lookup endpoint's strictness
  order. Existing exact-match callers are unaffected.
- **Additive schema:** new `Receipt` table (opaque `receipt_id`, owning
  `kiosk_pin_id`, on-disk URL); new `Transaction.receipt_id` column
  (nullable, indexed) so a custom line can link back to the receipt
  image. Web-UI orders never set this — no impact on existing rows.
- **Stays inside the mobile bubble:** all new routes go through the
  same bearer-auth `get_current_tech` dependency, the CSRF exemption
  for `/mobile/*` already covers them, and the web UI is untouched.

## [1.26.0] — 2026-06-05
- **Mobile companion API for rugged Android scanners.** New `/mobile/*`
  REST surface — bearer-token auth, JSON in/out, CSRF-exempt — for the
  Android app field techs will run on MUNBYN / iData PDAs. Five routes:
  `POST /mobile/auth/token` (exchange a kiosk PIN *or* an NFC badge UID
  for a 12-hour opaque token, persisted to a new `mobile_sessions`
  table so an admin can revoke a stolen device); `GET
  /mobile/items/by-barcode/{code}` (scan lookup with the tech's
  default-location stock count + cents-typed price); `POST
  /mobile/orders` (submit a whole charge-out in one shot, idempotent
  on a device-supplied `client_action_id` so a retry over flaky cell
  signal doesn't double-bill); `GET /mobile/orders/recent` (cursor-
  paginated "my recent submissions" feed); `GET
  /mobile/customers/by-card/{uid}` (tap-an-NFC-card customer pick).
  Reuses the existing `KioskPin` row as the tech identity — a tech's
  configured default location, audit username, and active flag all
  flow into the mobile session, so revoking a PIN revokes the
  matching mobile app. Additive columns: `customers.card_uid`,
  `kiosk_pins.badge_uid`, `orders.client_action_id`. No web-UI route
  changes — the namespace is self-contained.

## [1.25.0] — 2026-06-05
- **Re-tag any item, not just the auto-generated ones.** The 🏷️ print
  link now shows on every row in `/parts`, including items whose
  barcode was scanned in off a manufacturer code. The Edit-item modal
  gained a Barcode field so an item can be re-stickered with a fresh
  value (uniqueness enforced, dupe attempts bounce with a flash). The
  /labels sheet got a toggle — "Include manufacturer barcodes" — that
  drops the `barcode_generated` filter so a re-tag run can print a
  whole shelf in one pass.
- **Print an ad-hoc label for any value.** New `/labels/print?value=…`
  route renders a single label for an arbitrary barcode (with an
  optional caption) without creating a Part. Lives under the Labels
  page in a "Print an ad-hoc label" panel. Useful for pre-printing
  stickers or covering a worn label on something not yet in the
  catalog. The value goes through a control-character + length guard
  so a malformed query can't blow up the barcode encoder.
- **Pack-size items (10-packs of cables, boxes of jacks, …).** Items
  now have a `pack_size` (default 1) and a `pack_unit_label` (e.g.
  "cable", "outlet"). Stock and billing stay per-unit so consuming one
  cable from a 10-pack bills one cable's price — not the whole bag.
  The items table shows the derived "X packs + remainder of Y" hint
  under the on-hand count whenever pack_size > 1; pack_size=1 is a
  plain item with no visible change. Additive migration: existing
  rows pick up pack_size=1 on first boot so day-one upgrades are
  invisible.
- **Settings → Printing preview no longer needs a click to render.**
  The inline IIFE called `iconHTML()` from `/static/app.js`, which
  loads at the *end* of `<body>` — after the inline script's tag was
  parsed. The first paint silently threw on undefined `iconHTML` and
  the box stayed blank until the user touched a form field (by which
  point app.js had loaded). The render now runs on `DOMContentLoaded`
  so app.js is guaranteed available; the preview paints the moment
  the tab opens.

## [1.24.0] — 2026-06-04
- **Bulk-edit items straight from the list.** Tick rows in the items
  table (any category view or All items) and a bulk bar appears with
  three actions: re-home the selection to a different category, set an
  absolute on-hand count at a location across all of them, or move
  stock between locations with a per-item quantity. The move panel
  pre-fills each item's quantity from its on-hand at the chosen source
  and caps it there, then writes a single Transfer with one line per
  moved item so history reads the same as the per-item and multi-line
  transfer flows. All three require `manage_items`.
- **Users & roles is now one nested view.** The separate Users table
  and Roles/Groups list are merged into a single page: each role is an
  expandable card listing its members — reassign role, toggle active,
  lock against group mapping inline — with the role's permission editor
  tucked one level deeper, plus a "No role" bucket for anyone
  unassigned. The settings sidebar's two Access entries collapse into a
  single "Users & roles" link.

## [1.23.6] — 2026-06-04
- **Per-location stock breakdown on the items table was a pile of
  wrapping pills.** Under the On-hand count, each location's count
  rendered as a rounded `.tag` pill; in the narrow column on a phone
  they wrapped and stacked into messy blobs with clipped names. Now
  it's a tidy one-row-per-location list — location name on the left
  (ellipsised if long), count right-aligned in tabular figures — so a
  multi-location item reads cleanly.
- **Kiosk menu showed Report and Map, but tapping either dead-ended in
  a 403.** v1.23.5 gated those nav links by `view_catalog`, which the
  kiosk role has — but `/report` and `/map` sit *outside* the kiosk
  lockdown floor on purpose, so the links went nowhere. They're now
  hidden whenever the kiosk lockdown is active (new `kiosk_locked`
  template flag); granting the Kiosk role any extra perm lifts the
  lockdown and the links return. The default kiosk menu is now exactly
  what it can reach: Scan, Items, Categories, Clients, Jobs, History.
- **File pickers overflowed the card on phones.** The native "Choose
  File" control has a wide intrinsic size that wouldn't shrink in a
  flex row, so the Branding logo/favicon and Backup → Restore pickers
  pushed past the card edge and were clipped by the page's
  `overflow-x: hidden`. They now shrink to fit. Long form fields (e.g.
  the OIDC discovery URL on the Authentication tab) likewise wrap
  inside the card instead of being cut off.
- **Restore-from-backup warning now looks destructive.** Its
  `.notice.bad` styling was never defined, so the "replaces every row"
  warning showed in routine amber; it now gets a red rail and tint to
  match the severity of the action.

## [1.23.5] — 2026-06-04
- **Kiosk hamburger menu lost most of its links** after the v1.20.1
  perm-floor fix landed without a matching template update. Both the
  desktop nav and the mobile drawer in `base.html` wrapped every
  section link in `{% if not user.is_kiosk %}`, so a kiosk session
  with the correct floor perms (`view`, `view_catalog`, `checkout`)
  only ever saw Scan + Recent (24h) — even though the middleware
  allowlist already permits `/parts`, `/categories`, `/clients`,
  `/jobs`, `/report`, `/map`. Replaced the blanket gate with
  per-link `can(...)` checks, matching the pattern already used for
  `manage_locations` / `view_audit`. Default kiosk now sees Scan,
  Items, Categories, Clients, Jobs, History, Report, Map; granting
  extra perms to the Kiosk role under `/users#roles` lights up the
  matching links automatically. Empty dropdown shells are also
  hidden so a role without `view_catalog` doesn't get a stray
  caret-only button.

## [1.23.1] — 2026-06-04
- **Header nav: "Scan" no longer looks orphaned next to the dropdown
  buttons.** v1.22.1's button-sizing standard gave every `<button>` a
  `min-height: 2.4rem`, which leaked onto `.navdrop-btn` (Inventory ▾
  / Clients ▾ / Records ▾) — they're buttons for keyboard/JS reasons
  but visually have always been nav links. The taller dropdowns then
  misaligned with the plain `<a>Scan</a>` link sitting next to them,
  making "Scan" look short and detached and wasting horizontal space.
  Reset `min-height`, padding, border-radius, and font weight on
  `.navdrop-btn` so it matches the surrounding nav-link styling
  again.

## [1.23.0] — 2026-06-04
- **Scan page redesigned.** The "wall of dropdowns + wide table" feel
  is gone. Three changes:
  - **Compact targets header.** Source location, client, and job
    collapse into a one-line pill summary (📍 Main · 👤 Acme · 🛠️ Job 42).
    Tap the row to expand the pickers; the card auto-collapses once a
    client and location are set, so the scan input + cart get the full
    screen. The summary opens automatically on first load if no
    location is pinned (so a fresh kiosk session lands in "edit"
    mode).
  - **Tile-based cart lines.** The cart-lines table is replaced by
    card-tiles — one per line, with icon, name + barcode + unit
    price, qty stepper, charge total, and a remove ✕. No more
    horizontal scroll on phones, and the qty input + remove button
    are big enough to thumb without zooming.
  - **Sticky bottom action bar.** Cancel + Submit move out of the
    cart header into a footer bar that pins to the bottom of the
    viewport on phones. Submit is always one thumb-reach away no
    matter how long the cart is.
  No data-model changes; `/api/cart` payload is unchanged. The XSS
  hardening from v1.10.1 still applies — every user-controlled string
  (part name, barcode, walk-in name) is rendered via
  `createElement` + `textContent`.

## [1.22.1] — 2026-06-04
- **Explicit archive / restore / delete on clients**, mirroring the
  item lifecycle added in v1.21. New routes:
  - `POST /clients/<id>/archive` — reversible, hides the client from the
    default `/clients` list and the scan/order pickers without touching
    history.
  - `POST /clients/<id>/restore` — flips the bit back.
  - `POST /clients/<id>/delete` — permanent. Refused when any
    `Order.customer_id`, `Transaction.customer_id`, or `Job.client_id`
    row still references the client; the error message tells the user
    to archive instead so historical orders never lose the client name.
  The client edit card on `/clients` now renders a Save · Archive · Delete
  row (Archive flips to Restore once archived), confirm-prompted on
  Delete, matching the items modal pattern.
- **Standardized button sizing across the site.** Every actionable
  button now resolves to one of three classes that share identical
  padding, font-size, weight, border-radius, and min-height — so a row
  of mixed-purpose buttons (Save + Archive + Delete) lines up flush.
  - default `<button>` / `.btn` — primary, filled accent
  - `.ghost` — secondary, outlined neutral, transparent fill
  - `.danger` — destructive, filled red
  `.btn.small` is preserved for inline table-row actions. The previous
  drift (e.g. `.add-btn` padding ≠ `<button>` padding ≠ `.btn` padding)
  caused the head-action button to sit a pixel taller than its
  neighbours; that's gone. Inline `style="padding:…"` overrides on
  buttons are now exclusively for layout, never sizing.

## [1.22.0] — 2026-06-04
- **Built-in role permissions now stay edited.** Removing a default
  perm from a built-in role (e.g. dropping `view_catalog` from Kiosk
  under `/users#roles`) used to be undone on the next container
  restart — `rbac.seed_roles()` would re-add every default perm that
  wasn't there. Roles now carry a `customized` flag that the role-save
  handler sets on first edit; once set, the seeder leaves the stored
  perm list strictly alone. Untouched built-in roles still receive
  newly-shipped default perms on upgrade.
- **Multiple kiosk PINs for multi-location POS.** The single global
  `kiosk_pin` setting is replaced by a `kiosk_pins` table — one row
  per station, each with its own label, PIN, default source location,
  and audit username. The `/welcome` PIN entry accepts any active PIN;
  the matching row's defaults are applied to the session, so a
  Warehouse PIN starts the cart on the warehouse location and a Front
  Desk PIN gets the front-desk location. Per-station audit usernames
  also mean each kiosk's last-24h `/transactions` view stays scoped to
  its own charge-outs instead of seeing every other kiosk's traffic.
  The legacy single PIN is migrated into a row labelled "Default" on
  first start.
- Per-IP lockout after 5 bad attempts is unchanged. PIN comparison
  walks every active row in constant time so a timing leak can't
  reveal which slot a candidate PIN matches.

## [1.21.0] — 2026-06-04
- **Label barcode is now centered.** The Code128 SVG was forced to
  `width: 100%` which left-anchored the encoder's fixed-mm output, so
  the barcode + barcode-digits text rendered hard against the left
  edge of the label. Switch to height-driven scaling (`height: 100%;
  width: auto; margin: 0 auto`) so the natural aspect ratio is kept
  and the flex parent centers it horizontally.
- **Cart-lines no longer bleed off narrow scanners.** Wrapped the
  cart-lines table in a `table-scroll` container and tagged the
  Barcode + Unit columns so they hide on phones; the qty input
  shrinks to 4rem and row padding tightens. The remaining columns
  (Icon · Part · Qty · Charge · ✕) fit a 360-dp Android handheld.
- **Kiosk role can browse the catalog without seeing margin.** Two
  new permissions:
  - `view_catalog` — gates GET on `/parts`, `/categories`, `/clients`,
    `/jobs`, `/labels`, `/map`, `/report`. Default Kiosk gets it; the
    lockdown floor includes it so `+ Add item` and inline Edit / Stock
    buttons stay hidden until `manage_items` is granted.
  - `see_cost` — gates the "Our cost" column on `/parts` plus the
    matching input on Add / Edit item and the Custom-item dialog.
    Default Kiosk does NOT get it, so a shared front-desk device
    shows client price only.
- **Out-of-stock badge on `/parts` and in the cart-bar search.**
  Items at qty 0 still appear in the catalog (they were never
  auto-archived, despite the appearance) but now wear a small amber
  "Out of stock" tag, and the cart-bar suggestion row dims +
  strikes through the name so the operator sees it before scanning.
- **Explicit archive / restore / delete on items.** New
  `POST /parts/<id>/archive`, `/restore`, `/delete` routes plus
  matching buttons in the Edit-item modal:
  - Archive hides the item from the default catalog list (still
    reachable via *Show archived*) without touching history.
  - Restore flips the bit back when you open an archived item's
    edit modal.
  - Delete is permanent and refuses if any sale or transfer line
    references the part — the error tells you to archive instead.

## [1.20.1] — 2026-06-04
- **Kiosk role permissions now take effect.** The kiosk-PIN session was
  hardcoded to `{view, checkout}` and gated by a built-in path
  allowlist that ran *before* the RBAC permission check, so adding
  permissions to the Kiosk role under Users → Roles did nothing. The
  session now loads the live perm set from the Kiosk role row; the
  hardcoded allowlist is treated as a *lockdown floor* that applies
  only while the role still has just `{view, checkout}` — granting it
  any extra permission (e.g. `view_audit`, `manage_items`,
  `manage_locations`, `manage_settings`) lifts the lockdown and lets
  RBAC alone govern the kiosk session. The Kiosk settings panel calls
  this out so the behavior is discoverable.
- **Cart-bar search excludes archived items.** The autocomplete
  dropdown on `/` was filtering by `active = True` but not by
  `archived = False`, so retired one-time / walk-in `CUSTOM-…` items
  kept appearing in suggestions after the order they were created
  for had closed. Added the archived filter to `/api/search`.

## [1.20.0] — 2026-06-04
- **Label printing no longer spills onto blank pages.** The print
  stylesheet now hides the page footer, mobile nav, modal dialogs, and
  zeroes out body / main padding so a single label is a single sheet
  again instead of a leading label followed by four padded-only pages.
  A new `.label-sized` print rule pins the sized-label container's box
  model to zero so the @page width/height set per preset is the only
  thing the browser sees.
- **Label sizes now show inches.** Every preset on the Print / Settings
  dropdowns is labelled "Inches (mm)" — DYMO 30252 reads "DYMO 30252
  Address 3.5 × 1.1 in (89 × 28 mm)" rather than mm-only. **New presets:**
  DYMO 30256 Shipping (4 × 2.31 in), DYMO 30323 Shipping (4 × 2.13 in),
  DYMO 30277 File-folder (3.5 × 2.13 in), DYMO 30270 Postage
  (1.62 × 1.25 in) — the omissions that would silently mismatch a
  loaded label spool.
- **No more purple visited links.** Internal navigation isn't "content
  you've read"; the browser's purple :visited recoloring made
  /locations row links look like they'd been crossed out after a single
  click. Override :visited per context so colors stay consistent.
- **Settings has a left-hand sidebar.** /settings is no longer one
  very long scroll: a sticky sidebar lists every section (App: General /
  Branding / Printing / Android · Access: Users / Roles · Notifications:
  Email / Alerts · System: Version / Backup) and clicking switches the
  pane in place. On phones the sidebar collapses to a horizontal chip
  row above the content. The last-viewed tab survives form submits via
  localStorage so the form you just saved stays in view after the
  POST→redirect round-trip.
- **Users & Roles nest into the same shell.** /users now renders the
  Settings sidebar with the right entry highlighted, so the two pages
  feel like one administration area instead of two unrelated pages.
- **Check for updates from the UI.** A new "Version & updates" tab
  proxies the GitHub releases API (5-minute cache) and reports either
  "Up to date" or "Update available: vX.Y.Z — current is v1.20.0".
  Self-applying the update would break the container's security
  boundary, so the section also shows the two-command upgrade recipe
  (`docker compose pull && docker compose up -d`).

## [1.19.0] — 2026-06-03
- **Per-location detail + audit page.** Each row on `/locations` now
  links to a new `/locations/<id>` page that shows everything stocked
  at that location with a touch-friendly stocktake form: prior count,
  new count input, live Δ chip per row, an optional Reason field, and
  one Save button that commits every changed row in a single POST.
  Toggle "Show all items (incl. zero)" to add stock during a count
  without leaving the page. The form auto-disables on archived /
  inactive locations.
- New `POST /locations/<id>/stocktake` endpoint applies bulk deltas
  through the same `stock_levels`/`Part.quantity_on_hand` plumbing as
  the per-part stocktake — one `part.stock_set` audit row per changed
  item plus a `location.stocktake` rollup, so the audit page surfaces
  the count as a single discoverable event linked to the location.
- **Optimization pass.** Eliminated N+1 patterns on the busiest pages:
  `/locations` now totals stock in a single GROUP BY query instead of
  one-SUM-per-location; `/transactions` and `/` (recent transactions)
  selectinload `Transaction.part/client/job/location` so row rendering
  doesn't fan out into hundreds of follow-up queries; `/transfers`
  selectinloads `Transfer.from_location/to_location/lines`; `/parts`
  scopes its `stock_levels` query to the parts being rendered.
  Verified with a query-count harness — `/transactions` dropped from
  ≥500 SELECTs on a full page to 9; `/transfers` from ~200 to 3.

## [1.18.0] — 2026-06-03
- **Items page is now a touch-first category browser.** The flat list
  is gone; `/parts` opens with tap-friendly cards for each populated
  top-level category (plus Uncategorized and an "All items" flat view).
  Tap a card to drill in — sub-category cards stack first, items rendered
  directly in that category follow underneath. Arbitrary nesting is
  supported (Wiring → Ethernet → Cat 6 → 7ft works); a stack-style
  breadcrumb (📁 Items › Wiring › Ethernet › Cat 6 › 7ft) sits sticky on
  phones so the "you are here" path is always visible.
- **Empty categories are hidden in browse mode** to cut clutter — a
  category only shows up once it (or one of its descendants) holds an
  item. Switch the new **Manage** toggle on to see every category
  (including empties), and to get inline Rename / + Sub / Delete buttons
  per card so the whole tree can be authored from the same page.
- **Auto-skip single-child chains.** When a category has no direct items
  and only one populated branch beneath it, the drill-in lands you at
  the level where items actually live instead of paging through empty
  intermediates. The breadcrumb still shows the full path so you can
  jump back to any level. Disabled in Manage mode so you can park on
  any intermediate to rename / add siblings.
- **Add-item respects the current category.** Opening + Add item while
  inside a category pre-selects that category so the new part lands in
  the right place by default.
- Items are still organised the same way they were under the v1.17
  filter pills — that strip is replaced by the richer drill-down. The
  `/categories` flat-edit admin page stays available unchanged.

## [1.17.0] — 2026-06-03
- **Items are now organised by category.** The `/parts` page gains a
  filter strip of pills — `All`, one per category (with depth
  indicators for nested cats), and `Uncategorized` when relevant —
  each carrying a live item count so the populated buckets are
  obvious at a glance. Clicking a pill narrows the table to that
  bucket via `?cat=<id>` (or `?cat=none` for uncategorized); the
  archived-toggle state is preserved across clicks.
- **Grouped catalog view.** When no filter is active the items table
  now emits a header row each time the category changes, so the
  catalog reads as an organised list rather than one long flat dump.
  Items are sorted by category path then name, with `Uncategorized`
  sinking to the bottom.
- **Item counts on the Categories page.** Each category row shows
  how many (non-archived) items live in it, with a tap-through to
  the filtered items list. Empty categories render dimmed in the
  filter strip so users can spot dead buckets at a glance.

## [1.16.0] — 2026-06-03
- **Header reorganized around Inventory.** Items, Categories,
  Locations, and Transfers now live in a single Inventory dropdown
  instead of being split across Items and Records. Records keeps
  History, Report, Map, and Audit.
- **Per-item Stock dialog.** Each row on `/parts` has a new **Stock**
  button that opens a focused modal: a per-location quantity table
  plus three collapsed actions — `+ Add stock` at a chosen location,
  `↔ Move stock` between two locations (single-line transfer for
  this part, written via the same Transfer / TransferLine path so
  history stays uniform), and `Set absolute count` for stocktake
  corrections (logs the prior count to audit). The inline `+ Stock`
  chip is gone — everything stock-related for an item now lives in
  one place.
- New endpoints `POST /parts/{id}/stock/set` (admin/manager set
  absolute count, refuses negatives, records Δ in the audit log)
  and `POST /parts/{id}/stock/move` (single-item transfer that
  validates source qty + same-location and emits the same kind of
  Transfer row as the multi-line `/transfers/new` page).

## [1.15.0] — 2026-06-03
- **Stock is now counted per location.** A free-form list of locations
  lives in Settings → Locations: the office, work trucks, a job-site
  cage, anything you want counted separately. Every part has an
  independent per-location count; the legacy aggregate
  `quantity_on_hand` remains as the sum across locations so every
  existing page, report, and low-stock alert keeps working.
- **Scan from the right truck.** The cart card has a "From location"
  dropdown. Each scan decrements stock at that location, and the
  resulting transaction line records which location it came off —
  cancellations and voids restore stock back to the same place.
- **Stock transfers between locations.** Admins/managers can post an
  atomic transfer (multiple lines, source → destination) from
  `/transfers/new`. The full history is at `/transfers/<id>`, and
  inadequate source stock blocks the transfer cleanly before any
  rows are mutated.
- **Per-location billing breakdown on the report.** `/report` now has
  a location filter and a "By location" subtotal section showing
  lines, cost, charge, and margin per location. The CSV export
  honours the filter.
- **Kiosk PIN can pin a session to a default location.** Trucks that
  run as kiosks no longer need an operator to remember to pick the
  right source on every cart. The dropdown is still there for override.
- New built-in permission `manage_locations` (Admin + Manager). A
  one-time additive backfill grants it to existing Manager rows on
  startup so nothing breaks for upgrade-in-place users.
- Migration on first boot: a `Main` location is created and each
  part's existing quantity is copied into a per-location row there.
  Any open carts at the moment of upgrade are auto-cancelled and
  their stock restored to `Main` — pre-1.15 carts have no
  location stamp on their lines, so this is the only safe path.

## [1.14.0] — 2026-06-02
- **Kiosk PIN charge-out.** A new admin-configurable PIN can be entered on
  the sign-in screen to start a locked-down "Kiosk" session — scan and
  charge out only, plus a 24-hour rear-view of kiosk-submitted orders.
  Designed for shared front-counter tablets where forcing every operator
  through OIDC is impractical and signing in once as a human gives the
  audit log the wrong attribution. PIN attempts are throttled per IP
  (5 bad attempts → cooldown), the PIN is masked in the Settings UI like
  other secrets, and toggling the feature off immediately drops live
  kiosk sessions.
- **Admin "View as…" impersonation.** Admins now get a role dropdown in
  the header user menu that drops their session into another role's
  permission set (Manager / Operator / Viewer / Kiosk) so they can
  verify what each role actually sees without keeping a second test
  account. A banner stays pinned across the top while impersonating
  with a one-click Stop. Admin-only audited action; non-admins cannot
  reach the route.
- Built-in **Kiosk** role added to RBAC (`view` + `checkout`); the
  /transactions handler now scopes its query to the last 24 hours and
  the kiosk username when the request is from a kiosk session.

## [1.13.0] — 2026-06-02
- **Security headers on every response.** Added `Content-Security-Policy`
  (lax — allows the app's inline scripts/styles, and OpenStreetMap tiles for the
  maps), `X-Frame-Options: DENY`, `X-Content-Type-Options: nosniff`,
  `Referrer-Policy: no-referrer`, and HSTS (only when the request arrives over
  HTTPS). Closes the clickjacking / MIME-sniffing gap without breaking the UI.
- **Break-glass auth bypass is now impossible to miss.** When `DISABLE_AUTH=1`
  is set, a warning banner shows on *every* page (not just Settings), so the
  recovery flag can't silently linger in production.
- **Identity-provider wording generalized to OIDC.** UI, installer, and docs no
  longer imply Authentik specifically — Inv-Keep works with any OpenID Connect
  provider (Authentik, Entra, Okta, Keycloak, …) and you bring your own. The
  `x-authentik-*` forward-auth header names remain the configurable defaults.
- **Installer makes "bring your own reverse proxy" the obvious default** and
  frames the bundled Caddy proxy as the optional convenience it has always been.
- README now states plainly that TLS is bring-your-own by default and that login
  requires your own OIDC provider. Minor doc/grammar tidy-ups.

## [1.12.2] — 2026-06-02
- **Mobile top bar no longer wraps awkwardly.** Below 720px the
  header collapses to brand + a hamburger button; the nav (Scan, Items,
  Categories, Clients, Jobs, History, Report, Map, Audit), the account
  links (Users, Settings, Log out) and the "signed in as …" line all
  move into a right-side slide-in drawer with a tap-anywhere-else
  backdrop. Desktop layout is untouched. Tap targets are sized for
  thumbs (~3rem rows); drawer respects iOS safe-area insets so it
  doesn't sit under the notch on PWA installs.
- **Custom favicon.** Settings → Branding gains an "Upload favicon"
  control that mirrors the logo upload (PNG/JPG/WEBP/GIF/ICO, 512 KB
  cap, SVG rejected to avoid stored-XSS via /uploads/). When set, the
  browser-tab icon and bookmark icon come from your upload; when unset
  the default app icon is used. Audit-logged as
  `settings.branding_favicon`.

## [1.12.1] — 2026-06-02
- **Mobile sign-in is no longer a multi-reload guessing game.** Unauthed
  GETs to an HTML page now land on a new **/welcome** splash with a single
  "Sign in" tap target instead of an implicit `/` → `/login` → IdP →
  `/auth/callback` → `/` redirect chain. On slow mobile networks the user
  used to see a half-rendered page mid-redirect, hit reload, and end up
  stuck; the splash gives them one stable thing to tap. API and non-GET
  requests still get a plain 401 so XHR clients can detect the boundary.
- **Auth'd HTML pages now refuse bfcache.** Every response with
  `Content-Type: text/html` going through the auth middleware gets
  `Cache-Control: no-store, must-revalidate, max-age=0` + `Pragma:
  no-cache`. Stops mobile Safari + Android Chrome from restoring a stale
  page out of memory with a CSRF token that no longer matches the live
  session — the leading cause of "invalid CSRF" errors mid-shift.
- **CSRF rejection page now self-heals.** Instead of dead-ending the user
  on "Request rejected", the 403 page bounces them back to the page they
  came from (Referer-derived, same-origin only, HTML-escaped) after a
  short meta-refresh, so they land on a freshly minted token and can
  retry. Open-redirect protected; CI regression test still asserts the
  word "CSRF" appears so missing tokens still fail loudly.

## [1.12.0] — 2026-05-31
- **Restore from a backup, in the UI.** Settings → Backup gains a "Restore
  from a backup" upload form (admin-only). The server validates the
  uploaded `.tar.gz`, refuses path-traversal attempts, takes a safety
  copy of the live `data/` as `data/before-restore-<ts>/`, then uses
  SQLite's online `backup()` to copy the snapshot tables INTO the live DB
  — no container restart needed — and replaces `uploads/`. Audit-logged
  as `settings.restore`.
- **Walk-in / one-time-purchase cart.** New **+ Start walk-in / one-time
  order** button on the scan page opens a cart whose Client is an
  archived (hidden-from-roster) Client created on the fly when you type
  the customer name. Mirrors the custom-item flow: the line still flows
  through reports / audit / voids normally, but the catalog stays clean.
  Walk-in clients are excluded from the main /clients list and the
  cart's Client dropdown by default; **Show walk-ins** toggle on
  /clients reveals them.
- **Global header search.** New search input in every page header live-
  queries `/api/search/global` (debounced) and returns grouped suggestions
  for **Items / Categories / Clients / Jobs / Orders**. Each row links to
  the most natural destination. Keyboard nav (↑↓ enter esc) supported.
  Archived rows are excluded from suggestions to keep walk-ins / custom
  items out of typeahead noise; submitted orders for walk-in clients
  still match under "Orders".
- **Nav grouped under dropdowns.** Top-level **Items ▾** now nests
  Items + Categories; **Clients ▾** nests Clients + Jobs. Same `navdrop`
  pattern as Records. Cleaner header, especially on smaller widths.
- **Schema:** `Client.archived` flag (with additive migration); used to
  back the walk-in pattern without polluting the recurring-client
  roster. Mirror of `Part.archived`.
- **CSS:** `[hidden]` is now `display: none !important` so the HTML5
  hidden attribute reliably wins against `display: grid` etc. (caught
  via a residual walk-in row visible on cart card load).

## [1.11.0] — 2026-05-31
- **Distributable Docker stack.** New GitHub Actions workflow
  (`.github/workflows/release.yml`) builds a multi-arch image
  (`linux/amd64` + `linux/arm64`) on every `v*` tag push and publishes it
  to `ghcr.io/stephenthecold/inv-keep:{vX.Y.Z, vX.Y, latest}`.
  `docker-compose.yml` now defaults to **pulling** that image (pin a
  version with `INV_KEEP_VERSION=v1.11.0` in `.env`). A new
  `docker-compose.dev.yml` override re-adds `build: .` for local-source
  development. Upgrades are now `docker compose pull && docker compose up -d`
  — the `./data` volume mount survives recreates and `ensure_columns()`
  handles additive migrations on startup.
- **Container healthcheck.** The compose service now defines a 30-second
  healthcheck that hits `/health`, so `docker compose ps` and orchestrators
  can tell unhealthy from down.
- **Backup + restore tooling.**
  - **Admin-only UI**: Settings → Backup → **Download backup now** streams
    a `.tar.gz` containing a consistent SQLite `.backup` snapshot of every
    `*.db` plus `uploads/`. Action recorded as `settings.backup` in the
    audit log.
  - **Shell scripts**: `scripts/backup.sh` (cron-friendly, `BACKUP_KEEP=N`
    prunes old backups by age) and `scripts/restore.sh` (verifies bundle,
    stops the container, swaps `./data/` aside as a safety copy, restarts).
  - **Docs**: new `docs/BACKUPS.md` covers the UI / scripted / volume-
    snapshot options + restore procedure + a safer "back-up-then-upgrade"
    recipe with rollback.
- **Repo tidy.** Test DBs (`data/app.db`, `data/preview.db`) and item
  upload artifacts from the build process wiped — fresh installs start
  empty as intended.

## [1.10.1] — 2026-05-31
- **Security: XSS fix in map popups and cart re-renders.** The Leaflet popup
  HTML and the JS cart row / search-suggest renderers were concatenating
  user-controlled fields (part name, client name, scanned-by) into HTML
  templates, so a malicious item / client name could fire script when a marker
  popup was opened or when the cart refreshed. Switched to DOM construction +
  `textContent` for every user-supplied string in
  `app/templates/transactions.html`, `app/templates/map.html`, and the cart
  `render()` / `renderSuggest()` functions in `app/static/app.js`. Icons +
  server-controlled image paths + numeric fields stay literal.
- **Security: NaN / Infinity bypass on geo capture.** `lat &lt; -90 or lat &gt;
  90` is False for NaN, so a malicious client could POST `{"lat": NaN}` and
  have it stored. `tojson` of NaN then broke the entire `/map` page.
  Replaced the range check with an `_finite()` helper that rejects NaN /
  Infinity before the range comparison; applied in both `/api/cart/scan` and
  `/api/cart/custom`.
- **Order-number race**: `/api/cart/submit` now retries up to 3× on
  `IntegrityError` from the `Order.number` UNIQUE constraint, so a concurrent
  submit returns a clean error rather than a 500.
- **Markup % no longer leaked to non-admins**: the `window.DEFAULT_MARKUP_PCT`
  JS global is only emitted when `user.is_admin`. Managers still get
  client-price autofill suggestion if it's wired, but the % value isn't in
  the rendered HTML they can view-source.
- **Better cart-cancel audit summary**: now records line count, restored
  dollar value, and client/job — parallels the submit summary.
- Minor cleanup: removed a redundant `elif` branch in `api_cart_set` that
  duplicated the else case.

## [1.10.0] — 2026-05-30
- **Custom items in the cart** — new **+ Custom item** button on the order
  card opens a modal for ad-hoc / off-catalog purchases (name, description,
  optional photo, cost, client price, qty). Server creates an archived
  `Part` on the fly so the line still flows through reports / audit / voids
  like any other transaction; the catalog stays clean (Items page hides
  archived parts by default, **Show archived** toggle reveals them).
- **Map of charge-outs** — every transaction with a captured location is now
  pinnable on an embedded Leaflet + OpenStreetMap map. There's a collapsible
  map at the top of /transactions and a full-page **/map** view (linked
  from the Records dropdown). Both honour the same month / date-range
  filters as the report. Leaflet 1.9.4 is **vendored** under
  `app/static/vendor/leaflet/` — fully self-hosted, no CDN.

## [1.9.0] — 2026-05-30
- **Cart-based charge-out flow** — scanning a known item now opens a persistent
  **Current order** card on the home page. Set Client + Job once (asked after
  your first scan), then keep scanning items into the same cart; tweak qty
  inline or remove lines, and hit **Submit Order** when done. Each submitted
  order gets an auto-generated number **ORD-YYYYMM-NNNN** (counter resets
  monthly) that's stamped on every line. **Cancel** restores stock and
  discards the cart. One open cart per signed-in user; closing the browser
  doesn't lose the work — the cart reopens on next visit.
- **Order # on /transactions and the home page Recent activity** — every line
  now shows its `ORD-…` number (or `—` for legacy single-scan rows).
- **Reports + History exclude open-cart lines** — only submitted (or legacy)
  transactions count toward totals; a cart in progress doesn't pollute the
  monthly bill.
- Removed `/api/checkout`; the cart API (`/api/cart/scan`, `/api/cart/set`,
  `/api/cart/line/{id}`, `/api/cart/submit`, `/api/cart/cancel`) replaces it.
- **Schema**: new `orders` table; `transactions.order_id` (nullable FK);
  `transactions.customer_id` relaxed to nullable so a cart line can exist
  before the client is picked. Upgrade is automatic via `ensure_columns()` —
  including a one-time SQLite table rebuild to lift the old NOT NULL.

## [1.8.0] — 2026-05-30
- **Report — multi-client filter + date range** — the Charge-Out report now takes
  any combination of clients (multi-select dropdown, default = all) and either a
  month or an explicit From/To date window. CSV export honours the same filter.
- **Timezone-aware timestamps** — new General setting (curated IANA list,
  default UTC); audit log, transactions and scan-page recent activity render
  in the configured zone. Storage stays UTC; conversion is at the template layer
  via a new `local_dt` filter.
- **Geo capture on charge-out** — the browser is asked (best-effort, 4 s cap) for
  the device location before each `/api/checkout` POST; lat/lng/accuracy persist
  on the Transaction row and surface as a 📍 pin (OpenStreetMap link) on
  /transactions and in the audit summary. Denial / unsupported = the charge-out
  still goes through silently.
- **Default client markup %** — a new General setting (admin-only — hidden from
  managers); when adding an item the Client price field auto-fills as
  `our cost × (1 + markup%)`, rounded **up** to the nearest cent. Editing the
  price manually disables autofill for that item. Managers still get the
  autofill silently; only admins see and control the percentage.
- **Dollar values round up to the cent** — display + CSV totals are ceiling-rounded
  (`$1.231 → $1.24`) so client-facing numbers never under-bill. Stored values
  keep full precision; rounding is at the presentation layer.
- **Cleaner item icons** — every built-in SVG icon redrawn for recognition at
  small sizes; the patch-cable icon in particular is now a clear RJ45 plug +
  trailing cable. No data migration needed.
- **Fix: Add-Item modal didn't auto-open from a scan** — `openModal` was being
  called before `app.js` had loaded; wrapped in `DOMContentLoaded`.
- **Security hardening** — refuses to start with the placeholder `SESSION_SECRET`
  (raises at import time); OIDC email is only trusted if `email_verified=true`;
  session cookie now `Secure` + `SameSite=Lax`; SVG dropped from logo upload
  whitelist (stored-XSS); `html.escape` on the auth error page; 8 MB request-body
  cap in middleware (pre-DoS guard); `brand_accent` regex-validated; Dockerfile
  drops to a non-root user; `/logout` is now POST; audit-log summaries strip
  control chars.
- **CSRF protection** — pure ASGI middleware verifies a per-session token on
  every state-changing request via `X-CSRF-Token` header (for JSON/AJAX) or
  hidden `_csrf` form field (for HTML forms). Closes the cross-site write hole
  in `forward` auth mode where the proxy attaches SSO cookies cross-site.

## [1.7.0] — 2026-05-30
- **Label preview fixed** — the Settings live preview now reflects the chosen **code
  type** (shows a QR when QR is selected) and **fills the label** (flex distribution
  + the code grows to fill dead space), matching what prints.
- **Smarter monthly schedule** — choose "on day N" *or* "on the first/second/third/
  fourth/last <weekday> of every month" (e.g. first Monday).
- **Records dropdown** — History, Report and Audit moved out of the account menu
  into a single top-bar **Records ▾** dropdown; the account menu keeps Settings,
  Users & roles and Log out.

## [1.6.0] — 2026-05-30
- **Custom SVG icon set** — items can use crisp built-in line icons (network cable,
  power plug, connector, server, router, etc.) picked from a dropdown with a live
  preview; they render in the table, search, charge panel and on labels (custom
  emoji still supported).
- **Dynamic labels (Snipe-IT style)** — label content now flex-fills the label so
  bigger labels aren't half-empty: the barcode grows and fonts scale to the size.
  Added an optional **QR code** mode alongside Code128.
- **More alert schedules** — daily / weekly / monthly report emails, each with its
  own day/weekday + hour and recipients (checked hourly).
- **Users, roles & permissions (RBAC)** — granular permissions (view, checkout,
  manage items/clients/settings/users, view audit) grouped into roles
  (Admin/Manager/Operator/Viewer + custom). Users signing in via Authentik / Entra /
  OIDC are auto-created and mapped to roles by **IdP group claim** (configurable
  map), with per-user override, always-admin emails, and nav/route enforcement.

## [1.5.0] — 2026-05-30
- **Account menu** — History, Report, Audit and Settings moved into a clickable
  account dropdown (top-right), decluttering the main nav (Scan / Items /
  Categories / Clients / Jobs).
- **Currency picker** — currency is now a dropdown of the top ~20 world currencies
  (custom values still respected).
- **Item photos** — upload a custom photo per item; it shows in the items table,
  search results and the charge panel (falls back to the emoji icon).
- **Separate cable icons** — distinct “Network / Ethernet cable” and “Power cord /
  plug” options in the icon dropdown.
- **Tidier restock** — Edit + Restock grouped in a stable Actions cell that no
  longer shifts around as the window resizes.
- **More label brands + size-aware preview** — added **Epson** (ColorWorks /
  LabelWorks) and **Brady** (M21 / self-laminating) presets; the label customizer
  preview now resizes to the selected label size.

## [1.4.0] — 2026-05-30
- **Fix: stale assets** — the service worker is now network-first (cache only as an
  offline fallback) and CSS/JS are version-busted, so updates apply immediately.
  This was the root cause of broken logo/brand styling and the icon picker.
- **Logo scaling & optional title** — header logo is constrained and never overflows
  the window; the app-title text next to the logo is now optional (Settings →
  Branding → “Show title text”) and aligned. Page no longer horizontally overflows.
- **Item icon dropdown** — the emoji button grid is replaced by a tidy dropdown
  (with a custom option), in both Add and Edit.
- **Edit items after the fact** — items now have an **Edit** modal (name, icon,
  description, category, costs, threshold, active); the items table is compact and
  no longer overflows.
- **Label customizer live preview** — Settings → Printing shows a sample label that
  updates as you toggle fields.
- Button-wrapping / alignment fixes (e.g. “Send now”).

## [1.3.0] — 2026-05-30
- **Bring-your-own-cert / external proxy** — TLS now has three modes: bundled Caddy
  with Let's Encrypt, bundled Caddy with **your own certificate** (`Caddyfile.custom`
  + `certs/`), or **no bundled proxy** (use your own nginx/Traefik). The installer
  asks which. See [docs/DEPLOY.md](docs/DEPLOY.md).
- **Customizable label content** — Settings → Printing lets you choose what prints on
  each label (icon, name, barcode digits, price, description, category) plus a
  **company/header line** and **extra footer line**.
- **Full APK framework + PWA** — completed `android/twa-manifest.json` (versioned,
  shortcuts, splash, fingerprint flow) and `android/README.md`; PWA continues to work
  with no build.
- **docs/PROJECT_STATE.md** — consolidated handoff/context digest of the whole project.

## [1.2.0] — 2026-05-30
- **Top-4 label-brand presets** — label-size dropdown is now grouped by brand:
  **Brother** (QL + P-touch), **DYMO** (LabelWriter + LabelManager), **Zebra**
  (2×1 … 4×6 in) and **Rollo**, plus generic sizes. See [docs/PRINTING.md](docs/PRINTING.md).
- **Deployment config** — `HOSTNAME`, `APP_PORT`, and optional **automatic HTTPS**
  via a bundled Caddy reverse proxy (`docker compose --profile ssl up`). The app now
  runs behind proxy headers so OIDC/PWA URLs build as `https`. See [docs/DEPLOY.md](docs/DEPLOY.md).
- **`install.sh`** — interactive installer that collects hostname, port, SSL +
  Let's Encrypt email, branding, and OIDC up front, writes `.env`, and starts the stack.
- **Android build pipeline** — `.github/workflows/android.yml` builds a TWA APK/AAB
  in CI; `/.well-known/assetlinks.json` is served from a Settings field so the
  installed app can hide the URL bar. Plus a `ci.yml` checks workflow.

## [1.1.0] — 2026-05-30
- **Progressive Web App (PWA)** — installable on Android (and desktop): app
  manifest, service worker, icons, theme colour and a standalone fullscreen
  display. Optimised for **Android AIO barcode scanners** (keyboard-wedge input,
  responsive touch layout, persistent scan focus). See [docs/ANDROID.md](docs/ANDROID.md).
- **Thermal label printing** — label pages now offer size presets for **Rollo**
  (4×6 in, 2.25×1.25 in) and **Brother** (P-touch 12/18/24 mm tapes, QL 62×29 mm /
  62 mm continuous) with exact `@page` sizing, plus a default label size in
  Settings → Printing. See [docs/PRINTING.md](docs/PRINTING.md).
- **Open-source preparation** — added MIT `LICENSE`, `CONFIGURATION.md` (every env
  var + UI setting), this changelog, and a Bubblewrap TWA config for building an APK.
- Responsive layout improvements for small handheld screens.

## [1.0.0] — 2026-05-30
First versioned release. Cumulative feature set:

- **Scan-first home page** with live quick-search and a charge-out panel
  (quantity, client, job) before committing.
- **Items** (renamed from Parts) with **descriptions** and **emoji icons** that
  show in the search results and charge panel for quick identification.
- **Nested categories** with **descriptions**.
- **Clients** (renamed from Customers) with full contact records, and **Jobs**
  as a separate section attached to clients.
- **Cost vs. client price** tracked per item; reports show billable totals plus
  cost and margin.
- **Auto-generated barcodes + printable Code128 labels** for items with no barcode.
- **Monthly charge-out report** grouped by client → job, with CSV export.
- **Audit log** of every charge-out, void and configuration change.
- **Email alerts** (low stock + monthly report) via SMTP or OAuth2 (Microsoft 365 / Gmail).
- **UI-managed authentication** (Authentik/OIDC or forward-auth) with a
  `DISABLE_AUTH` break-glass override.
- **White-label / branding**: app title, brand emoji or uploaded logo, accent
  colour, and footer text — all configurable in Settings.
- **Add-new** actions presented as top-right buttons opening modal dialogs.
- Everything (except `DATABASE_URL`, `SESSION_SECRET`, `DISABLE_AUTH`) is
  configurable in the UI and stored in the database.
