// GameHub — Vista Principal: Hub / Directorio de Páginas + Resumen de Lanzamientos

import { icon } from "./icons.js";
import {
  $,
  canManageSources,
  esc,
  extractDomain,
  faviconUrl,
  hooks,
  originUrl,
  renderPlatformBadges,
  sourceInitials,
  state,
  svgPlaceholder,
  toast,
} from "./state.js";

const TYPE_META = {
  wp_api: { label: "WP API", ico: "zap", cls: "tag-api" },
  rss: { label: "RSS Feed", ico: "rss", cls: "tag-rss" },
  json_index: { label: "Catálogo JSON", ico: "database", cls: "tag-json" },
  search_url: { label: "Buscador", ico: "search", cls: "tag-search" },
};

function buildExternalSearchUrl(source, query) {
  const tpl = source?.search_url_template || "";
  if (!tpl || !tpl.includes("{query}")) return "";
  return tpl.replace("{query}", encodeURIComponent(query.trim()).replace(/%20/g, "+"));
}

function siteHomepage(source) {
  const raw = source?.url || source?.search_url_template || "";
  if (!raw || (!raw.startsWith("http://") && !raw.startsWith("https://"))) return "";
  if (source.type === "rss" || source.type === "json_index") {
    return originUrl(raw) || raw;
  }
  return raw.includes("{query}") ? originUrl(raw) : raw;
}

export function renderHub() {
  renderHubStats();
  renderHubCategories();
  renderHubDirectory();
  renderHubUpcomingRail();
}

export function renderHubStats() {
  const activeSources = (state.sources || []).filter((s) => s.enabled);
  const elSources = $("#hub-stat-sources");
  const elLatest = $("#hub-stat-latest");
  const elSaved = $("#hub-stat-saved");
  const elCal = $("#hub-stat-cal");

  if (elSources) elSources.textContent = String(activeSources.length);
  if (elLatest) elLatest.textContent = String(state.latestTotal || 0);
  if (elSaved) elSaved.textContent = $("#badge-bookmarks")?.textContent || String(state.bookmarks.length || 0);

  if (elCal) {
    const todayIso = state.calData.today || new Date().toISOString().slice(0, 10);
    const in7 = new Date();
    in7.setDate(in7.getDate() + 7);
    const weekEnd = in7.toISOString().slice(0, 10);
    const soonCount = (state.calData.items || []).filter(
      (it) => it.precision === "day" && it.release_date >= todayIso && it.release_date <= weekEnd
    ).length;
    elCal.textContent = state.calLoaded ? String(soonCount) : "—";
  }

  // Mostrar/ocultar CTA de añadir páginas según permisos
  const editable = canManageSources();
  $("#btn-hub-add-source")?.classList.toggle("hidden", !editable);
}

function renderHubCategories() {
  const wrap = $("#hub-category-pills");
  if (!wrap) return;
  const active = (state.sources || []).filter((s) => s.enabled);
  const counts = new Map();
  active.forEach((s) => {
    const cat = s.category || "General";
    counts.set(cat, (counts.get(cat) || 0) + 1);
  });

  const categories = ["", ...Array.from(counts.keys())];
  if (state.hubCategory && !counts.has(state.hubCategory)) {
    state.hubCategory = "";
  }

  wrap.innerHTML = "";
  categories.forEach((cat) => {
    const btn = document.createElement("button");
    btn.className = `pill ${state.hubCategory === cat ? "active" : ""}`;
    const cnt = cat ? counts.get(cat) : active.length;
    btn.innerHTML = `${esc(cat || "Todas las categorías")}<span class="pill-count">${cnt}</span>`;
    btn.addEventListener("click", () => {
      state.hubCategory = cat;
      renderHubCategories();
      renderHubDirectory();
    });
    wrap.appendChild(btn);
  });
}

