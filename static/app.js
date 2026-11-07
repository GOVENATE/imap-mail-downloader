"use strict";

const $ = (id) => document.getElementById(id);
const state = { token: null, carpetas: [], months: [] };

// Proveedores que requieren App Password.
const NEEDS_APPPASS = new Set(["gmail", "outlook", "yahoo", "icloud"]);

// --- Proveedor: mostrar host/puerto si es custom, y aviso de App Password ---
function onProviderChange() {
  const p = $("provider").value;
  $("customBox").classList.toggle("hidden", p !== "custom");
  $("appPassNote").classList.toggle("hidden", !NEEDS_APPPASS.has(p));
}
$("provider").addEventListener("change", onProviderChange);
onProviderChange();

// --- Ver/ocultar contraseña ---
$("togglePass").addEventListener("click", () => {
  const i = $("password");
  i.type = i.type === "password" ? "text" : "password";
});

// --- Helpers ---
async function postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(data.error || ("Error " + r.status));
  return data;
}

// --- Conectar ---
$("btnConnect").addEventListener("click", async () => {
  const btn = $("btnConnect");
  btn.disabled = true;
  $("connInfo").textContent = "Conectando…";
  try {
    const data = await postJSON("/api/connect", {
      provider: $("provider").value,
      email: $("email").value.trim(),
      password: $("password").value,
      host: $("host").value.trim(),
      port: $("port").value,
    });
    state.token = data.token;
    state.carpetas = data.carpetas;
    // Llenar carpetas: "TODAS" + cada una.
    const sel = $("folder");
    sel.innerHTML = "";
    const optAll = document.createElement("option");
    optAll.value = "__ALL__";
    optAll.textContent = "➤ TODAS las carpetas";
    sel.appendChild(optAll);
    for (const c of data.carpetas) {
      const o = document.createElement("option");
      o.value = c.raw; o.textContent = c.nombre;
      sel.appendChild(o);
    }
    $("connInfo").textContent = `✓ Conectado (${data.servidor}) · ${data.carpetas.length} carpetas`;
    $("card2").hidden = false;
    $("card2").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    $("connInfo").textContent = "";
    alert("No se pudo conectar:\n\n" + e.message +
      "\n\nTip: Gmail/Outlook/Yahoo/iCloud necesitan una Contraseña de aplicación.");
  } finally {
    btn.disabled = false;
  }
});

function carpetasObjetivo() {
  const v = $("folder").value;
  if (v === "__ALL__") return state.carpetas.map((c) => c.raw);
  return [v];
}

// --- Revisar meses ---
$("btnReview").addEventListener("click", async () => {
  const btn = $("btnReview");
  btn.disabled = true; btn.textContent = "Revisando…";
  try {
    const data = await postJSON("/api/review", {
      token: state.token,
      folders: carpetasObjetivo(),
      period: $("period").value,
    });
    renderMonths(data.meses);
    $("card3").hidden = false;
    $("card3").scrollIntoView({ behavior: "smooth", block: "nearest" });
  } catch (e) {
    alert(e.message);
  } finally {
    btn.disabled = false; btn.textContent = "Revisar meses";
  }
});

// --- Tabla de meses con casillas ---
function renderMonths(meses) {
  state.months = meses.map((m) => ({ ...m, on: false }));
  const tb = $("monthsTable").querySelector("tbody");
  tb.innerHTML = "";
  state.months.forEach((m, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML =
      `<td class="c">☐</td><td>${m.anio}</td><td>${m.mes_nombre}</td><td class="r">${m.cantidad}</td>`;
    tr.addEventListener("click", () => toggleMonth(i, tr));
    tb.appendChild(tr);
    m._tr = tr;
  });
  updateSummary();
}

function toggleMonth(i, tr) {
  const m = state.months[i];
  m.on = !m.on;
  tr.classList.toggle("on", m.on);
  tr.querySelector(".c").textContent = m.on ? "☑" : "☐";
  updateSummary();
}

