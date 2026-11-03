// bonk web client: The lobby: seats, the host's settings, teams, and picking your ball's colour and pattern.
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

// ---------------------------------------------------------------------------
// Lobby
// ---------------------------------------------------------------------------
function fillMapOptions() {
  const sel = $("map");
  sel.innerHTML = "";
  for (const m of app.welcome.maps) {
    const o = document.createElement("option");
    o.value = m.name;
    o.textContent = m.title;
    sel.appendChild(o);
  }
  fillSelect($("mode"), app.welcome.modes.map((m) => [m.id, m.title]));
  fillSelect($("gravity"), app.welcome.gravities.map((g) => [g, g[0].toUpperCase() + g.slice(1)]));
}

function fillSelect(sel, pairs) {
  const key = JSON.stringify(pairs);
  if (sel.dataset.key === key) return;
  sel.dataset.key = key;
  sel.innerHTML = "";
  for (const [value, label] of pairs) {
    const o = document.createElement("option");
    o.value = value;
    o.textContent = label;
    sel.appendChild(o);
  }
}

const roundTimeLabel = (t, map) => (t === null ? (map && map.round_time ? `${map.round_time}s (map)` : "Map's") : t === 0 ? "Off" : `${t}s`);
const modeInfo = (id) => app.welcome.modes.find((m) => m.id === id);

function botLabel(kind) {
  if (kind.startsWith("bot:")) return kind.slice(4)[0].toUpperCase() + kind.slice(5) + " bot";
  return kind.toUpperCase() + " agent";
}

const picker = { open: false };

function renderLobby() {
  const L = app.lobby, Wm = app.welcome;
  if (!Wm) return;
  $("room-code").textContent = L.room;
  const host = isHost();
  const s = L.settings;

  // Mode, map and the other settings
  const mode = modeInfo(s.mode);
  $("mode").value = s.mode;
  $("mode").disabled = !host;
  $("mode-desc").textContent = mode.description;
  for (const o of $("map").options) {
    const m = Wm.maps.find((x) => x.name === o.value);
    o.disabled = mode.respawns && !m.respawn_ok;
    o.textContent = m.title + (o.disabled ? " (not for this mode)" : "");
  }
  $("map").value = s.map;
  $("map").disabled = !host;
  const mapInfo = Wm.maps.find((m) => m.name === s.map);
  $("map-desc").textContent = mapInfo ? mapInfo.description : "";
  $("goal-label").textContent = mode.goal_label;
  const goals = mode.goal_choices.includes(s.first_to) ? mode.goal_choices : [...mode.goal_choices, s.first_to].sort((a, b) => a - b);
  fillSelect($("first-to"), goals.map((n) => [n, String(n)]));
  $("first-to").value = s.first_to;
  $("first-to").disabled = !host;
  $("round-time-box").classList.toggle("hidden", !mode.round_time);
  fillSelect($("round-time"), Wm.round_times.map((t) => [JSON.stringify(t), roundTimeLabel(t, mapInfo)]));
  $("round-time").value = JSON.stringify(s.round_time);
  $("round-time").disabled = !host;
  $("gravity").value = s.gravity;
  $("gravity").disabled = !host;
  $("power-ups").checked = !!s.power_ups;
  $("power-ups").disabled = !host;
  const teams = s.mode === "teams";
  const mine = L.seats.find((x) => x.id === me.token);
  $("switch-team").classList.toggle("hidden", !teams || !mine);
  if (teams && mine) $("switch-team").textContent = `Switch to ${Wm.team_names[1 - mine.team]}`;

  // Seats, in match order, as the server says they'd be right now
  const ul = $("seats");
  ul.innerHTML = "";
  const order = teams ? [...L.seats].sort((a, b) => a.team - b.team) : L.seats;
  let lastTeam = null;
  for (const seatInfo of order) {
    if (teams && seatInfo.team !== lastTeam) {
      lastTeam = seatInfo.team;
      const head = document.createElement("li");
      head.className = "team-head";
      head.style.color = Wm.team_colors[lastTeam];
      head.textContent = Wm.team_names[lastTeam];
      ul.appendChild(head);
    }
    if (seatInfo.kind === "human") {
      const you = seatInfo.id === me.token;
      const li = seat(seatInfo.color, seatInfo.name + (seatInfo.id === L.host ? "  ★" : ""), you ? "you" : "", you, seatInfo.pattern);
      if (you) {
        const ball = li.querySelector(".ball");
        ball.classList.add("pick");
        ball.title = "Pick your colour";
        ball.setAttribute("role", "button");
        ball.tabIndex = 0;
        const toggle = () => { picker.open = !picker.open; renderLobby(); };
        ball.addEventListener("click", toggle);
        ball.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
      } else if (host) {
        li.appendChild(removeButton("Remove from room", () => {
          if (confirm(`Remove ${seatInfo.name} from the room?`)) send({ type: "kick", id: seatInfo.id });
        }));
      }
      ul.appendChild(li);
      if (you && picker.open) ul.appendChild(colorPicker(seatInfo.color));
    } else {
      const b = seatInfo.bot;
      const li = seat(seatInfo.color, botLabel(seatInfo.kind), "", false);
      if (host) {
        const sel = document.createElement("select");
        sel.setAttribute("aria-label", "Bot type");
        for (const opt of L.bot_options) {
          const o = document.createElement("option");
          o.value = opt; o.textContent = botLabel(opt);
          sel.appendChild(o);
        }
        sel.value = seatInfo.kind;
        sel.addEventListener("change", () => {
          const next = s.bots.slice(); next[b] = sel.value;
          send({ type: "settings", bots: next });
        });
        li.querySelector(".who").textContent = "";
        li.insertBefore(sel, li.querySelector(".tag"));
        li.appendChild(removeButton("Remove bot", () => {
          const next = s.bots.slice(); next.splice(b, 1);
          send({ type: "settings", bots: next });
        }));
      }
      ul.appendChild(li);
    }
  }
  for (const m of L.members.filter((m) => !m.connected)) {
    const li = seat(null, m.name, "reconnecting…", false);
    li.classList.add("away");
    ul.appendChild(li);
  }
  const n = L.seats.length;
  $("seat-count").textContent = `${n} / ${Wm.max_players}`;
  $("add-bot").disabled = n >= Wm.max_players;
  const extra = L.members.filter((m) => m.connected).length - Wm.max_players;
  $("spectators").textContent = extra > 0 ? `${extra} more watching (the match is full).` : "";
  $("start").disabled = n < 2;

  // Rematch votes on the results screen
  if (L.phase === "results") {
    const here = L.members.filter((m) => m.connected).length;
    const voted = L.votes.includes(me.token);
    $("vote").textContent = voted ? `Waiting for others… ${L.votes.length}/${here}` : `Play again  ${L.votes.length}/${here}`;
    $("vote").classList.toggle("primary", !voted);
  }

  // Joined during a match: watch it
  if (L.phase === "match" && !app.match) status("A match is on. You'll play in the next one.");
}

