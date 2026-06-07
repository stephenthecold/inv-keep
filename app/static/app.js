// ---- shared helpers ----
function csrfToken() {
  const m = document.querySelector('meta[name="csrf-token"]');
  return m ? m.getAttribute("content") || "" : "";
}
function csrfHeaders(extra) {
  return Object.assign({ "X-CSRF-Token": csrfToken() }, extra || {});
}

function toast(msg, ok) {
  let el = document.getElementById("toast");
  if (!el) return;
  el.textContent = msg;
  el.className = "toast show " + (ok ? "good" : "bad");
  clearTimeout(el._t);
  el._t = setTimeout(() => (el.className = "toast"), 2200);
}

function beep(ok) {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.connect(g);
    g.connect(ctx.destination);
    o.frequency.value = ok ? 880 : 220;
    g.gain.value = 0.08;
    o.start();
    setTimeout(() => { o.stop(); ctx.close(); }, ok ? 90 : 220);
  } catch (e) {}
}

function ceilCents(n) {
  // Round UP to the nearest cent, mirroring server-side money_filter.
  // The -1e-9 guards against 1.20 stored as 1.1999... drifting to 1.21.
  return Math.ceil(Number(n) * 100 - 1e-9) / 100;
}

function tryGetGeo(timeoutMs) {
  // Best-effort geolocation. Resolves to {lat, lng, accuracy} or null on
  // denial / timeout / unsupported. NEVER throws — callers proceed regardless.
  return new Promise((resolve) => {
    if (!navigator.geolocation) return resolve(null);
    let done = false;
    const finish = (val) => { if (!done) { done = true; resolve(val); } };
    setTimeout(() => finish(null), timeoutMs || 4000);
    navigator.geolocation.getCurrentPosition(
      (pos) => finish({ lat: pos.coords.latitude, lng: pos.coords.longitude, accuracy: pos.coords.accuracy }),
      () => finish(null),
      { enableHighAccuracy: false, timeout: timeoutMs || 4000, maximumAge: 30_000 }
    );
  });
}

function money(n) {
  return (window.CURRENCY || "$") + ceilCents(n).toFixed(2);
}

// Render an item icon value (emoji or "svg:<key>") to HTML.
function iconHTML(v) {
  if (!v) return "";
  if (v.indexOf("svg:") === 0) {
    const inner = window.ICON_SET && window.ICON_SET[v.slice(4)];
    return inner
      ? '<svg class="ico" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' + inner + "</svg>"
      : "";
  }
  const span = document.createElement("span");
  span.className = "emoji-ico";
  span.textContent = v;
  return span.outerHTML;
}

// ---- modal helpers (used by list pages) ----
function openModal(id) { const d = document.getElementById(id); if (d && d.showModal) d.showModal(); }

// ---- global header search ----
(function(){
  const input = document.getElementById("global-search");
  const out   = document.getElementById("global-search-results");
  if (!input || !out) return;
  let timer = null;
  let lastQ = "";
  let activeIdx = -1;

  function close() { out.hidden = true; out.innerHTML = ""; activeIdx = -1; }
  function open()  { out.hidden = false; }

  function items() { return Array.from(out.querySelectorAll(".gs-item")); }
  function setActive(i) {
    const els = items();
    if (!els.length) { activeIdx = -1; return; }
    activeIdx = ((i % els.length) + els.length) % els.length;
    els.forEach((el, n) => el.classList.toggle("active", n === activeIdx));
    els[activeIdx].scrollIntoView({ block: "nearest" });
  }

  function render(d) {
    if (!d || !d.groups || !d.groups.length) {
      out.innerHTML = '<div class="gs-empty">No matches for ' + escapeAttr(d.q || "") + '</div>';
      open();
      return;
    }
    const frag = document.createDocumentFragment();
    d.groups.forEach((g) => {
      const grp = document.createElement("div");
      grp.className = "gs-group";
      const lbl = document.createElement("div");
      lbl.className = "gs-group-label";
      lbl.textContent = g.label;
      grp.appendChild(lbl);
      g.items.forEach((it) => {
        const a = document.createElement("a");
        a.className = "gs-item";
        a.href = it.href;
        const name = document.createElement("span");
        name.className = "gs-item-name";
        name.textContent = it.name;
        a.appendChild(name);
        if (it.meta) {
          const m = document.createElement("small");
          m.className = "gs-item-meta";
          m.textContent = it.meta;
          a.appendChild(m);
        }
        grp.appendChild(a);
      });
      frag.appendChild(grp);
    });
    out.innerHTML = "";
    out.appendChild(frag);
    open();
    activeIdx = -1;
  }

  function escapeAttr(s) { return String(s).replace(/[<>"&]/g, (c) => ({"<":"&lt;",">":"&gt;","\"":"&quot;","&":"&amp;"}[c])); }

  async function run(q) {
    if (q === lastQ) return;
    lastQ = q;
    if (q.length < 2) { close(); return; }
    const res = await fetch("/api/search/global?q=" + encodeURIComponent(q));
    if (!res.ok) { close(); return; }
    const d = await res.json();
    if (q !== input.value.trim()) return;  // user kept typing
    render(d);
  }

  input.addEventListener("input", () => {
    clearTimeout(timer);
    const q = input.value.trim();
    timer = setTimeout(() => run(q), 180);
  });
  input.addEventListener("focus", () => { if (out.children.length) open(); });
  input.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown") { e.preventDefault(); setActive(activeIdx + 1); }
    else if (e.key === "ArrowUp") { e.preventDefault(); setActive(activeIdx - 1); }
    else if (e.key === "Enter") {
      const els = items();
      if (activeIdx >= 0 && els[activeIdx]) { e.preventDefault(); els[activeIdx].click(); }
    }
    else if (e.key === "Escape") { close(); input.blur(); }
  });
  document.addEventListener("click", (e) => {
    if (!e.target.closest(".global-search")) close();
  });
})();