function renderSiteCard(src) {
  const domain = extractDomain(src.url || src.search_url_template || "");
  const fav = faviconUrl(src.url || src.search_url_template || "");
  const home = siteHomepage(src);
  const tMeta = TYPE_META[src.type] || { label: src.type, ico: "globe", cls: "" };
  const hasSearch = Boolean(src.search_url_template && src.search_url_template.includes("{query}"));
  const hasFeed = src.type !== "search_url";

  const card = document.createElement("article");
  card.className = "hub-card";

  const statusText = src.last_error
    ? "Error en sincronización"
    : hasFeed && src.cached_items > 0
      ? `${src.cached_items} entradas`
      : hasSearch
        ? "Búsqueda directa lista"
        : "Enlace listo";

  const statusCls = src.last_error ? "err" : "ok";

  card.innerHTML = `
    <div class="hub-card-top">
      <div class="hub-favicon">
        ${
          fav
            ? `<img src="${esc(fav)}" alt="" loading="lazy" onerror="this.style.display='none';this.nextElementSibling.style.display='grid';" />`
            : ""
        }
        <span class="hub-favicon-fallback" style="${fav ? "display:none;" : "display:grid;"}">${esc(sourceInitials(src.name))}</span>
      </div>
      <div class="hub-card-head">
        <div class="hub-card-title" title="${esc(src.name)}">${esc(src.name)}</div>
        <div class="hub-card-domain" title="${esc(domain || src.url)}">
          ${icon("globe", 12)}
          <span>${esc(domain || "Catálogo local")}</span>
        </div>
      </div>
      <span class="connector-tag ${tMeta.cls}" title="Tipo de conector">
        ${icon(tMeta.ico, 11)}
        <span>${esc(tMeta.label)}</span>
      </span>
    </div>

    ${src.notes ? `<p class="hub-card-notes">${esc(src.notes)}</p>` : ""}

    <div class="hub-card-status">
      <span class="dot-indicator ${statusCls}"></span>
      <span>${esc(statusText)}</span>
    </div>

    <div class="hub-card-actions">
      ${
        home
          ? `<a class="btn btn-primary btn-sm hub-act-open" href="${esc(home)}" target="_blank" rel="noopener">
              ${icon("external", 13)}
              <span>Abrir</span>
            </a>`
          : ""
      }
      ${
        hasSearch
          ? `<button type="button" class="btn btn-secondary btn-sm hub-act-search" title="Buscar un juego directamente en ${esc(src.name)}">
              ${icon("search", 13)}
              <span>Buscar</span>
            </button>`
          : ""
      }
      ${
        hasFeed
          ? `<button type="button" class="btn btn-ghost btn-sm hub-act-feed" title="Ver últimas entradas de ${esc(src.name)}">
              ${icon("flame", 13)}
              <span>Feed</span>
            </button>`
          : ""
      }
    </div>
  `;

  card.querySelector(".hub-act-search")?.addEventListener("click", () => {
    const heroQ = ($("#hub-search-input")?.value || $("#global-search-input")?.value || "").trim();
    if (heroQ) {
      const target = buildExternalSearchUrl(src, heroQ);
      if (target) {
        window.open(target, "_blank", "noopener");
        return;
      }
    }
    const q = window.prompt(`Buscar en ${src.name}:`, heroQ);
    if (q && q.trim()) {
      const target = buildExternalSearchUrl(src, q.trim());
      if (target) window.open(target, "_blank", "noopener");
    }
  });

  card.querySelector(".hub-act-feed")?.addEventListener("click", () => {
    state.selectedSource = src.id;
    state.selectedCategory = "";
    const sel = $("#filter-source");
    if (sel) sel.value = src.id;
    hooks.switchView?.("latest");
    hooks.loadLatest?.(true);
  });

  return card;
}

export function renderHubDirectory() {
  const container = $("#hub-directory");
  if (!container) return;

  const active = (state.sources || []).filter((s) => s.enabled);
  const filter = (state.hubFilter || "").trim().toLowerCase();

  const filtered = active.filter((s) => {
    if (state.hubCategory && (s.category || "General") !== state.hubCategory) return false;
    if (filter) {
      const hay = `${s.name} ${s.category} ${s.url} ${s.notes || ""}`.toLowerCase();
      if (!hay.includes(filter)) return false;
    }
    return true;
  });

  if (!active.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">${icon("layers", 28)}</div>
        <h3>Tu Hub todavía no tiene páginas activas</h3>
        <p>Añade tus sitios de confianza en <strong>Mis Fuentes</strong> pegando una o varias URLs de golpe para generar tu menú personalizado.</p>
        ${
          canManageSources()
            ? `<button class="btn btn-primary" id="btn-empty-goto-sources" style="margin-top:14px;">${icon("plus", 15)} Añadir mis páginas</button>`
            : ""
        }
      </div>`;
    container.querySelector("#btn-empty-goto-sources")?.addEventListener("click", () => {
      hooks.switchView?.("sources");
    });
    return;
  }

  if (!filtered.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">${icon("search", 26)}</div>
        <h3>Sin coincidencias en tu directorio</h3>
        <p>Prueba limpiando el filtro de categoría o buscando otro término.</p>
      </div>`;
    return;
  }

  // Agrupar por categoría respetando el orden de aparición
  const groups = new Map();
  filtered.forEach((s) => {
    const cat = s.category || "General";
    if (!groups.has(cat)) groups.set(cat, []);
    groups.get(cat).push(s);
  });

  container.innerHTML = "";
  groups.forEach((list, category) => {
    const section = document.createElement("div");
    section.className = "hub-category-section";
    section.innerHTML = `
      <div class="hub-cat-header">
        <h2 class="hub-cat-title">${esc(category)}</h2>
        <span class="badge">${list.length} ${list.length === 1 ? "página" : "páginas"}</span>
      </div>
      <div class="hub-grid"></div>
    `;
    const grid = section.querySelector(".hub-grid");
    list.forEach((src) => grid.appendChild(renderSiteCard(src)));
    container.appendChild(section);
  });
}