function removeButton(title, onClick) {
  const rm = document.createElement("button");
  rm.className = "remove"; rm.textContent = "✕"; rm.title = title;
  rm.setAttribute("aria-label", title);
  rm.addEventListener("click", onClick);
  return rm;
}

function colorPicker(current) {
  const li = document.createElement("li");
  li.className = "picker";
  const taken = new Set(app.lobby.seats.filter((x) => x.kind === "human" && x.id !== me.token).map((x) => x.color));
  // In teams, each side has its own colours
  const mine = app.lobby.seats.find((x) => x.id === me.token);
  const allowed = mine && mine.team !== null && mine.team !== undefined ? new Set(app.welcome.team_palettes[mine.team]) : null;
  app.welcome.colors.forEach((c, i) => {
    const b = document.createElement("button");
    b.className = "swatch" + (i === current ? " on" : "");
    b.style.background = c;
    b.title = app.welcome.color_names[i];
    b.setAttribute("aria-label", app.welcome.color_names[i]);
    b.disabled = taken.has(i) || (allowed !== null && !allowed.has(i));
    b.addEventListener("click", () => {
      me.color = i; saveProfile();
      send({ type: "color", color: i });
    });
    li.appendChild(b);
  });
  li.appendChild(patternRow(mine ? mine.pattern : me.pattern, mine ? app.welcome.colors[mine.color] : T.faint, (p) => {
    me.pattern = p; saveProfile();
    send({ type: "pattern", pattern: p });
  }));
  return li;
}

// A row of buttons, one per pattern, drawn on a ball of `color`
function patternRow(current, color, onPick) {
  const row = document.createElement("div");
  row.className = "patterns";
  for (const p of PATTERNS) {
    const b = document.createElement("button");
    b.className = "pattern" + (p === current ? " on" : "");
    b.title = PATTERN_NAMES[p];
    b.setAttribute("aria-label", PATTERN_NAMES[p]);
    b.dataset.pattern = p;
    b.appendChild(ballCanvas(30, color, p));
    b.addEventListener("click", () => onPick(p));
    row.appendChild(b);
  }
  return row;
}