// ---- generic header dropdown menus (account + records) ----
(function () {
  const allMenus = () => document.querySelectorAll("[data-menu-pop]");
  const closeAll = () => allMenus().forEach((m) => { m.hidden = true; });
  document.addEventListener("click", (e) => {
    const btn = e.target.closest("[data-menu]");
    if (btn) {
      e.stopPropagation();
      const menu = document.querySelector(btn.dataset.menu);
      if (!menu) return;
      const willOpen = menu.hidden;
      closeAll();
      menu.hidden = !willOpen;
      btn.setAttribute("aria-expanded", String(willOpen));
      return;
    }
    if (!e.target.closest("[data-menu-pop]")) closeAll();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeAll(); });
})();

// ---- icon dropdown: pick a built-in SVG icon or a custom emoji ----
document.addEventListener("change", (e) => {
  const sel = e.target.closest(".icon-select");
  if (!sel) return;
  const field = sel.closest(".icon-field");
  const input = field.querySelector(".icon-input");
  const prev = field.querySelector(".icon-preview");
  if (sel.value === "__custom") {
    if (input) { input.hidden = false; input.value = ""; input.focus(); }
    if (prev) prev.innerHTML = "";
  } else if (sel.value.indexOf("svg:") === 0) {
    if (input) { input.hidden = true; input.value = sel.value; }
    if (prev) prev.innerHTML = iconHTML(sel.value);
  } else {
    if (input) { input.hidden = true; input.value = ""; }
    if (prev) prev.innerHTML = "";
  }
});
// Typing a custom emoji updates the preview.
document.addEventListener("input", (e) => {
  const input = e.target.closest(".icon-input");
  if (!input) return;
  const prev = input.closest(".icon-field").querySelector(".icon-preview");
  if (prev) prev.innerHTML = iconHTML(input.value);
});

// Set an icon field (select + input + preview) to a given value.
function setIconField(scope, value) {
  const sel = scope.querySelector(".icon-select");
  const input = scope.querySelector(".icon-input");
  const prev = scope.querySelector(".icon-preview");
  if (input) input.value = value || "";
  if (prev) prev.innerHTML = iconHTML(value || "");
  if (!sel) return;
  if (value && value.indexOf("svg:") === 0 && Array.from(sel.options).some((o) => o.value === value)) {
    sel.value = value; if (input) input.hidden = true;
  } else if (value) {
    sel.value = "__custom"; if (input) input.hidden = false;
  } else {
    sel.value = ""; if (input) input.hidden = true;
  }
}

// ---- edit-item modal: populate the shared dialog from the row's data-* ----
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".edit-part");
  if (!btn) return;
  const d = btn.dataset;
  const form = document.getElementById("edit-part-form");
  form.action = "/parts/" + d.id + "/edit";
  document.getElementById("ep-name").value = d.name || "";
  document.getElementById("ep-description").value = d.description || "";
  document.getElementById("ep-cost").value = d.cost || "0";
  document.getElementById("ep-price").value = d.price || "0";
  document.getElementById("ep-threshold").value = d.threshold || "";
  document.getElementById("ep-category").value = d.category || "";
  document.getElementById("ep-active").checked = d.active === "1";
  const bcEl = document.getElementById("ep-barcode");
  if (bcEl) bcEl.value = d.barcode || "";
  const psEl = document.getElementById("ep-pack-size");
  if (psEl) psEl.value = d.packSize || "1";
  const puEl = document.getElementById("ep-pack-unit");
  if (puEl) puEl.value = d.packUnit || "";
  document.getElementById("ep-meta").textContent =
    "Barcode " + (d.barcode || "") + " · " + (d.type || "") + " · qty changes via Restock";
  setIconField(document.getElementById("edit-part"), d.icon || "");
  const cur = document.getElementById("ep-image-current");
  if (cur) {
    if (d.image) { cur.src = d.image; cur.style.display = ""; }
    else { cur.removeAttribute("src"); cur.style.display = "none"; }
  }
  const rm = document.getElementById("ep-remove");
  if (rm) rm.checked = false;
  const fileInput = document.querySelector("#edit-part input[type=file]");
  if (fileInput) fileInput.value = "";
  // Lifecycle action targets — archive flips to restore when the row is
  // already archived (data-active === '0' was historically the inactive
  // state; archived rows render with data-archived too, set below).
  const archForm = document.getElementById("ep-archive-form");
  const archBtn = document.getElementById("ep-archive-btn");
  const isArchived = (d.archived === "1");
  if (archForm && archBtn) {
    if (isArchived) {
      archForm.action = "/parts/" + d.id + "/restore";
      archBtn.textContent = "Restore from archive";
    } else {
      archForm.action = "/parts/" + d.id + "/archive";
      archBtn.textContent = "Archive";
    }
  }
  const delForm = document.getElementById("ep-delete-form");
  if (delForm) delForm.action = "/parts/" + d.id + "/delete";
  openModal("edit-part");
});