export function renderHubUpcomingRail() {
  const rail = $("#hub-upcoming-rail");
  const section = $("#hub-upcoming-section");
  if (!rail || !section) return;

  const todayIso = state.calData.today || new Date().toISOString().slice(0, 10);
  const upcoming = (state.calData.items || [])
    .filter((it) => it.precision === "day" && it.release_date >= todayIso)
    .slice(0, 6);

  if (!upcoming.length) {
    section.classList.toggle("hidden", state.calLoaded);
    if (!state.calLoaded) {
      rail.innerHTML = Array.from({ length: 6 })
        .map(
          () => `
          <div class="skeleton-card compact">
            <div class="skeleton skeleton-poster"></div>
            <div class="skeleton-body">
              <div class="skeleton skeleton-line w-85"></div>
              <div class="skeleton skeleton-line w-55"></div>
            </div>
          </div>`
        )
        .join("");
    }
    return;
  }

  section.classList.remove("hidden");
  rail.innerHTML = "";
  upcoming.forEach((c) => {
    const fallbacks = [c.header_url, svgPlaceholder(c.title)].filter(Boolean);
    const primary = c.poster_url || fallbacks[0];
    const [ty, tm, td] = todayIso.split("-").map(Number);
    const [ry, rm, rd] = c.release_date.split("-").map(Number);
    const diff = Math.round((Date.UTC(ry, rm - 1, rd) - Date.UTC(ty, tm - 1, td)) / 86400000);
    const badgeText = diff === 0 ? "HOY" : diff === 1 ? "Mañana" : `En ${diff}d`;
    const badgeCls = diff === 0 ? "today" : diff <= 7 ? "soon" : "";

    const card = document.createElement("article");
    card.className = "hub-release-card";
    card.innerHTML = `
      <div class="hub-rel-poster">
        <img
          src="${esc(primary)}"
          data-fallbacks="${esc(fallbacks.join("||"))}"
          onerror="window.__imgFallback(this)"
          loading="lazy"
          alt="${esc(c.title)}"
        />
        <span class="countdown-pill ${badgeCls}">${esc(badgeText)}</span>
      </div>
      <div class="hub-rel-body">
        <div class="hub-rel-title" title="${esc(c.title)}">${esc(c.title)}</div>
        <div class="plat-tags">${renderPlatformBadges(c.platforms, 3)}</div>
        <div class="hub-rel-date">${esc(c.window_label || c.release_date)}</div>
      </div>
    `;
    card.addEventListener("click", () => {
      if (hooks.openCalendarItem) hooks.openCalendarItem(c);
      else hooks.switchView?.("calendar");
    });
    rail.appendChild(card);
  });
}

export function bindHubEvents() {
  $("#hub-search-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    const q = ($("#hub-search-input")?.value || "").trim();
    if (!q) {
      toast("Escribe el nombre de un juego para buscar en tus páginas", "err");
      return;
    }
    const globalIn = $("#global-search-input");
    if (globalIn) globalIn.value = q;
    hooks.runSearch?.(q);
  });

  $("#hub-site-filter")?.addEventListener("input", (e) => {
    state.hubFilter = e.target.value;
    renderHubDirectory();
  });

  $("#btn-hub-add-source")?.addEventListener("click", () => {
    hooks.switchView?.("sources");
    setTimeout(() => $("#autodetect-url")?.focus(), 80);
  });

  $("#btn-hub-open-calendar")?.addEventListener("click", () => {
    hooks.switchView?.("calendar");
  });

  // KPI cards clicables
  $("#kpi-sources")?.addEventListener("click", () => hooks.switchView?.("sources"));
  $("#kpi-calendar")?.addEventListener("click", () => hooks.switchView?.("calendar"));
  $("#kpi-latest")?.addEventListener("click", () => hooks.switchView?.("latest"));
  $("#kpi-saved")?.addEventListener("click", () => hooks.switchView?.("bookmarks"));
}
