// GameHub — Gestión de Fuentes (Autodetector 1-clic, pegado masivo, edición y backup JSON)

import { icon } from "./icons.js";
import {
  $,
  api,
  canManageSources,
  esc,
  extractDomain,
  faviconUrl,
  hooks,
  relativeTime,
  sourceInitials,
  state,
  toast,
} from "./state.js";
import { renderHub } from "./hub.js";

const TYPE_LABELS = {
  wp_api: "WordPress API",
  rss: "Feed RSS / Atom",
  json_index: "Catálogo JSON (FTS5)",
  search_url: "Buscador Directo",
};

export async function loadSources() {
  try {
    const data = await api("/api/sources");
    state.sources = data.sources || [];
    const active = state.sources.filter((s) => s.enabled);
    const badge = $("#badge-sources");
    if (badge) badge.textContent = String(active.length);

    if (!state.latestLoaded) {
      const cachedTotal = active.reduce((acc, s) => acc + (Number(s.cached_items) || 0), 0);
      state.latestTotal = cachedTotal;
      const latestBadge = $("#badge-latest");
      if (latestBadge) latestBadge.textContent = String(cachedTotal);
    }

    const editable = canManageSources();
    $("#sources-admin-panel")?.classList.toggle("hidden", !editable);
    $("#sources-admin-actions")?.classList.toggle("hidden", !editable);
    $("#sources-readonly-note")?.classList.toggle("hidden", editable);

    // Actualizar selector de fuentes en Novedades
    const sel = $("#filter-source");
    if (sel) {
      const current = sel.value;
      sel.innerHTML =
        `<option value="">Todas las fuentes activas</option>` +
        active.map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("");
      sel.value = current;
    }

    renderSourcesList();
    renderHub();
  } catch (err) {
    toast(err.message, "err");
  }
}