// ---- scan / cart on the home page ----
const scan = document.getElementById("scan");
const cart = document.getElementById("cart");
if (scan && cart) {
  const suggest = document.getElementById("suggest");
  const clientSel = document.getElementById("cart-client");
  const jobSel = document.getElementById("cart-job");
  const locationSel = document.getElementById("cart-location");
  // v1.23: cart lines are tiles in #cart-tiles, not <tr> rows in #cart-body.
  const tiles = document.getElementById("cart-tiles");
  const subtotalEl = document.getElementById("cart-subtotal");
  const statusEl = document.getElementById("cart-status");
  const submitBtn = document.getElementById("cart-submit");
  const cancelBtn = document.getElementById("cart-cancel");
  // Compact-pill targets header (<details> wrapper around the three selects)
  const targetsCard = document.getElementById("cart-targets-card");
  const pillLocation = targetsCard && targetsCard.querySelector('[data-pill="location"] .ct-text');
  const pillClient   = targetsCard && targetsCard.querySelector('[data-pill="client"] .ct-text');
  const pillJob      = targetsCard && targetsCard.querySelector('[data-pill="job"] .ct-text');
  const pillLocationEl = targetsCard && targetsCard.querySelector('[data-pill="location"]');
  const pillClientEl   = targetsCard && targetsCard.querySelector('[data-pill="client"]');
  const pillJobEl      = targetsCard && targetsCard.querySelector('[data-pill="job"]');

  // Keep keyboard-wedge scanners working: any stray click on the page
  // refocuses the scan input unless the user is interacting with a
  // form element / link.
  document.addEventListener("click", (e) => {
    const t = e.target;
    if (t.closest("#suggest")) return;
    if (["SELECT", "INPUT", "BUTTON", "TEXTAREA", "A"].includes(t.tagName)) return;
    scan.focus();
  });

  // -- helpers --
  function filterJobsToClient(clientId) {
    if (!jobSel) return;
    for (const opt of jobSel.options) {
      if (!opt.value) { opt.hidden = false; continue; }
      opt.hidden = clientId ? (opt.dataset.client !== String(clientId)) : true;
    }
    const cur = jobSel.selectedOptions[0];
    if (cur && cur.value && cur.dataset.client !== String(clientId)) jobSel.value = "";
  }

  // Update the three pill summaries from the current select values. Called
  // after every cart render and from select-change listeners so the
  // collapsed header reflects what's been picked at all times.
  function updatePills() {
    function syncPill(sel, pillEl, pillTextEl, fallback) {
      if (!pillEl || !pillTextEl) return;
      const opt = sel && sel.selectedOptions && sel.selectedOptions[0];
      const label = opt && opt.value ? opt.textContent.trim() : "";
      pillEl.classList.toggle("is-set", !!label);
      pillTextEl.textContent = "";
      if (label) {
        pillTextEl.appendChild(document.createTextNode(label));
      } else {
        const em = document.createElement("em");
        em.textContent = fallback;
        pillTextEl.appendChild(em);
      }
    }
    syncPill(locationSel, pillLocationEl, pillLocation, "pick a location");
    syncPill(clientSel,   pillClientEl,   pillClient,   "pick a client");
    syncPill(jobSel,      pillJobEl,      pillJob,      "no job");
  }
  if (clientSel) clientSel.addEventListener("change", updatePills);
  if (jobSel)    jobSel.addEventListener("change", updatePills);
  if (locationSel) locationSel.addEventListener("change", updatePills);

  // Build one tile per cart line. textContent is used for every
  // user-controlled string (part name, barcode); image src is
  // server-controlled (/uploads/items/N.ext). Mirrors the v1.10.1 XSS
  // hardening from the old <tr> renderer.
  function buildTile(ln) {
    const tile = document.createElement("div");
    tile.className = "cart-tile";
    tile.role = "listitem";

    // Icon / thumbnail
    const iconCell = document.createElement("div");
    iconCell.className = "tile-icon";
    if (ln.image) {
      const img = document.createElement("img");
      img.src = ln.image;
      img.alt = "";
      iconCell.appendChild(img);
    } else if (ln.icon) {
      iconCell.innerHTML = iconHTML(ln.icon);
    }
    tile.appendChild(iconCell);

    // Name + barcode + unit price (meta)
    const nameWrap = document.createElement("div");
    nameWrap.className = "tile-name-wrap";
    const name = document.createElement("div");
    name.className = "tile-name";
    name.textContent = ln.part;
    nameWrap.appendChild(name);
    const meta = document.createElement("div");
    meta.className = "tile-meta";
    if (ln.barcode) {
      const code = document.createElement("code");
      code.textContent = ln.barcode;
      meta.appendChild(code);
    }
    if (ln.unit_price != null) {
      const dot = document.createElement("span");
      dot.textContent = (ln.barcode ? " · " : "") + money(ln.unit_price) + " ea";
      meta.appendChild(dot);
    }
    nameWrap.appendChild(meta);
    tile.appendChild(nameWrap);

    // Qty stepper (or fixed value for unique-serial items)
    const qty = document.createElement("div");
    qty.className = "tile-qty";
    if (ln.type === "unique") {
      const sp = document.createElement("span");
      sp.className = "tile-qty-fixed";
      sp.textContent = "× " + ln.quantity;
      qty.appendChild(sp);
    } else {
      const inp = document.createElement("input");
      inp.type = "number";
      inp.min = "1";
      inp.value = ln.quantity;
      inp.dataset.line = ln.id;
      inp.className = "line-qty";
      inp.setAttribute("aria-label", "Quantity for " + ln.part);
      qty.appendChild(inp);
    }
    tile.appendChild(qty);

    // Charge total for this line
    const charge = document.createElement("div");
    charge.className = "tile-charge";
    charge.textContent = money(ln.charge);
    tile.appendChild(charge);

    // Remove button
    const rm = document.createElement("button");
    rm.type = "button";
    rm.className = "ghost line-remove tile-remove";
    rm.dataset.line = ln.id;
    rm.title = "Remove";
    rm.setAttribute("aria-label", "Remove " + ln.part);
    rm.textContent = "✕";
    tile.appendChild(rm);

    return tile;
  }

  function render(c) {
    if (!c || !c.open) {
      cart.hidden = true;
      tiles.innerHTML = "";
      subtotalEl.textContent = money(0);
      updatePills();
      return;
    }
    cart.hidden = false;
    statusEl.textContent = c.number
      ? "Order " + c.number
      : "Order # will be assigned on submit";
    // Walk-in clients aren't in the dropdown (they're archived). Show the
    // walk-in row as a read-only "Walk-in: <name>" label instead.
    const walkinRowEl = document.getElementById("cart-walkin-row");
    const walkinInEl  = document.getElementById("cart-walkin");
    if (c.client_walkin) {
      clientSel.value = "";
      clientSel.disabled = true;
      if (walkinRowEl) walkinRowEl.hidden = false;
      if (walkinInEl) { walkinInEl.value = c.client_name; walkinInEl.readOnly = true; }
    } else {
      clientSel.disabled = false;
      clientSel.value = c.client_id ? String(c.client_id) : "";
      if (walkinRowEl) walkinRowEl.hidden = true;
      if (walkinInEl) { walkinInEl.readOnly = false; walkinInEl.value = ""; }
    }
    filterJobsToClient(c.client_id);
    jobSel.value = c.job_id ? String(c.job_id) : "";
    if (locationSel) {
      locationSel.value = c.location_id ? String(c.location_id) : (locationSel.dataset.default || "");
    }

    tiles.innerHTML = "";
    if (!c.lines.length) {
      const empty = document.createElement("div");
      empty.className = "cart-tile-empty";
      empty.textContent = "Cart is empty — scan an item or type to search above.";
      tiles.appendChild(empty);
    } else {
      c.lines.forEach((ln) => tiles.appendChild(buildTile(ln)));
    }
    subtotalEl.textContent = money(c.subtotal);
    submitBtn.disabled = !(c.lines.length && (c.client_id || c.client_walkin));

    updatePills();

    // Auto-collapse the targets header once a client is set, so the
    // expanded picker doesn't keep eating screen real estate after the
    // operator has confirmed the destination. They can re-expand any
    // time by tapping the pill row.
    if (targetsCard && targetsCard.open && (c.client_id || c.client_walkin) && c.location_id) {
      targetsCard.open = false;
    }
  }

  async function refresh() {
    const r = await fetch("/api/cart");
    const d = await r.json();
    render(d.cart);
  }
  refresh();

  // -- live search dropdown (unchanged feel) --
  let searchTimer = null;
  scan.addEventListener("input", () => {
    clearTimeout(searchTimer);
    const q = scan.value.trim();
    if (!q) { hideSuggest(); return; }
    searchTimer = setTimeout(() => runSearch(q), 180);
  });
  async function runSearch(q) {
    const res = await fetch("/api/search?q=" + encodeURIComponent(q));
    const data = await res.json();
    renderSuggest(data.results || []);
  }
  function renderSuggest(results) {
    if (!results.length) { hideSuggest(); return; }
    suggest.setAttribute("role", "listbox");
    suggest.setAttribute("aria-label", "Search suggestions");
    suggest.innerHTML = "";
    results.forEach((p) => {
      // A real <button> so the row is reachable by keyboard (Tab / arrows) and
      // announced to screen readers, not a mouse-only <div onclick>.
      const row = document.createElement("button");
      row.type = "button";
      row.className = "sg-row";
      row.setAttribute("role", "option");
      const oos = (p.qty || 0) <= 0;
      if (oos) row.classList.add("oos");
      // image / icon (server-controlled or trusted icon set)
      if (p.image) {
        const img = document.createElement("img");
        img.className = "sg-thumb"; img.src = p.image; img.alt = "";
        row.appendChild(img);
      } else if (p.icon) {
        const span = document.createElement("span");
        span.className = "sg-icon";
        span.innerHTML = iconHTML(p.icon);
        row.appendChild(span);
      }
      // name (textContent — primary XSS vector)
      const nameEl = document.createElement("b");
      nameEl.textContent = p.name;
      row.appendChild(nameEl);
      // metadata line (barcode is user-controlled too)
      const meta = document.createElement("span");
      meta.className = "muted";
      meta.textContent = " · " + p.barcode + " · on hand " + p.qty + " · " + money(p.unit_price);
      row.appendChild(meta);
      if (oos) {
        const oosBadge = document.createElement("span");
        oosBadge.className = "tag oos-tag";
        oosBadge.textContent = "Out of stock";
        row.appendChild(oosBadge);
      }
      // Tap is still allowed so the user gets the explicit
      // insufficient-stock toast — but the row is dimmed so they can
      // see in advance the part has zero on hand.
      row.onclick = () => { hideSuggest(); addToCart(p.barcode); };
      suggest.appendChild(row);
    });
    suggest.hidden = false;
  }
  function hideSuggest() { suggest.hidden = true; suggest.innerHTML = ""; }

  // Keyboard navigation for the suggestion list: ArrowDown from the input
  // enters the list; ArrowUp/Down move between options; Escape closes and
  // returns focus to the scan input. Click/Enter/Space activate natively
  // (the rows are <button>s).
  scan.addEventListener("keydown", (e) => {
    if (e.key === "ArrowDown" && !suggest.hidden) {
      const first = suggest.querySelector(".sg-row");
      if (first) { e.preventDefault(); first.focus(); }
    }
  });
  suggest.addEventListener("keydown", (e) => {
    const rows = Array.from(suggest.querySelectorAll(".sg-row"));
    if (!rows.length) return;
    const i = rows.indexOf(document.activeElement);
    if (e.key === "ArrowDown") {
      e.preventDefault();
      (rows[i + 1] || rows[0]).focus();
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      if (i <= 0) { scan.focus(); } else { rows[i - 1].focus(); }
    } else if (e.key === "Escape") {
      e.preventDefault();
      hideSuggest();
      scan.focus();
    }
  });

  // Enter / scanner submit: resolve exact barcode → add to cart; else search.
  scan.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const q = scan.value.trim();
    if (!q) return;
    const res = await fetch("/api/search?q=" + encodeURIComponent(q));
    const data = await res.json();
    const results = data.results || [];
    const exact = results.find((p) => p.barcode.toLowerCase() === q.toLowerCase());
    if (exact) { hideSuggest(); addToCart(exact.barcode); return; }
    if (results.length === 1) { hideSuggest(); addToCart(results[0].barcode); return; }
    if (results.length) { renderSuggest(results); return; }
    beep(false);
    toast("No match — opening Add Item…", false);
    setTimeout(() => (window.location = "/parts?barcode=" + encodeURIComponent(q)), 900);
  });

  async function addToCart(barcode) {
    const geo = await tryGetGeo(4000);
    const body = { barcode, quantity: 1 };
    if (geo) { body.lat = geo.lat; body.lng = geo.lng; body.geo_accuracy_m = geo.accuracy; }
    const res = await fetch("/api/cart/scan", {
      method: "POST",
      headers: csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(body),
    });
    const d = await res.json();
    if (!d.ok) {
      beep(false);
      if (d.error === "insufficient_stock") {
        const where = d.location ? ` at ${d.location}` : "";
        toast(`Out of stock: ${d.part}${where} (have ${d.available})`, false);
      }
      else if (d.error === "unknown_barcode") toast(`Unknown barcode ${d.barcode}`, false);
      else toast("Could not add to cart", false);
      return;
    }
    beep(true);
    render(d.cart);
    if (d.fresh && !d.cart.client_id) {
      toast("Cart started — pick a client to continue", true);
      clientSel.focus();
    } else {
      toast(`Added — cart subtotal ${money(d.cart.subtotal)}`, true);
    }
    scan.value = "";
    scan.focus();
  }

  // Client / Job / Location selectors push to the server immediately.
  async function pushTarget() {
    const cid = clientSel.value ? parseInt(clientSel.value, 10) : null;
    filterJobsToClient(cid);
    const jid = jobSel.value ? parseInt(jobSel.value, 10) : null;
    const lid = locationSel && locationSel.value ? parseInt(locationSel.value, 10) : null;
    const payload = { client_id: cid, job_id: jid };
    if (locationSel) payload.location_id = lid;
    const res = await fetch("/api/cart/set", {
      method: "POST",
      headers: csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify(payload),
    });
    const d = await res.json();
    if (d.ok) render(d.cart);
    else if (d.error === "bad_location") toast("Pick an active source location", false);
  }
  clientSel.addEventListener("change", pushTarget);
  jobSel.addEventListener("change", pushTarget);
  if (locationSel) locationSel.addEventListener("change", pushTarget);

  // Qty edits + remove on cart lines (delegated on the tile container).
  tiles.addEventListener("change", async (e) => {
    if (!e.target.classList.contains("line-qty")) return;
    const id = e.target.dataset.line;
    const newQty = Math.max(1, parseInt(e.target.value || "1", 10) || 1);
    const res = await fetch("/api/cart/line/" + id, {
      method: "POST",
      headers: csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ quantity: newQty }),
    });
    const d = await res.json();
    if (d.ok) { render(d.cart); }
    else {
      beep(false);
      toast(d.error === "insufficient_stock" ? `Only ${d.available} on hand` : "Could not update qty", false);
      refresh();
    }
  });
  tiles.addEventListener("click", async (e) => {
    if (!e.target.classList.contains("line-remove")) return;
    const id = e.target.dataset.line;
    const res = await fetch("/api/cart/line/" + id + "/remove", {
      method: "POST",
      headers: csrfHeaders(),
    });
    const d = await res.json();
    if (d.ok) render(d.cart);
  });

  const techSel = document.getElementById("cart-tech");
  // Hardware-verify mode: a keyboard-wedge badge scan / NFC tap lands in
  // #cart-tech-scan; resolve it to a technician id via /kiosk/verify-tech and
  // stash it on the hidden #cart-tech the submit handler already reads. Absent
  // (null) in plain-dropdown mode.
  const techScan = document.getElementById("cart-tech-scan");
  if (techScan && techSel) {
    const techName = document.getElementById("cart-tech-name");
    const techMsg  = document.getElementById("cart-tech-msg");
    let verifying = false;
    async function verifyTech(raw) {
      const cred = (raw || "").trim();
      if (!cred || verifying) return;
      verifying = true;
      try {
        const res = await fetch(techScan.dataset.verifyUrl || "/kiosk/verify-tech", {
          method: "POST",
          headers: csrfHeaders({ "Content-Type": "application/json" }),
          body: JSON.stringify({ credential: cred }),
        });
        const d = await res.json().catch(() => ({}));
        if (res.ok && d.ok) {
          techSel.value = String(d.tech_id);
          if (techName) { techName.textContent = "✓ " + d.tech_name; techName.hidden = false; }
          if (techMsg) { techMsg.textContent = "Verified — ready to submit."; techMsg.classList.remove("bad"); }
          beep(true);
        } else {
          techSel.value = "";
          if (techName) { techName.hidden = true; techName.textContent = ""; }
          if (techMsg) {
            techMsg.textContent = res.status === 429
              ? "Too many attempts — wait a moment and rescan."
              : "Badge not recognised — try again or see an admin.";
            techMsg.classList.add("bad");
          }
          beep(false);
        }
      } catch (e) {
        if (techMsg) { techMsg.textContent = "Couldn't verify — check the connection."; techMsg.classList.add("bad"); }
      } finally {
        verifying = false;
        techScan.value = "";
      }
    }
    // Keyboard-wedge scanners emit the value then Enter; also support manual
    // type + Enter and a blur/change fallback if the wedge omits Enter.
    techScan.addEventListener("keydown", (e) => {
      if (e.key === "Enter") { e.preventDefault(); verifyTech(techScan.value); }
    });
    techScan.addEventListener("change", () => { if (techScan.value.trim()) verifyTech(techScan.value); });
  }
  submitBtn.addEventListener("click", async () => {
    // Kiosk charge-out requires a technician (the picker is rendered only then).
    let techId = null;
    if (techSel) {
      techId = techSel.value ? parseInt(techSel.value, 10) : null;
      if (techSel.dataset.required && !techId) {
        beep(false);
        const m = techScan ? "Scan your badge to verify the technician"
                           : "Pick the technician charging this out";
        toast(m, false);
        const msg = document.getElementById("cart-tech-msg");
        if (msg) { msg.textContent = m; msg.classList.add("bad"); }
        (techScan || techSel).focus();
        return;
      }
    }
    submitBtn.disabled = true;
    const res = await fetch("/api/cart/submit", {
      method: "POST",
      headers: csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ tech_id: techId }),
    });
    const d = await res.json();
    if (!d.ok) {
      submitBtn.disabled = false;
      beep(false);
      const msg = d.error === "no_client" ? "Pick a client first" :
                  d.error === "empty_cart" ? "Cart is empty" :
                  d.error === "tech_required" ? "Pick the technician charging this out" :
                  "Could not submit";
      toast(msg, false);
      return;
    }
    beep(true);
    toast(`${d.order.number} submitted — ${d.order.lines} line(s), ${money(d.order.subtotal)}`, true);
    // Brief delay so the toast is visible, then reload to refresh Recent activity.
    setTimeout(() => location.reload(), 1100);
  });

  cancelBtn.addEventListener("click", async () => {
    if (!confirm("Cancel this cart? Stock will be returned and the order discarded.")) return;
    const res = await fetch("/api/cart/cancel", { method: "POST", headers: csrfHeaders() });
    const d = await res.json();
    if (d.ok) { toast("Cart cancelled", true); refresh(); }
  });

  // -- walk-in / one-time-purchase client --
  const startWalkin = document.getElementById("start-walkin");
  const walkinRow   = document.getElementById("cart-walkin-row");
  const walkinIn    = document.getElementById("cart-walkin");
  const walkinSave  = document.getElementById("cart-walkin-apply");
  const walkinCancel= document.getElementById("cart-walkin-cancel");

  function showWalkinRow(on) {
    if (!walkinRow) return;
    walkinRow.hidden = !on;
    if (walkinIn) walkinIn.readOnly = false;  // editable when opened anew
    if (on) {
      if (clientSel) clientSel.disabled = true;
      if (jobSel)    jobSel.disabled = true;
      setTimeout(() => walkinIn && walkinIn.focus(), 30);
    } else {
      if (clientSel) clientSel.disabled = false;
      if (jobSel)    jobSel.disabled = false;
    }
  }

  if (startWalkin) {
    startWalkin.addEventListener("click", () => {
      showWalkinRow(true);
      cart.hidden = false;          // make sure the cart card is visible
    });
  }
  if (walkinCancel) {
    walkinCancel.addEventListener("click", () => {
      walkinIn.value = "";
      showWalkinRow(false);
    });
  }
  async function applyWalkin() {
    const name = (walkinIn.value || "").trim();
    if (!name) { walkinIn.focus(); return; }
    const res = await fetch("/api/cart/walkin", {
      method: "POST",
      headers: csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ name }),
    });
    const d = await res.json();
    if (!d.ok) {
      beep(false);
      toast(d.error === "name_required" ? "Type a name first" :
            d.error === "name_too_long" ? "Name too long" :
            "Could not set walk-in", false);
      return;
    }
    beep(true);
    toast("Walk-in: " + name, true);
    showWalkinRow(false);
    walkinIn.value = "";
    render(d.cart);
    scan.focus();
  }
  if (walkinSave) walkinSave.addEventListener("click", applyWalkin);
  if (walkinIn) walkinIn.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); applyWalkin(); }
    if (e.key === "Escape") { e.preventDefault(); walkinCancel.click(); }
  });

  // -- inline new-job creation (mid-checkout) --
  // Creates a Job for the currently-selected client and attaches it to the
  // cart, so the operator can spin up a job without leaving the scan page.
  const startNewJob = document.getElementById("start-newjob");
  const newJobRow    = document.getElementById("cart-newjob-row");
  const newJobIn     = document.getElementById("cart-newjob");
  const newJobSave   = document.getElementById("cart-newjob-apply");
  const newJobCancel = document.getElementById("cart-newjob-cancel");

  function showNewJobRow(on) {
    if (!newJobRow) return;
    newJobRow.hidden = !on;
    if (on) setTimeout(() => newJobIn && newJobIn.focus(), 30);
  }
  if (startNewJob) {
    startNewJob.addEventListener("click", () => {
      if (!clientSel || !clientSel.value) { toast("Pick a client first", false); return; }
      showNewJobRow(true);
    });
  }
  if (newJobCancel) {
    newJobCancel.addEventListener("click", () => { newJobIn.value = ""; showNewJobRow(false); });
  }
  async function applyNewJob() {
    const name = (newJobIn.value || "").trim();
    if (!name) { newJobIn.focus(); return; }
    const res = await fetch("/api/cart/job/new", {
      method: "POST",
      headers: csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ name }),
    });
    const d = await res.json();
    if (!d.ok) {
      beep(false);
      toast(d.error === "no_client" ? "Pick a client first" :
            d.error === "name_required" ? "Type a job name" :
            d.error === "name_too_long" ? "Name too long" :
            "Could not create job", false);
      return;
    }
    // Add the new job as a client-scoped option and let render() select it
    // off the returned cart.job_id. textContent keeps user strings inert.
    if (jobSel && d.job) {
      const opt = document.createElement("option");
      opt.value = d.job.id;
      opt.dataset.client = d.job.client_id;
      opt.textContent = d.job.reference ? (d.job.name + " — " + d.job.reference) : d.job.name;
      jobSel.appendChild(opt);
    }
    beep(true);
    toast("Job created: " + name, true);
    showNewJobRow(false);
    newJobIn.value = "";
    render(d.cart);
    scan.focus();
  }
  if (newJobSave) newJobSave.addEventListener("click", applyNewJob);
  if (newJobIn) newJobIn.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); applyNewJob(); }
    if (e.key === "Escape") { e.preventDefault(); newJobCancel.click(); }
  });

  // -- custom (off-catalog) item form --
  const customForm = document.getElementById("custom-form");
  if (customForm) {
    // Mirror the markup autofill from the Items page so a custom-item price
    // suggests itself based on the configured markup %.
    const cCost = document.getElementById("custom-cost");
    const cPrice = document.getElementById("custom-price");
    let cAuto = true;
    cCost.addEventListener("input", () => {
      if (!cAuto) return;
      const pct = parseFloat(window.DEFAULT_MARKUP_PCT || "0") || 0;
      if (pct <= 0) return;
      cPrice.value = ceilCents(parseFloat(cCost.value || "0") * (1 + pct / 100)).toFixed(2);
    });
    cPrice.addEventListener("input", () => { cAuto = false; });

    customForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const fd = new FormData(customForm);
      const geo = await tryGetGeo(4000);
      if (geo) {
        fd.append("lat", geo.lat);
        fd.append("lng", geo.lng);
        fd.append("geo_accuracy_m", geo.accuracy);
      }
      const res = await fetch("/api/cart/custom", {
        method: "POST",
        headers: { "X-CSRF-Token": csrfToken() },  // don't override multipart Content-Type
        body: fd,
      });
      const d = await res.json();
      if (!d.ok) {
        beep(false);
        toast(d.error === "name_required" ? "Name is required" : "Could not add custom item", false);
        return;
      }
      beep(true);
      toast(`Custom item added — subtotal ${money(d.cart.subtotal)}`, true);
      render(d.cart);
      customForm.reset();
      cAuto = true;
      document.getElementById("add-custom").close();
      if (d.fresh && !d.cart.client_id) clientSel.focus();
      else scan.focus();
    });
  }
}

