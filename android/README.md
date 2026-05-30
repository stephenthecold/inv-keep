# Inv-Keep Android (full APK framework)

Two parallel paths ship in this repo. **The PWA works today** with no build; the
**TWA APK framework** is here for when you want a real installable `.apk`.

## Today: PWA (no build)
On the device's Chrome, open your HTTPS Inv-Keep URL → **⋮ → Install app**. It runs
fullscreen and the hardware scanner (keyboard-wedge mode) drives it. See
[../docs/ANDROID.md](../docs/ANDROID.md).

## Full APK: Trusted Web Activity (Bubblewrap)
[`twa-manifest.json`](twa-manifest.json) is a complete Bubblewrap config — the
"framework" for the APK. Bubblewrap generates the full native Android (Gradle)
project from it, so you don't hand-maintain Android sources.

### Build locally
```bash
npm i -g @bubblewrap/cli
cd android
# 1) set "host" (and the *.example.com URLs) to your domain in twa-manifest.json
bubblewrap init --manifest ./twa-manifest.json --directory .
bubblewrap build          # -> app-release-signed.apk + .aab
```
Requirements: JDK 17, Node 20, Android SDK (Bubblewrap installs it on first run).

### Build in CI (no local Android tooling)
Run the **Build Android APK (TWA)** GitHub Action
([`../.github/workflows/android.yml`](../.github/workflows/android.yml)); enter your
host; download the APK/AAB artifact. Add `ANDROID_KEYSTORE_B64` /
`ANDROID_KEYSTORE_PASS` / `ANDROID_KEY_ALIAS` secrets for a stable signing key.

### Hide the URL bar (Digital Asset Links)
After building, get the signing **SHA-256 fingerprint** (the build/CI prints it, or
`keytool -list -v -keystore android.keystore`). Put the assetlinks JSON into
**Settings → Android app (TWA)** in Inv-Keep — it's published at
`/.well-known/assetlinks.json` automatically:

```json
[{
  "relation": ["delegate_permission/common.handle_all_urls"],
  "target": {
    "namespace": "android_app",
    "package_name": "com.invkeep.twa",
    "sha256_cert_fingerprints": ["AA:BB:CC:..."]
  }
}]
```

## Native wrapper (optional, future)
If you need to consume a scanner's *intent broadcast* (DataWedge) or other native
APIs instead of keyboard-wedge input, a Capacitor/Kotlin wrapper is the path. Not
required for the keyboard-wedge scanners these AIO devices ship with.
