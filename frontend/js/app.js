// GameHub — Coordinador SPA (Hub, Calendario Releases.com, Novedades, Buscador, Guardados y Cuentas)

import { icon } from "./icons.js";
import {
  $,
  $$,
  api,
  esc,
  exportGamesToIcs,
  googleCalendarUrl,
  hooks,
  posterChain,
  relativeTime,
  renderPlatformBadges,
  renderPosterSkeletons,
  setStoredToken,
  splitUris,
  state,
  storeLabelForUrl,
  toast,
} from "./state.js";
import { bindHubEvents, renderHub, renderHubStats } from "./hub.js";
import { bindCalendarEvents, calItemToDrawerItem, loadCalendar, toggleCalendarFavorite } from "./calendar.js";
import { bindSourcesEvents, loadSources } from "./sources.js";

const VALID_VIEWS = new Set(["hub", "calendar", "latest", "search", "bookmarks", "dependencies", "sources"]);

// --------------------------------------------------------------------------- Enrutador Hash + Navegación

function parseHashRoute() {
  const raw = (window.location.hash || "").replace(/^#\/?/, "");
  if (!raw) return { view: "hub", query: "" };
  const [viewPart, qsPart] = raw.split("?");
  const view = VALID_VIEWS.has(viewPart) ? viewPart : "hub";
  const params = new URLSearchParams(qsPart || "");
  return { view, query: params.get("q") || "" };
}

function writeHashRoute(view, query = "") {
  const target = view === "search" && query ? `#search?q=${encodeURIComponent(query)}` : `#${view}`;
  if (window.location.hash !== target) {
    window.history.replaceState(null, "", target);
  }
}

export function switchView(view, { updateHash = true } = {}) {
  const target = VALID_VIEWS.has(view) ? view : "hub";
  state.view = target;

  $$(".nav-btn, .mobile-nav-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === target)
  );
  $$(".view-section").forEach((s) =>
    s.classList.toggle("hidden", s.id !== `view-${target}`)
  );

  if (updateHash) {
    writeHashRoute(target, target === "search" ? state.searchQuery : "");
  }

  // Subir scroll al cambiar de vista
  const scroller = $(".content-scroll");
  if (scroller) scroller.scrollTop = 0;

  if (target === "hub") {
    renderHub();
    if (!state.calLoaded) loadCalendar(false);
  }
  if (target === "calendar") loadCalendar(false);
  if (target === "latest" && !state.latestLoaded) loadLatest(true);
  if (target === "bookmarks") loadBookmarks();
  if (target === "dependencies" && state.depsConfig.runtimes.length === 0) loadDependencies();
  if (target === "sources") loadSources();
}

// --------------------------------------------------------------------------- Acciones de Descarga y Guardado

async function triggerMagnet(uri, ev) {
  ev?.stopPropagation();
  if (!uri || !uri.toLowerCase().startsWith("magnet:?xt=")) {
    toast("Enlace Magnet inválido", "err");
    return;
  }
  if (state.isWebMode) {
    const a = document.createElement("a");
    a.href = uri;
    document.body.appendChild(a);
    a.click();
    a.remove();
    toast("Abriendo enlace Magnet en tu cliente Torrent...");
    return;
  }
  try {
    await api("/api/download/magnet", { method: "POST", body: { uri } });
    toast("Abriendo enlace Magnet en tu cliente Torrent...");
  } catch (err) {
    toast(err.message, "err");
  }
}

async function triggerJDownloader(urls, packageName, ev) {
  ev?.stopPropagation();
  const cleanUrls = (urls || []).filter((u) => /^(https?:\/\/|magnet:\?xt=)/i.test(u));
  if (!cleanUrls.length) {
    toast("No hay enlaces válidos para enviar", "err");
    return;
  }

  if (state.isWebMode) {
    let copied = false;
    if (navigator.clipboard) {
      try {
        await navigator.clipboard.writeText(cleanUrls.join("\n"));
        copied = true;
      } catch {}
    }
    try {
      const formBody = new URLSearchParams({
        passwords: "",
        source: window.location.href,
        package: packageName || "GameHub",
        urls: cleanUrls.join("\r\n"),
      });
      await fetch("http://127.0.0.1:9666/flash/add", {
        method: "POST",
        mode: "no-cors",
        headers: { "Content-Type": "application/x-www-form-urlencoded" },
        body: formBody,
      });
      toast(
        copied
          ? `Enviado a JDownloader 2 (${cleanUrls.length} enlace/s + copiados)`
          : `Enviado a JDownloader 2 (${cleanUrls.length} enlace/s)`
      );
    } catch {
      toast(
        copied
          ? "Enlaces copiados al portapapeles (abre JDownloader 2 para capturarlos)"
          : "Abre JDownloader 2 en tu PC o usa Copiar enlaces",
        copied ? "ok" : "err"
      );
    }
    return;
  }

  try {
    const res = await api("/api/download/jdownloader", {
      method: "POST",
      body: { urls: cleanUrls, package_name: packageName },
    });
    updateJdIndicator(res.online);
    if (!res.sent && res.urls_text && navigator.clipboard) {
      try {
        await navigator.clipboard.writeText(res.urls_text);
      } catch {}
    }
    toast(res.message, "ok");
  } catch (err) {
    toast(err.message, "err");
  }
}

async function copyText(text, label, ev) {
  ev?.stopPropagation();
  try {
    await navigator.clipboard.writeText(text);
    toast(`${label} copiado al portapapeles`);
  } catch {
    toast("No se pudo acceder al portapapeles", "err");
  }
}

async function toggleBookmark(item, ev) {
  ev?.stopPropagation();
  try {
    const res = await api("/api/bookmarks/toggle", { method: "POST", body: { item } });
    item.bookmarked = res.bookmarked;
    toast(res.bookmarked ? "Añadido a Guardados" : "Quitado de Guardados");
    await refreshHealthBadges();
    if (state.view === "bookmarks") loadBookmarks();
    else if (state.view === "latest") renderLatestGrid();
    else if (state.view === "search") renderSearchResults();
  } catch (err) {
    toast(err.message, "err");
  }
}

// --------------------------------------------------------------------------- Tarjetas de Feed

function renderGameCard(item) {
  const { primary, fallbacks } = posterChain(item);
  const { magnets, httpLinks } = splitUris(item);
  const displayTitle = item.steam_info?.official_name || item.clean_title || item.raw_title;

  const el = document.createElement("article");
  el.className = "game-card";
  el.innerHTML = `
    <div class="poster-wrap">
      <img
        src="${esc(primary)}"
        data-fallbacks="${esc(fallbacks.join("||"))}"
        onerror="window.__imgFallback(this)"
        loading="lazy"
        alt="${esc(displayTitle)}"
      />
      <div class="card-badges-top">
        <span class="source-pill" title="${esc(item.source_name)}">${esc(item.source_name)}</span>
        <button class="bookmark-btn ${item.bookmarked ? "saved" : ""}" title="${item.bookmarked ? "Quitar de Guardados" : "Guardar en mi lista"}">
          ${icon(item.bookmarked ? "starFilled" : "star", 14)}
        </button>
      </div>
      <div class="poster-overlay">
        <div class="quick-actions">
          ${magnets.length ? `<button class="btn btn-magnet act-magnet" title="Abrir Magnet">${icon("magnet", 12)} Magnet</button>` : ""}
          ${httpLinks.length ? `<button class="btn btn-jd act-jd" title="Enviar a JDownloader 2">${icon("package", 12)} JD2</button>` : ""}
          ${item.page_url ? `<a class="btn btn-secondary act-web" href="${esc(item.page_url)}" target="_blank" rel="noopener" title="Abrir página original">${icon("arrowUpRight", 13)}</a>` : ""}
        </div>
      </div>
    </div>
    <div class="card-body">
      <div class="card-title" title="${esc(displayTitle)}">${esc(displayTitle)}</div>
      <div class="card-raw" title="${esc(item.raw_title)}">${esc(item.raw_title)}</div>
      <div class="card-meta">
        <span>${esc(relativeTime(item.published_at))}</span>
        ${item.file_size ? `<span class="size-tag">${esc(item.file_size)}</span>` : ""}
      </div>
    </div>
  `;

  el.querySelector(".bookmark-btn").addEventListener("click", (e) => toggleBookmark(item, e));
  el.querySelector(".act-magnet")?.addEventListener("click", (e) => triggerMagnet(magnets[0], e));
  el.querySelector(".act-jd")?.addEventListener("click", (e) => triggerJDownloader(httpLinks, displayTitle, e));
  el.querySelector(".act-web")?.addEventListener("click", (e) => e.stopPropagation());
  el.addEventListener("click", () => openDetailDrawer(item));
  return el;
}

// --------------------------------------------------------------------------- Vista Novedades

export async function loadLatest(reset = true) {
  const grid = $("#latest-grid");
  if (reset) {
    state.latestOffset = 0;
    state.latest = [];
    if (grid) grid.innerHTML = renderPosterSkeletons(10);
  }
  const params = new URLSearchParams({
    limit: String(state.latestLimit),
    offset: String(state.latestOffset),
  });
  if (state.selectedSource) params.set("source_id", state.selectedSource);
  if (state.selectedCategory) params.set("category", state.selectedCategory);
  if (state.magnetOnly) params.set("magnet_only", "true");

  try {
    const data = await api(`/api/releases/latest?${params}`);
    state.latest = reset ? data.items : [...state.latest, ...data.items];
    state.latestTotal = data.total;
    state.latestLoaded = true;
    const badge = $("#badge-latest");
    if (badge) badge.textContent = String(data.total);
    if (data.last_sync) {
      const lbl = $("#last-sync-label");
      if (lbl) lbl.textContent = `Actualizado ${relativeTime(data.last_sync)}`;
    }
    renderHubStats();
    renderCategoryPills();
    renderLatestGrid();
    $("#btn-load-more")?.classList.toggle("hidden", state.latest.length >= state.latestTotal);
  } catch (err) {
    toast(err.message, "err");
    if (grid && reset) {
      grid.innerHTML = `
        <div class="empty-state" style="grid-column:1/-1;">
          <div class="empty-icon">${icon("alertCircle", 26)}</div>
          <h3>Error al cargar novedades</h3>
          <p>${esc(err.message)}</p>
        </div>`;
    }
  }
}

function renderCategoryPills() {
  const fromSources = state.sources
    .filter((s) => s.enabled && s.type !== "search_url" && s.category)
    .map((s) => s.category);
  const unique = Array.from(new Set(fromSources));
  const categories = ["", ...unique];
  const wrap = $("#category-pills");
  if (!wrap) return;
  wrap.innerHTML = "";
  categories.forEach((cat) => {
    const btn = document.createElement("button");
    btn.className = `pill ${state.selectedCategory === cat ? "active" : ""}`;
    btn.textContent = cat || "Todas";
    btn.addEventListener("click", () => {
      state.selectedCategory = cat;
      loadLatest(true);
    });
    wrap.appendChild(btn);
  });
}

function renderLatestGrid() {
  const grid = $("#latest-grid");
  if (!grid) return;
  grid.innerHTML = "";
  const filter = state.inlineFilter.trim().toLowerCase();
  const visible = filter
    ? state.latest.filter((i) =>
        `${i.clean_title} ${i.raw_title} ${i.source_name}`.toLowerCase().includes(filter)
      )
    : state.latest;

  if (visible.length === 0) {
    grid.innerHTML = `
      <div class="empty-state" style="grid-column: 1 / -1;">
        <div class="empty-icon">${icon("flame", 26)}</div>
        <h3>No hay novedades con estos filtros</h3>
        <p>Pulsa <strong>Actualizar feeds</strong> arriba o añade páginas con RSS/API en <strong>Mis Fuentes</strong>.</p>
      </div>`;
    return;
  }
  visible.forEach((item) => grid.appendChild(renderGameCard(item)));
}

// --------------------------------------------------------------------------- Vista Buscador Unificado

let searchDebounce = null;

export async function runSearch(query) {
  const q = (query ?? "").trim();
  state.searchQuery = q;
  if (!q) {
    state.searchData = { items: [], groups: [], external_links: [] };
    renderSearchResults();
    return;
  }
  switchView("search");
  writeHashRoute("search", q);
  const container = $("#search-results");
  if (container) {
    container.innerHTML = `<div class="poster-grid">${renderPosterSkeletons(6)}</div>`;
  }
  try {
    state.searchData = await api(`/api/search?q=${encodeURIComponent(q)}`);
    renderSearchResults();
  } catch (err) {
    toast(err.message, "err");
  }
}

function renderSearchResults() {
  const extBox = $("#search-external-box");
  const extWrap = $("#search-external-links");
  const container = $("#search-results");
  if (!container) return;
  const { items, groups, external_links } = state.searchData;

  if (external_links?.length && state.searchQuery) {
    extBox?.classList.remove("hidden");
    extWrap.innerHTML = external_links
      .map(
        (l) => `
        <a class="btn btn-secondary btn-sm" href="${esc(l.url)}" target="_blank" rel="noopener">
          ${icon("search", 12)}
          <span>${esc(l.name)}</span>
          ${icon("arrowUpRight", 12)}
        </a>`
      )
      .join("");
  } else {
    extBox?.classList.add("hidden");
  }

  if (!state.searchQuery) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">${icon("search", 28)}</div>
        <h3>Escribe el nombre de un juego arriba (Ctrl+K)</h3>
        <p>Busca a la vez en tus fuentes indexadas, APIs WordPress y lanza búsquedas en 1 clic en tus páginas externas.</p>
      </div>`;
    return;
  }

  if (!items?.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">${icon("search", 26)}</div>
        <h3>Sin coincidencias en caché para «${esc(state.searchQuery)}»</h3>
        <p>Usa los accesos rápidos de arriba para buscar directamente en tus webs configuradas o añade más fuentes.</p>
      </div>`;
    return;
  }

  if (state.searchMode === "cards") {
    const grid = document.createElement("div");
    grid.className = "poster-grid";
    items.forEach((it) => grid.appendChild(renderGameCard(it)));
    container.innerHTML = "";
    container.appendChild(grid);
    return;
  }

  const list = document.createElement("div");
  list.className = "group-list";

  groups.forEach((grp) => {
    const sampleItem = grp.releases[0];
    const { primary, fallbacks } = posterChain({
      ...sampleItem,
      steam_info: grp.steam_info,
      clean_title: grp.title,
    });
    const card = document.createElement("div");
    card.className = "group-card";
    card.innerHTML = `
      <img
        class="group-poster"
        src="${esc(primary)}"
        data-fallbacks="${esc(fallbacks.join("||"))}"
        onerror="window.__imgFallback(this)"
        alt="${esc(grp.title)}"
      />
      <div>
        <div style="display:flex;align-items:center;justify-content:space-between;gap:10px;flex-wrap:wrap;">
          <div>
            <h3 style="font-size:17px;font-weight:700;">${esc(grp.title)}</h3>
            <span style="font-size:12px;color:var(--text-muted);">
              ${grp.releases.length} resultado(s) en ${grp.sources_count} fuente(s)
            </span>
          </div>
          ${grp.steam_info?.store_url ? `<a href="${esc(grp.steam_info.store_url)}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm">Ficha Steam ${icon("arrowUpRight", 12)}</a>` : ""}
        </div>
        <div class="release-rows"></div>
      </div>
    `;

    const rowsEl = card.querySelector(".release-rows");
    grp.releases.forEach((rel) => {
      const { magnets, httpLinks } = splitUris(rel);
      const row = document.createElement("div");
      row.className = "release-row";
      row.innerHTML = `
        <div style="min-width:0;flex:1;cursor:pointer;" class="rel-info">
          <div style="display:flex;align-items:center;gap:7px;flex-wrap:wrap;">
            <span class="badge">${esc(rel.source_name)}</span>
            ${rel.file_size ? `<span class="size-tag">${esc(rel.file_size)}</span>` : ""}
            <span style="font-size:11.5px;color:var(--text-dim);">${esc(relativeTime(rel.published_at))}</span>
          </div>
          <div style="font-weight:600;margin-top:4px;word-break:break-word;font-size:13px;">${esc(rel.raw_title)}</div>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          ${magnets.length ? `<button class="btn btn-magnet btn-sm r-mag">${icon("magnet", 12)} Magnet</button>` : ""}
          ${httpLinks.length ? `<button class="btn btn-jd btn-sm r-jd">${icon("package", 12)} JD2</button>` : ""}
          ${rel.page_url ? `<a class="btn btn-secondary btn-sm" href="${esc(rel.page_url)}" target="_blank" rel="noopener">Web ${icon("arrowUpRight", 12)}</a>` : ""}
        </div>
      `;
      row.querySelector(".rel-info").addEventListener("click", () => openDetailDrawer(rel));
      row.querySelector(".r-mag")?.addEventListener("click", (e) => triggerMagnet(magnets[0], e));
      row.querySelector(".r-jd")?.addEventListener("click", (e) => triggerJDownloader(httpLinks, grp.title, e));
      rowsEl.appendChild(row);
    });

    list.appendChild(card);
  });

  container.innerHTML = "";
  container.appendChild(list);
}

