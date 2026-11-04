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
  const here = L.members.filter((m) => m.connected).length;
  for (const o of $("map").options) {
    const m = Wm.maps.find((x) => x.name === o.value);
    const wrongMode = mode.respawns && !m.respawn_ok;
    const tooMany = here > m.players[1];
    o.disabled = (wrongMode || tooMany) && o.value !== s.map;
    o.textContent = `${m.title}  (${m.players[0]}–${m.players[1]})` + (wrongMode ? " · not for this mode" : tooMany ? " · too many here" : "");
  }
  $("map").value = s.map;
  $("map").disabled = !host;
  const mapInfo = Wm.maps.find((m) => m.name === s.map);
  $("map-desc").textContent = mapInfo ? `${mapInfo.description} For ${mapInfo.players[0]}–${mapInfo.players[1]} players.` : "";
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
      const li = seat(seatInfo.color, seatInfo.name + (seatInfo.id === L.host ? "  ★" : ""), you ? "you" : "", you, seatInfo.pattern,
                      seatInfo.own_color, seatInfo.hat);
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
      if (you && picker.open) ul.appendChild(colorPicker(seatInfo.color, seatInfo.own_color));
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
  // The map says how many can play
  const n = L.seats.length;
  const [fewest, most] = mapInfo ? mapInfo.players : [2, Wm.max_players];
  $("seat-count").textContent = `${n} / ${most}`;
  $("add-bot").disabled = n >= most;
  const extra = here - most;
  $("spectators").textContent = extra > 0 ? `${extra} more watching (the match is full).` : "";
  // Too few to start: say so next to the button, and offer the bots it'd take
  const short = Math.max(0, fewest - n);
  $("start").disabled = short > 0;
  $("start").textContent = short ? `Need ${short} more player${short === 1 ? "" : "s"}` : "Start match";
  $("need-players").classList.toggle("hidden", !short);
  if (short) {
    const title = mapInfo ? mapInfo.title : "This map";
    $("need-text").textContent = `${title} needs at least ${fewest} players, and there ${n === 1 ? "is" : "are"} ${n}. ` +
      (host ? "Add bots or invite friends (Copy invite link) to start, or pick another map."
            : "Waiting for the host to add bots or pick another map.");
    $("add-needed").textContent = short === 1 ? "+ Add a bot" : `+ Add ${short} bots`;
    $("add-needed").dataset.short = String(short);
  }

  // Rematch votes on the results screen
  if (L.phase === "results") {
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

function colorPicker(current, own) {
  const li = document.createElement("li");
  li.className = "picker";
  const taken = new Set(app.lobby.seats.filter((x) => x.kind === "human" && x.id !== me.token).map((x) => x.color));
  // In teams, each side has its own colours
  const mine = app.lobby.seats.find((x) => x.id === me.token);
  const allowed = mine && mine.team !== null && mine.team !== undefined ? new Set(app.welcome.team_palettes[mine.team]) : null;
  app.welcome.colors.forEach((c, i) => {
    const b = document.createElement("button");
    b.className = "swatch" + (i === current && !own ? " on" : "");
    b.style.background = c;
    b.title = app.welcome.color_names[i];
    b.setAttribute("aria-label", app.welcome.color_names[i]);
    b.disabled = taken.has(i) || (allowed !== null && !allowed.has(i));
    b.addEventListener("click", () => {
      me.color = i;
      if (me.ownColor) { me.ownColor = null; send({ type: "own_color", color: null }); }
      saveProfile();
      send({ type: "color", color: i });
    });
    li.appendChild(b);
  });
  // Any colour (signed in; not in teams, where colours show your side)
  if (allowed === null) {
    li.appendChild(ownColorButton(own || me.ownColor, (hex) => {
      me.ownColor = hex; saveProfile();
      send({ type: "own_color", color: hex });
    }));
    if (me.ownColor && !own) {
      const note = document.createElement("p");
      note.className = "dim small own-note";
      note.textContent = "Your colour is too close to someone else's here, so you have a palette colour this time.";
      li.appendChild(note);
    }
  }
  const ballColor = own || (mine ? app.welcome.colors[mine.color] : T.faint);
  for (const kind of looks.KINDS) {
    const current = mine && mine[kind] ? mine[kind] : me.look(kind);
    if (kind !== "pattern") {
      const label = document.createElement("p");
      label.className = "dim small look-label";
      label.textContent = looks.LABELS[kind];
      li.appendChild(label);
    }
    li.appendChild(lookRow(kind, current, ballColor, mine ? mine.pattern : me.pattern, (id) => {
      me.setLook(kind, id); saveProfile();
      send({ type: "look", [kind]: id });
    }));
  }
  return li;
}

// The "any colour" swatch: a colour picker when signed in, a lock (and how
// to get it) for guests. onPick(hex) when a colour is picked.
function ownColorButton(current, onPick) {
  const wrap = document.createElement("label");
  wrap.className = "swatch own" + (current ? " on" : "") + (profileStore.user ? "" : " locked");
  wrap.title = profileStore.user ? "Any colour" : "Any colour: sign in to unlock";
  if (current) wrap.style.background = current;
  else wrap.textContent = profileStore.user ? "🎨" : "🔒";
  if (!profileStore.user) {
    wrap.setAttribute("role", "button");
    wrap.addEventListener("click", () => toast("Sign in (on the home page) to pick any colour you like."));
    return wrap;
  }
  const input = document.createElement("input");
  input.type = "color";
  input.value = current || "#ff8800";
  input.setAttribute("aria-label", "Any colour");
  input.addEventListener("change", () => onPick(input.value.toLowerCase()));
  wrap.appendChild(input);
  return wrap;
}

// A little canvas with a ball on it (lobby seats, pickers), with its hat
function ballCanvas(size, color, pattern, hat = "none") {
  const c = document.createElement("canvas");
  const dpr = window.devicePixelRatio || 1;
  c.width = c.height = Math.round(size * dpr);
  c.style.width = c.style.height = size + "px";
  c.className = "ball-canvas";
  const g = c.getContext("2d");
  g.scale(dpr, dpr);
  if (hat && hat !== "none") drawBall(g, size / 2, size * 0.62, size * 0.36, 0, color, pattern, false, hat);
  else drawBall(g, size / 2, size / 2, size / 2, 0, color, pattern, false);
  return c;
}

// Home screen: your ball, and the editor for it
function renderHomeBall() {
  const el = $("home-ball");
  el.innerHTML = "";
  el.appendChild(ballCanvas(40, me.ballHex, me.pattern, me.look("hat")));
  const name = me.ownColor ? "Your own colour" : me.color === null ? "Any colour" : PALETTE[me.color][0];
  const extras = ["trail", "hat"].filter((k) => me.look(k) !== "none").map((k) => looks.name(k, me.look(k)).toLowerCase());
  $("home-ball-label").textContent = [name, looks.name("pattern", me.pattern).toLowerCase(), ...extras].join(", ");
}
function renderProfileEditor() {
  const box = $("profile-colors");
  box.innerHTML = "";
  const any = document.createElement("button");
  any.className = "swatch any" + (me.color === null && !me.ownColor ? " on" : "");
  any.title = "Any colour"; any.textContent = "?";
  any.setAttribute("aria-label", "Any colour");
  any.addEventListener("click", () => { me.color = null; if (me.ownColor) me.ownColor = null; saveProfile(); renderProfileEditor(); });
  box.appendChild(any);
  PALETTE.forEach(([name, hex], i) => {
    const b = document.createElement("button");
    b.className = "swatch" + (i === me.color && !me.ownColor ? " on" : "");
    b.style.background = hex;
    b.title = name;
    b.setAttribute("aria-label", name);
    b.addEventListener("click", () => { me.color = i; if (me.ownColor) me.ownColor = null; saveProfile(); renderProfileEditor(); });
    box.appendChild(b);
  });
  box.appendChild(ownColorButton(me.ownColor, (hex) => { me.ownColor = hex; saveProfile(); renderProfileEditor(); }));
  const pat = $("profile-patterns");
  pat.innerHTML = "";
  const pick = (kind) => (id) => { me.setLook(kind, id); saveProfile(); renderProfileEditor(); };
  pat.appendChild(lookRow("pattern", me.pattern, me.ballHex, me.pattern, pick("pattern")));
  const extras = $("profile-extras");
  extras.innerHTML = "";
  for (const kind of ["trail", "hat", "ko"]) {
    const label = document.createElement("label");
    label.textContent = looks.LABELS[kind];
    extras.append(label, lookRow(kind, me.look(kind), me.ballHex, me.pattern, pick(kind)));
  }
  $("profile-unlock").textContent = !looks.catalog ? ""
    : profileStore.user ? "More unlock as you play: tap a 🔒 to see how."
    : "Sign in (on the home page) to unlock more as you play.";
  $("profile-preview").innerHTML = "";
  $("profile-preview").appendChild(ballCanvas(72, me.ballHex, me.pattern, me.look("hat")));
}
$("edit-ball").addEventListener("click", () => { renderProfileEditor(); $("profile").classList.remove("hidden"); });
$("profile-close").addEventListener("click", () => $("profile").classList.add("hidden"));
$("profile").addEventListener("click", (e) => { if (e.target === $("profile")) $("profile").classList.add("hidden"); });

function seat(color, label, tag, you, pattern = "plain", own = null, hat = "none") {
  const li = document.createElement("li");
  li.className = "seat" + (you ? " you" : "");
  const ball = ballCanvas(22, own || (color === null ? T.faint : app.welcome.colors[color]), pattern, hat);
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
$("add-needed").addEventListener("click", (e) => {
  const short = +e.target.dataset.short || 1;
  send({ type: "settings", bots: [...app.lobby.settings.bots, ...Array(short).fill("bot:medium")] });
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
