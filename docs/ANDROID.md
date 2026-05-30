# Running Inv-Keep on Android AIO barcode scanners

"AIO" (all-in-one) Android scanners — Zebra TC/MC, Sunmi, Chainway, Honeywell EDA,
Urovo, etc. — are Android handhelds with an integrated barcode engine and a
hardware scan trigger. Inv-Keep is a web app, so there are two good ways to run it
on these devices.

## 1. Install as a PWA (recommended, zero build)

Inv-Keep ships as a **Progressive Web App**: it has a manifest, icons, a service
worker, and a standalone fullscreen display.

1. Host Inv-Keep over **HTTPS** (PWA install requires it — see “HTTPS” below).
2. On the device, open the URL in **Chrome**.
3. Menu **⋮ → Add to Home screen / Install app**.
4. Launch it from the home screen — it opens fullscreen, no browser chrome, and
   starts on the scan page.

### Make the hardware scanner work
The app's scan box accepts text + Enter, so set the scanner to **keyboard-wedge
(HID) mode** with an **Enter / CR suffix**:

- **Zebra (DataWedge)**: in the DataWedge profile, enable **Keystroke output** and
  set the **basic data formatting** action suffix to **Enter (\\n / 0x0D)**. (Or
  leave the default profile, which already does keystroke output.)
- **Sunmi / Chainway / Urovo / Honeywell**: open the built-in **Scan/Scanner
  Settings** app → output mode **Keyboard / HID** → suffix **Enter**.

That's it — pull the trigger with the scan box focused and the item pops up for
quantity / client / job. The page keeps the scan box focused automatically.

## 2. Wrap it as an installable APK (TWA)

If you want a real `.apk` (side-load or MDM push) instead of “Add to Home screen”,
build a **Trusted Web Activity** with Google's Bubblewrap. A starter config is in
[`android/twa-manifest.json`](../android/twa-manifest.json).

```bash
npm i -g @bubblewrap/cli
cd android
# edit twa-manifest.json: set "host" to your HTTPS domain
bubblewrap init --manifest ./twa-manifest.json   # or: bubblewrap build
bubblewrap build
```

This produces a signed APK/AAB that opens your hosted PWA fullscreen. To remove the
browser address bar entirely you must publish a **Digital Asset Links** file at
`https://your-domain/.well-known/assetlinks.json` (Bubblewrap prints the JSON to
use). The scanner setup is identical to the PWA case above.

> A Capacitor/WebView wrapper is also possible if you need deeper native hooks
> (e.g. consuming a scanner's *intent* broadcast instead of keyboard mode), but for
> keyboard-wedge scanners the TWA/PWA route needs no native code.

## HTTPS

Browsers only allow PWA install / service workers over HTTPS (or `http://localhost`).
Put Inv-Keep behind a TLS reverse proxy (Caddy, Traefik, nginx, or your Authentik
proxy). Make sure the proxy forwards `X-Forwarded-Proto: https` so generated URLs
(OIDC callback, etc.) are correct.

## Tips for small screens
- The layout is responsive: the nav scrolls horizontally and forms stack.
- Keep the device on the **Scan** (home) screen during a charge-out run.
- For repeated charge-outs to one job, scan → adjust qty → Charge out → scan again.
