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
  // Estado del Calendario Multi-Plataforma (estilo Releases.com)
  calMode: "hot",          // 'hot' | 'classic' | 'favorites'
  calLayout: "agenda",     // 'agenda' | 'month' | 'week'
  calAgendaRange: "30d",   // '30d' | 'all' | 'month'
  calYear: new Date().getFullYear(),
  calMonth: new Date().getMonth(), // 0-11
  calWeekRef: new Date(),
  calPlatform: "",
  calGenre: "",
  calInlineFilter: "",
  calSelectedDay: "",
  calData: {
    items: [],
    alerts: [],
    available_genres: [],
    available_platforms: [],
    platform_counts: {},
    favorites_count: 0,
    today: "",
  },
  calLoaded: false,
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

  if (view === "calendar") loadCalendar(false);
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
  const fromSources = state.sources
    .filter((s) => s.enabled && s.type !== "search_url" && s.category)
    .map((s) => s.category);
  const base = ["Repacks", "Descarga Directa", "Catálogo JSON"];
  const unique = Array.from(new Set([...fromSources, ...base]));
  const categories = ["", ...unique];
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

// --------------------------------------------------------------------------- Vista Calendario (Releases.com style)

const MONTHS_ES = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
];
const WEEKDAYS_SHORT = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const WEEKDAYS_FULL = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];

