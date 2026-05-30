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

## Size presets
| Preset | Size | Typical use |
|---|---|---|
| Plain paper sheet | A4/Letter, many per page | laser/inkjet sheets |
| Rollo 4×6 in | 102 × 152 mm | Rollo shipping-size labels |
| Asset 2.25×1.25 in | 57 × 32 mm | small asset labels (Rollo, Zebra, Munbyn) |
| 50×25 mm | 50 × 25 mm | generic small label |
| Brother QL 62×29 mm | 62 × 29 mm | QL die-cut address labels |
| Brother QL 62 mm continuous | 62 mm wide | QL continuous roll |
| Brother P-touch 24/18/12 mm | tape width | PT continuous tape |

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

## Notes & limits
- Direct raster/ESC-P streaming to Brother, or Rollo's wireless API, is **not**
  used — the OS print path is more portable and needs no per-printer code. If you
  later want one-tap silent printing (no dialog), that would be a printer-specific
  integration; open an issue.
- For very narrow tapes (12 mm) only the barcode + a short name fit; use concise
  item names or rely on the barcode.
- Always print a test label and adjust the preset if your media differs slightly.
