# Deployment: hostname, ports & SSL

## Quickest path — the installer
```bash
./install.sh
```
It interactively asks for **hostname, port, SSL (+ Let's Encrypt email), app title,
currency, and OIDC**, generates a `SESSION_SECRET`, writes `.env`, and starts the
stack (adding the HTTPS proxy if you enabled SSL). Run `./install.sh -y` to accept
all defaults non-interactively.

## What the settings mean (`.env`)
| Variable | Effect |
|---|---|
| `HOSTNAME` | Public hostname. Used by the SSL proxy and OIDC redirect URLs. |
| `APP_PORT` | Host port for direct (non-SSL) access → `http://HOSTNAME:APP_PORT`. |
| `ACME_EMAIL` | Contact email Let's Encrypt uses when SSL is enabled. |
| `OIDC_REDIRECT_URL` | Set to `https://HOSTNAME/auth/callback` (SSL) so logins work behind the proxy. |

## Ports / direct access (no SSL)
```bash
docker compose up -d --build
```
Serves on `http://HOSTNAME:APP_PORT` (default 8000). Good for LAN use or when TLS is
already handled by an upstream proxy.

## Automatic HTTPS (bundled Caddy)
```bash
docker compose --profile ssl up -d --build
```
The `caddy` service obtains and renews a **Let's Encrypt** certificate for
`HOSTNAME` and reverse-proxies to the app. Requirements:

- `HOSTNAME` is a real domain whose **DNS A/AAAA record points at this server**.
- Ports **80 and 443** are open to the internet (Caddy needs them for the ACME
  challenge and HTTPS).
- `ACME_EMAIL` is set.

The app runs with `--proxy-headers`, so it trusts Caddy's `X-Forwarded-Proto/Host`
and builds correct `https://` URLs (OIDC callback, PWA, etc.).

## Bring your own certificate (bundled Caddy, no Let's Encrypt)
Use the bundled proxy but with **your own** cert/key:

1. Put PEM files at `certs/cert.pem` (full chain) and `certs/key.pem`.
2. In `.env` set `CADDY_CONFIG=./Caddyfile.custom` and `HOSTNAME=your.domain`.
3. `docker compose --profile ssl up -d --build`

The `certs/*.pem` files are git-ignored. The installer's TLS option **2) My own
cert** sets this up for you.

## Behind your own reverse proxy (nginx / Traefik / Authentik outpost)
Skip the `ssl` profile, expose `APP_PORT`, and proxy to it. Forward
`X-Forwarded-Proto: https` and `X-Forwarded-Host`. If you use Authentik's proxy
outpost, set **Settings → Authentication → Forward-auth** and the app trusts the
`X-authentik-*` headers.

## TLS for the PWA
Installing the PWA / registering the service worker requires **HTTPS** (or
`localhost`). Use the SSL profile or an upstream TLS proxy before installing on
Android devices. See [ANDROID.md](ANDROID.md).

## Pulling the image from a private repo

`docker-compose.yml` pulls `ghcr.io/stephenthecold/inv-keep` by default. When
the GitHub repo is **private**, the image inherits that visibility and a
plain `docker compose pull` fails with `unauthorized`. Authenticate first:

```bash
# One-shot (uses the GitHub CLI's existing token, which needs the `read:packages` scope):
gh auth refresh -h github.com -s read:packages
gh auth token | docker login ghcr.io -u YOUR_GH_USER --password-stdin
```

Or, with a personal access token (classic) that has `read:packages`:

```bash
echo "$GHCR_PAT" | docker login ghcr.io -u YOUR_GH_USER --password-stdin
```

Docker caches the credential, so subsequent `docker compose pull` calls
work without re-auth. To deploy on a host that isn't yours (a colleague's
server, a customer site, etc.), give them a token with just `read:packages`
and they run the same `docker login` once.

**Skip auth entirely** by making the package itself public (independent
of repo visibility):

```bash
# Open the package settings page, switch visibility → public:
gh repo view stephenthecold/inv-keep --json url --jq .url
#   then go to /packages → inv-keep → Package settings → Change visibility
```

After that, `docker compose pull` works anywhere without `docker login`.
