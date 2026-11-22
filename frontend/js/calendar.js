// GameHub — Calendario de Lanzamientos Multi-Plataforma (estilo Releases.com)

import { icon } from "./icons.js";
import {
  $,
  $$,
  api,
  esc,
  exportGamesToIcs,
  googleCalendarUrl,
  hooks,
  PLATFORM_STYLE,
  renderListSkeletons,
  renderPlatformBadges,
  renderPosterSkeletons,
  state,
  storeLabelForUrl,
  svgPlaceholder,
  toast,
} from "./state.js";
import { renderHubStats, renderHubUpcomingRail } from "./hub.js";

const MONTHS_ES = [
  "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio",
  "Julio", "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre",
];
const MONTHS_SHORT = ["Ene", "Feb", "Mar", "Abr", "May", "Jun", "Jul", "Ago", "Sep", "Oct", "Nov", "Dic"];
const WEEKDAYS_SHORT = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"];
const WEEKDAYS_FULL = ["Domingo", "Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado"];

let countdownTimer = null;

export function toIsoLocal(d) {
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
  const dow = (copy.getDay() + 6) % 7;
  copy.setDate(copy.getDate() - dow);
  return copy;
}

function diffDays(targetIso, todayIso) {
  const [ty, tm, td] = todayIso.split("-").map(Number);
  const [ry, rm, rd] = targetIso.split("-").map(Number);
  return Math.round((Date.UTC(ry, rm - 1, rd) - Date.UTC(ty, tm - 1, td)) / 86400000);
}

export function countdownMeta(calItem, todayIso) {
  if (calItem.precision !== "day" || !calItem.release_date) {
    return { label: calItem.window_label || "Próximamente", cls: "tba", days: null };
  }
  const diff = diffDays(calItem.release_date, todayIso);
  if (diff === 0) return { label: "Sale HOY", cls: "today", days: 0 };
  if (diff === 1) return { label: "Mañana", cls: "soon", days: 1 };
  if (diff > 1 && diff <= 14) return { label: `En ${diff} días`, cls: "soon", days: diff };
  if (diff > 14 && diff <= 60) return { label: `En ${diff} días`, cls: "", days: diff };
  if (diff > 60) return { label: calItem.window_label || calItem.release_date, cls: "", days: diff };
  if (diff === -1) return { label: "Salió ayer", cls: "released", days: -1 };
  if (diff >= -30) return { label: `Hace ${Math.abs(diff)} d`, cls: "released", days: diff };
  return { label: calItem.window_label || calItem.release_date, cls: "released", days: diff };
}

function liveClockString(isoDate) {
  const [y, m, d] = isoDate.split("-").map(Number);
  const target = new Date(y, m - 1, d, 0, 0, 0).getTime();
  const diffMs = target - Date.now();
  if (diffMs <= 0) return "DISPONIBLE HOY";
  const totalMin = Math.floor(diffMs / 60000);
  const days = Math.floor(totalMin / 1440);
  const hrs = Math.floor((totalMin % 1440) / 60);
  const mins = totalMin % 60;
  if (days > 0) return `${days}d ${String(hrs).padStart(2, "0")}h ${String(mins).padStart(2, "0")}m`;
  return `${String(hrs).padStart(2, "0")}h ${String(mins).padStart(2, "0")}m`;
}

function formatDayHeading(isoDate, todayIso) {
  const [y, m, d] = isoDate.split("-").map(Number);
  const dt = new Date(y, m - 1, d);
  const wname = WEEKDAYS_FULL[dt.getDay()];
  const curYear = new Date().getFullYear();
  const base = `${wname} ${d} de ${MONTHS_ES[m - 1]}${y !== curYear ? " " + y : ""}`;
  const diff = diffDays(isoDate, todayIso);
  if (diff === 0) return { tag: "HOY", tagCls: "today", text: base };
  if (diff === 1) return { tag: "MAÑANA", tagCls: "soon", text: base };
  if (diff === -1) return { tag: "AYER", tagCls: "released", text: base };
  if (diff > 1 && diff <= 7) return { tag: `EN ${diff} DÍAS`, tagCls: "soon", text: base };
  return { tag: "", tagCls: "", text: base };
}