// --------------------------------------------------------------------------- Vista Guardados

async function loadBookmarks() {
  const grid = $("#bookmarks-grid");
  if (grid) grid.innerHTML = renderPosterSkeletons(6);
  try {
    const data = await api("/api/bookmarks");
    state.bookmarks = data.items || [];
    const badge = $("#badge-bookmarks");
    if (badge) badge.textContent = String(state.bookmarks.length);
    renderHubStats();
    grid.innerHTML = "";
    if (!state.bookmarks.length) {
      grid.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1;">
          <div class="empty-icon">${icon("bookmark", 26)}</div>
          <h3>Aún no tienes juegos guardados</h3>
          <p>Pulsa el botón de estrella en cualquier tarjeta de Novedades o del Buscador para guardarlo en tu lista personal.</p>
        </div>`;
      return;
    }
    state.bookmarks.forEach((it) => grid.appendChild(renderGameCard(it)));
  } catch (err) {
    toast(err.message, "err");
  }
}

// --------------------------------------------------------------------------- Drawer de Detalles

export async function openDetailDrawer(item) {
  const backdrop = $("#detail-backdrop");
  const { primary, fallbacks } = posterChain(item);
  const { magnets, httpLinks } = splitUris(item);
  const title = item.steam_info?.official_name || item.clean_title || item.raw_title;
  const heroBg = item.steam_info?.header_url || item.image_url || "";
  const calItem = item.cal_item || null;
  const gcal = calItem ? googleCalendarUrl(calItem) : "";
  const ytTrailer = `https://www.youtube.com/results?search_query=${encodeURIComponent(title + " official trailer")}`;

  $("#drawer-hero").style.backgroundImage =
    heroBg && /^https?:\/\//i.test(heroBg) ? `url("${heroBg.replace(/"/g, "%22")}")` : "none";
  const poster = $("#drawer-poster");
  poster.src = primary;
  poster.dataset.fallbacks = fallbacks.join("||");
  poster.onerror = function () {
    window.__imgFallback(this);
  };

  $("#drawer-title").textContent = title;
  $("#drawer-raw").textContent = item.raw_title;
  $("#drawer-badges").innerHTML = `
    <span class="badge">${esc(item.source_name)}</span>
    <span class="badge">${esc(item.source_category)}</span>
    ${item.platforms?.length ? renderPlatformBadges(item.platforms, 6) : ""}
    ${item.file_size ? `<span class="size-tag">${esc(item.file_size)}</span>` : ""}
  `;

  const extStoreLabel = item.external_store_url ? storeLabelForUrl(item.external_store_url, null) : "";
  const body = $("#drawer-body");
  body.innerHTML = `
    <div class="drawer-actions">
      ${
        calItem
          ? `<button class="btn ${calItem.favorited ? "btn-primary" : "btn-secondary"}" id="d-cal-fav">
              ${icon(calItem.favorited ? "starFilled" : "star", 14)}
              <span>${calItem.favorited ? "Siguiendo" : "Seguir lanzamiento"}</span>
            </button>`
          : ""
      }
      ${magnets.map((m, idx) => `<button class="btn btn-magnet d-mag" data-idx="${idx}">${icon("magnet", 14)} Magnet ${magnets.length > 1 ? idx + 1 : ""}</button>`).join("")}
      ${httpLinks.length ? `<button class="btn btn-jd" id="d-jd">${icon("package", 14)} JDownloader 2 (${httpLinks.length})</button>` : ""}
      ${magnets.length || httpLinks.length ? `<button class="btn btn-secondary" id="d-copy">${icon("copy", 14)} Copiar enlaces</button>` : ""}
      ${item.page_url ? `<a class="btn btn-secondary" href="${esc(item.page_url)}" target="_blank" rel="noopener">${icon("external", 14)} Página fuente</a>` : ""}
      <button class="btn btn-primary" id="d-search-hub">${icon("search", 14)} Buscar en mi Hub</button>
      ${gcal ? `<a class="btn btn-secondary" href="${esc(gcal)}" target="_blank" rel="noopener">${icon("calendarPlus", 14)} Google Calendar</a>` : ""}
      ${calItem && calItem.precision === "day" ? `<button class="btn btn-secondary" id="d-ics">${icon("download", 14)} .ics</button>` : ""}
      <a class="btn btn-secondary" href="${esc(ytTrailer)}" target="_blank" rel="noopener">${icon("play", 14)} Tráiler</a>
      ${item.steam_info?.store_url ? `<a class="btn btn-secondary" href="${esc(item.steam_info.store_url)}" target="_blank" rel="noopener">${icon("external", 14)} Steam</a>` : ""}
      ${item.external_store_url ? `<a class="btn btn-secondary" href="${esc(item.external_store_url)}" target="_blank" rel="noopener">${icon("external", 14)} ${esc(extStoreLabel)}</a>` : ""}
    </div>

    ${
      item.genres?.length && !item.steam_info?.appid
        ? `<div style="display:flex;gap:6px;flex-wrap:wrap;">
            ${item.genres.map((g) => `<span class="pill pill-xs">${esc(g)}</span>`).join("")}
          </div>`
        : ""
    }
    ${item.excerpt ? `<div class="req-box">${esc(item.excerpt)}</div>` : ""}
    <div id="drawer-steam-extra" style="color:var(--text-muted);font-size:13px;">
      ${
        item.steam_info?.appid
          ? `<div style="display:flex;flex-direction:column;gap:10px;">
              <div class="skeleton skeleton-line w-85"></div>
              <div class="skeleton skeleton-line w-55"></div>
            </div>`
          : ""
      }
    </div>
  `;

  body.querySelector("#d-cal-fav")?.addEventListener("click", async (e) => {
    await toggleCalendarFavorite(calItem, e);
    const btn = body.querySelector("#d-cal-fav");
    if (btn) {
      btn.className = `btn ${calItem.favorited ? "btn-primary" : "btn-secondary"}`;
      btn.innerHTML = `${icon(calItem.favorited ? "starFilled" : "star", 14)}<span>${calItem.favorited ? "Siguiendo" : "Seguir lanzamiento"}</span>`;
    }
  });
  body.querySelector("#d-ics")?.addEventListener("click", () => {
    exportGamesToIcs([calItem], `${title.toLowerCase().replace(/[^a-z0-9]+/g, "-")}.ics`);
  });
  body.querySelectorAll(".d-mag").forEach((btn) =>
    btn.addEventListener("click", (e) => triggerMagnet(magnets[Number(btn.dataset.idx)], e))
  );
  body.querySelector("#d-jd")?.addEventListener("click", (e) => triggerJDownloader(httpLinks, title, e));
  body.querySelector("#d-copy")?.addEventListener("click", (e) =>
    copyText([...magnets, ...httpLinks].join("\n"), "Enlaces", e)
  );
  body.querySelector("#d-search-hub")?.addEventListener("click", () => {
    backdrop.classList.add("hidden");
    const input = $("#global-search-input");
    if (input) input.value = title;
    runSearch(title);
  });

  backdrop.classList.remove("hidden");

  if (item.steam_info?.appid) {
    try {
      const det = await api(`/api/steam/details/${item.steam_info.appid}`);
      const extra = $("#drawer-steam-extra");
      const metaChips = [
        ...(det.genres || []).map((g) => `<span class="pill pill-xs">${esc(g)}</span>`),
        det.metacritic ? `<span class="badge badge-installed">Metacritic ${esc(det.metacritic)}</span>` : "",
        det.release_date ? `<span class="badge">${esc(det.release_date)}</span>` : "",
      ].filter(Boolean);

      const devPub = [
        det.developers?.length ? `Desarrollador: ${det.developers.join(", ")}` : "",
        det.publishers?.length ? `Editor: ${det.publishers.join(", ")}` : "",
      ]
        .filter(Boolean)
        .join(" · ");

      extra.innerHTML = `
        ${metaChips.length ? `<div style="display:flex;gap:7px;flex-wrap:wrap;margin-bottom:12px;">${metaChips.join("")}</div>` : ""}
        ${devPub ? `<div style="font-size:12px;color:var(--text-dim);margin-bottom:10px;">${esc(devPub)}</div>` : ""}
        ${det.short_description ? `<p style="color:var(--text-main);margin-bottom:16px;line-height:1.65;">${esc(det.short_description)}</p>` : ""}
        ${
          det.screenshots?.length
            ? `<div class="shots-grid" style="margin-bottom:16px;">
                ${det.screenshots.map((s) => `<a href="${esc(s.full)}" target="_blank" rel="noopener"><img src="${esc(s.thumb)}" loading="lazy" alt="Captura" /></a>`).join("")}
              </div>`
            : ""
        }
        ${
          det.pc_minimum || det.pc_recommended
            ? `
            <div class="req-header">
              <h4>Requisitos de PC (Steam)</h4>
              ${
                det.pc_minimum && det.pc_recommended
                  ? `<div class="seg-group sm">
                      <button type="button" class="seg-btn active" data-req="min">Mínimos</button>
                      <button type="button" class="seg-btn" data-req="rec">Recomendados</button>
                    </div>`
                  : ""
              }
            </div>
            <div class="req-box" id="drawer-req-box">${esc(det.pc_minimum || det.pc_recommended)}</div>
          `
            : ""
        }
      `;

      extra.querySelectorAll("[data-req]").forEach((btn) =>
        btn.addEventListener("click", () => {
          extra.querySelectorAll("[data-req]").forEach((b) => b.classList.toggle("active", b === btn));
          const rbox = extra.querySelector("#drawer-req-box");
          if (rbox) rbox.textContent = btn.dataset.req === "rec" ? det.pc_recommended : det.pc_minimum;
        })
      );
    } catch {
      const extra = $("#drawer-steam-extra");
      if (extra) extra.textContent = "";
    }
  }
}

// --------------------------------------------------------------------------- Vista Dependencias

function buildWingetCmd(id) {
  return `winget install --id ${id} -e --accept-package-agreements --accept-source-agreements`;
}

function downloadRuntimesBat() {
  const runtimes = state.depsConfig.runtimes || [];
  if (!runtimes.length) return;
  const lines = [
    "@echo off",
    "chcp 65001 >nul",
    "title GameHub - Instalador Oficial de Runtimes PC Gaming",
    "echo ===============================================================",
    "echo   GameHub - Instalando Runtimes Oficiales de Windows via Winget",
    "echo ===============================================================",
    "echo.",
    ...runtimes.flatMap((r) => [
      `echo [+] Instalando ${r.name} (${r.winget_id})...`,
      buildWingetCmd(r.winget_id),
      "echo.",
    ]),
    "echo ===============================================================",
    "echo   Proceso completado. Ya puedes cerrar esta ventana.",
    "echo ===============================================================",
    "pause",
  ];
  const blob = new Blob([lines.join("\r\n")], { type: "text/plain;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = "Instalar_Runtimes_GameHub.bat";
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1500);
  toast("Descargado Instalar_Runtimes_GameHub.bat");
}

async function loadDependencies() {
  try {
    state.depsConfig = await api("/api/dependencies");
    renderDependencies();
    if (!state.isWebMode) {
      checkInstalledDeps(false);
    } else {
      const c = $("#deps-counter");
      if (c) c.textContent = "Instalación local vía Winget (.bat)";
    }
  } catch (err) {
    toast(err.message, "err");
  }
}

async function checkInstalledDeps(notify = true) {
  if (state.isWebMode) return;
  const btn = $("#btn-check-deps");
  if (btn) {
    btn.disabled = true;
    btn.innerHTML = `${icon("refresh", 14, "spin")} <span>Comprobando...</span>`;
  }
  try {
    const res = await api("/api/dependencies/status");
    state.depsInstalled = res.installed || {};
    const c = $("#deps-counter");
    if (c) {
      c.textContent = res.winget_available
        ? `${res.installed_count} / ${res.total_count} instalados`
        : "Winget no detectado";
    }
    renderDependencies();
    if (notify) toast("Estado de dependencias actualizado");
  } catch (err) {
    if (notify) toast(err.message, "err");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.innerHTML = `${icon("search", 14)} <span>Comprobar instalados</span>`;
    }
  }
}

async function installWinget(ids) {
  if (state.isWebMode) {
    if (ids.length > 1) downloadRuntimesBat();
    else if (ids.length === 1) await copyText(buildWingetCmd(ids[0]), `Comando Winget (${ids[0]})`);
    return;
  }
  try {
    const res = await api("/api/dependencies/install", {
      method: "POST",
      body: { package_ids: ids, interactive_window: true },
    });
    toast(res.message);
  } catch (err) {
    toast(err.message, "err");
  }
}

function renderDepCard(dep) {
  const isInstalled = !state.isWebMode && Boolean(state.depsInstalled[dep.winget_id]);
  const btnHtml = state.isWebMode
    ? `${icon("copy", 13)} <span>Copiar comando Winget</span>`
    : isInstalled
      ? `${icon("refresh", 13)} <span>Reinstalar / Actualizar</span>`
      : `${icon("zap", 13)} <span>Instalar en 1 clic</span>`;

  const card = document.createElement("div");
  card.className = "dep-card";
  card.innerHTML = `
    <div class="dep-top">
      <div>
        <div style="font-weight:700;font-size:14.5px;">${esc(dep.name)}</div>
        <code class="mono-id">${esc(dep.winget_id)}</code>
      </div>
      <span class="badge ${isInstalled ? "badge-installed" : ""}">
        ${isInstalled ? "Instalado" : esc(dep.badge || "Oficial")}
      </span>
    </div>
    <p style="font-size:12.5px;color:var(--text-muted);flex:1;">${esc(dep.description)}</p>
    ${dep.fixes ? `<div class="dep-fixes">${icon("checkCircle", 13)} <span>${esc(dep.fixes)}</span></div>` : ""}
    <div style="display:flex;gap:8px;margin-top:4px;">
      <button class="btn ${isInstalled ? "btn-secondary" : "btn-primary"} btn-sm act-winget" style="flex:1;">
        ${btnHtml}
      </button>
      <a class="btn btn-secondary btn-sm" href="${esc(dep.official_url)}" target="_blank" rel="noopener">Oficial ${icon("arrowUpRight", 12)}</a>
    </div>
  `;
  card.querySelector(".act-winget").addEventListener("click", () => installWinget([dep.winget_id]));
  return card;
}

function renderDependencies() {
  const rGrid = $("#runtimes-grid");
  const tGrid = $("#tools-grid");
  const sGrid = $("#safety-grid");
  if (!rGrid || !tGrid || !sGrid) return;
  rGrid.innerHTML = "";
  tGrid.innerHTML = "";
  sGrid.innerHTML = "";

  (state.depsConfig.runtimes || []).forEach((d) => rGrid.appendChild(renderDepCard(d)));
  (state.depsConfig.tools || []).forEach((d) => tGrid.appendChild(renderDepCard(d)));

  (state.depsConfig.safety_rules || []).forEach((rule) => {
    const c = document.createElement("div");
    c.className = "dep-card";
    c.innerHTML = `
      <div class="dep-top">
        <strong style="font-size:14.5px;">${esc(rule.title)}</strong>
        <span class="badge">${esc(rule.tag)}</span>
      </div>
      <p style="font-size:12.5px;color:var(--text-muted);white-space:pre-line;flex:1;">${esc(rule.body)}</p>
      ${
        rule.links?.length
          ? `<div style="display:flex;gap:7px;flex-wrap:wrap;margin-top:4px;">
              ${rule.links.map((l) => `<a class="btn btn-secondary btn-sm" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ${icon("arrowUpRight", 12)}</a>`).join("")}
            </div>`
          : ""
      }
    `;
    sGrid.appendChild(c);
  });
}

// --------------------------------------------------------------------------- Cuentas, Sesión y Modo Web vs Local

function renderUserSessionUI() {
  const box = $("#sidebar-user-box");
  const topSlot = $("#topbar-user-slot");
  const u = state.user;

  if (u) {
    const initials = (u.display_name || u.username || "U").slice(0, 2).toUpperCase();
    if (box) {
      box.innerHTML = `
        <div class="user-avatar" title="${esc(u.display_name)} (@${esc(u.username)})">${esc(initials)}</div>
        <div class="user-meta">
          <div class="user-name">
            <span>${esc(u.display_name)}</span>
            ${u.is_admin ? `<span class="badge-admin">Admin</span>` : ""}
          </div>
          <div class="user-handle">@${esc(u.username)}</div>
        </div>
        <button class="btn btn-ghost btn-icon-only" id="btn-logout-sidebar" title="Cerrar sesión">${icon("logOut", 15)}</button>
      `;
      box.querySelector("#btn-logout-sidebar")?.addEventListener("click", logoutUser);
    }
    if (topSlot) {
      topSlot.innerHTML = `
        <button class="topbar-user-pill" id="btn-topbar-logout" title="Sesión: @${esc(u.username)} (pulsa para salir)">
          <span class="mini-avatar">${esc(initials)}</span>
          <span class="topbar-user-name">${esc(u.display_name)}</span>
          ${icon("logOut", 13)}
        </button>
      `;
      topSlot.querySelector("#btn-topbar-logout")?.addEventListener("click", () => {
        if (window.confirm(`¿Cerrar sesión de @${u.username}?`)) logoutUser();
      });
    }
  } else {
    if (box) {
      box.innerHTML = `
        <button class="btn btn-secondary btn-sm" id="btn-open-auth-sidebar" style="width:100%;">
          ${icon("user", 14)} <span>Iniciar sesión / Registro</span>
        </button>
      `;
      box.querySelector("#btn-open-auth-sidebar")?.addEventListener("click", () =>
        openAuthModal(state.hasAnyUsers ? "login" : "register")
      );
    }
    if (topSlot) {
      topSlot.innerHTML = `
        <button class="btn btn-secondary btn-sm" id="btn-open-auth-top">${icon("user", 14)} <span>Entrar</span></button>
      `;
      topSlot.querySelector("#btn-open-auth-top")?.addEventListener("click", () =>
        openAuthModal(state.hasAnyUsers ? "login" : "register")
      );
    }
  }
}

function applyDeploymentModeUI() {
  const modeBadge = $("#mode-badge");
  if (modeBadge) {
    modeBadge.textContent = state.isWebMode ? "CLOUD" : "LOCAL";
    modeBadge.classList.toggle("badge-web", state.isWebMode);
  }
  document.title = state.isWebMode
    ? "GameHub — Hub de Juegos & Calendario de Lanzamientos"
    : "GameHub Local — Hub Gaming & Calendario";

  // En modo Web ocultamos por completo los controles de escritorio Windows para evitar ruido
  $("#jd-status-box")?.classList.toggle("hidden", state.isWebMode);
  $("#btn-desktop-shortcut")?.classList.toggle("hidden", state.isWebMode);
  $("#btn-check-deps")?.classList.toggle("hidden", state.isWebMode);

  const installAllBtn = $("#btn-install-all-runtimes");
  if (installAllBtn) {
    installAllBtn.innerHTML = state.isWebMode
      ? `${icon("download", 14)} <span>Descargar Instalador Runtimes (.bat)</span>`
      : `${icon("zap", 14)} <span>Instalar Todos los Runtimes</span>`;
  }

  renderUserSessionUI();
}

function setAuthTab(tab) {
  state.authTab = tab === "register" ? "register" : "login";
  const isReg = state.authTab === "register";
  $("#tab-auth-login")?.classList.toggle("active", !isReg);
  $("#tab-auth-register")?.classList.toggle("active", isReg);
  $("#field-auth-displayname")?.classList.toggle("hidden", !isReg);
  $("#field-auth-invite")?.classList.toggle("hidden", !(isReg && state.inviteCodeRequired));
  $("#auth-first-admin-hint")?.classList.toggle("hidden", !(isReg && !state.hasAnyUsers));
  $("#auth-password").autocomplete = isReg ? "new-password" : "current-password";
  $("#btn-auth-submit").innerHTML = isReg
    ? `${icon("sparkles", 14)} <span>Crear mi cuenta y entrar</span>`
    : `${icon("arrowRight", 14)} <span>Iniciar sesión</span>`;
  $("#auth-error")?.classList.add("hidden");
}

function openAuthModal(tab = "login") {
  setAuthTab(tab);
  const canDismiss = !state.requireAuth || Boolean(state.user);
  $("#auth-close-btn")?.classList.toggle("hidden", !canDismiss);
  $("#auth-overlay")?.classList.remove("hidden");
  setTimeout(() => $("#auth-username")?.focus(), 40);
}

function closeAuthModal() {
  if (state.requireAuth && !state.user) return;
  $("#auth-overlay")?.classList.add("hidden");
}

async function loadAuthenticatedData() {
  state.calLoaded = false;
  state.latestLoaded = false;

  const route = parseHashRoute();
  await Promise.all([refreshHealthBadges(), loadSources()]);

  // Lanzar vista inicial sin sobrecargar el arranque en frío con peticiones innecesarias
  if (route.view === "search" && route.query) {
    const input = $("#global-search-input");
    if (input) input.value = route.query;
    await runSearch(route.query);
  } else {
    switchView(route.view, { updateHash: false });
  }
}

async function logoutUser() {
  try {
    await api("/api/auth/logout", { method: "POST" });
  } catch {}
  setStoredToken("");
  state.user = null;
  state.bookmarks = [];
  state.calLoaded = false;
  renderUserSessionUI();
  toast("Sesión cerrada");
  if (state.requireAuth) {
    openAuthModal("login");
  } else {
    await loadAuthenticatedData();
  }
}

function updateJdIndicator(online) {
  state.jdOnline = Boolean(online);
  $("#jd-dot")?.classList.toggle("online", state.jdOnline);
  const lbl = $("#jd-label");
  if (lbl) lbl.textContent = state.jdOnline ? "JDownloader 2: Conectado" : "JDownloader 2: Off";
}

export async function refreshHealthBadges() {
  try {
    const h = await api("/api/health");
    if (h.user !== undefined) {
      state.user = h.user;
      renderUserSessionUI();
    }
    if (h.storage) {
      const modeBadge = $("#mode-badge");
      if (modeBadge && state.isWebMode) {
        const isTurso = h.storage.backend === "turso";
        modeBadge.textContent = isTurso ? "TURSO" : "CLOUD";
        modeBadge.title = isTurso
          ? "Base de datos persistente Turso activa"
          : "Modo Web sin Turso (SQLite efímero)";
      }
    }
    if (!state.isWebMode) updateJdIndicator(h.jdownloader?.online);
    const bBm = $("#badge-bookmarks");
    const bCal = $("#badge-calendar");
    const bSrc = $("#badge-sources");
    if (bBm) bBm.textContent = String(h.stats?.bookmarks || 0);
    if (bCal) bCal.textContent = String(h.stats?.calendar_favorites || 0);
    if (bSrc) bSrc.textContent = String(h.sources_enabled || 0);
    renderHubStats();
  } catch {}
}

// --------------------------------------------------------------------------- Eventos Globales

function bindEvents() {
  $$(".nav-btn, .mobile-nav-btn").forEach((btn) =>
    btn.addEventListener("click", () => switchView(btn.dataset.view))
  );
  $$("[data-goto]").forEach((btn) =>
    btn.addEventListener("click", () => switchView(btn.dataset.goto))
  );

  window.addEventListener("hashchange", () => {
    const route = parseHashRoute();
    if (route.view === "search" && route.query && route.query !== state.searchQuery) {
      const input = $("#global-search-input");
      if (input) input.value = route.query;
      runSearch(route.query);
    } else if (route.view !== state.view) {
      switchView(route.view, { updateHash: false });
    }
  });

  // Auth Modal
  $("#tab-auth-login")?.addEventListener("click", () => setAuthTab("login"));
  $("#tab-auth-register")?.addEventListener("click", () => setAuthTab("register"));
  $("#auth-close-btn")?.addEventListener("click", closeAuthModal);
  $("#auth-overlay")?.addEventListener("click", (e) => {
    if (e.target.id === "auth-overlay") closeAuthModal();
  });

  $("#auth-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const errBox = $("#auth-error");
    const submitBtn = $("#btn-auth-submit");
    errBox.classList.add("hidden");

    const username = $("#auth-username").value.trim();
    const password = $("#auth-password").value;
    const display_name = $("#auth-displayname").value.trim();
    const invite_code = $("#auth-invite").value.trim();

    const isReg = state.authTab === "register";
    submitBtn.disabled = true;
    submitBtn.innerHTML = `${icon("refresh", 14, "spin")} <span>${isReg ? "Creando cuenta..." : "Verificando..."}</span>`;
    try {
      const endpoint = isReg ? "/api/auth/register" : "/api/auth/login";
      const body = isReg
        ? { username, password, display_name, invite_code }
        : { username, password };
      const res = await api(endpoint, { method: "POST", body });
      setStoredToken(res.token || "");
      state.user = res.user;
      state.hasAnyUsers = true;
      $("#auth-password").value = "";
      $("#auth-overlay")?.classList.add("hidden");
      renderUserSessionUI();
      toast(isReg ? `Cuenta creada. Bienvenido, ${res.user.display_name}` : `Hola de nuevo, ${res.user.display_name}`);
      await loadAuthenticatedData();
    } catch (err) {
      errBox.textContent = err.message;
      errBox.classList.remove("hidden");
    } finally {
      submitBtn.disabled = false;
      setAuthTab(state.authTab);
    }
  });

  // Atajos de teclado: Ctrl+K, / y Esc
  window.addEventListener("keydown", (e) => {
    const tag = (document.activeElement?.tagName || "").toLowerCase();
    const typing = tag === "input" || tag === "textarea" || tag === "select";

    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      if (!$("#auth-overlay")?.classList.contains("hidden")) return;
      e.preventDefault();
      const input = $("#global-search-input");
      input?.focus();
      input?.select();
    } else if (e.key === "/" && !typing) {
      if (!$("#auth-overlay")?.classList.contains("hidden")) return;
      e.preventDefault();
      $("#global-search-input")?.focus();
    } else if (e.key === "Escape") {
      $("#detail-backdrop")?.classList.add("hidden");
      closeAuthModal();
    }
  });

  $("#drawer-close")?.addEventListener("click", () => $("#detail-backdrop")?.classList.add("hidden"));
  $("#detail-backdrop")?.addEventListener("click", (e) => {
    if (e.target.id === "detail-backdrop") $("#detail-backdrop")?.classList.add("hidden");
  });

  // Buscador global
  $("#global-search-form")?.addEventListener("submit", (e) => {
    e.preventDefault();
    clearTimeout(searchDebounce);
    runSearch($("#global-search-input").value);
  });
  $("#global-search-input")?.addEventListener("input", (e) => {
    clearTimeout(searchDebounce);
    const val = e.target.value;
    if (!val.trim() && state.view === "search") {
      runSearch("");
      return;
    }
    if (val.trim().length >= 2) {
      searchDebounce = setTimeout(() => runSearch(val), 380);
    }
  });

  $("#mode-grouped")?.addEventListener("click", () => {
    state.searchMode = "grouped";
    $("#mode-grouped")?.classList.add("active");
    $("#mode-cards")?.classList.remove("active");
    renderSearchResults();
  });
  $("#mode-cards")?.addEventListener("click", () => {
    state.searchMode = "cards";
    $("#mode-cards")?.classList.add("active");
    $("#mode-grouped")?.classList.remove("active");
    renderSearchResults();
  });

  // Filtros Novedades
  $("#filter-source")?.addEventListener("change", (e) => {
    state.selectedSource = e.target.value;
    loadLatest(true);
  });
  $("#filter-magnet")?.addEventListener("change", (e) => {
    state.magnetOnly = e.target.checked;
    loadLatest(true);
  });
  $("#filter-inline")?.addEventListener("input", (e) => {
    state.inlineFilter = e.target.value;
    renderLatestGrid();
  });
  $("#btn-load-more")?.addEventListener("click", () => {
    state.latestOffset += state.latestLimit;
    loadLatest(false);
  });

  // Refresco global de feeds
  $("#btn-refresh-all")?.addEventListener("click", async () => {
    const btn = $("#btn-refresh-all");
    const ico = btn.querySelector(".ico");
    btn.disabled = true;
    ico?.classList.add("spin");
    try {
      const res = await api("/api/releases/refresh", { method: "POST", body: {} });
      toast(`Feeds sincronizados (${res.synced}/${res.total} OK)`);
      await loadLatest(true);
      await loadSources();
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
      ico?.classList.remove("spin");
    }
  });

  // Local-only controls
  $("#btn-check-jd")?.addEventListener("click", async () => {
    if (state.isWebMode) return;
    const st = await api("/api/download/jd-status");
    updateJdIndicator(st.online);
    toast(st.online ? "JDownloader 2 detectado en 127.0.0.1:9666" : "JDownloader 2 no responde");
  });
  $("#btn-desktop-shortcut")?.addEventListener("click", async () => {
    try {
      const res = await api("/api/system/desktop-shortcut", { method: "POST" });
      toast(res.message);
    } catch (err) {
      toast(err.message, "err");
    }
  });

  // Dependencias
  $("#btn-check-deps")?.addEventListener("click", () => checkInstalledDeps(true));
  $("#btn-install-all-runtimes")?.addEventListener("click", () => {
    const ids = (state.depsConfig.runtimes || []).map((r) => r.winget_id);
    if (ids.length) installWinget(ids);
  });

  // Módulos
  bindHubEvents();
  bindCalendarEvents();
  bindSourcesEvents();
}

