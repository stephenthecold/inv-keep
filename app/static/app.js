// ---- shared helpers ----
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

function money(n) {
  return (window.CURRENCY || "$") + Number(n).toFixed(2);
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

// ---- filter the charge-panel job list to the selected client ----
function filterPanelJobs() {
  const clientEl = document.getElementById("cp-client");
  const jobEl = document.getElementById("cp-job");
  if (!clientEl || !jobEl) return;
  const cid = clientEl.value;
  for (const opt of jobEl.options) {
    if (!opt.value) { opt.hidden = false; continue; }
    opt.hidden = opt.dataset.client !== cid;
  }
  const cur = jobEl.selectedOptions[0];
  if (cur && cur.value && cur.dataset.client !== cid) jobEl.value = "";
}

// ---- scan / search / charge home page ----
const scan = document.getElementById("scan");
if (scan) {
  let sessionTotal = 0;
  let currentPart = null;
  const suggest = document.getElementById("suggest");
  const panel = document.getElementById("charge-panel");

  const panelOpen = () => panel && !panel.hidden;
  const refocusScan = () => { if (!panelOpen()) scan.focus(); };
  document.addEventListener("click", (e) => {
    const t = e.target;
    if (t.closest("#charge-panel") || t.closest("#suggest")) return;
    if (["SELECT", "INPUT", "BUTTON", "TEXTAREA", "A"].includes(t.tagName)) return;
    refocusScan();
  });

  // -- live search --
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
      row.onclick = () => { hideSuggest(); openCharge(p); };
      suggest.appendChild(row);
    });
    suggest.hidden = false;
  }
  function hideSuggest() { suggest.hidden = true; suggest.innerHTML = ""; }

  // Enter in the scan box → resolve exact barcode, else search.
  scan.addEventListener("keydown", async (e) => {
    if (e.key !== "Enter") return;
    e.preventDefault();
    const q = scan.value.trim();
    if (!q) return;
    const res = await fetch("/api/search?q=" + encodeURIComponent(q));
    const data = await res.json();
    const results = data.results || [];
    const exact = results.find((p) => p.barcode.toLowerCase() === q.toLowerCase());
    if (exact) { hideSuggest(); openCharge(exact); return; }
    if (results.length === 1) { hideSuggest(); openCharge(results[0]); return; }
    if (results.length) { renderSuggest(results); return; }
    beep(false);
    toast("No match — opening Add Item…", false);
    setTimeout(() => (window.location = "/parts?barcode=" + encodeURIComponent(q)), 900);
  });

  // -- charge panel --
  function openCharge(part) {
    currentPart = part;
    const cpImg = document.getElementById("cp-image");
    if (part.image) {
      cpImg.src = part.image; cpImg.style.display = "";
      document.getElementById("cp-icon").textContent = "";
    } else {
      cpImg.style.display = "none";
      document.getElementById("cp-icon").innerHTML = iconHTML(part.icon || "");
    }
    document.getElementById("cp-name").textContent = part.name;
    document.getElementById("cp-desc").textContent = part.description || "";
    document.getElementById("cp-barcode").textContent = part.barcode;
    document.getElementById("cp-qty").textContent = part.qty;
    document.getElementById("cp-price").textContent = money(part.unit_price);
    document.getElementById("cp-cost").textContent = money(part.unit_cost);
    const qtyEl = document.getElementById("cp-quantity");
    qtyEl.value = "1";
    qtyEl.disabled = part.type === "unique";
    filterPanelJobs();
    panel.hidden = false;
    qtyEl.focus();
    qtyEl.select();
  }

  window.cancelCharge = function () {
    panel.hidden = true;
    currentPart = null;
    scan.value = "";
    hideSuggest();
    scan.focus();
  };

  window.confirmCharge = async function () {
    if (!currentPart) return;
    const clientEl = document.getElementById("cp-client");
    if (!clientEl || !clientEl.value) { toast("Pick a client first", false); beep(false); return; }
    const jobEl = document.getElementById("cp-job");
    const jobId = jobEl && jobEl.value ? parseInt(jobEl.value, 10) : null;
    const quantity = parseInt(document.getElementById("cp-quantity").value || "1", 10) || 1;
    const note = document.getElementById("cp-note").value;

    const res = await fetch("/api/checkout", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ barcode: currentPart.barcode, client_id: parseInt(clientEl.value, 10), job_id: jobId, quantity, note }),
    });
    const data = await res.json();
    if (!data.ok) {
      beep(false);
      if (data.error === "insufficient_stock") toast(`Out of stock: ${data.part} (have ${data.available})`, false);
      else toast("Could not charge that part", false);
      return;
    }
    beep(true);
    addLine(data.line);
    const dest = data.line.client + (data.line.job ? " / " + data.line.job : "");
    toast(`${data.line.part} ×${data.line.quantity} → ${dest}`, true);
    document.getElementById("cp-note").value = "";
    panel.hidden = true;
    currentPart = null;
    scan.value = "";
    scan.focus();
  };

  // Enter confirms / Esc cancels while inside the panel.
  panel.addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); confirmCharge(); }
    if (e.key === "Escape") { e.preventDefault(); cancelCharge(); }
  });

  function addLine(line) {
    const body = document.getElementById("session-body");
    const empty = body.querySelector(".empty");
    if (empty) empty.remove();
    const dest = line.client + (line.job ? " / " + line.job : "");
    const tr = document.createElement("tr");
    tr.id = "sl-" + line.id;
    tr.innerHTML = `
      <td>${line.part}</td>
      <td>${dest}</td>
      <td class="num">${line.quantity}</td>
      <td class="num">${money(line.unit_price)}</td>
      <td class="num">${money(line.charge)}</td>
      <td><button class="undo" data-id="${line.id}" data-total="${line.charge}">undo</button></td>`;
    body.prepend(tr);
    sessionTotal += line.charge;
    document.getElementById("session-total").textContent = money(sessionTotal);
  }

  document.addEventListener("click", async (e) => {
    if (!e.target.classList.contains("undo")) return;
    const id = e.target.dataset.id;
    const res = await fetch("/api/void/" + id, { method: "POST" });
    const data = await res.json();
    if (data.ok) {
      sessionTotal -= parseFloat(e.target.dataset.total);
      document.getElementById("session-total").textContent = money(sessionTotal);
      document.getElementById("sl-" + id).classList.add("voided");
      e.target.remove();
      toast("Reversed", true);
    }
  });
}

// ---- transactions page void ----
document.addEventListener("click", async (e) => {
  if (!e.target.classList.contains("void-btn")) return;
  if (!confirm("Void this transaction and return stock?")) return;
  const id = e.target.dataset.id;
  const res = await fetch("/api/void/" + id, { method: "POST" });
  const data = await res.json();
  if (data.ok) {
    document.getElementById("txn-" + id).classList.add("voided");
    e.target.outerHTML = '<span class="muted">voided</span>';
  }
});
