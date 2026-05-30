# Custom TLS certificates

To serve HTTPS with **your own certificate** instead of Let's Encrypt:

1. Put your PEM files here as:
   - `cert.pem` — full certificate chain (leaf + intermediates)
   - `key.pem`  — private key
2. In `.env` set:
   ```
   CADDY_CONFIG=./Caddyfile.custom
   HOSTNAME=your.domain
   ```
3. Start with the SSL profile:
   ```
   docker compose --profile ssl up -d --build
   ```

The actual `cert.pem` / `key.pem` are git-ignored so secrets never get committed.
Prefer a different reverse proxy entirely? Choose the **external** option in
`install.sh` (or just expose `APP_PORT` and proxy to it) — see ../docs/DEPLOY.md.