// Registrar hooks compartidos
hooks.onUnauthorized = () => {
  renderUserSessionUI();
  openAuthModal(state.hasAnyUsers ? "login" : "register");
};
hooks.switchView = switchView;
hooks.runSearch = runSearch;
hooks.openDetailDrawer = openDetailDrawer;
hooks.openCalendarItem = (c) => openDetailDrawer(calItemToDrawerItem(c));
hooks.loadSources = loadSources;
hooks.loadLatest = loadLatest;
hooks.loadCalendar = loadCalendar;
hooks.refreshHealthBadges = refreshHealthBadges;

async function init() {
  bindEvents();
  try {
    const authStatus = await api("/api/auth/status");
    state.deploymentMode = authStatus.deployment_mode || "local";
    state.isWebMode = Boolean(authStatus.is_web_mode);
    state.requireAuth = Boolean(authStatus.require_auth);
    state.inviteCodeRequired = Boolean(authStatus.invite_code_required);
    state.hasAnyUsers = Boolean(authStatus.has_any_users);
    state.user = authStatus.user || null;
  } catch {}

  applyDeploymentModeUI();

  if (state.requireAuth && !state.user) {
    openAuthModal(state.hasAnyUsers ? "login" : "register");
    return;
  }

  await loadAuthenticatedData();
}

init();