// ---- transactions page void ----
document.addEventListener("click", async (e) => {
  if (!e.target.classList.contains("void-btn")) return;
  if (!confirm("Void this transaction and return stock?")) return;
  const id = e.target.dataset.id;
  const res = await fetch("/api/void/" + id, { method: "POST", headers: csrfHeaders() });
  const data = await res.json();
  if (data.ok) {
    document.getElementById("txn-" + id).classList.add("voided");
    e.target.outerHTML = '<span class="muted">voided</span>';
  }
});

// ---- order comment thread (History) ----
(function () {
  const dlg = document.getElementById("order-comments");
  if (!dlg) return;
  const threadEl = document.getElementById("oc-thread");
  const form = document.getElementById("oc-form");
  const input = document.getElementById("oc-input");
  const numEl = document.getElementById("oc-order-number");
  let currentOrderId = null;

  function metaText(c) {
    let s = c.author + " · " + c.created_at;
    if (c.edited) {
      s += " (edited";
      if (c.edited_by) s += " by " + c.edited_by;
      if (c.edited_at) s += " " + c.edited_at;
      s += ")";
    }
    return s;
  }

  // All user-controlled text goes through textContent — never innerHTML — so a
  // comment body can't inject markup (the cart-XSS rule, applied here too).
  function commentNode(c) {
    const wrap = document.createElement("div");
    wrap.className = "oc-item";
    wrap.dataset.id = c.id;
    const meta = document.createElement("div");
    meta.className = "oc-meta";
    meta.textContent = metaText(c);
    const edit = document.createElement("button");
    edit.type = "button";
    edit.className = "oc-edit-link";
    edit.textContent = "Edit";
    edit.addEventListener("click", () => startEdit(wrap, c));
    meta.appendChild(document.createTextNode(" "));
    meta.appendChild(edit);
    const body = document.createElement("div");
    body.className = "oc-body";
    body.textContent = c.body;
    wrap.appendChild(meta);
    wrap.appendChild(body);
    return wrap;
  }

  function originNode(text) {
    const wrap = document.createElement("div");
    wrap.className = "oc-item oc-origin";
    const meta = document.createElement("div");
    meta.className = "oc-meta";
    meta.textContent = "📱 Justification (from app)";
    const body = document.createElement("div");
    body.className = "oc-body";
    body.textContent = text;
    wrap.appendChild(meta);
    wrap.appendChild(body);
    return wrap;
  }

  function startEdit(wrap, c) {
    if (wrap.querySelector("textarea")) return;
    const bodyEl = wrap.querySelector(".oc-body");
    const ta = document.createElement("textarea");
    ta.className = "oc-edit-input";
    ta.rows = 2;
    ta.maxLength = 2000;
    ta.value = c.body;
    const bar = document.createElement("div");
    bar.className = "oc-edit-bar";
    const save = document.createElement("button");
    save.type = "button"; save.textContent = "Save";
    const cancel = document.createElement("button");
    cancel.type = "button"; cancel.textContent = "Cancel"; cancel.className = "ghost";
    bar.appendChild(save); bar.appendChild(cancel);
    bodyEl.replaceWith(ta);
    ta.after(bar);
    ta.focus();
    cancel.addEventListener("click", () => { ta.replaceWith(bodyEl); bar.remove(); });
    save.addEventListener("click", async () => {
      const text = ta.value.trim();
      if (!text) return;
      save.disabled = true;
      const res = await fetch("/orders/" + currentOrderId + "/comments/" + c.id + "/edit", {
        method: "POST", headers: csrfHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ body: text }),
      });
      const d = await res.json().catch(() => ({}));
      if (res.ok && d.ok) { wrap.replaceWith(commentNode(d.comment)); toast("Comment updated", true); }
      else { save.disabled = false; toast("Couldn't save", false); }
    });
  }

  async function load(orderId) {
    threadEl.textContent = "Loading…";
    let d = {};
    try { const res = await fetch("/orders/" + orderId + "/comments"); d = await res.json(); }
    catch (e) { d = {}; }
    threadEl.textContent = "";
    if (!d.ok) { threadEl.textContent = "Couldn't load comments."; return; }
    if (d.justification) threadEl.appendChild(originNode(d.justification));
    (d.comments || []).forEach((c) => threadEl.appendChild(commentNode(c)));
    if (!d.justification && !(d.comments || []).length) {
      const empty = document.createElement("div");
      empty.className = "oc-empty muted";
      empty.textContent = "No notes yet — add the first one below.";
      threadEl.appendChild(empty);
    }
    threadEl.scrollTop = threadEl.scrollHeight;
  }

  function open(orderId, orderNumber) {
    currentOrderId = orderId;
    numEl.textContent = orderNumber || ("#" + orderId);
    input.value = "";
    load(orderId);
    if (typeof dlg.showModal === "function") dlg.showModal(); else dlg.setAttribute("open", "");
  }

  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".comment-btn");
    if (btn) { open(btn.dataset.orderId, btn.dataset.orderNumber); return; }
    if (e.target.closest(".oc-close")) dlg.close();
  });

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || currentOrderId == null) return;
    const btn = form.querySelector("button[type=submit]");
    btn.disabled = true;
    let d = {};
    try {
      const res = await fetch("/orders/" + currentOrderId + "/comments", {
        method: "POST", headers: csrfHeaders({ "Content-Type": "application/json" }),
        body: JSON.stringify({ body: text }),
      });
      d = await res.json();
    } catch (err) { d = {}; }
    btn.disabled = false;
    if (d.ok) {
      const empty = threadEl.querySelector(".oc-empty");
      if (empty) empty.remove();
      threadEl.appendChild(commentNode(d.comment));
      threadEl.scrollTop = threadEl.scrollHeight;
      input.value = "";
      toast("Comment added", true);
    } else { toast("Couldn't add comment", false); }
  });
})();

// ---- mobile nav drawer (hamburger) ----
(function () {
  const toggle = document.querySelector(".nav-toggle");
  const drawer = document.getElementById("nav-mobile");
  const backdrop = document.querySelector(".nav-backdrop");
  if (!toggle || !drawer) return;

  const setOpen = (open) => {
    document.body.classList.toggle("nav-open", open);
    toggle.setAttribute("aria-expanded", open ? "true" : "false");
  };

  toggle.addEventListener("click", (e) => {
    e.stopPropagation();
    setOpen(!document.body.classList.contains("nav-open"));
  });

  // Close after tapping any link or the logout button so the drawer doesn't
  // sit open over the next page if it loads instantly from cache.
  drawer.addEventListener("click", (e) => {
    const t = e.target.closest("a, button");
    if (t) setTimeout(() => setOpen(false), 60);
  });

  if (backdrop) backdrop.addEventListener("click", () => setOpen(false));

  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && document.body.classList.contains("nav-open")) setOpen(false);
  });
})();
