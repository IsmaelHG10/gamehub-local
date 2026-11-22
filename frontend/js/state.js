// GameHub — Estado compartido, utilidades API, helpers de formato y exportación de calendario

import { icon } from "./icons.js";

export const TOKEN_STORAGE_KEY = "gamehub_token";

export const state = {
  view: "hub",
  // Despliegue y sesión
  deploymentMode: "local",
  isWebMode: false,
  requireAuth: false,
  inviteCodeRequired: false,
  hasAnyUsers: false,
  user: null,
  authTab: "login",
  // Hub / Directorio
  hubCategory: "",
  hubFilter: "",
  // Novedades y Búsqueda
  latest: [],
  latestTotal: 0,
  latestOffset: 0,
  latestLimit: 48,
  latestLoaded: false,
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
  // Calendario Multi-Plataforma (estilo Releases.com)
  calMode: "hot",           // 'hot' | 'classic' | 'favorites'
  calLayout: "agenda",      // 'agenda' | 'list' | 'month' | 'week'
  calAgendaRange: "30d",    // 'recent' | '30d' | 'all' | 'month'
  calYear: new Date().getFullYear(),
  calMonth: new Date().getMonth(),
  calWeekRef: new Date(),
  calPlatforms: [],         // Multi-selección (vacío = todas)
  calGenre: "",
  calExactOnly: false,
  calSort: "date",          // 'date' | 'hot' | 'alpha'
  calInlineFilter: "",
  calSelectedDay: "",
  calData: {
    items: [],
    alerts: [],
    upcoming_soon: [],
    available_genres: [],
    available_platforms: [],
    platform_counts: {},
    favorites_count: 0,
    today: "",
    last_sync: null,
  },
  calLoaded: false,
};

// Hooks registrados por app.js para evitar dependencias circulares
export const hooks = {
  onUnauthorized: null,
  switchView: null,
  runSearch: null,
  openDetailDrawer: null,
  openCalendarItem: null,
  loadSources: null,
  loadLatest: null,
  loadCalendar: null,
  refreshHealthBadges: null,
};

export const $ = (sel, root = document) => root.querySelector(sel);
export const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

export function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function toast(msg, type = "ok") {
  const stack = $("#toast-stack");
  if (!stack) return;
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  const icoName = type === "err" ? "alertCircle" : "checkCircle";
  el.innerHTML = `<span class="toast-ico">${icon(icoName, 16)}</span><span>${esc(msg)}</span>`;
  stack.appendChild(el);
  setTimeout(() => {
    el.classList.add("toast-out");
    setTimeout(() => el.remove(), 220);
  }, 4000);
}

export function getStoredToken() {
  try {
    return localStorage.getItem(TOKEN_STORAGE_KEY) || "";
  } catch {
    return "";
  }
}

export function setStoredToken(token) {
  try {
    if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
    else localStorage.removeItem(TOKEN_STORAGE_KEY);
  } catch {}
}

export async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const tok = getStoredToken();
  if (tok && !headers.Authorization) {
    headers.Authorization = `Bearer ${tok}`;
  }
  const init = { ...opts, headers };
  if (init.body && typeof init.body !== "string") init.body = JSON.stringify(init.body);
  const res = await fetch(path, init);
  let data = null;
  try {
    data = await res.json();
  } catch {
    data = null;
  }
  if (!res.ok) {
    if (res.status === 401 && !path.startsWith("/api/auth/")) {
      setStoredToken("");
      state.user = null;
      hooks.onUnauthorized?.();
    }
    throw new Error(data?.detail || `Error HTTP ${res.status}`);
  }
  return data;
}

export function svgPlaceholder(title) {
  const clean = (title || "Game").trim();
  const initials =
    clean
      .split(/\s+/)
      .slice(0, 2)
      .map((w) => w[0] || "")
      .join("")
      .toUpperCase() || "GH";
  const shortTitle = clean.length > 26 ? clean.slice(0, 24) + "…" : clean;
  const svg = `<svg xmlns="http://www.w3.org/2000/svg" width="400" height="600" viewBox="0 0 400 600">
    <defs>
      <linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0%" stop-color="#0b1120"/>
        <stop offset="55%" stop-color="#172038"/>
        <stop offset="100%" stop-color="#090d16"/>
      </linearGradient>
    </defs>
    <rect width="400" height="600" fill="url(#g)"/>
    <circle cx="200" cy="235" r="70" fill="rgba(56,189,248,0.09)" stroke="rgba(56,189,248,0.32)" stroke-width="2"/>
    <text x="200" y="253" text-anchor="middle" fill="#38bdf8" font-family="Plus Jakarta Sans, Segoe UI, sans-serif" font-size="46" font-weight="800">${esc(initials)}</text>
    <text x="200" y="368" text-anchor="middle" fill="#cbd5e1" font-family="Inter, Segoe UI, sans-serif" font-size="19" font-weight="600">${esc(shortTitle)}</text>
  </svg>`;
  return `data:image/svg+xml;charset=utf-8,${encodeURIComponent(svg)}`;
}

