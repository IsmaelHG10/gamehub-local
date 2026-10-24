// GameHub Local — Frontend SPA (ES Module sin dependencias externas)

const state = {
  view: "latest",
  latest: [],
  latestTotal: 0,
  latestOffset: 0,
  latestLimit: 48,
  selectedCategory: "",
  selectedSource: "",
  magnetOnly: false,
  inlineFilter: "",
  searchQuery: "",
  searchMode: "grouped",
  searchData: { items: [], groups: [], external_links: [] },
  bookmarks: [],
  sources: [],
  depsConfig: { runtimes: [], tools: [], safety_rules: [] },
  depsInstalled: {},
  jdOnline: false,
};

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function toast(msg, type = "ok") {
  const stack = $("#toast-stack");
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.textContent = msg;
  stack.appendChild(el);
  setTimeout(() => el.remove(), 4200);
}

async function api(path, opts = {}) {
  const init = { ...opts, headers: { "Content-Type": "application/json", ...(opts.headers || {}) } };
  if (init.body && typeof init.body !== "string") init.body = JSON.stringify(init.body);
  const res = await fetch(path, init);
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    throw new Error(data?.detail || `Error HTTP ${res.status}`);
  }
  return data;
}

function svgPlaceholder(title) {
  const clean = (title || "Game").trim();
  const initials = clean
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0] || "")
    .join("")
    .toUpperCase() || "GH";
  const shortTitle = clean.length > 26 ? clean.slice(0, 24) + "…" : clean;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600" viewBox="0 0 400 600">
    <defs>
      <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#0f172a"/>
        <stop offset="55%" stop-color="#1e1b4b"/>
        <stop offset="100%" stop-color="#0b1324"/>
      </linearGradient>
    </defs>
    <rect width="400" height="600" fill="url(#g)"/>
    <circle cx="200" cy="235" r="74" fill="rgba(56,189,248,0.12)" stroke="rgba(56,189,248,0.35)" stroke-width="2"/>
    <text x="200" y="253" text-anchor="middle" fill="#38bdf8" font-family="Segoe UI, sans-serif" font-size="48" font-weight="700">${esc(initials)}</text>
    <text x="200" y="375" text-anchor="middle" fill="#e2e8f0" font-family="Segoe UI, sans-serif" font-size="20" font-weight="600">${esc(shortTitle)}</text>
  </svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

function posterChain(item) {
  const s = item?.steam_info || {};
  const list = [s.poster_url, s.header_url, item?.image_url].filter(Boolean);
  return {
    primary: list[0] || svgPlaceholder(item?.clean_title || item?.raw_title),
    fallbacks: [...list.slice(1), svgPlaceholder(item?.clean_title || item?.raw_title)],
  };
}

window.__imgFallback = function (img) {
  const queue = (img.dataset.fallbacks || "").split("||").filter(Boolean);
  if (queue.length > 0) {
    img.src = queue.shift();
    img.dataset.fallbacks = queue.join("||");
  } else {
    img.onerror = null;
  }
};

function relativeTime(isoOrEpoch) {
  if (!isoOrEpoch) return "Reciente";
  const ms = typeof isoOrEpoch === "number"
    ? (isoOrEpoch < 1e12 ? isoOrEpoch * 1000 : isoOrEpoch)
    : Date.parse(isoOrEpoch);
  if (Number.isNaN(ms)) return "Reciente";
  const diffSec = Math.max(0, Math.floor((Date.now() - ms) / 1000));
  if (diffSec < 60) return "hace unos seg";
  const min = Math.floor(diffSec / 60);
  if (min < 60) return `hace ${min} min`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `hace ${hr} h`;
  const days = Math.floor(hr / 24);
  if (days < 30) return `hace ${days} d`;
  return new Date(ms).toLocaleDateString("es-ES");
}