// A little canvas with a ball on it (lobby seats, pickers)
function ballCanvas(size, color, pattern) {
  const c = document.createElement("canvas");
  const dpr = window.devicePixelRatio || 1;
  c.width = c.height = Math.round(size * dpr);
  c.style.width = c.style.height = size + "px";
  c.className = "ball-canvas";
  const g = c.getContext("2d");
  g.scale(dpr, dpr);
  drawBall(g, size / 2, size / 2, size / 2, 0, color, pattern, false);
  return c;
}

// Home screen: your ball, and the editor for it
function renderHomeBall() {
  const color = me.color === null ? PALETTE[0][1] : PALETTE[me.color][1];
  const el = $("home-ball");
  el.innerHTML = "";
  el.appendChild(ballCanvas(40, color, me.pattern));
  $("home-ball-label").textContent = `${me.color === null ? "Any colour" : PALETTE[me.color][0]}, ${PATTERN_NAMES[me.pattern].toLowerCase()}`;
}
function renderProfileEditor() {
  const box = $("profile-colors");
  box.innerHTML = "";
  const any = document.createElement("button");
  any.className = "swatch any" + (me.color === null ? " on" : "");
  any.title = "Any colour"; any.textContent = "?";
  any.setAttribute("aria-label", "Any colour");
  any.addEventListener("click", () => { me.color = null; saveProfile(); renderProfileEditor(); });
  box.appendChild(any);
  PALETTE.forEach(([name, hex], i) => {
    const b = document.createElement("button");
    b.className = "swatch" + (i === me.color ? " on" : "");
    b.style.background = hex;
    b.title = name;
    b.setAttribute("aria-label", name);
    b.addEventListener("click", () => { me.color = i; saveProfile(); renderProfileEditor(); });
    box.appendChild(b);
  });
  const pat = $("profile-patterns");
  pat.innerHTML = "";
  pat.appendChild(patternRow(me.pattern, me.color === null ? PALETTE[0][1] : PALETTE[me.color][1], (p) => {
    me.pattern = p; saveProfile(); renderProfileEditor();
  }));
  $("profile-preview").innerHTML = "";
  $("profile-preview").appendChild(ballCanvas(72, me.color === null ? PALETTE[0][1] : PALETTE[me.color][1], me.pattern));
}
$("edit-ball").addEventListener("click", () => { renderProfileEditor(); $("profile").classList.remove("hidden"); });
$("profile-close").addEventListener("click", () => $("profile").classList.add("hidden"));
$("profile").addEventListener("click", (e) => { if (e.target === $("profile")) $("profile").classList.add("hidden"); });

function seat(color, label, tag, you, pattern = "plain") {
  const li = document.createElement("li");
  li.className = "seat" + (you ? " you" : "");
  const ball = ballCanvas(22, color === null ? T.faint : app.welcome.colors[color], pattern);
  ball.classList.add("ball");
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = label;
  const t = document.createElement("span");
  t.className = "tag";
  t.textContent = tag;
  li.append(ball, who, t);
  return li;
}

$("map").addEventListener("change", () => send({ type: "settings", map: $("map").value }));
$("first-to").addEventListener("change", () => send({ type: "settings", first_to: +$("first-to").value }));
$("mode").addEventListener("change", () => send({ type: "settings", mode: $("mode").value }));
$("round-time").addEventListener("change", () => send({ type: "settings", round_time: JSON.parse($("round-time").value) }));
$("gravity").addEventListener("change", () => send({ type: "settings", gravity: $("gravity").value }));
$("power-ups").addEventListener("change", () => send({ type: "settings", power_ups: $("power-ups").checked }));
$("switch-team").addEventListener("click", () => {
  const mine = app.lobby.seats.find((x) => x.id === me.token);
  if (mine) send({ type: "team", team: 1 - mine.team });
});
$("add-bot").addEventListener("click", () => send({ type: "settings", bots: [...app.lobby.settings.bots, "bot:medium"] }));
$("start").addEventListener("click", () => send({ type: "start" }));
$("again").addEventListener("click", () => send({ type: "start" }));
$("vote").addEventListener("click", () => send({ type: "vote" }));
$("to-lobby").addEventListener("click", () => send({ type: "lobby" }));
$("copy-link").addEventListener("click", async () => {
  const link = `${location.origin}/r/${app.room}`;
  try {
    await navigator.clipboard.writeText(link);
    toast("Invite link copied");
  } catch (e) {
    toast(link);
  }
});
