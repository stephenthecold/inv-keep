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

// ---- modal helpers (used by list pages) ----
function openModal(id) { const d = document.getElementById(id); if (d && d.showModal) d.showModal(); }

// ---- emoji icon picker: clicking a swatch fills the target input ----
document.addEventListener("click", (e) => {
  const btn = e.target.closest(".emoji-pick button");
  if (!btn) return;
  e.preventDefault();
  const wrap = btn.closest(".emoji-pick");
  const target = document.getElementById(wrap.dataset.target);
  if (target) target.value = btn.textContent.trim();
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
      const ic = p.icon ? `<span class="sg-icon">${p.icon}</span>` : "";
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
    document.getElementById("cp-icon").textContent = part.icon || "";
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
