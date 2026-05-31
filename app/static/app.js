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
  openModal("edit-part");
});

// ---- scan / cart on the home page ----
const scan = document.getElementById("scan");
const cart = document.getElementById("cart");
if (scan && cart) {
  const suggest = document.getElementById("suggest");
  const clientSel = document.getElementById("cart-client");
  const jobSel = document.getElementById("cart-job");
  const body = document.getElementById("cart-body");
  const subtotalEl = document.getElementById("cart-subtotal");
  const statusEl = document.getElementById("cart-status");
  const submitBtn = document.getElementById("cart-submit");
  const cancelBtn = document.getElementById("cart-cancel");

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

  function render(c) {
    if (!c || !c.open) {
      cart.hidden = true;
      body.innerHTML = "";
      subtotalEl.textContent = money(0);
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

    body.innerHTML = "";
    if (!c.lines.length) {
      const tr = document.createElement("tr");
      tr.className = "empty";
      const td = document.createElement("td");
      td.colSpan = 7;
      td.textContent = "Cart is empty — scan an item below.";
      tr.appendChild(td);
      body.appendChild(tr);
    } else {
      // Build each cell via the DOM so user-controlled fields (part name,
      // barcode, image path) can't break out as HTML.
      c.lines.forEach((ln) => {
        const tr = document.createElement("tr");
        // icon / image cell — image src is server-controlled (/uploads/items/N.ext)
        const tdIcon = document.createElement("td");
        tdIcon.className = "item-icon";
        if (ln.image) {
          const img = document.createElement("img");
          img.className = "item-thumb";
          img.src = ln.image;
          img.alt = "";
          tdIcon.appendChild(img);
        } else if (ln.icon) {
          // iconHTML returns sanitized SVG / escaped emoji from a known set.
          tdIcon.innerHTML = iconHTML(ln.icon);
        }
        tr.appendChild(tdIcon);
        // part name + barcode (textContent — these are the XSS vectors)
        const tdName = document.createElement("td");
        tdName.textContent = ln.part;
        tr.appendChild(tdName);
        const tdBc = document.createElement("td");
        const code = document.createElement("code");
        code.textContent = ln.barcode;
        tdBc.appendChild(code);
        tr.appendChild(tdBc);
        // qty
        const tdQty = document.createElement("td");
        tdQty.className = "num";
        if (ln.type === "unique") {
          const sp = document.createElement("span");
          sp.textContent = ln.quantity;
          tdQty.appendChild(sp);
        } else {
          const inp = document.createElement("input");
          inp.type = "number";
          inp.min = "1";
          inp.value = ln.quantity;
          inp.dataset.line = ln.id;
          inp.className = "line-qty";
          inp.style.width = "5rem";
          tdQty.appendChild(inp);
        }
        tr.appendChild(tdQty);
        // money cells — numeric, safe
        const tdUnit = document.createElement("td"); tdUnit.className = "num"; tdUnit.textContent = money(ln.unit_price); tr.appendChild(tdUnit);
        const tdCh = document.createElement("td"); tdCh.className = "num"; tdCh.textContent = money(ln.charge); tr.appendChild(tdCh);
        const tdAct = document.createElement("td");
        const btn = document.createElement("button");
        btn.className = "ghost line-remove";
        btn.dataset.line = ln.id;
        btn.title = "Remove";
        btn.textContent = "✕";
        tdAct.appendChild(btn);
        tr.appendChild(tdAct);
        body.appendChild(tr);
      });
    }
    subtotalEl.textContent = money(c.subtotal);
    submitBtn.disabled = !(c.lines.length && c.client_id);
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
    suggest.innerHTML = "";
    results.forEach((p) => {
      const row = document.createElement("div");
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
      row.onclick = () => { hideSuggest(); addToCart(p.barcode); };
      suggest.appendChild(row);
    });
    suggest.hidden = false;
  }
  function hideSuggest() { suggest.hidden = true; suggest.innerHTML = ""; }

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
      if (d.error === "insufficient_stock") toast(`Out of stock: ${d.part} (have ${d.available})`, false);
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

  // Client / Job selectors push to the server immediately.
  async function pushTarget() {
    const cid = clientSel.value ? parseInt(clientSel.value, 10) : null;
    filterJobsToClient(cid);
    const jid = jobSel.value ? parseInt(jobSel.value, 10) : null;
    const res = await fetch("/api/cart/set", {
      method: "POST",
      headers: csrfHeaders({ "Content-Type": "application/json" }),
      body: JSON.stringify({ client_id: cid, job_id: jid }),
    });
    const d = await res.json();
    if (d.ok) render(d.cart);
  }
  clientSel.addEventListener("change", pushTarget);
  jobSel.addEventListener("change", pushTarget);

  // Qty edits + remove on cart lines.
  body.addEventListener("change", async (e) => {
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
  body.addEventListener("click", async (e) => {
    if (!e.target.classList.contains("line-remove")) return;
    const id = e.target.dataset.line;
    const res = await fetch("/api/cart/line/" + id + "/remove", {
      method: "POST",
      headers: csrfHeaders(),
    });
    const d = await res.json();
    if (d.ok) render(d.cart);
  });

  submitBtn.addEventListener("click", async () => {
    submitBtn.disabled = true;
    const res = await fetch("/api/cart/submit", { method: "POST", headers: csrfHeaders() });
    const d = await res.json();
    if (!d.ok) {
      submitBtn.disabled = false;
      beep(false);
      const msg = d.error === "no_client" ? "Pick a client first" :
                  d.error === "empty_cart" ? "Cart is empty" :
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