function setAll(val) {
  state.months.forEach((m) => {
    m.on = val;
    m._tr.classList.toggle("on", val);
    m._tr.querySelector(".c").textContent = val ? "☑" : "☐";
  });
  updateSummary();
}
$("btnAll").addEventListener("click", () => setAll(true));
$("btnNone").addEventListener("click", () => setAll(false));

function updateSummary() {
  const sel = state.months.filter((m) => m.on);
  const correos = sel.reduce((s, m) => s + m.cantidad, 0);
  $("selSummary").textContent = `${sel.length} meses · ${correos} correos`;
  $("btnDownload").disabled = sel.length === 0;
}

// --- Descargar con progreso en vivo (SSE) ---
let evtSource = null;
let curJob = null;

$("btnDownload").addEventListener("click", async () => {
  const sel = state.months.filter((m) => m.on);
  if (!sel.length) return;
  const borrar = $("delete").checked;
  if (borrar) {
    const total = sel.reduce((s, m) => s + m.cantidad, 0);
    if (!confirm(`Vas a descargar ${sel.length} mes(es) (~${total} correos) y luego ` +
      `BORRARLOS del servidor.\n\nSolo se borra lo que se descargue y verifique.\n` +
      `Esta acción es IRREVERSIBLE.\n\n¿Continuar?`)) return;
  }
  openDialog();
  try {
    const data = await postJSON("/api/download", {
      token: state.token,
      folders: carpetasObjetivo(),
      months: sel.map((m) => ({ anio: m.anio, mes: m.mes })),
      period: $("period").value,
      delete: borrar,
      dest: $("dest").value,
    });
    curJob = data.job_id;
    listenProgress(data.job_id);
  } catch (e) {
    setDialogError(e.message);
  }
});

function listenProgress(jobId) {
  evtSource = new EventSource(`/api/progress/${jobId}`);
  evtSource.onmessage = (ev) => {
    const d = JSON.parse(ev.data);
    if (d.tipo === "progreso") {
      updateDialog(d);
    } else if (d.tipo === "completado") {
      finishDialog(d);
      evtSource.close();
    } else if (d.tipo === "error") {
      setDialogError(d.mensaje);
      evtSource.close();
    }
  };
  evtSource.onerror = () => { /* se reintenta solo; el cierre llega por mensaje */ };
}

// --- Modal ---
function openDialog() {
  $("overlay").classList.remove("hidden");
  $("btnCancel").classList.remove("hidden");
  $("btnClose").classList.add("hidden");
  $("dlgTitle").textContent = "Descargando correos";
  $("dlgState").textContent = "Preparando…";
  $("dlgCount").textContent = "";
  setPct(0);
}
function setPct(pct) {
  pct = Math.max(0, Math.min(100, Math.round(pct)));
  $("donut").style.setProperty("--pct", pct);
  $("donutPct").textContent = pct + "%";
  $("bar").style.width = pct + "%";
}
function updateDialog(d) {
  setPct(d.pct || 0);
  $("dlgState").textContent = d.estado || "";
  if (d.total) {
    const faltan = Math.max(d.total - d.actual, 0);
    $("dlgCount").textContent = `${d.actual} de ${d.total} · faltan ${faltan}`;
  }
}
function finishDialog(d) {
  setPct(100);
  $("dlgState").textContent = d.mensaje || "✅ Listo";
  const s = d.stats || {};
  $("dlgCount").textContent =
    `Verificados ${s.verificados || 0} · Fallidos ${s.fallidos || 0}` +
    (d.destino ? ` · 📁 ${d.destino}` : "");
  $("btnCancel").classList.add("hidden");
  $("btnClose").classList.remove("hidden");
}
function setDialogError(msg) {
  $("dlgState").textContent = "⚠ " + msg;
  $("btnCancel").classList.add("hidden");
  $("btnClose").classList.remove("hidden");
}
$("btnCancel").addEventListener("click", async () => {
  $("dlgState").textContent = "Cancelando…";
  if (curJob) await postJSON("/api/cancel", { job_id: curJob }).catch(() => {});
});
$("btnClose").addEventListener("click", () => {
  $("overlay").classList.add("hidden");
  if (evtSource) evtSource.close();
});
