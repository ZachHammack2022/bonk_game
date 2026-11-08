// bonk admin: the server's numbers now and over time, from
// /api/admin/metrics (web.py), which needs the metrics token.
//
// The token is kept in sessionStorage (this tab only), or localStorage if
// you tick "Remember on this device", and only ever sent in the
// Authorization header to this same server.
"use strict";

(function () {
  const $ = (id) => document.getElementById(id);
  const KEY = "bonk-admin-token";
  const RANGE_KEY = "bonk-admin-range";
  const REFRESH_MS = 15000;
  const SVG = "http://www.w3.org/2000/svg";
  const RANGES = [
    [3600, "1h"], [6 * 3600, "6h"], [86400, "24h"],
    [7 * 86400, "7d"], [30 * 86400, "30d"], [90 * 86400, "90d"],
  ];

  // What's charted. gauge: drawn from "avg" or "max" of each stretch of
  // time. count: how many happened in each stretch (or a rate, per second).
  const CHARTS = [
    { title: "Players online", sub: "peak", gauge: "members_connected", pick: "max", fmt: "int" },
    { title: "Rooms", sub: "peak", gauge: "rooms", pick: "max", fmt: "int" },
    { title: "Matches running", sub: "peak", gauge: "matches_running", pick: "max", fmt: "int" },
    { title: "Matches started", count: "matches_started_total", fmt: "int" },
    { title: "Ping", sub: "median of everyone online", gauge: "ping_med_ms", pick: "avg", fmt: "ms" },
    { title: "Drawing delay", sub: "median of everyone in a match", gauge: "delay_med_ms", pick: "avg", fmt: "ms" },
    { title: "Stalls", sub: "per minute of play", gauge: "stalls_per_min", pick: "avg", fmt: "num" },
    { title: "Tick time p99", sub: "average, ms", gauge: "tick_ms_p99", pick: "avg", fmt: "ms" },
    { title: "Late ticks", sub: "rooms falling behind", count: "late_ticks_total", fmt: "int" },
    { title: "Sent on the wire", sub: "average", count: "wire_bytes_sent_total", rate: true, fmt: "bytes/s" },
    { title: "Browser errors", count: "client_errors_total", fmt: "int" },
  ];

  // Who comes back (metrics.Retention), per day. vals: from the report.
  const RET_CHARTS = [
    { title: "Players per day", sub: "joined a game", fmt: "int", daily: true,
      vals: (r) => r.daily.map((d) => d.active) },
    { title: "New players per day", sub: "first game ever", fmt: "int", daily: true,
      vals: (r) => r.daily.map((d) => d.new) },
    { title: "D1 retention", sub: "of that day's new players", fmt: "%", daily: true,
      vals: (r) => r.daily.map((d) => rate(cohortOf(r, d.day), "d1")) },
    { title: "From the home screen", sub: "players who opened the web app", fmt: "int", daily: true,
      vals: (r) => r.daily.map((d) => d.installed) },
  ];
  // Retention targets for a casual game (rough): below these is worth a look
  const TARGETS = { d1: 0.35, d7: 0.1, d30: 0.04 };
  function cohortOf(r, day) { return r.cohorts.find((c) => c.day === day); }
  function rate(c, mark) { return c && c.new && c[mark] != null ? c[mark] / c.new : null; }

  const store = {
    get(k) {
      try { return sessionStorage.getItem(k) || localStorage.getItem(k); } catch { return null; }
    },
    set(k, v, remember) {
      try { (remember ? localStorage : sessionStorage).setItem(k, v); } catch { /* private mode */ }
    },
    clear(k) {
      try { sessionStorage.removeItem(k); localStorage.removeItem(k); } catch { /* private mode */ }
    },
  };

  let token = store.get(KEY);
  let range = Number(store.get(RANGE_KEY)) || 86400;
  let data = null;
  let timer = null;
  let lastNow = null; // [time, snapshot], for the bytes-per-second tile

  // --- formatting -----------------------------------------------------------
  const nf = new Intl.NumberFormat();
  function fmt(v, kind) {
    if (v == null || Number.isNaN(v)) return "–";
    if (kind === "ms") return (v < 10 ? v.toFixed(2) : v.toFixed(1)) + " ms";
    if (kind === "bytes/s") return bytes(v) + "/s";
    if (kind === "bytes") return bytes(v);
    if (kind === "%") return (v * 100).toFixed(v < 0.1 ? 1 : 0) + "%";
    return nf.format(Math.round(v * 10) / 10);
  }
  function bytes(v) {
    const units = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (Math.abs(v) >= 1000 && i < units.length - 1) { v /= 1000; i++; }
    return (i && v < 10 ? v.toFixed(1) : Math.round(v)) + " " + units[i];
  }
  function short(v, kind) {
    if (kind === "bytes/s") return bytes(v);
    if (kind === "%") return Math.round(v * 100) + "%";
    if (kind === "ms") return v < 10 && v % 1 ? v.toFixed(1) : String(Math.round(v));
    if (v >= 1e6) return (v / 1e6).toFixed(v >= 1e7 ? 0 : 1) + "M";
    if (v >= 1e3) return (v / 1e3).toFixed(v >= 1e4 ? 0 : 1) + "k";
    return String(Math.round(v * 10) / 10);
  }
  function duration(s) {
    s = Math.round(s);
    if (s < 60) return s + " s";
    if (s < 3600) return Math.round(s / 60) + " min";
    if (s < 86400) return (s / 3600).toFixed(s < 36000 ? 1 : 0).replace(/\.0$/, "") + " h";
    return (s / 86400).toFixed(1).replace(/\.0$/, "") + " days";
  }
  function when(t, withDate) {
    const d = new Date(t * 1000);
    const time = d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    if (!withDate) return time;
    return d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + time;
  }
  function dayName(day) {  // a UTC day number
    return new Date(day * 86400e3).toLocaleDateString([], { month: "short", day: "numeric", timeZone: "UTC" });
  }
  function axisWhen(t, daily) {
    const d = new Date(t * 1000);
    if (daily) return dayName(t / 86400);
    if (range <= 86400) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    return d.toLocaleDateString([], { month: "short", day: "numeric" });
  }

  // --- talking to the server ----------------------------------------------
  async function load() {
    if (!token) return showLogin();
    let r;
    try {
      r = await fetch(`/api/admin/metrics?range=${range}`, {
        headers: { Authorization: `Bearer ${token}` }, cache: "no-store", credentials: "omit",
      });
    } catch {
      $("updated").textContent = "Can't reach the server. Trying again…";
      return schedule();
    }
    if (r.status === 401 || r.status === 429 || r.status === 503) {
      const text = r.status === 401 ? "That token wasn't right." : await r.text();
      store.clear(KEY);
      token = null;
      return showLogin(text);
    }
    if (!r.ok) {
      $("updated").textContent = `The server said ${r.status}. Trying again…`;
      return schedule();
    }
    data = await r.json();
    showDash();
    render();
    schedule();
  }
  function schedule() {
    clearTimeout(timer);
    timer = setTimeout(() => { if (!document.hidden) load(); else schedule(); }, REFRESH_MS);
  }
  document.addEventListener("visibilitychange", () => { if (!document.hidden && token) load(); });

  function showLogin(error) {
    clearTimeout(timer);
    $("dash").classList.add("hidden");
    $("sign-out").classList.add("hidden");
    $("about").textContent = "";
    $("login").classList.remove("hidden");
    $("login-error").textContent = error || "";
    $("token").focus();
  }
  function showDash() {
    $("login").classList.add("hidden");
    $("dash").classList.remove("hidden");
    $("sign-out").classList.remove("hidden");
  }

  $("login").addEventListener("submit", (e) => {
    e.preventDefault();
    token = $("token").value.trim();
    $("token").value = "";
    if (!token) return;
    store.set(KEY, token, $("remember").checked);
    $("login-error").textContent = "";
    load();
  });
  $("sign-out").addEventListener("click", () => {
    store.clear(KEY);
    token = null;
    data = null;
    lastNow = null;
    showLogin();
  });

  // --- the page -------------------------------------------------------------
  for (const [seconds, label] of RANGES) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.dataset.range = seconds;
    b.addEventListener("click", () => {
      range = seconds;
      store.set(RANGE_KEY, String(seconds), true);
      load();
    });
    $("ranges").appendChild(b);
  }

  function render() {
    const now = data.now;
    $("about").textContent = `version ${now.version} · up ${duration(now.uptime_seconds)}` +
      (now.draining ? " · restarting" : "");
    $("updated").textContent = `Updated ${new Date().toLocaleTimeString()} · every ${REFRESH_MS / 1000} s`;
    for (const b of $("ranges").children) b.setAttribute("aria-pressed", String(Number(b.dataset.range) === data.range));
    renderTiles(now);
    if (data.retention) renderRetention(data.retention);
    renderRegions(now.regions || {}, data.regions || []);
    const h = data.history;
    $("history-note").textContent = data.kept
      ? `Sampled every minute, kept ${data.keep_days} days. Gaps are when the server was stopped. Each point covers ${duration(h.step)}.`
      : "History isn't saved: set BONK_METRICS_DB to a file to keep it across restarts. Sampled every minute.";
    renderCharts(h);
    if ($("table-view").open) renderTable(h);
  }
  $("table-view").addEventListener("toggle", () => { if ($("table-view").open && data) renderTable(data.history); });

  function renderTiles(now) {
    const t = performance.now();
    let rate = null;
    if (lastNow && t > lastNow[0] && now.wire_bytes_sent_total >= lastNow[1].wire_bytes_sent_total) {
      rate = (now.wire_bytes_sent_total - lastNow[1].wire_bytes_sent_total) / ((t - lastNow[0]) / 1000);
    }
    lastNow = [t, now];
    const tiles = [
      ["Players online", fmt(now.members_connected)],
      ["Rooms", fmt(now.rooms), now.rooms_locked ? `${now.rooms_locked} locked` : ""],
      ["Matches running", fmt(now.matches_running)],
      ["Connections", fmt(now.connections)],
      ["Ping", now.ping_med_ms == null ? "–" : fmt(now.ping_med_ms, "ms"),
        now.ping_p95_ms == null ? "nobody's said yet" : `slow: ${fmt(now.ping_p95_ms, "ms")}`, now.ping_med_ms > 150],
      ["Stalls", now.stalls_per_min == null ? "–" : `${fmt(now.stalls_per_min)} / min`,
        now.delay_med_ms == null ? "nobody in a match" : `drawing ${fmt(now.delay_med_ms, "ms")} behind`, now.stalls_per_min > STALLING],
      ["Tick time p99", fmt(now.tick_ms_p99, "ms"), `avg ${fmt(now.tick_ms_avg, "ms")}`, now.tick_ms_p99 > 20],
      ["Sending", rate == null ? "–" : fmt(rate, "bytes/s"), rate == null ? "next update" : "on the wire"],
      ["Uptime", duration(now.uptime_seconds)],
    ];
    fillTiles($("tiles"), tiles);
    const totals = [
      ["matches started", now.matches_started_total], ["finished", now.matches_finished_total],
      ["rooms made", now.rooms_created_total], ["late ticks", now.late_ticks_total],
      ["sent", bytes(now.wire_bytes_sent_total)], ["browser errors", now.client_errors_total],
      ["player reports", now.player_reports_total], ["playtest reports", now.playtest_reports_total],
      ["old tabs refreshed", now.refused_old_clients_total],
    ];
    $("totals").textContent = "Since this restart: " +
      totals.map(([k, v]) => `${typeof v === "number" ? nf.format(v) : v} ${k}`).join(" · ");
  }

  function fillTiles(box, tiles) {
    box.textContent = "";
    for (const [label, value, note, warn] of tiles) {
      const el = document.createElement("div");
      el.className = "tile" + (warn ? " warn" : "");
      const l = document.createElement("div");
      l.className = "label";
      l.textContent = label;
      const v = document.createElement("div");
      v.className = "value";
      v.textContent = value;
      el.append(l, v);
      if (note) {
        const s = document.createElement("div");
        s.className = "note";
        s.textContent = note;
        el.appendChild(s);
      }
      box.appendChild(el);
    }
  }

  // --- where players are ---------------------------------------------------
  // Fly.io's region codes (the ones players are likeliest to come through)
  const REGION_NAMES = {
    iad: "Virginia, US", ewr: "New Jersey, US", ord: "Chicago, US", atl: "Atlanta, US", mia: "Miami, US",
    dfw: "Dallas, US", den: "Denver, US", lax: "Los Angeles, US", sjc: "San Jose, US", sea: "Seattle, US",
    yyz: "Toronto, CA", yul: "Montreal, CA", gdl: "Guadalajara, MX", qro: "Querétaro, MX",
    lhr: "London, UK", ams: "Amsterdam, NL", fra: "Frankfurt, DE", cdg: "Paris, FR", mad: "Madrid, ES",
    arn: "Stockholm, SE", waw: "Warsaw, PL", otp: "Bucharest, RO",
    sin: "Singapore", nrt: "Tokyo, JP", hkg: "Hong Kong", bom: "Mumbai, IN", syd: "Sydney, AU",
    gru: "São Paulo, BR", scl: "Santiago, CL", bog: "Bogotá, CO", eze: "Buenos Aires, AR", jnb: "Johannesburg, ZA",
    direct: "not through Fly",
  };
  const STALLING = 1;  // stalls a minute (metrics.STALLING_PER_MIN)
  function renderRegions(nowRegions, ranged) {
    const label = RANGES.find(([s]) => s === data.range);
    $("regions-range").textContent = `now, and over the last ${label ? label[1] : duration(data.range)}`;
    const byRegion = new Map(ranged.map((r) => [r.region, r]));
    for (const region of Object.keys(nowRegions)) if (!byRegion.has(region)) byRegion.set(region, { region });
    const rows = [...byRegion.values()].sort((a, b) =>
      ((nowRegions[b.region] || {}).players || 0) - ((nowRegions[a.region] || {}).players || 0)
      || (b.players_avg || 0) - (a.players_avg || 0));
    const table = $("regions");
    table.textContent = "";
    const head = table.createTHead().insertRow();
    for (const label of ["Region", "Online now", "Ping now", "Average online", "Peak", "Typical ping", "Slow ping", "Over 150 ms",
      "Drawing delay", "Stalls / min", "Stalling often"]) {
      const th = document.createElement("th");
      th.textContent = label;
      head.appendChild(th);
    }
    const body = table.createTBody();
    const ms = (v) => (v == null ? "–" : `${Math.round(v)} ms`);
    for (const r of rows) {
      const n = nowRegions[r.region] || {};
      const row = body.insertRow();
      const name = REGION_NAMES[r.region];
      row.insertCell().textContent = name ? `${r.region} · ${name}` : r.region;
      row.insertCell().textContent = n.players ? nf.format(n.players) : "–";
      row.insertCell().textContent = ms(n.med);
      row.insertCell().textContent = r.players_avg == null ? "–" : fmt(r.players_avg);
      row.insertCell().textContent = r.players_peak == null ? "–" : nf.format(r.players_peak);
      const typical = row.insertCell();
      typical.textContent = ms(r.med);
      if (r.med > 150) typical.className = "bad";
      row.insertCell().textContent = ms(r.p95);
      row.insertCell().textContent = r.slow_share == null ? "–" : fmt(r.slow_share, "%");
      row.insertCell().textContent = r.delay_med == null ? "–" : `${ms(r.delay_med)} (slow ${ms(r.delay_p95)})`;
      const st = row.insertCell();
      st.textContent = r.stalls_per_min == null ? "–" : fmt(r.stalls_per_min);
      if (r.stalls_per_min > STALLING) st.className = "bad";
      const often = row.insertCell();
      often.textContent = r.stalling_share == null ? "–" : fmt(r.stalling_share, "%");
      if (r.stalling_share > 0.1) often.className = "bad";
    }
    if (!rows.length) {
      const cell = body.insertRow().insertCell();
      cell.colSpan = 11;
      cell.textContent = "Nobody's been online in this range.";
    }
  }

  // --- retention ----------------------------------------------------------
  function renderRetention(r) {
    const tiles = [];
    for (const mark of ["d1", "d7", "d30"]) {
      const o = r.overall[mark];
      tiles.push([mark.toUpperCase() + " retention", o.rate == null ? "–" : fmt(o.rate, "%"),
        o.cohort ? `${nf.format(o.back)} of ${nf.format(o.cohort)} came back` : "no cohort old enough yet",
        o.rate != null && o.cohort >= 20 && o.rate < TARGETS[mark]]);
    }
    tiles.push(["Players today", fmt(r.dau)], ["This week", fmt(r.wau), "last 7 days"],
      ["This month", fmt(r.mau), "last 30 days"],
      ["From the home screen", fmt(r.installed_wau), "this week"]);
    fillTiles($("ret-tiles"), tiles);
    const h = { start: r.daily[0].day * 86400, step: 86400, t: r.daily.map((d) => d.day * 86400),
      restarts: [], gauges: {}, counts: {} };
    makeCards($("ret-chart"), RET_CHARTS);
    for (const c of RET_CHARTS) { c.data = c.vals(r); drawChart(c, h); }
    renderCohorts(r);
  }
  function renderCohorts(r) {
    const table = $("cohorts");
    table.textContent = "";
    const head = table.createTHead().insertRow();
    for (const label of ["First day", "New players", "D1", "D7", "D30"]) {
      const th = document.createElement("th");
      th.textContent = label;
      head.appendChild(th);
    }
    const body = table.createTBody();
    for (const c of r.cohorts) {
      if (!c.new) continue;
      const row = body.insertRow();
      row.insertCell().textContent = dayName(c.day);
      row.insertCell().textContent = nf.format(c.new);
      for (const mark of ["d1", "d7", "d30"]) {
        const cell = row.insertCell();
        cell.textContent = c[mark] == null ? "–" : `${fmt(c[mark] / c.new, "%")} (${c[mark]})`;
        if (c[mark] == null) cell.title = "Not that many days ago yet";
      }
    }
    if (!body.rows.length) {
      const cell = body.insertRow().insertCell();
      cell.colSpan = 5;
      cell.textContent = "Nobody's joined a game in the last 30 days yet.";
    }
  }

  // One chart's values, from the history
  function values(c, h) {
    if (c.data) return c.data;
    if (c.gauge) {
      const g = h.gauges[c.gauge];
      return g ? g[c.pick] : h.t.map(() => null);
    }
    const counts = h.counts[c.count] || h.t.map(() => null);
    return c.rate ? counts.map((v) => (v == null ? null : v / h.step)) : counts;
  }
  function subtitle(c, h) {
    if (c.count && !c.rate) return (c.sub ? c.sub + ", " : "") + `per ${duration(h.step)}`;
    return c.sub || "";
  }

  // --- charts (plain SVG) -------------------------------------------------
  function el(name, attrs, parent) {
    const e = document.createElementNS(SVG, name);
    for (const k in attrs) e.setAttribute(k, attrs[k]);
    if (parent) parent.appendChild(e);
    return e;
  }
  function niceMax(v) {
    if (!(v > 0)) return 1;
    const p = 10 ** Math.floor(Math.log10(v));
    for (const m of [1, 2, 2.5, 5, 10]) if (m * p >= v) return m * p;
    return 10 * p;
  }

  function renderCharts(h) {
    makeCards($("charts"), CHARTS);
    for (const c of CHARTS) drawChart(c, h);
  }
  function makeCards(box, charts) {
    if (box.children.length !== charts.length) {
      box.textContent = "";
      for (const c of charts) {
        const card = document.createElement("figure");
        card.className = "chart";
        card.innerHTML = '<div class="head"><div><h3></h3><div class="sub"></div></div><div class="latest"></div></div>';
        card.querySelector("h3").textContent = c.title;
        box.appendChild(card);
        c.card = card;
      }
    }
  }

  function drawChart(c, h) {
    const card = c.card;
    const vals = values(c, h);
    card.querySelector(".sub").textContent = subtitle(c, h);
    let last = null;
    for (let k = vals.length - 1; k >= 0; k--) if (vals[k] != null) { last = vals[k]; break; }
    card.querySelector(".latest").textContent = last == null ? "" : fmt(last, c.fmt);
    const old = card.querySelector("svg");
    if (old) old.remove();
    const tipOld = card.querySelector(".tip");
    if (tipOld) tipOld.remove();

    const W = Math.max(240, card.clientWidth - 24);
    const H = 150;
    const L = 38, R = 8, T = 8, B = 20;
    const svg = el("svg", { viewBox: `0 0 ${W} ${H}`, role: "img",
      "aria-label": `${c.title}${last == null ? "" : ": latest " + fmt(last, c.fmt)}` });
    card.appendChild(svg);
    const n = vals.length;
    const max = niceMax(Math.max(0, ...vals.filter((v) => v != null)));
    const x = (k) => L + (n <= 1 ? 0 : (k / (n - 1)) * (W - L - R));
    const y = (v) => T + (1 - v / max) * (H - T - B);

    // Grid and axes
    for (const f of [0, 0.5, 1]) {
      const gy = y(max * f);
      el("line", { class: "grid", x1: L, x2: W - R, y1: gy, y2: gy }, svg);
      el("text", { class: "axis-text", x: L - 6, y: gy + 3.5, "text-anchor": "end" }, svg).textContent = short(max * f, c.fmt);
    }
    for (const f of [0, 0.5, 1]) {
      const k = Math.round(f * (n - 1));
      const t = h.t[k] + (f === 1 ? h.step : 0);
      el("text", { class: "axis-text", x: x(k), y: H - 4, "text-anchor": f === 0 ? "start" : f === 1 ? "end" : "middle" }, svg)
        .textContent = axisWhen(c.daily ? h.t[k] : t, c.daily);
    }
    // Restarts and deploys
    const tx = (t) => x((t - h.start) / h.step - 0.5);
    for (const t of h.restarts) {
      const m = el("line", { class: "marker", x1: tx(t), x2: tx(t), y1: T, y2: H - B }, svg);
      el("title", {}, m).textContent = `Restarted ${when(t, true)}`;
    }

    if (!vals.some((v) => v != null)) {
      el("text", { class: "empty", x: (L + W - R) / 2, y: (T + H - B) / 2, "text-anchor": "middle" }, svg)
        .textContent = "No samples in this range yet";
      return;
    }

    // The line (broken where the server was stopped) and the area under it
    let line = "", area = "";
    let run = [];
    const flush = () => {
      if (run.length === 1) {
        const [k, v] = run[0];
        el("circle", { class: "dot", cx: x(k), cy: y(v), r: 2.5 }, svg);
      } else if (run.length > 1) {
        const pts = run.map(([k, v]) => `${x(k).toFixed(1)},${y(v).toFixed(1)}`);
        line += "M" + pts.join("L");
        area += `M${x(run[0][0]).toFixed(1)},${y(0)}L${pts.join("L")}L${x(run[run.length - 1][0]).toFixed(1)},${y(0)}Z`;
      }
      run = [];
    };
    vals.forEach((v, k) => { if (v == null) flush(); else run.push([k, v]); });
    flush();
    if (area) el("path", { class: "area", d: area }, svg);
    if (line) el("path", { class: "line", d: line }, svg);

    // Hover: a crosshair and a tooltip for the nearest point
    const cross = el("line", { class: "cross hidden", y1: T, y2: H - B }, svg);
    const dot = el("circle", { class: "hover-dot hidden", r: 4 }, svg);
    const tip = document.createElement("div");
    tip.className = "tip hidden";
    card.appendChild(tip);
    const hit = el("rect", { x: L, y: 0, width: W - L - R, height: H, fill: "transparent" }, svg);
    const move = (e) => {
      const box = svg.getBoundingClientRect();
      const px = ((e.clientX - box.left) / box.width) * W;
      const k = Math.max(0, Math.min(n - 1, Math.round(((px - L) / (W - L - R)) * (n - 1))));
      const v = vals[k];
      cross.setAttribute("x1", x(k));
      cross.setAttribute("x2", x(k));
      cross.classList.remove("hidden");
      if (v != null) {
        dot.setAttribute("cx", x(k));
        dot.setAttribute("cy", y(v));
        dot.classList.remove("hidden");
      } else dot.classList.add("hidden");
      tip.textContent = "";
      const b = document.createElement("b");
      let text = v == null ? (c.daily ? "–" : "No samples (server stopped)") : fmt(v, c.fmt);
      if (v != null && c.gauge) {
        const g = h.gauges[c.gauge];
        const other = c.pick === "max" ? "avg" : "max";
        text += ` · ${other === "max" ? "peak" : "avg"} ${fmt(g[other][k], c.fmt)}`;
      }
      b.textContent = text;
      const s = document.createElement("span");
      s.className = "dim";
      s.textContent = c.daily ? dayName(h.t[k] / 86400) : h.step > 60
        ? `${when(h.t[k], range > 86400)} – ${when(h.t[k] + h.step, false)}`
        : when(h.t[k], range > 86400);
      tip.append(b, s);
      tip.classList.remove("hidden");
      const left = 12 + (x(k) / W) * box.width;
      const half = tip.offsetWidth / 2;
      tip.style.left = Math.max(4, Math.min(card.clientWidth - tip.offsetWidth - 4, left - half)) + "px";
      tip.style.top = box.top - card.getBoundingClientRect().top - 2 + "px";
    };
    const leave = () => { cross.classList.add("hidden"); dot.classList.add("hidden"); tip.classList.add("hidden"); };
    hit.addEventListener("pointermove", move);
    hit.addEventListener("pointerdown", move);
    hit.addEventListener("pointerleave", leave);
  }

  function renderTable(h) {
    const table = $("table");
    table.textContent = "";
    const head = table.createTHead().insertRow();
    for (const label of ["Time", ...CHARTS.map((c) => c.title + (subtitle(c, h) ? ` (${subtitle(c, h)})` : ""))]) {
      const th = document.createElement("th");
      th.textContent = label;
      head.appendChild(th);
    }
    const cols = CHARTS.map((c) => values(c, h));
    const body = table.createTBody();
    for (let k = h.t.length - 1; k >= 0; k--) {
      if (cols.every((col) => col[k] == null)) continue;
      const row = body.insertRow();
      row.insertCell().textContent = when(h.t[k], true);
      CHARTS.forEach((c, j) => { row.insertCell().textContent = fmt(cols[j][k], c.fmt); });
    }
  }

  let resizeTimer = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (!data) return;
      renderCharts(data.history);
      if (data.retention) renderRetention(data.retention);
    }, 150);
  });

  if (token) load(); else showLogin();
})();