export function posterChain(item) {
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

export function extractDomain(rawUrl) {
  try {
    const u = new URL(rawUrl.includes("://") ? rawUrl : `https://${rawUrl}`);
    return u.hostname.replace(/^www\./i, "");
  } catch {
    return "";
  }
}

export function originUrl(rawUrl) {
  try {
    const u = new URL(rawUrl.includes("://") ? rawUrl : `https://${rawUrl}`);
    return u.origin;
  } catch {
    return "";
  }
}

export function faviconUrl(rawUrl) {
  const domain = extractDomain(rawUrl);
  if (!domain || domain.includes("localhost") || !domain.includes(".")) return "";
  return `https://www.google.com/s2/favicons?domain=${encodeURIComponent(domain)}&sz=64`;
}

export function sourceInitials(name) {
  return (
    String(name || "GH")
      .replace(/[^a-zA-Z0-9\s]/g, " ")
      .trim()
      .split(/\s+/)
      .slice(0, 2)
      .map((w) => w[0] || "")
      .join("")
      .toUpperCase() || "GH"
  );
}

export function relativeTime(isoOrEpoch) {
  if (!isoOrEpoch) return "Reciente";
  const ms =
    typeof isoOrEpoch === "number"
      ? isoOrEpoch < 1e12
        ? isoOrEpoch * 1000
        : isoOrEpoch
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

export function splitUris(item) {
  const uris = item?.uris || [];
  const magnets = uris.filter((u) => u.toLowerCase().startsWith("magnet:?xt="));
  const httpLinks = uris.filter((u) => /^https?:\/\//i.test(u));
  if (httpLinks.length === 0 && item?.page_url) {
    httpLinks.push(item.page_url);
  }
  return { magnets, httpLinks };
}

export function canManageSources() {
  if (!state.isWebMode && !state.requireAuth) {
    return !state.user || Boolean(state.user.is_admin);
  }
  return Boolean(state.user?.is_admin);
}

// --------------------------------------------------------------------------- Plataformas y Calendario

export const PLATFORM_STYLE = {
  PC: { cls: "plat-pc", short: "PC", pillCls: "p-pc", dot: "#38bdf8" },
  "Switch 2": { cls: "plat-ns2", short: "Switch 2", pillCls: "p-ns2", dot: "#f87171" },
  PS5: { cls: "plat-ps5", short: "PS5", pillCls: "p-ps5", dot: "#60a5fa" },
  "Xbox Series": { cls: "plat-xsx", short: "XSX", pillCls: "p-xsx", dot: "#4ade80" },
  Switch: { cls: "plat-ns", short: "Switch", pillCls: "p-ns", dot: "#fb7185" },
  PS4: { cls: "plat-ps4", short: "PS4", pillCls: "", dot: "#818cf8" },
  "Xbox One": { cls: "plat-xbo", short: "XOne", pillCls: "", dot: "#34d399" },
  Mac: { cls: "", short: "Mac", pillCls: "", dot: "#cbd5e1" },
  Linux: { cls: "", short: "Linux", pillCls: "", dot: "#fbbf24" },
};

export function renderPlatformBadges(platforms, maxCount = 4) {
  const list = platforms && platforms.length ? platforms : ["PC"];
  return list
    .slice(0, maxCount)
    .map((p) => {
      const st = PLATFORM_STYLE[p] || { cls: "", short: p };
      return `<span class="plat-badge ${st.cls}" title="${esc(p)}">${esc(st.short)}</span>`;
    })
    .join("");
}

export function storeLabelForUrl(url, appid) {
  const u = String(url || "").toLowerCase();
  if (Number(appid) > 0 || u.includes("steampowered.com")) return "Ver en Steam";
  if (u.includes("nintendo.")) return "Nintendo eShop";
  if (u.includes("playstation.")) return "PlayStation";
  if (u.includes("xbox.")) return "Xbox Store";
  if (u.includes("wikipedia.org")) return "Ficha Wikipedia";
  return "Ficha oficial";
}

// --------------------------------------------------------------------------- Exportación .ics y Google Calendar

function icsEscape(str) {
  return String(str || "")
    .replace(/\\/g, "\\\\")
    .replace(/;/g, "\\;")
    .replace(/,/g, "\\,")
    .replace(/\r?\n/g, "\\n");
}

function nextIsoDay(isoDate) {
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d + 1));
  return dt.toISOString().slice(0, 10);
}

export function googleCalendarUrl(calItem) {
  if (!calItem || calItem.precision !== "day" || !calItem.release_date) return "";
  const start = calItem.release_date.replace(/-/g, "");
  const end = nextIsoDay(calItem.release_date).replace(/-/g, "");
  const plats = (calItem.platforms || ["PC"]).join(", ");
  const details = `Lanzamiento de ${calItem.title} (${plats}).${calItem.store_url ? "\nFicha: " + calItem.store_url : ""}`;
  const params = new URLSearchParams({
    action: "TEMPLATE",
    text: `Lanzamiento: ${calItem.title}`,
    dates: `${start}/${end}`,
    details,
  });
  return `https://calendar.google.com/calendar/render?${params.toString()}`;
}

export function exportGamesToIcs(items, filename = "gamehub-lanzamientos.ics") {
  const dated = (items || []).filter((it) => it.precision === "day" && /^\d{4}-\d{2}-\d{2}$/.test(it.release_date || ""));
  if (!dated.length) {
    toast("No hay juegos con fecha exacta confirmada para exportar", "err");
    return false;
  }
  const stamp = new Date().toISOString().replace(/[-:]/g, "").slice(0, 15) + "Z";
  const events = dated.map((it) => {
    const start = it.release_date.replace(/-/g, "");
    const end = nextIsoDay(it.release_date).replace(/-/g, "");
    const plats = (it.platforms || ["PC"]).join(", ");
    const desc = [
      `Plataformas: ${plats}`,
      it.genres?.length ? `Géneros: ${it.genres.join(", ")}` : "",
      it.store_url ? `Enlace: ${it.store_url}` : "",
    ]
      .filter(Boolean)
      .join("\n");
    return [
      "BEGIN:VEVENT",
      `UID:gamehub-${it.appid}-${start}@gamehub`,
      `DTSTAMP:${stamp}`,
      `DTSTART;VALUE=DATE:${start}`,
      `DTEND;VALUE=DATE:${end}`,
      `SUMMARY:${icsEscape(`Lanzamiento: ${it.title}`)}`,
      `DESCRIPTION:${icsEscape(desc)}`,
      "END:VEVENT",
    ].join("\r\n");
  });

  const content = [
    "BEGIN:VCALENDAR",
    "VERSION:2.0",
    "PRODID:-//GameHub//Release Calendar//ES",
    "CALSCALE:GREGORIAN",
    "X-WR-CALNAME:GameHub Lanzamientos",
    ...events,
    "END:VCALENDAR",
  ].join("\r\n");

  const blob = new Blob([content], { type: "text/calendar;charset=utf-8" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(a.href), 1500);
  toast(`Exportados ${dated.length} lanzamiento(s) a ${filename}`);
  return true;
}

// --------------------------------------------------------------------------- Skeleton Loaders

export function renderPosterSkeletons(count = 10) {
  return Array.from({ length: count })
    .map(
      () => `
      <div class="skeleton-card">
        <div class="skeleton skeleton-poster"></div>
        <div class="skeleton-body">
          <div class="skeleton skeleton-line w-85"></div>
          <div class="skeleton skeleton-line w-55"></div>
        </div>
      </div>`
    )
    .join("");
}

export function renderListSkeletons(count = 6) {
  return Array.from({ length: count })
    .map(
      () => `
      <div class="skeleton-row">
        <div class="skeleton skeleton-thumb"></div>
        <div style="flex:1;display:flex;flex-direction:column;gap:8px;">
          <div class="skeleton skeleton-line w-55"></div>
          <div class="skeleton skeleton-line w-35"></div>
        </div>
      </div>`
    )
    .join("");
}
