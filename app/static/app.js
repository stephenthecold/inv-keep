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
    clientSel.value = c.client_id ? String(c.client_id) : "";
    filterJobsToClient(c.client_id);
    jobSel.value = c.job_id ? String(c.job_id) : "";

    body.innerHTML = "";
    if (!c.lines.length) {
      const tr = document.createElement("tr");
      tr.className = "empty";
      tr.innerHTML = `<td colspan="7">Cart is empty — scan an item below.</td>`;
      body.appendChild(tr);
    } else {
      c.lines.forEach((ln) => {
        const tr = document.createElement("tr");
        const icoCell = ln.image
          ? `<img class="item-thumb" src="${ln.image}" alt="">`
          : (ln.icon ? iconHTML(ln.icon) : "");
        const qtyCell = ln.type === "unique"
          ? `<span>${ln.quantity}</span>`
          : `<input type="number" min="1" value="${ln.quantity}" data-line="${ln.id}" class="line-qty" style="width:5rem">`;
        tr.innerHTML = `
          <td class="item-icon">${icoCell}</td>
          <td>${ln.part}</td>
          <td><code>${ln.barcode}</code></td>
          <td class="num">${qtyCell}</td>
          <td class="num">${money(ln.unit_price)}</td>
          <td class="num">${money(ln.charge)}</td>
          <td><button class="ghost line-remove" data-line="${ln.id}" title="Remove">✕</button></td>`;
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
      const ic = p.image
        ? `<img class="sg-thumb" src="${p.image}" alt="">`
        : (p.icon ? `<span class="sg-icon">${iconHTML(p.icon)}</span>` : "");
      row.innerHTML = `${ic}<b>${p.name}</b> <span class="muted">· ${p.barcode} · on hand ${p.qty} · ${money(p.unit_price)}</span>`;
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