export function calItemToDrawerItem(c) {
  const hasSteam = Number(c.appid) > 0;
  const plats = c.platforms && c.platforms.length ? c.platforms : ["PC"];
  return {
    id: `cal-${c.appid}`,
    cal_item: c,
    raw_title: `${c.title} · ${plats.join(" / ")} (${c.window_label || "Próximamente"})`,
    clean_title: c.title,
    source_id: "multi-calendar",
    source_name: `Calendario (${plats.slice(0, 3).join(" · ")})`,
    source_category: c.window_label || "Lanzamiento",
    published_at: c.precision === "day" ? `${c.release_date}T12:00:00Z` : null,
    page_url: "",
    external_store_url: !hasSteam ? c.store_url || "" : "",
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

export async function toggleCalendarFavorite(calItem, ev) {
  ev?.stopPropagation();
  try {
    const res = await api("/api/calendar/favorites/toggle", {
      method: "POST",
      body: { item: calItem },
    });
    calItem.favorited = res.favorited;
    (state.calData.items || []).forEach((it) => {
      if (it.appid === calItem.appid) it.favorited = res.favorited;
    });
    toast(
      res.favorited
        ? `Siguiendo «${calItem.title}» en tu Calendario`
        : `Dejaste de seguir «${calItem.title}»`
    );
    if (state.calMode === "favorites" && !res.favorited) {
      await loadCalendar(false);
    } else {
      const delta = res.favorited ? 1 : -1;
      state.calData.favorites_count = Math.max(0, (state.calData.favorites_count || 0) + delta);
      updateFavBadges();
      renderCalendar();
    }
  } catch (err) {
    toast(err.message, "err");
  }
}

function updateFavBadges() {
  const n = String(state.calData.favorites_count || 0);
  const el1 = $("#cal-fav-count");
  const el2 = $("#badge-calendar");
  if (el1) el1.textContent = n;
  if (el2) el2.textContent = n;
}

export async function loadCalendar(forceRefresh = false) {
  const container = $("#cal-container");
  if (container && (!state.calLoaded || forceRefresh)) {
    container.innerHTML =
      state.calLayout === "list"
        ? `<div class="cal-list-wrap">${renderListSkeletons(8)}</div>`
        : `<div class="poster-grid">${renderPosterSkeletons(10)}</div>`;
  }
  try {
    const params = new URLSearchParams({ mode: state.calMode });
    if (forceRefresh) params.set("force_refresh", "true");
    const data = await api(`/api/calendar?${params}`);
    state.calData = data;
    state.calLoaded = true;
    updateFavBadges();
    renderHubStats();
    renderHubUpcomingRail();
    renderCalendarAlerts();
    renderCalendarPlatforms();
    renderCalendarGenres();
    renderCalendar();
  } catch (err) {
    toast(err.message, "err");
    if (container) {
      container.innerHTML = `
        <div class="empty-state">
          <div class="empty-icon">${icon("alertCircle", 26)}</div>
          <h3>No se pudo cargar el calendario</h3>
          <p>${esc(err.message)}</p>
        </div>`;
    }
  }
}

function renderCalendarAlerts() {
  const box = $("#cal-alerts");
  if (!box) return;
  const alerts = state.calData.alerts || [];
  const soon = state.calData.upcoming_soon || [];
  const todayIso = state.calData.today || toIsoLocal(new Date());

  if (!alerts.length && !soon.length) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }

  const parts = [];
  if (alerts.length) {
    const names = alerts
      .slice(0, 4)
      .map((a) => `<strong>${esc(a.title)}</strong> (${a.release_date === todayIso ? "Sale HOY" : a.window_label})`)
      .join(" · ");
    parts.push(`
      <div class="cal-alert-banner released">
        <div class="cal-alert-left">
          <span class="cal-alert-ico">${icon("bell", 16)}</span>
          <div><strong>Lanzamientos seguidos ya disponibles:</strong> ${names}</div>
        </div>
        <button class="btn btn-primary btn-sm" id="btn-alert-search">
          ${icon("search", 13)} Buscar «${esc(alerts[0].title)}»
        </button>
      </div>
    `);
  }

  if (soon.length) {
    const names = soon
      .slice(0, 4)
      .map((a) => {
        const d = diffDays(a.release_date, todayIso);
        return `<strong>${esc(a.title)}</strong> (${d === 1 ? "Mañana" : `en ${d} días`})`;
      })
      .join(" · ");
    parts.push(`
      <div class="cal-alert-banner upcoming">
        <div class="cal-alert-left">
          <span class="cal-alert-ico">${icon("clock", 16)}</span>
          <div><strong>Salen esta semana de tu lista:</strong> ${names}</div>
        </div>
        <button class="btn btn-secondary btn-sm" id="btn-alert-ics">
          ${icon("calendarPlus", 13)} Exportar .ics
        </button>
      </div>
    `);
  }

  box.className = "cal-alerts-stack";
  box.innerHTML = parts.join("");

  box.querySelector("#btn-alert-search")?.addEventListener("click", () => {
    const input = $("#global-search-input");
    if (input) input.value = alerts[0].title;
    hooks.runSearch?.(alerts[0].title);
  });
  box.querySelector("#btn-alert-ics")?.addEventListener("click", () => {
    exportGamesToIcs(soon, "gamehub-esta-semana.ics");
  });
}

function renderCalendarPlatforms() {
  const wrap = $("#cal-platform-pills");
  if (!wrap) return;
  const counts = state.calData.platform_counts || {};
  const totalAll = (state.calData.items || []).length;
  const ordered = ["PC", "Switch 2", "PS5", "Xbox Series", "Switch", "PS4", "Xbox One"];
  const visiblePlats = ordered.filter((p) => counts[p] > 0 || ["PC", "Switch 2", "PS5", "Xbox Series"].includes(p));

  wrap.innerHTML = "";

  const allBtn = document.createElement("button");
  allBtn.className = `pill ${state.calPlatforms.length === 0 ? "active" : ""}`;
  allBtn.innerHTML = `Todas<span class="pill-count">${totalAll}</span>`;
  allBtn.addEventListener("click", () => {
    state.calPlatforms = [];
    renderCalendarPlatforms();
    renderCalendar();
  });
  wrap.appendChild(allBtn);

  visiblePlats.forEach((p) => {
    const st = PLATFORM_STYLE[p] || { dot: "#94a3b8", pillCls: "" };
    const isSelected = state.calPlatforms.includes(p);
    const btn = document.createElement("button");
    btn.className = `pill ${st.pillCls || ""} ${isSelected ? "active" : ""}`.trim();
    btn.innerHTML = `
      <span class="plat-dot" style="background:${st.dot};"></span>
      <span>${esc(p)}</span>
      <span class="pill-count">${counts[p] || 0}</span>
    `;
    btn.addEventListener("click", () => {
      if (isSelected) {
        state.calPlatforms = state.calPlatforms.filter((x) => x !== p);
      } else {
        state.calPlatforms = [...state.calPlatforms, p];
      }
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
  if (!wrap) return;
  wrap.innerHTML = "";
  list.forEach((g) => {
    const btn = document.createElement("button");
    btn.className = `pill pill-subtle ${state.calGenre === g ? "active" : ""}`;
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
  let items = [...(state.calData.items || [])];
  if (state.calPlatforms.length > 0) {
    items = items.filter((it) =>
      (it.platforms || []).some((p) => state.calPlatforms.includes(p))
    );
  }
  if (state.calGenre) {
    items = items.filter((it) => (it.genres || []).includes(state.calGenre));
  }
  if (state.calExactOnly) {
    items = items.filter((it) => it.precision === "day");
  }
  const q = state.calInlineFilter.trim().toLowerCase();
  if (q) {
    items = items.filter((it) => it.title.toLowerCase().includes(q));
  }

  if (state.calSort === "alpha") {
    items.sort((a, b) => a.title.localeCompare(b.title, "es"));
  } else if (state.calSort === "hot") {
    items.sort(
      (a, b) =>
        Number(Boolean(b.favorited)) - Number(Boolean(a.favorited)) ||
        Number(Boolean(b.is_hot)) - Number(Boolean(a.is_hot)) ||
        (a.release_date || "9999-12-31").localeCompare(b.release_date || "9999-12-31")
    );
  } else {
    items.sort(
      (a, b) =>
        (a.release_date || "9999-12-31").localeCompare(b.release_date || "9999-12-31") ||
        Number(Boolean(b.is_hot)) - Number(Boolean(a.is_hot)) ||
        a.title.localeCompare(b.title, "es")
    );
  }
  return items;
}

function renderSpotlight(items, todayIso) {
  const wrap = $("#cal-spotlight");
  if (!wrap) return;
  if (countdownTimer) {
    clearInterval(countdownTimer);
    countdownTimer = null;
  }

  // Solo mostrar en vistas Agenda o Lista cuando no hay filtro de texto activo
  if (state.calInlineFilter.trim() || state.calLayout === "month" || state.calLayout === "week") {
    wrap.classList.add("hidden");
    wrap.innerHTML = "";
    return;
  }

  const upcomingDated = items
    .filter((it) => it.precision === "day" && it.release_date >= todayIso)
    .sort((a, b) => {
      // Priorizar los que sigues o los Hot más inminentes
      const aScore = (a.favorited ? -1000 : 0) + (a.is_hot ? -200 : 0) + diffDays(a.release_date, todayIso);
      const bScore = (b.favorited ? -1000 : 0) + (b.is_hot ? -200 : 0) + diffDays(b.release_date, todayIso);
      return aScore - bScore;
    })
    .slice(0, 4);

  if (!upcomingDated.length) {
    wrap.classList.add("hidden");
    wrap.innerHTML = "";
    return;
  }

  wrap.classList.remove("hidden");
  wrap.innerHTML = `
    <div class="cal-spotlight-header">
      <div class="cal-spotlight-title">
        ${icon("clock", 15)}
        <span>Cuenta atrás · Próximos lanzamientos clave</span>
      </div>
      <span class="cal-spotlight-sub">Actualización en tiempo real</span>
    </div>
    <div class="cal-spotlight-grid"></div>
  `;

  const grid = wrap.querySelector(".cal-spotlight-grid");
  upcomingDated.forEach((c) => {
    const fallbacks = [c.header_url, svgPlaceholder(c.title)].filter(Boolean);
    const primary = c.poster_url || fallbacks[0];
    const bg = c.header_url || c.poster_url || "";
    const card = document.createElement("article");
    card.className = "cal-spot-card";
    if (bg && /^https?:\/\//i.test(bg)) {
      card.style.setProperty("--spot-bg", `url("${bg.replace(/"/g, "%22")}")`);
    }
    card.innerHTML = `
      <div class="cal-spot-bg"></div>
      <div class="cal-spot-inner">
        <img
          class="cal-spot-poster"
          src="${esc(primary)}"
          data-fallbacks="${esc(fallbacks.join("||"))}"
          onerror="window.__imgFallback(this)"
          alt="${esc(c.title)}"
        />
        <div class="cal-spot-meta">
          <div class="cal-spot-clock" data-iso="${esc(c.release_date)}">${esc(liveClockString(c.release_date))}</div>
          <div class="cal-spot-name" title="${esc(c.title)}">${esc(c.title)}</div>
          <div class="plat-tags">${renderPlatformBadges(c.platforms, 3)}</div>
          <div class="cal-spot-date">${esc(c.window_label || c.release_date)}</div>
        </div>
        <button class="bookmark-btn ${c.favorited ? "saved" : ""}" title="${c.favorited ? "Quitar seguimiento" : "Seguir lanzamiento"}">
          ${icon(c.favorited ? "starFilled" : "star", 14)}
        </button>
      </div>
    `;
    card.querySelector(".bookmark-btn").addEventListener("click", (e) => toggleCalendarFavorite(c, e));
    card.addEventListener("click", () => hooks.openDetailDrawer?.(calItemToDrawerItem(c)));
    grid.appendChild(card);
  });

  // Actualizar relojes cada 30 segundos solo cuando el calendario está visible
  countdownTimer = setInterval(() => {
    if (state.view !== "calendar") return;
    $$(".cal-spot-clock", wrap).forEach((el) => {
      if (el.dataset.iso) el.textContent = liveClockString(el.dataset.iso);
    });
  }, 30000);
}

function renderMonthJumpStrip(items, todayIso) {
  const strip = $("#cal-month-strip");
  if (!strip) return;

  if (state.calLayout === "week") {
    strip.classList.add("hidden");
    return;
  }
  strip.classList.remove("hidden");

  // Contar lanzamientos por YYYY-MM desde el mes actual hacia adelante (y mes previo)
  const curYm = todayIso.slice(0, 7);
  const monthMap = new Map();
  items.forEach((it) => {
    const rd = it.release_date || "";
    if (/^\d{4}-\d{2}/.test(rd) && !rd.startsWith("9999")) {
      const ym = rd.slice(0, 7);
      if (ym >= curYm) {
        monthMap.set(ym, (monthMap.get(ym) || 0) + 1);
      }
    }
  });

  const sortedMonths = Array.from(monthMap.entries())
    .sort((a, b) => a[0].localeCompare(b[0]))
    .slice(0, 12);

  strip.innerHTML = "";
  const activeYm = `${state.calYear}-${String(state.calMonth + 1).padStart(2, "0")}`;

  sortedMonths.forEach(([ym, cnt]) => {
    const [yStr, mStr] = ym.split("-");
    const y = Number(yStr);
    const m = Number(mStr) - 1;
    const isActive =
      (state.calLayout === "month" && activeYm === ym) ||
      ((state.calLayout === "agenda" || state.calLayout === "list") &&
        state.calAgendaRange === "month" &&
        activeYm === ym);

    const btn = document.createElement("button");
    btn.className = `month-chip ${isActive ? "active" : ""}`;
    btn.innerHTML = `<span>${MONTHS_SHORT[m]} ${String(y).slice(2)}</span><span class="pill-count">${cnt}</span>`;
    btn.addEventListener("click", () => {
      state.calYear = y;
      state.calMonth = m;
      if (state.calLayout === "agenda" || state.calLayout === "list") {
        state.calAgendaRange = "month";
      }
      renderCalendar();
    });
    strip.appendChild(btn);
  });
}

function updateCalendarNavLabels() {
  const curYear = new Date().getFullYear();
  const recentBtn = $("#btn-cal-recent");
  const upBtn = $("#btn-cal-upcoming30");
  const allBtn = $("#btn-cal-allupcoming");
  if (allBtn) {
    allBtn.innerHTML = `${icon("calendar", 13)} <span>Todo ${curYear}–${curYear + 1}+</span>`;
  }

  const showRanges = (state.calLayout === "agenda" || state.calLayout === "list") && state.calMode !== "favorites";
  recentBtn?.classList.toggle("hidden", !showRanges);
  upBtn?.classList.toggle("hidden", !showRanges);
  allBtn?.classList.toggle("hidden", !showRanges);

  recentBtn?.classList.toggle("active", showRanges && state.calAgendaRange === "recent");
  upBtn?.classList.toggle("active", showRanges && state.calAgendaRange === "30d");
  allBtn?.classList.toggle("active", showRanges && state.calAgendaRange === "all");

  const label = $("#cal-period-label");
  if (!label) return;
  if (state.calMode === "favorites" && (state.calLayout === "agenda" || state.calLayout === "list")) {
    label.textContent = "Todos mis seguidos";
  } else if (state.calLayout === "week") {
    const mon = mondayOfWeek(state.calWeekRef);
    const sun = addDays(mon, 6);
    label.textContent = `${mon.getDate()} ${MONTHS_SHORT[mon.getMonth()]} – ${sun.getDate()} ${MONTHS_SHORT[sun.getMonth()]} ${sun.getFullYear()}`;
  } else if ((state.calLayout === "agenda" || state.calLayout === "list") && state.calAgendaRange === "recent") {
    label.textContent = "Recientes (últimos 30 días)";
  } else if ((state.calLayout === "agenda" || state.calLayout === "list") && state.calAgendaRange === "30d") {
    label.textContent = "Próximos 30 días";
  } else if ((state.calLayout === "agenda" || state.calLayout === "list") && state.calAgendaRange === "all") {
    label.textContent = `Horizonte ${curYear}–${curYear + 1}+`;
  } else {
    label.textContent = `${MONTHS_ES[state.calMonth]} ${state.calYear}`;
  }
}

export function renderCalendar() {
  updateCalendarNavLabels();
  $("#cal-selected-day-box")?.classList.add("hidden");
  const todayIso = state.calData.today || toIsoLocal(new Date());
  const items = filteredCalendarItems();

  renderSpotlight(items, todayIso);
  renderMonthJumpStrip(items, todayIso);

  if (state.calLayout === "month") {
    renderCalendarMonth(items, todayIso);
  } else if (state.calLayout === "week") {
    renderCalendarWeek(items, todayIso);
  } else if (state.calLayout === "list") {
    renderCalendarAgendaOrList(items, todayIso, "list");
  } else {
    renderCalendarAgendaOrList(items, todayIso, "agenda");
  }
}

function scopeTimelineItems(items, todayIso) {
  if (state.calMode === "favorites" || state.calInlineFilter.trim()) {
    return items;
  }
  if (state.calAgendaRange === "recent") {
    const startIso = toIsoLocal(addDays(new Date(), -35));
    return items
      .filter((it) => it.precision === "day" && it.release_date >= startIso && it.release_date <= todayIso)
      .sort((a, b) => (b.release_date || "").localeCompare(a.release_date || ""));
  }
  if (state.calAgendaRange === "30d") {
    const endIso = toIsoLocal(addDays(new Date(), 35));
    return items.filter(
      (it) =>
        (it.precision === "day" && it.release_date >= todayIso && it.release_date <= endIso) ||
        (it.precision !== "day" && (it.release_date || "").slice(0, 7) >= todayIso.slice(0, 7))
    );
  }
  if (state.calAgendaRange === "all") {
    return items.filter(
      (it) =>
        (it.precision === "day" && it.release_date >= todayIso) ||
        (it.precision !== "day" && (it.release_date || "").slice(0, 7) >= todayIso.slice(0, 7))
    );
  }
  const ym = `${state.calYear}-${String(state.calMonth + 1).padStart(2, "0")}`;
  return items.filter((it) => (it.release_date || "").startsWith(ym));
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
        <button class="bookmark-btn ${c.favorited ? "saved" : ""}" title="${c.favorited ? "Quitar seguimiento" : "Seguir lanzamiento"}">
          ${icon(c.favorited ? "starFilled" : "star", 14)}
        </button>
      </div>
      <div class="poster-overlay">
        <div class="quick-actions">
          <button class="btn btn-primary act-find" title="Buscar en mis fuentes">${icon("search", 12)} Buscar</button>
          ${c.store_url ? `<a class="btn btn-secondary act-steam" href="${esc(c.store_url)}" target="_blank" rel="noopener" title="${esc(storeTitle)}">${icon("arrowUpRight", 13)}</a>` : ""}
        </div>
      </div>
    </div>
    <div class="card-body">
      <div class="card-title" title="${esc(c.title)}">${esc(c.title)}</div>
      <div class="plat-tags">${renderPlatformBadges(c.platforms, 4)}</div>
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
    const input = $("#global-search-input");
    if (input) input.value = c.title;
    hooks.runSearch?.(c.title);
  });
  el.querySelector(".act-steam")?.addEventListener("click", (e) => e.stopPropagation());
  el.addEventListener("click", () => hooks.openDetailDrawer?.(calItemToDrawerItem(c)));
  return el;
}

function renderCalendarListRow(c, todayIso) {
  const fallbacks = [c.header_url, svgPlaceholder(c.title)].filter(Boolean);
  const primary = c.poster_url || fallbacks[0];
  const cd = countdownMeta(c, todayIso);
  const gcal = googleCalendarUrl(c);

  const row = document.createElement("article");
  row.className = "cal-list-row";
  row.innerHTML = `
    <img
      class="cal-list-thumb"
      src="${esc(primary)}"
      data-fallbacks="${esc(fallbacks.join("||"))}"
      onerror="window.__imgFallback(this)"
      loading="lazy"
      alt="${esc(c.title)}"
    />
    <div class="cal-list-main">
      <div class="cal-list-title-row">
        <span class="cal-list-title">${esc(c.title)}</span>
        ${c.is_hot ? `<span class="hot-dot" title="Lanzamiento destacado">${icon("flame", 12)}</span>` : ""}
      </div>
      <div class="cal-list-tags">
        ${renderPlatformBadges(c.platforms, 5)}
        ${(c.genres || []).slice(0, 3).map((g) => `<span class="genre-mini">${esc(g)}</span>`).join("")}
      </div>
    </div>
    <div class="cal-list-date">
      <span class="countdown-pill ${cd.cls}">${esc(cd.label)}</span>
      <span class="cal-list-window">${esc(c.window_label || "Próximamente")}</span>
    </div>
    <div class="cal-list-actions">
      <button class="btn btn-secondary btn-sm act-find" title="Buscar en mis fuentes">${icon("search", 13)}</button>
      ${gcal ? `<a class="btn btn-secondary btn-sm act-gcal" href="${esc(gcal)}" target="_blank" rel="noopener" title="Añadir a Google Calendar">${icon("calendarPlus", 13)}</a>` : ""}
      ${c.store_url ? `<a class="btn btn-secondary btn-sm act-store" href="${esc(c.store_url)}" target="_blank" rel="noopener" title="${esc(storeLabelForUrl(c.store_url, c.appid))}">${icon("external", 13)}</a>` : ""}
      <button class="bookmark-btn ${c.favorited ? "saved" : ""}" title="${c.favorited ? "Quitar seguimiento" : "Seguir lanzamiento"}">
        ${icon(c.favorited ? "starFilled" : "star", 14)}
      </button>
    </div>
  `;

  row.querySelector(".bookmark-btn").addEventListener("click", (e) => toggleCalendarFavorite(c, e));
  row.querySelector(".act-find").addEventListener("click", (e) => {
    e.stopPropagation();
    const input = $("#global-search-input");
    if (input) input.value = c.title;
    hooks.runSearch?.(c.title);
  });
  row.querySelector(".act-gcal")?.addEventListener("click", (e) => e.stopPropagation());
  row.querySelector(".act-store")?.addEventListener("click", (e) => e.stopPropagation());
  row.addEventListener("click", () => hooks.openDetailDrawer?.(calItemToDrawerItem(c)));
  return row;
}

function renderCalendarAgendaOrList(items, todayIso, mode) {
  const container = $("#cal-container");
  if (!container) return;
  container.innerHTML = "";

  const scoped = scopeTimelineItems(items, todayIso);

  if (!scoped.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">${icon("calendar", 28)}</div>
        <h3>
          ${state.calMode === "favorites" ? "Aún no sigues ningún lanzamiento" : "No hay lanzamientos en este tramo"}
        </h3>
        <p>
          ${
            state.calMode === "favorites"
              ? "Marca cualquier juego con la estrella en Hot o Clásico (o añádelo arriba por nombre) para seguir su cuenta atrás."
              : "Prueba ampliando al horizonte completo, cambiando a Clásico (Todos) o ajustando los filtros."
          }
        </p>
      </div>`;
    return;
  }

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

  const sortedDays = Array.from(byDay.keys()).sort((a, b) =>
    state.calAgendaRange === "recent" ? b.localeCompare(a) : a.localeCompare(b)
  );

  sortedDays.forEach((dayIso) => {
    const dayItems = byDay.get(dayIso);
    const heading = formatDayHeading(dayIso, todayIso);
    const block = document.createElement("div");
    block.className = "cal-day-block";
    block.innerHTML = `
      <div class="cal-day-header ${dayIso === todayIso ? "is-today" : ""}">
        <div class="cal-day-title">
          ${heading.tag ? `<span class="day-chip ${heading.tagCls}">${esc(heading.tag)}</span>` : ""}
          <span>${esc(heading.text)}</span>
        </div>
        <span class="badge">${dayItems.length} ${dayItems.length === 1 ? "juego" : "juegos"}</span>
      </div>
      <div class="${mode === "list" ? "cal-list-wrap" : "poster-grid"}"></div>
    `;
    const body = block.lastElementChild;
    dayItems.forEach((c) =>
      body.appendChild(mode === "list" ? renderCalendarListRow(c, todayIso) : renderCalendarCard(c, todayIso))
    );
    container.appendChild(block);
  });

  if (state.calMode !== "favorites" && state.calAgendaRange === "30d") {
    const endIso = toIsoLocal(addDays(new Date(), 35));
    const laterCount = items.filter((it) => it.precision === "day" && it.release_date > endIso).length;
    if (laterCount > 0) {
      const moreBanner = document.createElement("div");
      moreBanner.className = "panel-box cal-horizon-banner";
      moreBanner.innerHTML = `
        <span>Hay <strong>${laterCount}</strong> lanzamiento(s) más con día exacto confirmado más allá de 30 días.</span>
        <button class="btn btn-secondary btn-sm" id="btn-expand-horizon">
          <span>Ver horizonte completo</span>
          ${icon("arrowRight", 13)}
        </button>
      `;
      moreBanner.querySelector("#btn-expand-horizon").addEventListener("click", () => {
        state.calAgendaRange = "all";
        renderCalendar();
      });
      container.appendChild(moreBanner);
    }
  }

  Array.from(windows.entries())
    .slice(0, 14)
    .forEach(([wLabel, wItems]) => {
      const block = document.createElement("div");
      block.className = "cal-day-block";
      const initialSlice = mode === "list" ? 30 : 24;
      block.innerHTML = `
        <div class="cal-day-header is-window">
          <div class="cal-day-title">
            <span class="day-chip tba">VENTANA</span>
            <span>${esc(wLabel)}</span>
          </div>
          <span class="badge">${wItems.length} ${wItems.length === 1 ? "juego" : "juegos"}</span>
        </div>
        <div class="${mode === "list" ? "cal-list-wrap" : "poster-grid"}"></div>
        ${
          wItems.length > initialSlice
            ? `<div style="text-align:center;margin-top:12px;"><button class="btn btn-secondary btn-sm btn-more-win">Mostrar los ${wItems.length - initialSlice} restantes de ${esc(wLabel)}</button></div>`
            : ""
        }
      `;
      const body = block.querySelector(mode === "list" ? ".cal-list-wrap" : ".poster-grid");
      wItems
        .slice(0, initialSlice)
        .forEach((c) =>
          body.appendChild(mode === "list" ? renderCalendarListRow(c, todayIso) : renderCalendarCard(c, todayIso))
        );
      block.querySelector(".btn-more-win")?.addEventListener("click", (e) => {
        wItems
          .slice(initialSlice)
          .forEach((c) =>
            body.appendChild(mode === "list" ? renderCalendarListRow(c, todayIso) : renderCalendarCard(c, todayIso))
          );
        e.currentTarget.parentElement.remove();
      });
      container.appendChild(block);
    });
}

function renderCalendarMonth(items, todayIso) {
  const container = $("#cal-container");
  if (!container) return;
  container.innerHTML = "";

  const scrollWrap = document.createElement("div");
  scrollWrap.className = "cal-month-scroll";

  const head = document.createElement("div");
  head.className = "cal-weekdays";
  head.innerHTML = WEEKDAYS_SHORT.map((w) => `<div>${w}</div>`).join("");
  scrollWrap.appendChild(head);

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

    if (i === 35 && !inMonth && cellDate.getDate() <= 7) break;

    const cell = document.createElement("div");
    cell.className = [
      "cal-cell",
      inMonth ? "" : "outside",
      iso === todayIso ? "today" : "",
      dayGames.length ? "has-games" : "",
      state.calSelectedDay === iso ? "selected" : "",
    ]
      .filter(Boolean)
      .join(" ");

    cell.innerHTML = `
      <div class="cal-cell-top">
        <span class="cal-cell-day">${cellDate.getDate()}${iso === todayIso ? ' <span class="today-dot">HOY</span>' : ""}</span>
        ${dayGames.length ? `<span class="size-tag">${dayGames.length}</span>` : ""}
      </div>
      <div class="cal-thumbs">
        ${dayGames
          .slice(0, 3)
          .map(
            (g) => `
          <div class="cal-thumb-wrap ${g.favorited ? "fav" : ""}" title="${esc(g.title)}">
            <img src="${esc(g.poster_url || g.header_url || svgPlaceholder(g.title))}" data-fallbacks="${esc(g.header_url)}||${esc(svgPlaceholder(g.title))}" onerror="window.__imgFallback(this)" loading="lazy" alt="${esc(g.title)}" />
          </div>
        `
          )
          .join("")}
      </div>
      ${
        dayGames.length > 3
          ? `<div class="cal-cell-more">+${dayGames.length - 3} más</div>`
          : dayGames.length > 0
            ? `<div class="cal-cell-caption" title="${esc(dayGames[0].title)}">${esc(dayGames[0].title)}</div>`
            : ""
      }
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

  scrollWrap.appendChild(grid);
  container.appendChild(scrollWrap);

  const ym = `${state.calYear}-${String(state.calMonth + 1).padStart(2, "0")}`;
  const monthTba = items.filter((it) => it.precision === "month" && (it.release_date || "").startsWith(ym));
  if (monthTba.length) {
    const block = document.createElement("div");
    block.className = "cal-day-block";
    block.style.marginTop = "22px";
    block.innerHTML = `
      <div class="cal-day-header is-window">
        <div class="cal-day-title">
          <span class="day-chip tba">MES</span>
          <span>Confirmados para ${MONTHS_ES[state.calMonth]} ${state.calYear} (día por anunciar)</span>
        </div>
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
  if (!box) return;
  const heading = formatDayHeading(iso, todayIso);
  box.classList.remove("hidden");
  box.innerHTML = `
    <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:14px;gap:10px;flex-wrap:wrap;">
      <strong style="font-size:15.5px;">Lanzamientos del ${esc(heading.text)} (${dayGames.length})</strong>
      <button class="btn btn-secondary btn-sm" id="btn-close-daybox">${icon("x", 13)} Cerrar</button>
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
  if (!container) return;
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
      <div class="cal-week-head">
        <div>
          <div class="cal-week-dow">${WEEKDAYS_SHORT[i]}${iso === todayIso ? " · HOY" : ""}</div>
          <div class="cal-week-date">${d.getDate()} ${MONTHS_SHORT[d.getMonth()]}</div>
        </div>
        <span class="badge">${list.length}</span>
      </div>
      <div class="w-items"></div>
    `;
    const wWrap = col.querySelector(".w-items");
    if (!list.length) {
      wWrap.innerHTML = `<div class="cal-week-empty">Sin lanzamientos</div>`;
    } else {
      list.forEach((c) => {
        const row = document.createElement("div");
        row.className = "cal-week-item";
        row.innerHTML = `
          <img src="${esc(c.poster_url || c.header_url || svgPlaceholder(c.title))}" data-fallbacks="${esc(c.header_url)}||${esc(svgPlaceholder(c.title))}" onerror="window.__imgFallback(this)" loading="lazy" alt="${esc(c.title)}" />
          <div style="min-width:0;flex:1;">
            <div class="cal-week-name">${esc(c.title)}</div>
            <div class="plat-tags" style="margin-top:3px;">${renderPlatformBadges(c.platforms, 3)}</div>
          </div>
          <button class="bookmark-btn sm ${c.favorited ? "saved" : ""}" title="Seguir">
            ${icon(c.favorited ? "starFilled" : "star", 13)}
          </button>
        `;
        row.querySelector(".bookmark-btn").addEventListener("click", (e) => toggleCalendarFavorite(c, e));
        row.addEventListener("click", () => hooks.openDetailDrawer?.(calItemToDrawerItem(c)));
        wWrap.appendChild(row);
      });
    }
    grid.appendChild(col);
  }
  container.appendChild(grid);
}

export function bindCalendarEvents() {
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

  $("#btn-cal-recent")?.addEventListener("click", () => {
    state.calAgendaRange = "recent";
    renderCalendar();
  });

  $("#btn-cal-upcoming30")?.addEventListener("click", () => {
    state.calAgendaRange = "30d";
    renderCalendar();
  });

  $("#btn-cal-allupcoming")?.addEventListener("click", () => {
    state.calAgendaRange = "all";
    renderCalendar();
  });

  $("#btn-cal-prev")?.addEventListener("click", () => {
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

  $("#btn-cal-next")?.addEventListener("click", () => {
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

  $("#btn-cal-today")?.addEventListener("click", () => {
    const now = new Date();
    state.calYear = now.getFullYear();
    state.calMonth = now.getMonth();
    state.calWeekRef = now;
    if (state.calLayout === "agenda" || state.calLayout === "list") state.calAgendaRange = "30d";
    renderCalendar();
  });

  $("#cal-exact-only")?.addEventListener("change", (e) => {
    state.calExactOnly = e.target.checked;
    renderCalendar();
  });

  $("#cal-sort-select")?.addEventListener("change", (e) => {
    state.calSort = e.target.value;
    renderCalendar();
  });

  $("#cal-search-inline")?.addEventListener("input", (e) => {
    state.calInlineFilter = e.target.value;
    renderCalendar();
  });

  $("#btn-cal-export-ics")?.addEventListener("click", () => {
    const items = filteredCalendarItems();
    const fname =
      state.calMode === "favorites" ? "gamehub-siguiendo.ics" : "gamehub-lanzamientos.ics";
    exportGamesToIcs(items, fname);
  });

  $("#btn-cal-refresh")?.addEventListener("click", async () => {
    const btn = $("#btn-cal-refresh");
    btn.disabled = true;
    btn.innerHTML = `${icon("refresh", 14, "spin")} <span>Actualizando...</span>`;
    try {
      await loadCalendar(true);
      toast("Calendario multi-plataforma actualizado");
    } finally {
      btn.disabled = false;
      btn.innerHTML = `${icon("refresh", 14)} <span>Actualizar</span>`;
    }
  });

  $("#cal-track-form")?.addEventListener("submit", async (e) => {
    e.preventDefault();
    const input = $("#cal-track-input");
    const q = input.value.trim();
    if (!q) return;
    const btn = $("#btn-cal-track");
    btn.disabled = true;
    btn.innerHTML = `${icon("refresh", 13, "spin")} <span>Buscando...</span>`;
    try {
      const res = await api("/api/calendar/track", {
        method: "POST",
        body: { query: q, favorite: true },
      });
      const plats = (res.item.platforms || ["PC"]).join(" · ");
      toast(`Siguiendo «${res.item.title}» [${plats}] (${res.item.window_label})`);
      input.value = "";
      await loadCalendar(false);
    } catch (err) {
      toast(err.message, "err");
    } finally {
      btn.disabled = false;
      btn.innerHTML = `${icon("star", 13)} <span>Seguir</span>`;
    }
  });
}
