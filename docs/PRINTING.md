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

## Size presets (six label brands)
The label-size dropdown is grouped by brand. Pick the one that matches your media.
Sizes are labelled inches-first since the supported printer fleet is mostly US.

**Brother** — QL 2.4×1.1 in (62×29 mm) die-cut, QL 2.4×1.6 in (62×40 mm) continuous,
QL 3.5×1.1 in (90×29 mm) address, P-touch 0.94 in (24 mm) / 0.71 in (18 mm) /
0.47 in (12 mm) tapes.

**DYMO** — LabelWriter **30252 Address** (3.5×1.1 in / 89×28 mm),
**30256 Shipping** (4×2.31 in / 101×59 mm),
**30323 Shipping** (4×2.13 in / 101×54 mm),
**30277 File-folder** (3.5×2.13 in / 89×54 mm),
**30334 Medium** (2.25×1.25 in / 57×32 mm),
**30336 Multipurpose** (2.13×1 in / 54×25 mm),
**30330 Return** (2×0.75 in / 51×19 mm),
**30270 Postage** (1.62×1.25 in / 41×32 mm),
LabelManager **0.47 in (12 mm)** tape.

**Zebra** — 2×1 in (51×25 mm), 2.25×1.25 in (57×32 mm), 3×2 in (76×51 mm),
4×6 in (102×152 mm).

**Rollo** — 4×6 in (102×152 mm), 2.25×1.25 in (57×32 mm).

**Epson** — ColorWorks 4×6 in / 2.25×1.25 in / 2×1 in, plus LabelWorks
0.94 in (24 mm) / 0.71 in (18 mm) / 0.47 in (12 mm) tape.

**Brady** — M21 0.75 in (19 mm) / 0.5 in (12.7 mm) tape, 1×0.5 in (25×13 mm)
label, self-laminating wire 1×1.5 in (25×38 mm), 2×1 in (51×25 mm) label.

**Generic** — plain paper sheet (many per page), 2×1 in (50×25 mm).

> **Match the loaded label.** The most common print bug we've seen is the app
> preset and the physically-loaded label disagreeing. If the print preview shows
> the right label-sized first sheet followed by 4–5 blank ones, the printer is
> tiling the @page across mismatched paper. Either change the preset to match the
> physical media or load the media the preset expects. The presets above carry
> both inches and mm so cross-referencing the box label is easy.

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
