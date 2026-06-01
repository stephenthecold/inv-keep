# Backups + restore

Inv-Keep's entire state lives in `./data/`:

- `*.db` — SQLite databases (the app, your settings, all clients/jobs/items,
  orders, audit log)
- `uploads/` — the brand logo and any item photos that have been uploaded

Back this folder up and you can restore the app from scratch.

## What's in a backup bundle

Whether you use the UI button, the shell script, or roll your own, the canonical
bundle is a `.tar.gz` containing:

```
BACKUP_INFO.txt        # plain-text manifest (timestamp, app version, db list)
app.db                 # primary database (others if you've configured them)
uploads/               # brand logo + item photos
uploads/items/...
```

The `.db` files are produced with SQLite's [`sqlite3.backup()`][sb] — an online
snapshot that is **consistent even while the app is actively writing**, so you
never have to stop the container to take a backup.

[sb]: https://docs.python.org/3/library/sqlite3.html#sqlite3.Connection.backup

---

## Taking a backup

### Option 1 — UI button (admin only)

Settings → **Backup → Download backup now**. Streams a fresh `.tar.gz` to your
browser. Action is recorded in the audit log (`settings.backup`).

### Option 2 — shell script on the host

```bash
./scripts/backup.sh
# → ./backups/inv-keep-20260531-040000.tar.gz
```

Useful overrides:

- `BACKUP_DIR=/mnt/nas/inv-keep-backups ./scripts/backup.sh` — write elsewhere
- `BACKUP_KEEP=14 ./scripts/backup.sh` — prune backups older than 14 days
- `./scripts/backup.sh /tmp/today.tar.gz` — explicit output path

### Option 3 — cron (daily, keep 30 days)

Add to the host's crontab:

```cron
15 2 * * *  cd /opt/inv-keep && BACKUP_KEEP=30 ./scripts/backup.sh >> /var/log/inv-keep-backup.log 2>&1
```

### Option 4 — just snapshot the volume

If your host already snapshots the volume backing `./data/` (ZFS / Btrfs /
LVM / S3 sync / `restic` / borg / …), you don't need any of the above. Just
make sure your snapshot tool doesn't tear a write mid-page; in practice all
of the above handle that. If you want belt-and-braces, run `./scripts/backup.sh`
into the snapshotted folder so you have a known-consistent SQLite copy.

---

## Restoring

```bash
./scripts/restore.sh path/to/inv-keep-YYYYMMDD-HHMMSS.tar.gz
```

What it does:

1. Verifies the bundle is a readable `.tar.gz` with at least one `.db` and a
   `BACKUP_INFO.txt`
2. Asks you to confirm (skip with `ASSUME_YES=1`)
3. **Stops the `inv-keep` container if it's running** (via `docker compose stop`)
4. Moves the current `./data/` aside to `./data.before-restore-<timestamp>/`
   (a safety copy — delete it once you've confirmed the restore looks right)
5. Lays down the bundle's contents at `./data/`
6. **Restarts the container**

Manual equivalent (if you're not on the standard compose setup):

```bash
docker compose stop inv-keep            # or: systemctl stop your-service
mv data data.before-restore
mkdir data && tar -xzf inv-keep-XXX.tar.gz -C data
rm data/BACKUP_INFO.txt
docker compose up -d inv-keep
```

## Upgrading without losing data

```bash
docker compose pull && docker compose up -d
```

The `./data` volume mount survives container recreates; SQLite schema
migrations run automatically on startup via `database.ensure_columns()`.

For a safer upgrade with rollback:

```bash
./scripts/backup.sh                    # snapshot first
docker compose pull
docker compose up -d
# if something is wrong:
./scripts/restore.sh backups/inv-keep-<latest>.tar.gz
```

### Pinning a specific version

By default `docker-compose.yml` pulls `ghcr.io/stephenthecold/inv-keep:latest`.
Pin a specific tag:

```bash
INV_KEEP_VERSION=v1.12.0 docker compose up -d
```

Or put `INV_KEEP_VERSION=v1.12.0` in `.env` to make it sticky.

## What's NOT in the backup

- `.env` — contains your `SESSION_SECRET`. Back it up separately (or just
  regenerate; only the cookies of currently-logged-in users will be
  invalidated).
- `./certs/` — if you're using bring-your-own-cert TLS (Caddyfile.custom),
  back those keys up on your own schedule.
- `./backups/` — meta-recursive; not included.

## Verifying a backup

Quick sanity check without restoring:

```bash
tar -tzf inv-keep-XXX.tar.gz | head -10        # listing
tar -xzOf inv-keep-XXX.tar.gz BACKUP_INFO.txt  # the manifest
# Extract the DB into a temp file and poke at it:
tar -xzf inv-keep-XXX.tar.gz -C /tmp/inv-keep-verify app.db
sqlite3 /tmp/inv-keep-verify/app.db 'SELECT COUNT(*) FROM transactions;'
```