function splitUris(item) {
  const uris = item?.uris || [];
  const magnets = uris.filter((u) => u.toLowerCase().startsWith("magnet:?xt="));
  const httpLinks = uris.filter((u) => /^https?:\/\//i.test(u));
  if (httpLinks.length === 0 && item?.page_url) {
    httpLinks.push(item.page_url);
  }
  return { magnets, httpLinks };
}

// --------------------------------------------------------------------------- Navegación

function switchView(view) {
  state.view = view;
  $$(".nav-btn").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  $$(".view-section").forEach((s) => s.classList.toggle("hidden", s.id !== `view-${view}`));

  if (view === "bookmarks") loadBookmarks();
  if (view === "dependencies" && state.depsConfig.runtimes.length === 0) loadDependencies();
  if (view === "sources") loadSources();
}

// --------------------------------------------------------------------------- Acciones de Descarga

async function triggerMagnet(uri, ev) {
  ev?.stopPropagation();
  try {
    await api("/api/download/magnet", { method: "POST", body: { uri } });
    toast("🧲 Abriendo enlace Magnet en tu cliente Torrent...");
  } catch (err) {
    toast(err.message, "err");
  }
}

async function triggerJDownloader(urls, packageName, ev) {
  ev?.stopPropagation();
  try {
    const res = await api("/api/download/jdownloader", {
      method: "POST",
      body: { urls, package_name: packageName },
    });
    updateJdIndicator(res.online);
    if (!res.sent && res.urls_text && navigator.clipboard) {
      try { await navigator.clipboard.writeText(res.urls_text); } catch {}
    }
    toast(res.message, res.sent ? "ok" : "ok");
  } catch (err) {
    toast(err.message, "err");
  }
}

async function copyText(text, label, ev) {
  ev?.stopPropagation();
  try {
    await navigator.clipboard.writeText(text);
    toast(`📋 ${label} copiado al portapapeles`);
  } catch {
    toast("No se pudo acceder al portapapeles del navegador", "err");
  }
}

async function toggleBookmark(item, ev) {
  ev?.stopPropagation();
  try {
    const res = await api("/api/bookmarks/toggle", { method: "POST", body: { item } });
    item.bookmarked = res.bookmarked;
    toast(res.bookmarked ? "⭐ Añadido a Guardados" : "Quitado de Guardados");
    await refreshHealthBadges();
    if (state.view === "bookmarks") loadBookmarks();
    else if (state.view === "latest") renderLatestGrid();
    else if (state.view === "search") renderSearchResults();
  } catch (err) {
    toast(err.message, "err");
  }
}

// --------------------------------------------------------------------------- Render de Tarjetas

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
        <button class="bookmark-btn ${item.bookmarked ? "saved" : ""}" title="Guardar en mi lista">
          ${item.bookmarked ? "★" : "☆"}
        </button>
      </div>
      <div class="poster-overlay">
        <div class="quick-actions">
          ${magnets.length ? `<button class="btn btn-magnet act-magnet" title="Abrir Magnet en 1 clic">🧲 Magnet</button>` : ""}
          ${httpLinks.length ? `<button class="btn btn-jd act-jd" title="Enviar a JDownloader 2">📦 JD2</button>` : ""}
          ${item.page_url ? `<a class="btn btn-secondary act-web" href="${esc(item.page_url)}" target="_blank" rel="noopener" title="Abrir página original">↗</a>` : ""}
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

// --------------------------------------------------------------------------- Vista 1: Novedades

async function loadLatest(reset = true) {
  if (reset) {
    state.latestOffset = 0;
    state.latest = [];
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
    $("#badge-latest").textContent = String(data.total);
    if (data.last_sync) {
      $("#last-sync-label").textContent = `Actualizado ${relativeTime(data.last_sync)}`;
    }
    renderCategoryPills();
    renderLatestGrid();
    const moreBtn = $("#btn-load-more");
    moreBtn.classList.toggle("hidden", state.latest.length >= state.latestTotal);
  } catch (err) {
    toast(err.message, "err");
  }
}

function renderCategoryPills() {
  const categories = ["", "Repacks", "Descarga Directa", "Catálogo JSON", "Retro / DRM-Free"];
  const wrap = $("#category-pills");
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
        <h3 style="margin-bottom:6px;color:#fff;">No hay novedades con estos filtros</h3>
        <p>Pulsa <strong>Actualizar feeds ahora</strong> arriba a la derecha o añade nuevas páginas en <strong>⚙️ Mis Fuentes</strong>.</p>
      </div>`;
    return;
  }
  visible.forEach((item) => grid.appendChild(renderGameCard(item)));
}

// --------------------------------------------------------------------------- Vista 2: Buscador

let searchDebounce = null;

async function runSearch(query) {
  const q = (query ?? "").trim();
  state.searchQuery = q;
  if (!q) {
    state.searchData = { items: [], groups: [], external_links: [] };
    renderSearchResults();
    return;
  }
  switchView("search");
  $("#search-results").innerHTML = `<div class="empty-state">Buscando «${esc(q)}» en todas tus fuentes y Steam...</div>`;
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
  const { items, groups, external_links } = state.searchData;

  if (external_links?.length && state.searchQuery) {
    extBox.classList.remove("hidden");
    extWrap.innerHTML = external_links
      .map(
        (l) => `
        <a class="btn btn-secondary btn-sm" href="${esc(l.url)}" target="_blank" rel="noopener">
          🔎 Buscar en <strong>${esc(l.name)}</strong> ↗
        </a>`
      )
      .join("");
  } else {
    extBox.classList.add("hidden");
  }

  if (!state.searchQuery) {
    container.innerHTML = `
      <div class="empty-state">
        <h3 style="color:#fff;margin-bottom:6px;">Escribe el nombre de un juego arriba (Ctrl+K)</h3>
        <p>Comparará versiones, tamaños y enlaces directos entre todas tus páginas y catálogos activos.</p>
      </div>`;
    return;
  }

  if (!items?.length) {
    container.innerHTML = `
      <div class="empty-state">
        <h3 style="color:#fff;margin-bottom:6px;">Sin coincidencias locales para «${esc(state.searchQuery)}»</h3>
        <p>Usa los botones de arriba para abrir la búsqueda directa en 1 clic en tus webs externas, o añade más catálogos en ⚙️ Mis Fuentes.</p>
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

  // Modo Comparador agrupado por juego
  const list = document.createElement("div");
  list.className = "group-list";

  groups.forEach((grp) => {
    const sampleItem = grp.releases[0];
    const { primary, fallbacks } = posterChain({ ...sampleItem, steam_info: grp.steam_info, clean_title: grp.title });
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
            <h3 style="font-size:18px;font-weight:700;">${esc(grp.title)}</h3>
            <span style="font-size:12px;color:var(--text-muted);">
              ${grp.releases.length} subida(s) en ${grp.sources_count} fuente(s)
            </span>
          </div>
          ${grp.steam_info?.store_url ? `<a href="${esc(grp.steam_info.store_url)}" target="_blank" rel="noopener" class="btn btn-secondary btn-sm">Ficha Steam ↗</a>` : ""}
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
          <div style="font-weight:600;margin-top:4px;word-break:break-word;">${esc(rel.raw_title)}</div>
        </div>
        <div style="display:flex;gap:6px;flex-wrap:wrap;">
          ${magnets.length ? `<button class="btn btn-magnet btn-sm r-mag">🧲 Magnet</button>` : ""}
          ${httpLinks.length ? `<button class="btn btn-jd btn-sm r-jd">📦 JD2</button>` : ""}
          ${rel.page_url ? `<a class="btn btn-secondary btn-sm" href="${esc(rel.page_url)}" target="_blank" rel="noopener">Web ↗</a>` : ""}
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

// --------------------------------------------------------------------------- Vista 3: Guardados

async function loadBookmarks() {
  try {
    const data = await api("/api/bookmarks");
    state.bookmarks = data.items || [];
    $("#badge-bookmarks").textContent = String(state.bookmarks.length);
    const grid = $("#bookmarks-grid");
    grid.innerHTML = "";
    if (!state.bookmarks.length) {
      grid.innerHTML = `
        <div class="empty-state" style="grid-column: 1 / -1;">
          <h3 style="color:#fff;margin-bottom:6px;">Aún no tienes juegos guardados</h3>
          <p>Pulsa la estrella ☆ en cualquier tarjeta para guardarlo aquí y descargarlo cuando quieras.</p>
        </div>`;
      return;
    }
    state.bookmarks.forEach((it) => grid.appendChild(renderGameCard(it)));
  } catch (err) {
    toast(err.message, "err");
  }
}

// --------------------------------------------------------------------------- Drawer de Detalles

async function openDetailDrawer(item) {
  const backdrop = $("#detail-backdrop");
  const { primary, fallbacks } = posterChain(item);
  const { magnets, httpLinks } = splitUris(item);
  const title = item.steam_info?.official_name || item.clean_title || item.raw_title;
  const heroBg = item.steam_info?.header_url || item.image_url || "";

  $("#drawer-hero").style.backgroundImage = heroBg ? `url("${heroBg}")` : "none";
  const poster = $("#drawer-poster");
  poster.src = primary;
  poster.dataset.fallbacks = fallbacks.join("||");
  poster.onerror = function () { window.__imgFallback(this); };

  $("#drawer-title").textContent = title;
  $("#drawer-raw").textContent = item.raw_title;
  $("#drawer-badges").innerHTML = `
    <span class="badge">${esc(item.source_name)}</span>
    <span class="badge">${esc(item.source_category)}</span>
    ${item.file_size ? `<span class="size-tag">${esc(item.file_size)}</span>` : ""}
  `;

  const body = $("#drawer-body");
  body.innerHTML = `
    <div style="display:flex;gap:9px;flex-wrap:wrap;">
      ${magnets.map((m, idx) => `<button class="btn btn-magnet d-mag" data-idx="${idx}">🧲 Abrir Magnet ${magnets.length > 1 ? idx + 1 : "(Torrent)"}</button>`).join("")}
      ${httpLinks.length ? `<button class="btn btn-jd" id="d-jd">📦 Enviar a JDownloader 2 (${httpLinks.length})</button>` : ""}
      ${(magnets.length || httpLinks.length) ? `<button class="btn btn-secondary" id="d-copy">📋 Copiar enlaces</button>` : ""}
      ${item.page_url ? `<a class="btn btn-secondary" href="${esc(item.page_url)}" target="_blank" rel="noopener">🌐 Abrir Página Fuente ↗</a>` : ""}
      ${item.steam_info?.store_url ? `<a class="btn btn-secondary" href="${esc(item.steam_info.store_url)}" target="_blank" rel="noopener">🛒 Ver en Steam ↗</a>` : ""}
    </div>
    ${item.excerpt ? `<div class="req-box">${esc(item.excerpt)}</div>` : ""}
    <div id="drawer-steam-extra" style="color:var(--text-muted);font-size:13px;">
      ${item.steam_info?.appid ? "Cargando sinopsis, capturas y requisitos desde Steam..." : "No se encontró ficha vinculada en Steam para este título."}
    </div>
  `;

  body.querySelectorAll(".d-mag").forEach((btn) =>
    btn.addEventListener("click", (e) => triggerMagnet(magnets[Number(btn.dataset.idx)], e))
  );
  body.querySelector("#d-jd")?.addEventListener("click", (e) => triggerJDownloader(httpLinks, title, e));
  body.querySelector("#d-copy")?.addEventListener("click", (e) =>
    copyText([...magnets, ...httpLinks].join("\n"), "Enlaces", e)
  );

  backdrop.classList.remove("hidden");

  if (item.steam_info?.appid) {
    try {
      const det = await api(`/api/steam/details/${item.steam_info.appid}`);
      const extra = $("#drawer-steam-extra");
      extra.innerHTML = `
        <div style="display:flex;gap:8px;flex-wrap:wrap;margin-bottom:12px;">
          ${(det.genres || []).map((g) => `<span class="pill" style="padding:3px 10px;font-size:11.5px;">${esc(g)}</span>`).join("")}
          ${det.metacritic ? `<span class="badge badge-installed">Metacritic ${esc(det.metacritic)}</span>` : ""}
          ${det.release_date ? `<span class="badge">${esc(det.release_date)}</span>` : ""}
        </div>
        ${det.short_description ? `<p style="color:var(--text-main);margin-bottom:16px;line-height:1.6;">${esc(det.short_description)}</p>` : ""}
        ${det.screenshots?.length ? `
          <div class="shots-grid" style="margin-bottom:16px;">
            ${det.screenshots.map((s) => `<a href="${esc(s.full)}" target="_blank" rel="noopener"><img src="${esc(s.thumb)}" loading="lazy" alt="Captura" /></a>`).join("")}
          </div>` : ""}
        ${det.pc_minimum ? `
          <h4 style="color:#fff;margin-bottom:6px;">Requisitos de PC (Steam)</h4>
          <div class="req-box">${esc(det.pc_minimum)}</div>` : ""}
      `;
    } catch {
      $("#drawer-steam-extra").textContent = "";
    }
  }
}

// --------------------------------------------------------------------------- Vista 4: Dependencias

async function loadDependencies() {
  try {
    state.depsConfig = await api("/api/dependencies");
    renderDependencies();
    checkInstalledDeps(false);
  } catch (err) {
    toast(err.message, "err");
  }
}

async function checkInstalledDeps(notify = true) {
  const btn = $("#btn-check-deps");
  btn.disabled = true;
  btn.textContent = "⏳ Comprobando Winget...";
  try {
    const res = await api("/api/dependencies/status");
    state.depsInstalled = res.installed || {};
    $("#deps-counter").textContent = res.winget_available
      ? `${res.installed_count} / ${res.total_count} instalados`
      : "Winget no detectado";
    renderDependencies();
    if (notify) toast("Estado de dependencias actualizado");
  } catch (err) {
    if (notify) toast(err.message, "err");
  } finally {
    btn.disabled = false;
    btn.textContent = "🔍 Comprobar instalados";
  }
}

async function installWinget(ids) {
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
  const isInstalled = Boolean(state.depsInstalled[dep.winget_id]);
  const card = document.createElement("div");
  card.className = "dep-card";
  card.innerHTML = `
    <div class="dep-top">
      <div>
        <div style="font-weight:700;font-size:14.5px;">${esc(dep.name)}</div>
        <code style="font-size:11px;color:var(--text-dim);">${esc(dep.winget_id)}</code>
      </div>
      <span class="badge ${isInstalled ? "badge-installed" : ""}">
        ${isInstalled ? "✓ Instalado" : esc(dep.badge || "Oficial")}
      </span>
    </div>
    <p style="font-size:12.5px;color:var(--text-muted);flex:1;">${esc(dep.description)}</p>
    ${dep.fixes ? `<div class="dep-fixes">💡 ${esc(dep.fixes)}</div>` : ""}
    <div style="display:flex;gap:8px;margin-top:4px;">
      <button class="btn ${isInstalled ? "btn-secondary" : "btn-primary"} btn-sm act-winget" style="flex:1;">
        ${isInstalled ? "↻ Reinstalar / Actualizar" : "⚡ Instalar en 1 clic"}
      </button>
      <a class="btn btn-secondary btn-sm" href="${esc(dep.official_url)}" target="_blank" rel="noopener">Web Oficial ↗</a>
    </div>
  `;
  card.querySelector(".act-winget").addEventListener("click", () => installWinget([dep.winget_id]));
  return card;
}

function renderDependencies() {
  const rGrid = $("#runtimes-grid");
  const tGrid = $("#tools-grid");
  const sGrid = $("#safety-grid");
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
      ${rule.links?.length ? `
        <div style="display:flex;gap:7px;flex-wrap:wrap;margin-top:4px;">
          ${rule.links.map((l) => `<a class="btn btn-secondary btn-sm" href="${esc(l.url)}" target="_blank" rel="noopener">${esc(l.label)} ↗</a>`).join("")}
        </div>` : ""}
    `;
    sGrid.appendChild(c);
  });
}

// --------------------------------------------------------------------------- Vista 5: Mis Fuentes

const TYPE_LABELS = {
  wp_api: "WordPress API (Novedades + Búsqueda)",
  rss: "Feed RSS / Atom",
  json_index: "Catálogo JSON (FTS5)",
  search_url: "Buscador Directo 1-Clic",
};

async function loadSources() {
  try {
    const data = await api("/api/sources");
    state.sources = data.sources || [];
    const active = state.sources.filter((s) => s.enabled);
    $("#badge-sources").textContent = String(active.length);

    // Banner de bienvenida solo si la única fuente activa es la demo inicial
    const onlyDemo = active.length <= 1 && active.every((s) => s.id === "catalogo-demo-local");
    $("#demo-banner").classList.toggle("hidden", !onlyDemo);

    // Actualizar selector de fuentes en Novedades
    const sel = $("#filter-source");
    const current = sel.value;
    sel.innerHTML = `<option value="">Todas las fuentes activas</option>` +
      active.map((s) => `<option value="${esc(s.id)}">${esc(s.name)}</option>`).join("");
    sel.value = current;

    renderSourcesList();
  } catch (err) {
    toast(err.message, "err");
  }
}

function renderSourcesList() {
  const wrap = $("#sources-list");
  wrap.innerHTML = "";
  if (!state.sources.length) {
    wrap.innerHTML = `<div class="empty-state">No hay fuentes configuradas todavía. Pega una URL arriba y pulsa Autodetectar.</div>`;
    return;
  }

  state.sources.forEach((src) => {
    const el = document.createElement("div");
    el.className = `source-item ${src.enabled ? "" : "disabled"}`;
    el.innerHTML = `
      <div style="min-width:220px;flex:1;">
        <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
          <strong style="font-size:15px;">${esc(src.name)}</strong>
          <span class="badge">${esc(TYPE_LABELS[src.type] || src.type)}</span>
          <span class="pill" style="padding:2px 9px;font-size:11px;">${esc(src.category)}</span>
          ${src.cached_items ? `<span class="size-tag">${src.cached_items} en caché</span>` : ""}
        </div>
        <div style="font-size:12px;color:var(--text-dim);margin-top:4px;word-break:break-all;">
          ${esc(src.url || src.search_url_template)}
        </div>
        ${src.last_error ? `<div style="font-size:12px;color:var(--rose);margin-top:4px;">⚠️ Último aviso: ${esc(src.last_error)}</div>` : ""}
      </div>
      <div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;">
        <button class="btn btn-secondary btn-sm s-test">🧪 Probar</button>
        <button class="btn btn-secondary btn-sm s-edit">✏️ Editar</button>
        <button class="btn btn-danger btn-sm s-del">🗑️</button>
        <label class="switch" title="Activar / Desactivar fuente">
          <input type="checkbox" class="s-toggle" ${src.enabled ? "checked" : ""} />
          <span class="slider"></span>
        </label>
      </div>
    `;

    el.querySelector(".s-toggle").addEventListener("change", async () => {
      await api(`/api/sources/${encodeURIComponent(src.id)}/toggle`, { method: "PATCH" });
      await loadSources();
      await loadLatest(true);
    });

    el.querySelector(".s-test").addEventListener("click", async (e) => {
      const btn = e.currentTarget;
      btn.disabled = true;
      btn.textContent = "⏳...";
      try {
        const res = await api("/api/sources/probe", { method: "POST", body: src });
        toast(`✅ ${src.name}: ${res.message}`);
      } catch (err) {
        toast(err.message, "err");
      } finally {
        btn.disabled = false;
        btn.textContent = "🧪 Probar";
      }
    });

    el.querySelector(".s-edit").addEventListener("click", () => {
      $("#manual-source-form").classList.remove("hidden");
      $("#src-id").value = src.id;
      $("#src-name").value = src.name;
      $("#src-type").value = src.type;
      $("#src-category").value = src.category || "Descarga Directa";
      $("#src-url").value = src.url || "";
      $("#src-template").value = src.search_url_template || "";
      $("#manual-source-form").scrollIntoView({ behavior: "smooth" });
    });

    el.querySelector(".s-del").addEventListener("click", async () => {
      if (!confirm(`¿Eliminar la fuente «${src.name}» y su caché local?`)) return;
      await api(`/api/sources/${encodeURIComponent(src.id)}`, { method: "DELETE" });
      toast(`Fuente «${src.name}» eliminada`);
      await loadSources();
      await loadLatest(true);
    });

    wrap.appendChild(el);
  });
}

// --------------------------------------------------------------------------- Salud y Eventos Globales

function updateJdIndicator(online) {
  state.jdOnline = Boolean(online);
  $("#jd-dot").classList.toggle("online", state.jdOnline);
  $("#jd-label").textContent = state.jdOnline ? "JDownloader 2: Conectado" : "JDownloader 2: Off";
}

async function refreshHealthBadges() {
  try {
    const h = await api("/api/health");
    updateJdIndicator(h.jdownloader?.online);
    $("#badge-bookmarks").textContent = String(h.stats?.bookmarks || 0);
    $("#badge-sources").textContent = String(h.sources_enabled || 0);
  } catch {}
}

function bindEvents() {
  $$(".nav-btn").forEach((btn) =>
    btn.addEventListener("click", () => switchView(btn.dataset.view))
  );
  $$("[data-goto]").forEach((btn) =>
    btn.addEventListener("click", () => switchView(btn.dataset.goto))
  );

  // Atajo global Ctrl+K y Esc
  window.addEventListener("keydown", (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
      e.preventDefault();
      const input = $("#global-search-input");
      input.focus();
      input.select();
    } else if (e.key === "Escape") {
      $("#detail-backdrop").classList.add("hidden");
    }
  });

  $("#drawer-close").addEventListener("click", () => $("#detail-backdrop").classList.add("hidden"));
  $("#detail-backdrop").addEventListener("click", (e) => {
    if (e.target.id === "detail-backdrop") $("#detail-backdrop").classList.add("hidden");
  });

  // Buscador global con debounce suave
  $("#global-search-form").addEventListener("submit", (e) => {
    e.preventDefault();
    clearTimeout(searchDebounce);
    runSearch($("#global-search-input").value);
  });
  $("#global-search-input").addEventListener("input", (e) => {
    clearTimeout(searchDebounce);
    const val = e.target.value;
    if (!val.trim() && state.view === "search") {
      runSearch("");
      return;
    }
    if (val.trim().length >= 2) {
      searchDebounce = setTimeout(() => runSearch(val), 360);
    }
  });

  $("#mode-grouped").addEventListener("click", () => {
    state.searchMode = "grouped";
    $("#mode-grouped").classList.add("active");
    $("#mode-cards").classList.remove("active");
    renderSearchResults();
  });
  $("#mode-cards").addEventListener("click", () => {
    state.searchMode = "cards";
    $("#mode-cards").classList.add("active");
    $("#mode-grouped").classList.remove("active");
    renderSearchResults();
  });

  // Filtros Novedades
  $("#filter-source").addEventListener("change", (e) => {
    state.selectedSource = e.target.value;
    loadLatest(true);
  });
  $("#filter-magnet").addEventListener("change", (e) => {
    state.magnetOnly = e.target.checked;
    loadLatest(true);
  });
  $("#filter-inline").addEventListener("input", (e) => {
    state.inlineFilter = e.target.value;
    renderLatestGrid();
  });
  $("#btn-load-more").addEventListener("click", () => {
    state.latestOffset += state.latestLimit;
    loadLatest(false);
  });

  // Actualizar todos los feeds
  $("#btn-refresh-all").addEventListener("click", async () => {
    const btn = $("#btn-refresh-all");
    const icon = $("#refresh-icon");
    btn.disabled = true;
    icon.classList.add("spin");
    try {
      const res = await api("/api/releases/refresh", { method: "POST", body: {} });
      toast(`Feeds sincronizados (${res.synced}/${res.total} fuentes OK)`);
      await loadLatest(true);
      if (state.view === "sources") await loadSources();
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
      icon.classList.remove("spin");
    }
  });

  // JDownloader status & Acceso directo
  $("#btn-check-jd").addEventListener("click", async () => {
    const st = await api("/api/download/jd-status");
    updateJdIndicator(st.online);
    toast(st.online ? "✅ JDownloader 2 detectado en 127.0.0.1:9666" : "JDownloader 2 no responde (ábrelo si quieres envío directo)");
  });
  $("#btn-desktop-shortcut").addEventListener("click", async () => {
    try {
      const res = await api("/api/system/desktop-shortcut", { method: "POST" });
      toast(res.message);
    } catch (err) {
      toast(err.message, "err");
    }
  });

  // Dependencias
  $("#btn-check-deps").addEventListener("click", () => checkInstalledDeps(true));
  $("#btn-install-all-runtimes").addEventListener("click", () => {
    const ids = (state.depsConfig.runtimes || []).map((r) => r.winget_id);
    if (ids.length) installWinget(ids);
  });

  // Mis Fuentes: Autodetect 1 clic
  $("#autodetect-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#autodetect-url");
    const url = input.value.trim();
    if (!url) return;
    const btn = $("#btn-autodetect");
    btn.disabled = true;
    btn.textContent = "⏳ Detectando...";
    try {
      const detected = await api("/api/sources/autodetect", { method: "POST", body: { url } });
      await api("/api/sources", { method: "POST", body: { ...detected, id: "", sync_now: true } });
      toast(`✅ ${detected.name}: ${detected.message}`);
      input.value = "";
      await loadSources();
      await loadLatest(true);
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = "✨ Autodetectar y Añadir";
    }
  });

  $("#btn-toggle-batch").addEventListener("click", () => $("#batch-box").classList.toggle("hidden"));
  $("#btn-toggle-manual").addEventListener("click", () => $("#manual-source-form").classList.toggle("hidden"));

  $("#btn-run-batch").addEventListener("click", async () => {
    const lines = $("#batch-urls").value.split(/\r?\n/).map((s) => s.trim()).filter(Boolean);
    if (!lines.length) return;
    const btn = $("#btn-run-batch");
    btn.disabled = true;
    btn.textContent = `⏳ Detectando ${lines.length} fuente(s)...`;
    try {
      const res = await api("/api/sources/autodetect-batch", {
        method: "POST",
        body: { urls: lines, auto_save: true },
      });
      toast(`✅ Añadidas ${res.added} de ${res.processed} fuentes`);
      $("#batch-urls").value = "";
      $("#batch-box").classList.add("hidden");
      await loadSources();
      await loadLatest(true);
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = "🚀 Detectar y Guardar Lista Completa";
    }
  });

  // Formulario manual
  const readManualPayload = () => ({
    id: $("#src-id").value.trim() || null,
    name: $("#src-name").value.trim(),
    type: $("#src-type").value,
    category: $("#src-category").value.trim() || "Descarga Directa",
    url: $("#src-url").value.trim(),
    search_url_template: $("#src-template").value.trim(),
    enabled: true,
    sync_now: true,
  });

  $("#manual-source-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    try {
      const res = await api("/api/sources", { method: "POST", body: readManualPayload() });
      toast(`💾 Fuente «${res.source.name}» guardada`);
      $("#btn-reset-manual").click();
      await loadSources();
      await loadLatest(true);
    } catch (err) {
      toast(err.message, "err");
    }
  });

  $("#btn-reset-manual").addEventListener("click", () => {
    $("#src-id").value = "";
    $("#src-name").value = "";
    $("#src-url").value = "";
    $("#src-template").value = "";
    $("#probe-output").classList.add("hidden");
  });

  $("#btn-probe-source").addEventListener("click", async () => {
    const out = $("#probe-output");
    out.classList.remove("hidden");
    out.textContent = "Probando conexión con la fuente...";
    try {
      const res = await api("/api/sources/probe", { method: "POST", body: readManualPayload() });
      const sampleLines = (res.sample || []).map((s) => `• ${s.clean_title}  ←  "${s.raw_title}"`);
      out.textContent = [res.message, ...sampleLines].join("\n");
    } catch (err) {
      out.textContent = `❌ ${err.message}`;
    }
  });

  $("#btn-sync-json").addEventListener("click", async () => {
    toast("Sincronizando catálogos JSON...");
    const res = await api("/api/releases/refresh", { method: "POST", body: { only_type: "json_index" } });
    toast(`Catálogos JSON sincronizados (${res.synced}/${res.total})`);
    await loadSources();
    await loadLatest(true);
  });

  $("#btn-export-sources").addEventListener("click", async () => {
    const data = await api("/api/sources/export");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = "gamehub_sources_backup.json";
    a.click();
  });

  $("#input-import-sources").addEventListener("change", async (e) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text());
      const list = Array.isArray(parsed) ? parsed : parsed.sources || [];
      const res = await api("/api/sources/import", { method: "POST", body: { sources: list, merge: true } });
      toast(`📥 Importadas ${res.imported} fuentes`);
      await loadSources();
      await loadLatest(true);
    } catch (err) {
      toast(`Archivo inválido: ${err.message}`, "err");
    } finally {
      e.target.value = "";
    }
  });
}

async function init() {
  bindEvents();
  await Promise.all([refreshHealthBadges(), loadSources()]);
  await loadLatest(true);
}

init();
