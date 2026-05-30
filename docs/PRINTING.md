# Printing labels (thermal printers)

Inv-Keep renders each item's barcode as a **Code128 label** and prints it through
the **browser/OS print dialog**, sized exactly to your label stock with CSS
`@page`. That makes it work with any printer the OS can see — including **Rollo**
and **Brother** thermal printers — without printer-specific drivers in the app.

## How it works
- **Items → 🏷️ Print labels** (a sheet of every auto-generated barcode), or the
  🏷️ icon on a single item.
- On the label page, pick a **Label size** preset. It sets the page dimensions and
  scales the barcode to fit. Then **Print** and choose your thermal printer.
- Set a **default** size under **Settings → Printing**.
- In the print dialog: select the thermal printer, set paper size to match, and
  **turn off** headers/footers and any “fit to page”/scaling.

## Size presets (top 4 label brands)
The label-size dropdown is grouped by brand. Pick the one that matches your media.

**Brother** — QL 62×29 mm die-cut, QL 62 mm continuous, QL 29×90 mm address,
P-touch 24 / 18 / 12 mm tapes.

**DYMO** — LabelWriter 30252 Address (89×28 mm), 30336 Multipurpose (54×25 mm),
30334 Medium (57×32 mm), 30330 Return (51×19 mm), LabelManager 12 mm tape.

**Zebra** — 2×1 in (51×25 mm), 2.25×1.25 in (57×32 mm), 3×2 in (76×51 mm),
4×6 in (102×152 mm).

**Rollo** — 4×6 in (102×152 mm), 2.25×1.25 in (57×32 mm).

**Generic** — plain paper sheet (many per page), 50×25 mm.

## Rollo
Rollo printers install as a normal system printer (USB or network) via Rollo's
driver / the OS print framework.

- **Desktop**: install the Rollo driver, choose **Rollo** in the print dialog, and
  pick the 4×6 or 2.25×1.25 preset. Disable scaling.
- **Android**: install Rollo's print service (or use the generic **Default Print
  Service** / **Mopria**), then Print → select Rollo.
- The X1040 and Wireless models both accept these OS print jobs; the preset's
  `@page` size keeps the barcode from being scaled down.

## Brother
### P-touch (PT-P700/P750/P900/P910 — continuous tape)
- **Desktop**: install the Brother P-touch driver, pick the matching **tape width**
  preset (12/18/24 mm). The label length flows with the content.
- **Android**: use **Brother iPrint&Label** or the **Brother Print Service Plugin**,
  then Print → select the printer. Choose the tape size to match the preset.

### QL series (QL-800/820/1100 — die-cut or continuous)
- Pick **QL 62×29 mm** (die-cut) or **QL 62 mm continuous**.
- Same driver/print-service flow as P-touch.

## DYMO
DYMO LabelWriter (450/550/5xx) and LabelManager install via DYMO Connect / the
DYMO driver.

- **Desktop**: install DYMO Connect, choose the **DYMO LabelWriter** in the print
  dialog, pick the matching 302xx preset, and disable scaling.
- **Android**: DYMO's own apps are limited; use a LabelWriter shared through the OS
  print framework (Mopria/USB) where supported, or print from a desktop.
- Note the LabelWriter 5xx series uses auto-detected die-cut labels — the preset's
  `@page` size should match the loaded label.

## Zebra
Zebra (ZD/GK/GX desktop, ZSB) install via the Zebra driver or **Zebra Printer
Setup Utility**.

- **Desktop**: install the Zebra driver, select the printer, choose the matching
  Zebra preset, and turn off scaling.
- **Android**: use the **Zebra Print** service / Print Station, or Mopria, then
  Print → select the Zebra printer.
- These presets render the barcode as an image sized to the label; for raw ZPL
  templating you'd want a printer-specific integration (not built in).

## Notes & limits
- Direct raster/ESC-P streaming to Brother, or Rollo's wireless API, is **not**
  used — the OS print path is more portable and needs no per-printer code. If you
  later want one-tap silent printing (no dialog), that would be a printer-specific
  integration; open an issue.
- For very narrow tapes (12 mm) only the barcode + a short name fit; use concise
  item names or rely on the barcode.
- Always print a test label and adjust the preset if your media differs slightly.