function toIsoLocal(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function addDays(d, n) {
  const copy = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  copy.setDate(copy.getDate() + n);
  return copy;
}

function mondayOfWeek(d) {
  const copy = new Date(d.getFullYear(), d.getMonth(), d.getDate());
  const dow = (copy.getDay() + 6) % 7; // 0 = Lunes, 6 = Domingo
  copy.setDate(copy.getDate() - dow);
  return copy;
}

function countdownMeta(calItem, todayIso) {
  if (calItem.precision !== "day" || !calItem.release_date) {
    return { label: calItem.window_label || "Próximamente", cls: "" };
  }
  const [ty, tm, td] = todayIso.split("-").map(Number);
  const [ry, rm, rd] = calItem.release_date.split("-").map(Number);
  const tDate = Date.UTC(ty, tm - 1, td);
  const rDate = Date.UTC(ry, rm - 1, rd);
  const diff = Math.round((rDate - tDate) / 86400000);

  if (diff === 0) return { label: "🔥 ¡Sale HOY!", cls: "today" };
  if (diff === 1) return { label: "Mañana", cls: "soon" };
  if (diff > 1 && diff <= 14) return { label: `En ${diff} días`, cls: "soon" };
  if (diff > 14) return { label: calItem.window_label || calItem.release_date, cls: "" };
  if (diff === -1) return { label: "Salió ayer", cls: "" };
  if (diff >= -7) return { label: `Hace ${Math.abs(diff)} d`, cls: "" };
  return { label: calItem.window_label || calItem.release_date, cls: "" };
}

function formatDayHeading(isoDate, todayIso) {
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  const wname = WEEKDAYS_FULL[dt.getDay()];
  const base = `${wname} ${d} de ${MONTHS_ES[m - 1]}${y !== new Date().getFullYear() ? " " + y : ""}`;

  const [ty, tm, td] = todayIso.split("-").map(Number);
  const diff = Math.round((Date.UTC(y, m - 1, d) - Date.UTC(ty, tm - 1, td)) / 86400000);
  if (diff === 0) return `🟢 HOY · ${base}`;
  if (diff === 1) return `⏳ Mañana · ${base}`;
  if (diff === -1) return `Ayer · ${base}`;
  return base;
}

const PLATFORM_STYLE = {
  "PC": { cls: "plat-pc", short: "PC", pillCls: "p-pc", icon: "💻" },
  "Switch 2": { cls: "plat-ns2", short: "Switch 2", pillCls: "p-ns2", icon: "🔴" },
  "PS5": { cls: "plat-ps5", short: "PS5", pillCls: "p-ps5", icon: "🔵" },
  "Xbox Series": { cls: "plat-xsx", short: "XSX", pillCls: "p-xsx", icon: "🟢" },
  "Switch": { cls: "plat-ns", short: "Switch", pillCls: "p-ns", icon: "🕹️" },
  "PS4": { cls: "", short: "PS4", pillCls: "", icon: "🎮" },
  "Xbox One": { cls: "", short: "XOne", pillCls: "", icon: "🎮" },
  "Mac": { cls: "", short: "Mac", pillCls: "", icon: "🍎" },
  "Linux": { cls: "", short: "Linux", pillCls: "", icon: "🐧" },
};

function renderPlatformBadges(platforms, maxCount = 4) {
  const list = (platforms && platforms.length) ? platforms : ["PC"];
  return list
    .slice(0, maxCount)
    .map((p) => {
      const st = PLATFORM_STYLE[p] || { cls: "", short: p };
      return `<span class="plat-badge ${st.cls}" title="${esc(p)}">${esc(st.short)}</span>`;
    })
    .join("");
}

function storeLabelForUrl(url, appid) {
  const u = String(url || "").toLowerCase();
  if (Number(appid) > 0 || u.includes("steampowered.com")) return "Ver en Steam";
  if (u.includes("nintendo.")) return "Ver en Nintendo eShop";
  if (u.includes("playstation.")) return "Ver en PlayStation";
  if (u.includes("wikipedia.org")) return "Ver ficha informativa";
  return "Ver ficha oficial";
}

function calItemToDrawerItem(c) {
  const hasSteam = Number(c.appid) > 0;
  const plats = (c.platforms && c.platforms.length) ? c.platforms : ["PC"];
  return {
    id: `cal-${c.appid}`,
    raw_title: `${c.title} · ${plats.join(" / ")} (${c.window_label || "Próximamente"})`,
    clean_title: c.title,
    source_id: "multi-calendar",
    source_name: `Calendario (${plats.slice(0, 3).join(" · ")})`,
    source_category: c.window_label || "Lanzamiento",
    published_at: c.precision === "day" ? `${c.release_date}T12:00:00Z` : null,
    page_url: "",
    external_store_url: !hasSteam ? (c.store_url || "") : "",
    file_size: null,
    uris: [],
    excerpt: c.summary || "",
    image_url: c.header_url || c.poster_url,
    platforms: plats,
    genres: c.genres || [],
    steam_info: {
      appid: hasSteam ? c.appid : null,
      official_name: c.title,
      poster_url: c.poster_url,
      header_url: c.header_url || c.poster_url,
      store_url: hasSteam ? c.store_url : "",
    },
  };
}

async function toggleCalendarFavorite(calItem, ev) {
  ev?.stopPropagation();
  try {
    const res = await api("/api/calendar/favorites/toggle", {
      method: "POST",
      body: { item: calItem },
    });
    calItem.favorited = res.favorited;
    // Sincronizar en la lista en memoria
    state.calData.items.forEach((it) => {
      if (it.appid === calItem.appid) it.favorited = res.favorited;
    });
    toast(res.favorited ? `★ Siguiendo «${calItem.title}» en tu Calendario` : `Dejaste de seguir «${calItem.title}»`);
    if (state.calMode === "favorites" && !res.favorited) {
      await loadCalendar(false);
    } else {
      const delta = res.favorited ? 1 : -1;
      state.calData.favorites_count = Math.max(0, (state.calData.favorites_count || 0) + delta);
      $("#cal-fav-count").textContent = String(state.calData.favorites_count);
      $("#badge-calendar").textContent = String(state.calData.favorites_count);
      renderCalendar();
    }
  } catch (err) {
    toast(err.message, "err");
  }
}

function renderCalendarCard(c, todayIso) {
  const fallbacks = [c.header_url, svgPlaceholder(c.title)].filter(Boolean);
  const primary = c.poster_url || fallbacks[0];
  const cd = countdownMeta(c, todayIso);
  const storeTitle = storeLabelForUrl(c.store_url, c.appid);

  const el = document.createElement("article");
  el.className = "game-card";
  el.innerHTML = `
    <div class="poster-wrap">
      <img
        src="${esc(primary)}"
        data-fallbacks="${esc(fallbacks.join("||"))}"
        onerror="window.__imgFallback(this)"
        loading="lazy"
        alt="${esc(c.title)}"
      />
      <div class="card-badges-top">
        <span class="countdown-pill ${cd.cls}">${esc(cd.label)}</span>
        <button class="bookmark-btn ${c.favorited ? "saved" : ""}" title="${c.favorited ? "Quitar de seguimiento" : "Seguir lanzamiento (Favorito)"}">
          ${c.favorited ? "★" : "☆"}
        </button>
      </div>
      <div class="poster-overlay">
        <div class="quick-actions">
          <button class="btn btn-primary act-find" title="Buscar descargas en todas mis fuentes">🔍 Buscar</button>
          ${c.store_url ? `<a class="btn btn-secondary act-steam" href="${esc(c.store_url)}" target="_blank" rel="noopener" title="${esc(storeTitle)}">↗</a>` : ""}
        </div>
      </div>
    </div>
    <div class="card-body">
      <div class="card-title" title="${esc(c.title)}">${esc(c.title)}</div>
      <div class="plat-tags">
        ${renderPlatformBadges(c.platforms, 4)}
      </div>
      <div class="genre-mini-tags">
        ${(c.genres || []).slice(0, 2).map((g) => `<span class="genre-mini">${esc(g)}</span>`).join("")}
      </div>
      <div class="card-meta">
        <span>${esc(c.window_label || "Próximamente")}</span>
      </div>
    </div>
  `;

  el.querySelector(".bookmark-btn").addEventListener("click", (e) => toggleCalendarFavorite(c, e));
  el.querySelector(".act-find").addEventListener("click", (e) => {
    e.stopPropagation();
    $("#global-search-input").value = c.title;
    runSearch(c.title);
  });
  el.querySelector(".act-steam")?.addEventListener("click", (e) => e.stopPropagation());
  el.addEventListener("click", () => openDetailDrawer(calItemToDrawerItem(c)));
  return el;
}

async function loadCalendar(forceRefresh = false) {
  const container = $("#cal-container");
  if (!state.calLoaded || forceRefresh) {
    container.innerHTML = `<div class="empty-state">Sincronizando calendario multi-plataforma (PC/Steam, Nintendo Switch 2, PS5)...</div>`;
  }
  try {
    const params = new URLSearchParams({ mode: state.calMode });
    if (forceRefresh) params.set("force_refresh", "true");
    const data = await api(`/api/calendar?${params}`);
    state.calData = data;
    state.calLoaded = true;
    $("#cal-fav-count").textContent = String(data.favorites_count || 0);
    $("#badge-calendar").textContent = String(data.favorites_count || 0);
    renderCalendarAlerts();
    renderCalendarPlatforms();
    renderCalendarGenres();
    renderCalendar();
  } catch (err) {
    toast(err.message, "err");
  }
}

function renderCalendarAlerts() {
  const box = $("#cal-alerts");
  const alerts = state.calData.alerts || [];
  if (!alerts.length) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  box.className = "cal-alert-banner";
  const names = alerts.map((a) => `<strong>${esc(a.title)}</strong> (${a.release_date === state.calData.today ? "¡Sale HOY!" : a.window_label})`).join(" · ");
  box.innerHTML = `
    <div>🎉 <strong>Lanzamientos de tu lista disponibles:</strong> ${names}</div>
    <button class="btn btn-primary btn-sm" id="btn-alert-search">🔍 Buscar «${esc(alerts[0].title)}» en mis fuentes</button>
  `;
  box.querySelector("#btn-alert-search").addEventListener("click", () => {
    $("#global-search-input").value = alerts[0].title;
    runSearch(alerts[0].title);
  });
}

function renderCalendarPlatforms() {
  const wrap = $("#cal-platform-pills");
  if (!wrap) return;
  const counts = state.calData.platform_counts || {};
  const totalAll = (state.calData.items || []).length;
  const mainPlats = ["", "PC", "Switch 2", "PS5", "Xbox Series", "Switch"];

  wrap.innerHTML = "";
  mainPlats.forEach((p) => {
    if (p && !counts[p] && p !== "Switch 2" && p !== "PS5" && p !== "PC") return;
    const st = PLATFORM_STYLE[p] || { icon: "🎮", pillCls: "" };
    const cnt = p ? (counts[p] || 0) : totalAll;
    const btn = document.createElement("button");
    btn.className = `pill ${st.pillCls || ""} ${state.calPlatform === p ? "active" : ""}`.trim();
    const labelText = p ? `${st.icon} ${p}` : "🎮 Todas las plataformas";
    btn.innerHTML = `${esc(labelText)}<span class="plat-pill-count">(${cnt})</span>`;
    btn.addEventListener("click", () => {
      state.calPlatform = p;
      // Al filtrar por consola específica en Agenda, ampliar horizonte si estaba solo en 30 días y hay pocos días cercanos
      renderCalendarPlatforms();
      renderCalendar();
    });
    wrap.appendChild(btn);
  });
}

function renderCalendarGenres() {
  const preferred = [
    "", "Acción", "RPG", "Aventura", "Estrategia", "Terror", "Supervivencia",
    "Shooter", "Plataformas", "Lucha", "Carreras", "Deportes", "Puzles",
    "Simulación", "Roguelike", "Mundo Abierto", "Soulslike", "Indie", "Multijugador",
  ];
  const available = new Set(state.calData.available_genres || []);
  const list = preferred.filter((g) => !g || available.has(g));
  const wrap = $("#cal-genre-pills");
  wrap.innerHTML = "";
  list.forEach((g) => {
    const btn = document.createElement("button");
    btn.className = `pill ${state.calGenre === g ? "active" : ""}`;
    btn.textContent = g || "Todos los géneros";
    btn.addEventListener("click", () => {
      state.calGenre = g;
      renderCalendarGenres();
      renderCalendar();
    });
    wrap.appendChild(btn);
  });
}

function filteredCalendarItems() {
  let items = state.calData.items || [];
  if (state.calPlatform) {
    items = items.filter((it) => (it.platforms || []).includes(state.calPlatform));
  }
  if (state.calGenre) {
    items = items.filter((it) => (it.genres || []).includes(state.calGenre));
  }
  const q = state.calInlineFilter.trim().toLowerCase();
  if (q) {
    items = items.filter((it) => it.title.toLowerCase().includes(q));
  }
  return items;
}

function updateCalendarNavLabels() {
  const upBtn = $("#btn-cal-upcoming30");
  const allBtn = $("#btn-cal-allupcoming");
  const showAgendaRanges = state.calLayout === "agenda" && state.calMode !== "favorites";
  upBtn.classList.toggle("hidden", !showAgendaRanges);
  allBtn?.classList.toggle("hidden", !showAgendaRanges);
  upBtn.classList.toggle("active", showAgendaRanges && state.calAgendaRange === "30d");
  allBtn?.classList.toggle("active", showAgendaRanges && state.calAgendaRange === "all");

  const label = $("#cal-period-label");
  if (state.calMode === "favorites" && state.calLayout === "agenda") {
    label.textContent = "Todos mis seguidos";
  } else if (state.calLayout === "week") {
    const mon = mondayOfWeek(state.calWeekRef);
    const sun = addDays(mon, 6);
    label.textContent = `${mon.getDate()} ${MONTHS_ES[mon.getMonth()].slice(0, 3)} – ${sun.getDate()} ${MONTHS_ES[sun.getMonth()].slice(0, 3)} ${sun.getFullYear()}`;
  } else if (state.calLayout === "agenda" && state.calAgendaRange === "30d") {
    label.textContent = "Próximos 30 días";
  } else if (state.calLayout === "agenda" && state.calAgendaRange === "all") {
    label.textContent = "Horizonte 2026–2027+";
  } else {
    label.textContent = `${MONTHS_ES[state.calMonth]} ${state.calYear}`;
  }
}

function renderCalendar() {
  updateCalendarNavLabels();
  $("#cal-selected-day-box").classList.add("hidden");
  const todayIso = state.calData.today || toIsoLocal(new Date());
  const items = filteredCalendarItems();

  if (state.calLayout === "month") {
    renderCalendarMonth(items, todayIso);
  } else if (state.calLayout === "week") {
    renderCalendarWeek(items, todayIso);
  } else {
    renderCalendarAgenda(items, todayIso);
  }
}

function renderCalendarAgenda(items, todayIso) {
  const container = $("#cal-container");
  container.innerHTML = "";

  let scoped = items;
  if (state.calMode !== "favorites" && !state.calInlineFilter.trim()) {
    if (state.calAgendaRange === "30d") {
      const endIso = toIsoLocal(addDays(new Date(), 35));
      scoped = items.filter(
        (it) =>
          (it.precision === "day" && it.release_date >= todayIso && it.release_date <= endIso) ||
          (it.precision !== "day" && (it.release_date || "").slice(0, 7) >= todayIso.slice(0, 7))
      );
    } else if (state.calAgendaRange === "all") {
      scoped = items.filter(
        (it) =>
          (it.precision === "day" && it.release_date >= todayIso) ||
          (it.precision !== "day" && (it.release_date || "").slice(0, 7) >= todayIso.slice(0, 7))
      );
    } else {
      const ym = `${state.calYear}-${String(state.calMonth + 1).padStart(2, "0")}`;
      scoped = items.filter((it) => (it.release_date || "").startsWith(ym));
    }
  }

  if (!scoped.length) {
    container.innerHTML = `
      <div class="empty-state">
        <h3 style="color:#fff;margin-bottom:6px;">
          ${state.calMode === "favorites" ? "Aún no sigues ningún próximo lanzamiento" : "No hay lanzamientos registrados en este tramo"}
        </h3>
        <p>
          ${state.calMode === "favorites"
            ? "Marca cualquier juego con ★ en las pestañas Hot o Clásico (o añádelo arriba por nombre) para seguir su cuenta atrás."
            : "Prueba pulsando 🔭 Todo 2026–2027+, cambiando al modo 📋 Clásico (Todos) o quitando algún filtro."}
        </p>
      </div>`;
    return;
  }

  // Separar días exactos y ventanas estimadas (como Releases.com)
  const byDay = new Map();
  const windows = new Map();

  scoped.forEach((it) => {
    if (it.precision === "day" && it.release_date) {
      if (!byDay.has(it.release_date)) byDay.set(it.release_date, []);
      byDay.get(it.release_date).push(it);
    } else {
      const w = it.window_label || "Próximamente";
      if (!windows.has(w)) windows.set(w, []);
      windows.get(w).push(it);
    }
  });

  const sortedDays = Array.from(byDay.keys()).sort();
  sortedDays.forEach((dayIso) => {
    const dayItems = byDay.get(dayIso);
    const block = document.createElement("div");
    block.className = "cal-day-block";
    block.innerHTML = `
      <div class="cal-day-header ${dayIso === todayIso ? "is-today" : ""}">
        <div class="cal-day-title">${esc(formatDayHeading(dayIso, todayIso))}</div>
        <span class="badge">${dayItems.length} juego${dayItems.length === 1 ? "" : "s"}</span>
      </div>
      <div class="poster-grid"></div>
    `;
    const grid = block.querySelector(".poster-grid");
    dayItems.forEach((c) => grid.appendChild(renderCalendarCard(c, todayIso)));
    container.appendChild(block);
  });

  // Si estamos en 30d pero hay más lanzamientos fechados más adelante (ej. 2027 en Switch 2 / PS5), ofrecer atajo 1 clic
  if (state.calMode !== "favorites" && state.calAgendaRange === "30d") {
    const endIso = toIsoLocal(addDays(new Date(), 35));
    const laterDatedCount = items.filter((it) => it.precision === "day" && it.release_date > endIso).length;
    if (laterDatedCount > 0) {
      const moreBanner = document.createElement("div");
      moreBanner.className = "panel-box";
      moreBanner.style.cssText = "display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:24px;";
      moreBanner.innerHTML = `
        <span style="font-size:13.5px;color:var(--text-muted);">
          🔭 Hay <strong>${laterDatedCount}</strong> lanzamiento(s) más con día exacto confirmado más allá de 30 días${state.calPlatform ? ` en <strong>${esc(state.calPlatform)}</strong>` : ""}.
        </span>
        <button class="btn btn-secondary btn-sm" id="btn-expand-horizon">Ver calendario completo 2026–2027+ →</button>
      `;
      moreBanner.querySelector("#btn-expand-horizon").addEventListener("click", () => {
        state.calAgendaRange = "all";
        renderCalendar();
      });
      container.appendChild(moreBanner);
    }
  }

  // Ventanas estimadas (ej. Noviembre 2026, 2026, T1 2027, 2027, Próximamente)
  Array.from(windows.entries()).slice(0, 14).forEach(([wLabel, wItems]) => {
    const block = document.createElement("div");
    block.className = "cal-day-block";
    const initialSlice = 24;
    block.innerHTML = `
      <div class="cal-day-header">
        <div class="cal-day-title">📆 Ventana estimada · ${esc(wLabel)}</div>
        <span class="badge">${wItems.length} juego${wItems.length === 1 ? "" : "s"}</span>
      </div>
      <div class="poster-grid"></div>
      ${wItems.length > initialSlice ? `<div style="text-align:center;margin-top:12px;"><button class="btn btn-secondary btn-sm btn-more-win">Mostrar los ${wItems.length - initialSlice} restantes de ${esc(wLabel)}</button></div>` : ""}
    `;
    const grid = block.querySelector(".poster-grid");
    wItems.slice(0, initialSlice).forEach((c) => grid.appendChild(renderCalendarCard(c, todayIso)));
    block.querySelector(".btn-more-win")?.addEventListener("click", (e) => {
      wItems.slice(initialSlice).forEach((c) => grid.appendChild(renderCalendarCard(c, todayIso)));
      e.currentTarget.parentElement.remove();
    });
    container.appendChild(block);
  });
}

function renderCalendarMonth(items, todayIso) {
  const container = $("#cal-container");
  container.innerHTML = "";

  const head = document.createElement("div");
  head.className = "cal-weekdays";
  head.innerHTML = WEEKDAYS_SHORT.map((w) => `<div>${w}</div>`).join("");
  container.appendChild(head);

  const byDay = new Map();
  items.forEach((it) => {
    if (it.precision === "day" && it.release_date) {
      if (!byDay.has(it.release_date)) byDay.set(it.release_date, []);
      byDay.get(it.release_date).push(it);
    }
  });

  const firstOfMonth = new Date(state.calYear, state.calMonth, 1);
  const startCell = mondayOfWeek(firstOfMonth);
  const grid = document.createElement("div");
  grid.className = "cal-month-grid";

  for (let i = 0; i < 42; i++) {
    const cellDate = addDays(startCell, i);
    const iso = toIsoLocal(cellDate);
    const inMonth = cellDate.getMonth() === state.calMonth;
    const dayGames = byDay.get(iso) || [];

    // Si la última fila entera pertenece ya al mes siguiente, no la pintamos
    if (i >= 35 && !inMonth && cellDate.getDate() <= 7 && i === 35) break;

    const cell = document.createElement("div");
    cell.className = [
      "cal-cell",
      inMonth ? "" : "outside",
      iso === todayIso ? "today" : "",
      dayGames.length ? "has-games" : "",
      state.calSelectedDay === iso ? "selected" : "",
    ].filter(Boolean).join(" ");

    cell.innerHTML = `
      <div class="cal-cell-top">
        <span>${cellDate.getDate()} ${iso === todayIso ? "· HOY" : ""}</span>
        ${dayGames.length ? `<span class="size-tag">${dayGames.length}</span>` : ""}
      </div>
      <div class="cal-thumbs">
        ${dayGames.slice(0, 3).map((g) => `
          <div class="cal-thumb-wrap ${g.favorited ? "fav" : ""}" title="${esc(g.title)}">
            <img src="${esc(g.poster_url)}" data-fallbacks="${esc(g.header_url)}||${esc(svgPlaceholder(g.title))}" onerror="window.__imgFallback(this)" loading="lazy" alt="${esc(g.title)}" />
          </div>
        `).join("")}
      </div>
      ${dayGames.length > 3 ? `<div style="font-size:11px;color:var(--text-muted);text-align:right;margin-top:auto;">+${dayGames.length - 3} más</div>` : ""}
    `;

    if (dayGames.length) {
      cell.addEventListener("click", () => {
        state.calSelectedDay = iso;
        $$(".cal-cell").forEach((c) => c.classList.remove("selected"));
        cell.classList.add("selected");
        showSelectedDayDetail(iso, dayGames, todayIso);
      });
    }
    grid.appendChild(cell);
  }

  container.appendChild(grid);

  // Ventanas del mes sin día exacto
  const ym = `${state.calYear}-${String(state.calMonth + 1).padStart(2, "0")}`;
  const monthTba = items.filter((it) => it.precision === "month" && (it.release_date || "").startsWith(ym));
  if (monthTba.length) {
    const block = document.createElement("div");
    block.className = "cal-day-block";
    block.style.marginTop = "22px";
    block.innerHTML = `
      <div class="cal-day-header">
        <div class="cal-day-title">📆 Confirmados para ${MONTHS_ES[state.calMonth]} ${state.calYear} (día exacto por anunciar)</div>
        <span class="badge">${monthTba.length}</span>
      </div>
      <div class="poster-grid"></div>
    `;
    const pgrid = block.querySelector(".poster-grid");
    monthTba.forEach((c) => pgrid.appendChild(renderCalendarCard(c, todayIso)));
    container.appendChild(block);
  }
}

function showSelectedDayDetail(iso, dayGames, todayIso) {
  const box = $("#cal-selected-day-box");
  box.classList.remove("hidden");
  box.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;">
      <strong style="font-size:16px;">📅 Lanzamientos del ${esc(formatDayHeading(iso, todayIso))} (${dayGames.length})</strong>
      <button class="btn btn-secondary btn-sm" id="btn-close-daybox">Cerrar ✕</button>
    </div>
    <div class="poster-grid" id="selected-day-grid"></div>
  `;
  const g = box.querySelector("#selected-day-grid");
  dayGames.forEach((c) => g.appendChild(renderCalendarCard(c, todayIso)));
  box.querySelector("#btn-close-daybox").addEventListener("click", () => box.classList.add("hidden"));
  box.scrollIntoView({ behavior: "smooth", block: "nearest" });
}

function renderCalendarWeek(items, todayIso) {
  const container = $("#cal-container");
  container.innerHTML = "";
  const byDay = new Map();
  items.forEach((it) => {
    if (it.precision === "day" && it.release_date) {
      if (!byDay.has(it.release_date)) byDay.set(it.release_date, []);
      byDay.get(it.release_date).push(it);
    }
  });

  const mon = mondayOfWeek(state.calWeekRef);
  const grid = document.createElement("div");
  grid.className = "cal-week-grid";

  for (let i = 0; i < 7; i++) {
    const d = addDays(mon, i);
    const iso = toIsoLocal(d);
    const list = byDay.get(iso) || [];
    const col = document.createElement("div");
    col.className = `cal-week-col ${iso === todayIso ? "today" : ""}`;
    col.innerHTML = `
      <div style="display:flex;justify-content:space-between;align-items:center;padding-bottom:6px;border-bottom:1px solid var(--border);">
        <div>
          <div style="font-size:11px;color:var(--text-muted);text-transform:uppercase;font-weight:700;">${WEEKDAYS_SHORT[i]}</div>
          <div style="font-size:16px;font-weight:800;">${d.getDate()} ${MONTHS_ES[d.getMonth()].slice(0, 3)}</div>
        </div>
        <span class="badge">${list.length}</span>
      </div>
      <div class="w-items" style="display:flex;flex-direction:column;gap:7px;"></div>
    `;
    const wWrap = col.querySelector(".w-items");
    if (!list.length) {
      wWrap.innerHTML = `<div style="font-size:12px;color:var(--text-dim);padding:12px 4px;text-align:center;">Sin lanzamientos</div>`;
    } else {
      list.forEach((c) => {
        const row = document.createElement("div");
        row.className = "cal-week-item";
        row.innerHTML = `
          <img src="${esc(c.poster_url)}" data-fallbacks="${esc(c.header_url)}||${esc(svgPlaceholder(c.title))}" onerror="window.__imgFallback(this)" loading="lazy" alt="${esc(c.title)}" />
          <div style="min-width:0;flex:1;">
            <div style="font-size:12.5px;font-weight:700;line-height:1.25;word-break:break-word;">${esc(c.title)}</div>
            <div class="plat-tags" style="margin-top:3px;">${renderPlatformBadges(c.platforms, 3)}</div>
          </div>
          <button class="bookmark-btn ${c.favorited ? "saved" : ""}" style="width:26px;height:26px;flex-shrink:0;" title="Seguir">
            ${c.favorited ? "★" : "☆"}
          </button>
        `;
        row.querySelector(".bookmark-btn").addEventListener("click", (e) => toggleCalendarFavorite(c, e));
        row.addEventListener("click", () => openDetailDrawer(calItemToDrawerItem(c)));
        wWrap.appendChild(row);
      });
    }
    grid.appendChild(col);
  }
  container.appendChild(grid);
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
    ${item.platforms?.length ? renderPlatformBadges(item.platforms, 6) : ""}
    ${item.file_size ? `<span class="size-tag">${esc(item.file_size)}</span>` : ""}
  `;

  const extStoreLabel = item.external_store_url ? storeLabelForUrl(item.external_store_url, null) : "";
  const body = $("#drawer-body");
  body.innerHTML = `
    <div style="display:flex;gap:9px;flex-wrap:wrap;">
      ${magnets.map((m, idx) => `<button class="btn btn-magnet d-mag" data-idx="${idx}">🧲 Abrir Magnet ${magnets.length > 1 ? idx + 1 : "(Torrent)"}</button>`).join("")}
      ${httpLinks.length ? `<button class="btn btn-jd" id="d-jd">📦 Enviar a JDownloader 2 (${httpLinks.length})</button>` : ""}
      ${(magnets.length || httpLinks.length) ? `<button class="btn btn-secondary" id="d-copy">📋 Copiar enlaces</button>` : ""}
      ${item.page_url ? `<a class="btn btn-secondary" href="${esc(item.page_url)}" target="_blank" rel="noopener">🌐 Abrir Página Fuente ↗</a>` : ""}
      <button class="btn btn-primary" id="d-search-hub">🔍 Buscar en mis fuentes</button>
      ${item.steam_info?.store_url ? `<a class="btn btn-secondary" href="${esc(item.steam_info.store_url)}" target="_blank" rel="noopener">🛒 Ver en Steam ↗</a>` : ""}
      ${item.external_store_url ? `<a class="btn btn-secondary" href="${esc(item.external_store_url)}" target="_blank" rel="noopener">🎮 ${esc(extStoreLabel)} ↗</a>` : ""}
    </div>
    ${item.genres?.length && !item.steam_info?.appid ? `
      <div style="display:flex;gap:8px;flex-wrap:wrap;">
        ${item.genres.map((g) => `<span class="pill" style="padding:3px 10px;font-size:11.5px;">${esc(g)}</span>`).join("")}
      </div>` : ""}
    ${item.excerpt ? `<div class="req-box">${esc(item.excerpt)}</div>` : ""}
    <div id="drawer-steam-extra" style="color:var(--text-muted);font-size:13px;">
      ${item.steam_info?.appid
        ? "Cargando sinopsis, capturas y requisitos desde Steam..."
        : (item.source_id === "multi-calendar"
            ? ""
            : "No se encontró ficha vinculada en Steam para este título.")}
    </div>
  `;

  body.querySelectorAll(".d-mag").forEach((btn) =>
    btn.addEventListener("click", (e) => triggerMagnet(magnets[Number(btn.dataset.idx)], e))
  );
  body.querySelector("#d-jd")?.addEventListener("click", (e) => triggerJDownloader(httpLinks, title, e));
  body.querySelector("#d-copy")?.addEventListener("click", (e) =>
    copyText([...magnets, ...httpLinks].join("\n"), "Enlaces", e)
  );
  body.querySelector("#d-search-hub")?.addEventListener("click", () => {
    backdrop.classList.add("hidden");
    $("#global-search-input").value = title;
    runSearch(title);
  });

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
    $("#badge-calendar").textContent = String(h.stats?.calendar_favorites || 0);
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

  // Eventos del Calendario (estilo Releases.com)
  $$("#cal-mode-group .seg-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      state.calMode = btn.dataset.calmode;
      $$("#cal-mode-group .seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
      loadCalendar(false);
    })
  );

  $$("#cal-layout-group .seg-btn").forEach((btn) =>
    btn.addEventListener("click", () => {
      state.calLayout = btn.dataset.callayout;
      $$("#cal-layout-group .seg-btn").forEach((b) => b.classList.toggle("active", b === btn));
      renderCalendar();
    })
  );

  $("#btn-cal-upcoming30").addEventListener("click", () => {
    state.calAgendaRange = "30d";
    renderCalendar();
  });

  $("#btn-cal-allupcoming")?.addEventListener("click", () => {
    state.calAgendaRange = "all";
    renderCalendar();
  });

  $("#btn-cal-prev").addEventListener("click", () => {
    if (state.calLayout === "week") {
      state.calWeekRef = addDays(state.calWeekRef, -7);
    } else {
      state.calAgendaRange = "month";
      state.calMonth -= 1;
      if (state.calMonth < 0) {
        state.calMonth = 11;
        state.calYear -= 1;
      }
    }
    renderCalendar();
  });

  $("#btn-cal-next").addEventListener("click", () => {
    if (state.calLayout === "week") {
      state.calWeekRef = addDays(state.calWeekRef, 7);
    } else {
      state.calAgendaRange = "month";
      state.calMonth += 1;
      if (state.calMonth > 11) {
        state.calMonth = 0;
        state.calYear += 1;
      }
    }
    renderCalendar();
  });

  $("#btn-cal-today").addEventListener("click", () => {
    const now = new Date();
    state.calYear = now.getFullYear();
    state.calMonth = now.getMonth();
    state.calWeekRef = now;
    if (state.calLayout === "agenda") state.calAgendaRange = "30d";
    renderCalendar();
  });

  $("#cal-search-inline").addEventListener("input", (e) => {
    state.calInlineFilter = e.target.value;
    renderCalendar();
  });

  $("#btn-cal-refresh").addEventListener("click", async () => {
    const btn = $("#btn-cal-refresh");
    btn.disabled = true;
    btn.textContent = "⏳ Actualizando...";
    try {
      await loadCalendar(true);
      toast("📅 Calendario multi-plataforma actualizado (PC, Switch 2, PS5 y global)");
    } finally {
      btn.disabled = false;
      btn.textContent = "🔄 Actualizar";
    }
  });

  $("#cal-track-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#cal-track-input");
    const q = input.value.trim();
    if (!q) return;
    const btn = $("#btn-cal-track");
    btn.disabled = true;
    btn.textContent = "⏳...";
    try {
      const res = await api("/api/calendar/track", {
        method: "POST",
        body: { query: q, favorite: true },
      });
      const plats = (res.item.platforms || ["PC"]).join(" · ");
      toast(`★ Siguiendo «${res.item.title}» [${plats}] (${res.item.window_label})`);
      input.value = "";
      await loadCalendar(false);
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
      btn.textContent = "Seguir ★";
    }
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
