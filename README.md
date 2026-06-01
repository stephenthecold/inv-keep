# Inv-Keep

Self-hosted barcode charge-out tracker for MSPs. Scan items into a cart, set
client + job once, submit — each order is auto-numbered (`ORD-YYYYMM-NNNN`)
and feeds a monthly billing report. Custom items, walk-in clients, geo-
tagged charge-outs, and a built-in restore-from-backup flow. SQLite, FastAPI,
fits in one container.

Releases are tagged (`vX.Y.Z`) with a [CHANGELOG.md](CHANGELOG.md) entry; the
running version shows in the footer and under Settings.

---

## Install

**One line** — git + Docker need to be installed on the host:

```bash
git clone https://github.com/stephenthecold/inv-keep.git && cd inv-keep && ./install.sh
```

`install.sh` asks for hostname, port, TLS mode, and OIDC (optional), writes
`.env` with a generated `SESSION_SECRET`, and starts the stack. Use
`./install.sh -y` for all-defaults / no prompts. See
[docs/DEPLOY.md](docs/DEPLOY.md) for TLS modes (Let's Encrypt vs your-own-
cert vs external proxy) and ghcr.io image-pull auth.

The app starts with **no login** — sane for a trusted LAN. Set up auth
under **Settings → Authentication** before exposing it.

## Upgrade

```bash
docker compose pull && docker compose up -d
```

`./data` survives container recreates and schema migrations run automatically
on startup. Pin a version with `INV_KEEP_VERSION=v1.12.0` in `.env`.
For a back-up-first-then-upgrade recipe with rollback, see
[docs/BACKUPS.md](docs/BACKUPS.md).

## Backup + restore

Three ways to get a consistent snapshot of `./data/`:

- **Settings → Backup → Download backup now** (admin-only) — streams `.tar.gz`.
- **`./scripts/backup.sh`** on the host — cron-friendly; `BACKUP_KEEP=N` prunes.
- **Volume snapshot** (ZFS / restic / your tool) — works too.

Restore via **Settings → Backup → Restore from a backup** (admin upload), or
`./scripts/restore.sh <bundle>.tar.gz` on the host. Full walk-through in
[docs/BACKUPS.md](docs/BACKUPS.md).

## Configuration

Three env vars only — everything else lives under **Settings** in the UI:

| Env var | Purpose |
|---|---|
| `DATABASE_URL` | SQLite path (default `sqlite:////code/data/app.db`) |
| `SESSION_SECRET` | Random 32+ char string; app refuses to start with a weak / placeholder value |
| `DISABLE_AUTH` | `1` = break-glass; bypasses all auth. Recover from OIDC lockouts. |

Full table of in-app settings: [CONFIGURATION.md](CONFIGURATION.md).

## Docs

| Path | Covers |
|---|---|
| [CHANGELOG.md](CHANGELOG.md) | Per-version feature list |
| [CONFIGURATION.md](CONFIGURATION.md) | Every env var + UI setting |
| [docs/DEPLOY.md](docs/DEPLOY.md) | Hostname, ports, TLS modes, installer, ghcr.io auth |
| [docs/BACKUPS.md](docs/BACKUPS.md) | Backup / restore / safe upgrade |
| [docs/ANDROID.md](docs/ANDROID.md) | Android AIO scanner PWA + APK packaging |
| [docs/PRINTING.md](docs/PRINTING.md) | Brother / DYMO / Zebra / Rollo label sizes |
| [docs/PROJECT_STATE.md](docs/PROJECT_STATE.md) | Architecture digest for contributors |

## License

[MIT](LICENSE).