export function renderSourcesList() {
  const wrap = $("#sources-list");
  if (!wrap) return;
  wrap.innerHTML = "";
  const editable = canManageSources();

  if (!state.sources.length) {
    wrap.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">${icon("layers", 26)}</div>
        <h3>${editable ? "No hay páginas configuradas todavía" : "El administrador aún no ha añadido páginas"}</h3>
        <p>${
          editable
            ? "Pega arriba la dirección de cualquier web o una lista completa de URLs: GameHub configurará automáticamente el conector y la añadirá a tu Hub."
            : "Cuando el administrador configure las fuentes aparecerán aquí y en el Hub."
        }</p>
      </div>`;
    return;
  }

  state.sources.forEach((src) => {
    const fav = faviconUrl(src.url || src.search_url_template || "");
    const domain = extractDomain(src.url || src.search_url_template || "");
    const el = document.createElement("div");
    el.className = `source-item ${src.enabled ? "" : "disabled"}`;
    el.innerHTML = `
      <div class="source-item-left">
        <div class="hub-favicon sm">
          ${
            fav
              ? `<img src="${esc(fav)}" alt="" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='grid';" />`
              : ""
          }
          <span class="hub-favicon-fallback" style="${fav ? "display:none;" : "display:grid;"}">${esc(sourceInitials(src.name))}</span>
        </div>
        <div style="min-width:0;flex:1;">
          <div class="source-item-head">
            <strong class="source-item-name">${esc(src.name)}</strong>
            <span class="badge">${esc(TYPE_LABELS[src.type] || src.type)}</span>
            <span class="pill pill-xs">${esc(src.category || "General")}</span>
            ${src.cached_items ? `<span class="size-tag">${src.cached_items} en caché</span>` : ""}
            ${src.last_sync ? `<span class="source-sync-time">${esc(relativeTime(src.last_sync))}</span>` : ""}
          </div>
          ${src.notes ? `<div class="source-item-notes">${esc(src.notes)}</div>` : ""}
          ${
            editable
              ? `<div class="source-item-url">${esc(src.url || src.search_url_template || domain)}</div>
                 ${src.last_error ? `<div class="source-item-err">${icon("alertCircle", 13)} ${esc(src.last_error)}</div>` : ""}`
              : ""
          }
        </div>
      </div>

      <div class="source-item-actions">
        ${
          editable
            ? `
          <button class="btn btn-secondary btn-sm s-test" title="Probar conexión">${icon("flask", 13)} <span>Probar</span></button>
          <button class="btn btn-secondary btn-sm s-edit" title="Editar fuente">${icon("edit", 13)} <span>Editar</span></button>
          <button class="btn btn-danger btn-sm s-del" title="Eliminar fuente">${icon("trash", 13)}</button>
          <label class="switch" title="Activar / Desactivar en tu Hub">
            <input type="checkbox" class="s-toggle" ${src.enabled ? "checked" : ""} />
            <span class="slider"></span>
          </label>
        `
            : `
          <span class="badge ${src.enabled ? "badge-installed" : ""}">
            ${src.enabled ? "Activa" : "Inactiva"}
          </span>
        `
        }
      </div>
    `;

    if (editable) {
      el.querySelector(".s-toggle").addEventListener("change", async () => {
        try {
          await api(`/api/sources/${encodeURIComponent(src.id)}/toggle`, { method: "PATCH" });
          await loadSources();
          await hooks.loadLatest?.(true);
        } catch (err) {
          toast(err.message, "err");
        }
      });

      el.querySelector(".s-test").addEventListener("click", async (e) => {
        const btn = e.currentTarget;
        btn.disabled = true;
        btn.innerHTML = `${icon("refresh", 13, "spin")} <span>...</span>`;
        try {
          const res = await api("/api/sources/probe", { method: "POST", body: src });
          toast(`${src.name}: ${res.message}`);
        } catch (err) {
          toast(err.message, "err");
        } finally {
          btn.disabled = false;
          btn.innerHTML = `${icon("flask", 13)} <span>Probar</span>`;
        }
      });

      el.querySelector(".s-edit").addEventListener("click", () => {
        $("#manual-source-form")?.classList.remove("hidden");
        $("#batch-box")?.classList.add("hidden");
        $("#src-id").value = src.id;
        $("#src-name").value = src.name;
        $("#src-type").value = src.type;
        $("#src-category").value = src.category || "General";
        $("#src-url").value = src.url || "";
        $("#src-template").value = src.search_url_template || "";
        const notesEl = $("#src-notes");
        if (notesEl) notesEl.value = src.notes || "";
        $("#manual-source-form")?.scrollIntoView({ behavior: "smooth", block: "nearest" });
      });

      el.querySelector(".s-del").addEventListener("click", async () => {
        if (!window.confirm(`¿Eliminar «${src.name}» de tu Hub y limpiar su caché?`)) return;
        try {
          await api(`/api/sources/${encodeURIComponent(src.id)}`, { method: "DELETE" });
          toast(`Fuente «${src.name}» eliminada`);
          await loadSources();
          await hooks.loadLatest?.(true);
        } catch (err) {
          toast(err.message, "err");
        }
      });
    }

    wrap.appendChild(el);
  });
}

function renderBatchReport(results) {
  const box = $("#batch-report");
  if (!box) return;
  if (!results?.length) {
    box.classList.add("hidden");
    return;
  }
  box.classList.remove("hidden");
  box.innerHTML = `
    <div class="batch-report-title">Resultado de la autodetección (${results.filter((r) => r.ok).length}/${results.length} añadidas)</div>
    <div class="batch-report-list">
      ${results
        .map(
          (r) => `
        <div class="batch-report-row ${r.ok ? "ok" : "err"}">
          <span>${icon(r.ok ? "checkCircle" : "alertCircle", 14)}</span>
          <strong style="min-width:130px;">${esc(r.ok ? r.source.name : r.input)}</strong>
          <span class="batch-report-msg">${esc(r.ok ? `${TYPE_LABELS[r.source.type] || r.source.type} · ${r.source.category} — ${r.source.message}` : r.error)}</span>
        </div>`
        )
        .join("")}
    </div>
  `;
}

export function bindSourcesEvents() {
  // Autodetector 1 URL
  $("#autodetect-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#autodetect-url");
    const catOverride = ($("#autodetect-category")?.value || "").trim();
    const url = input.value.trim();
    if (!url) return;
    const btn = $("#btn-autodetect");
    btn.disabled = true;
    btn.innerHTML = `${icon("refresh", 14, "spin")} <span>Detectando...</span>`;
    try {
      const detected = await api("/api/sources/autodetect", { method: "POST", body: { url } });
      if (catOverride) detected.category = catOverride;
      await api("/api/sources", { method: "POST", body: { ...detected, id: "", sync_now: true } });
      toast(`${detected.name}: ${detected.message}`);
      input.value = "";
      await loadSources();
      await hooks.loadLatest?.(true);
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
      btn.innerHTML = `${icon("sparkles", 14)} <span>Autodetectar y Añadir</span>`;
    }
  });

  $("#btn-toggle-batch")?.addEventListener("click", () => {
    $("#batch-box")?.classList.toggle("hidden");
    $("#manual-source-form")?.classList.add("hidden");
  });

  $("#btn-toggle-manual")?.addEventListener("click", () => {
    $("#manual-source-form")?.classList.toggle("hidden");
    $("#batch-box")?.classList.add("hidden");
  });

  // Lote de URLs
  $("#btn-run-batch")?.addEventListener("click", async () => {
    const lines = $("#batch-urls")
      .value.split(/\r?\n/)
      .map((s) => s.trim())
      .filter((s) => s && !s.startsWith("#"));
    if (!lines.length) {
      toast("Pega al menos una URL en el cuadro de texto", "err");
      return;
    }
    const btn = $("#btn-run-batch");
    btn.disabled = true;
    btn.innerHTML = `${icon("refresh", 14, "spin")} <span>Detectando ${lines.length} enlace(s)...</span>`;
    try {
      const res = await api("/api/sources/autodetect-batch", {
        method: "POST",
        body: { urls: lines, auto_save: true },
      });
      toast(`Añadidas ${res.added} de ${res.processed} páginas a tu Hub`);
      renderBatchReport(res.results || []);
      $("#batch-urls").value = "";
      await loadSources();
      await hooks.loadLatest?.(true);
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
      btn.innerHTML = `${icon("sparkles", 14)} <span>Detectar y Guardar Lista Completa</span>`;
    }
  });

  const readManualPayload = () => ({
    id: $("#src-id").value.trim() || null,
    name: $("#src-name").value.trim(),
    type: $("#src-type").value,
    category: $("#src-category").value.trim() || "General",
    url: $("#src-url").value.trim(),
    search_url_template: $("#src-template").value.trim(),
    notes: ($("#src-notes")?.value || "").trim(),
    enabled: true,
    sync_now: true,
  });

  $("#manual-source-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await api("/api/sources", { method: "POST", body: readManualPayload() });
      toast(`Fuente «${res.source.name}» guardada`);
      $("#btn-reset-manual")?.click();
      await loadSources();
      await hooks.loadLatest?.(true);
    } catch (err) {
      toast(err.message, "err");
    }
  });

  $("#btn-reset-manual")?.addEventListener("click", () => {
    $("#src-id").value = "";
    $("#src-name").value = "";
    $("#src-url").value = "";
    $("#src-template").value = "";
    if ($("#src-notes")) $("#src-notes").value = "";
    $("#probe-output")?.classList.add("hidden");
  });

  $("#btn-probe-source")?.addEventListener("click", async () => {
    const out = $("#probe-output");
    out.classList.remove("hidden");
    out.textContent = "Probando conexión con la fuente...";
    try {
      const res = await api("/api/sources/probe", { method: "POST", body: readManualPayload() });
      const sampleLines = (res.sample || []).map((s) => `• ${s.clean_title}  ←  "${s.raw_title}"`);
      out.textContent = [res.message, ...sampleLines].join("\n");
    } catch (err) {
      out.textContent = `Error: ${err.message}`;
    }
  });

  $("#btn-sync-json")?.addEventListener("click", async () => {
    toast("Sincronizando catálogos JSON...");
    try {
      const res = await api("/api/releases/refresh", { method: "POST", body: { only_type: "json_index" } });
      toast(`Catálogos JSON sincronizados (${res.synced}/${res.total})`);
      await loadSources();
      await hooks.loadLatest?.(true);
    } catch (err) {
      toast(err.message, "err");
    }
  });

  $("#btn-export-sources")?.addEventListener("click", async () => {
    try {
      const data = await api("/api/sources/export");
      const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = "gamehub_sources_backup.json";
      a.click();
      setTimeout(() => URL.revokeObjectURL(a.href), 1500);
      toast("Copia de seguridad de fuentes descargada");
    } catch (err) {
      toast(err.message, "err");
    }
  });

  $("#input-import-sources")?.addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      const list = Array.isArray(parsed) ? parsed : parsed.sources || [];
      const res = await api("/api/sources/import", { method: "POST", body: { sources: list, merge: true } });
      toast(`Importadas ${res.imported} fuentes correctamente`);
      await loadSources();
      await hooks.loadLatest?.(true);
    } catch (err) {
      toast(`Archivo inválido: ${err.message}`, "err");
    } finally {
      e.target.value = "";
    }
  });
}
