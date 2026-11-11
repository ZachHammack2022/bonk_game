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
  fillSelect($("speed"), (app.welcome.speeds || ["normal"]).map((g) => [g, g[0].toUpperCase() + g.slice(1)]));
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


function renderLobby() {
  const L = app.lobby, Wm = app.welcome;
  if (!Wm) return;
  $("room-code").textContent = L.room;
  const host = isHost();
  const s = L.settings;

  // The room: its name (the host edits it in place), public or private, and
  // a private room's password (everyone in the room sees it, to invite people)
  const nameBox = $("room-name-input");
  if (document.activeElement !== nameBox) nameBox.value = L.title || "";
  nameBox.size = Math.max(6, nameBox.value.length + 1);  // (as wide as the name, where CSS can't say)
  nameBox.readOnly = !host;
  nameBox.title = host ? "Rename the room" : "";
  for (const b of $("privacy").querySelectorAll("button")) {
    const on = (b.dataset.private === "1") === !!s.password;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", String(on));
    b.disabled = !host;
    b.classList.toggle("hidden", !host && !on);  // (guests just see which it is)
  }
  // A private room's password: made up by the server, shown to everyone in
  // the room (to invite people), changed by switching to public and back
  $("password-row").classList.toggle("hidden", !s.password);
  $("room-password").textContent = s.password || "";

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
  drawMapPreview($("map-preview"), mapInfo);
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
  $("speed").value = s.speed || "normal";
  $("speed").disabled = !host;
  $("power-ups").checked = !!s.power_ups;
  $("power-ups").disabled = !host;
  drawPowerKinds(Wm.power_kinds || [], s, host);
  $("game-settings-done").textContent = host ? "Done" : "Close";
  $("game-settings-title").textContent = host ? "Game settings" : "Game settings (the host picks them)";

  // The panel: the map, the mode, and the rest in a line. All of it is in
  // the Game settings dialog
  $("sum-map").textContent = mapInfo ? mapInfo.title : s.map;
  $("sum-mode").textContent = mode.title;
  const goalChoice = $("first-to").selectedOptions[0];
  const rest = [`${mode.goal_label} ${goalChoice ? goalChoice.textContent : s.first_to}`];
  if (mode.round_time) rest.push(`Round time ${roundTimeLabel(s.round_time, mapInfo)}`);
  if (s.gravity !== "normal") rest.push(`${s.gravity[0].toUpperCase() + s.gravity.slice(1)} gravity`);
  if ((s.speed || "normal") !== "normal") rest.push(`${s.speed[0].toUpperCase() + s.speed.slice(1)} speed`);
  // (Power-ups on or off is the checkbox; this says which, when not all)
  const power = powerSummary(Wm.power_kinds || [], s);
  if (s.power_ups && power !== "Power-ups on") rest.push(power);
  $("sum-rest").textContent = rest.join(" · ");
  $("open-game-settings-text").textContent = "All settings";

  // The quick controls on the panel: copies of the dialog's map, mode and
  // power-ups, kept in step with them
  for (const id of ["map", "mode"]) mirrorSelect($(id), $(`quick-${id}`));
  $("quick-power-ups").checked = !!s.power_ups;
  $("quick-power-ups").disabled = !host;
  const teams = s.mode === "teams";
  const mine = L.seats.find((x) => x.id === me.id);
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
      const you = seatInfo.id === me.id;
      const tag = [you && "you", seatInfo.id === L.host && "host"].filter(Boolean).join(" · ");
      const li = seat(seatInfo.color, shownName(seatInfo.id, seatInfo.name), tag, you,
                      seatInfo.pattern, seatInfo.own_color, seatInfo.hat);
      // Signed-in players' rank badge (rating.js)
      const member = L.members.find((x) => x.id === seatInfo.id);
      if (member && member.rating) li.querySelector(".tag").prepend(rankBadge(member.rating));
      if (you) {
        const ball = li.querySelector(".ball");
        ball.classList.add("pick");
        ball.title = "Customize your ball";
        ball.setAttribute("role", "button");
        ball.tabIndex = 0;
        // Your profile's Ball tab, the same as on the start page (changes
        // reach your seat: saveProfile)
        const edit = () => openMe("ball");
        ball.addEventListener("click", edit);
        ball.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); edit(); } });
      } else {
        li.appendChild(personButton(seatInfo.id, seatInfo.name));
        if (host) {
          li.appendChild(removeButton("Remove from room", () => {
            if (confirm(`Remove ${seatInfo.name} from the room?`)) send({ type: "kick", id: seatInfo.id });
          }));
        }
      }
      ul.appendChild(li);
    } else {
      const b = seatInfo.bot;
      const li = seat(seatInfo.color, botLabel(seatInfo.kind), "bot", false);
      if (host) {
        const sel = document.createElement("select");
        sel.setAttribute("aria-label", "Bot type");
        for (const opt of L.bot_options) {
          const o = document.createElement("option");
          o.value = opt; o.textContent = botLabel(opt).replace(/ bot$/, "");  // (the card says "bot")
          sel.appendChild(o);
        }
        sel.value = seatInfo.kind;
        sel.addEventListener("change", () => {
          const next = s.bots.slice(); next[b] = sel.value;
          send({ type: "settings", bots: next });
        });
        li.querySelector(".who").replaceWith(sel);
        li.appendChild(removeButton("Remove bot", () => {
          const next = s.bots.slice(); next.splice(b, 1);
          send({ type: "settings", bots: next });
        }));
      }
      ul.appendChild(li);
    }
  }
  for (const m of L.members.filter((m) => !m.connected)) {
    const li = seat(null, shownName(m.id, m.name), "reconnecting…", false);
    li.classList.add("away");
    ul.appendChild(li);
  }
  // The map says how many can play: the seats left show as open, and the
  // host fills one with a bot by clicking it
  const n = L.seats.length;
  const [fewest, most] = mapInfo ? mapInfo.players : [2, Wm.max_players];
  $("seat-count").textContent = `${n} / ${most}`;
  for (let k = n; k < most; k++) {
    const li = document.createElement("li");
    li.className = "open-seat";
    if (host) {
      const b = document.createElement("button");
      if (k === n) b.id = "add-bot";
      b.className = "add-seat";
      b.innerHTML = `${icon("plus")}Add bot`;
      b.title = "Fill this seat with a bot (people who join take bots' seats)";
      b.addEventListener("click", () => send({ type: "settings", bots: [...app.lobby.settings.bots, "bot:medium"] }));
      li.appendChild(b);
    } else {
      li.textContent = "Open seat";
    }
    ul.appendChild(li);
  }
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
    const voted = L.votes.includes(me.id);
    $("vote").textContent = voted ? `Waiting for others… ${L.votes.length}/${here}` : `Play again  ${L.votes.length}/${here}`;
    $("vote").classList.toggle("primary", !voted);
  }

  // Joined during a match: watch it
  const watching = watchingNow();  // (people.js: came to watch, with Play to join in)
  if (L.phase === "match" && !app.match && !watching) status("A match is on. You'll play in the next one.");

  // Here while a match is on (you came out to the lobby): go back to it.
  // Watching: the same bar says so, with Play
  const on = !!app.match && (L.phase === "match" || (app.away && !!app.results));
  $("match-on").classList.toggle("hidden", !on && !watching);
  $("back-to-match").classList.toggle("hidden", !on);
  $("lobby-play").classList.toggle("hidden", !watching);
  $("back-to-match").classList.toggle("primary", !watching);
  if (on) {
    const playingIt = app.match.slots.some((x) => x.id === me.id);
    $("match-on-text").textContent = app.results ? "The match has finished."
      : playingIt ? "A match is on. A bot is playing for you while you're here."
      : watching ? "A match is on. You're watching." : "A match is on.";
    $("back-to-match").textContent = app.results ? "See the results" : playingIt ? "Back to the match" : "Watch the match";
  } else if (watching) {
    $("match-on-text").textContent = "You're watching. Press Play to join in.";
  }
  if (L.phase === "match") {
    $("start").disabled = true;
    $("start").textContent = "A match is on";
  }
}

// Out of a match to the lobby (and from there, ← Leave goes home). A bot
// plays for you meanwhile; Back to the match puts you back in
function goToLobby() {
  if (!app.match || !app.lobby || !app.ws) return;
  app.away = true;
  held.keys.clear(); held.touch.fill(0); held.pad.fill(0);
  send({ type: "away" });
  closeSettings();
  show("lobby");
  renderLobby();
}
function backToMatch() {
  if (!app.match) return;
  app.away = false;
  send({ type: "back" });
  show("game");
  resize();
  sendInput(true);
}
$("go-lobby").addEventListener("click", goToLobby);

// The host ends the match early (say, to change the map): everyone goes back
// to the lobby, with no results. Asks first if other people are playing.
function endMatch() {
  if (!app.match || !isHost()) return;
  // People playing who are still in the room (not someone who's left: a bot has their ball)
  const here = new Set((app.lobby ? app.lobby.seats : []).map((x) => x.id));
  const others = app.match.slots.filter((x) => x.kind === "human" && x.id !== me.id && here.has(x.id)).length;
  if (others && !confirm(`End the match for everyone? ${others === 1 ? "1 other person is" : others + " other people are"} playing.`)) return;
  send({ type: "end_match" });
}
for (const id of ["end-match", "end-match-lobby"]) {
  $(id).addEventListener("click", (e) => { e.currentTarget.blur(); endMatch(); });
}
$("back-to-match").addEventListener("click", backToMatch);

function removeButton(title, onClick) {
  const rm = document.createElement("button");
  rm.className = "remove icon-button"; rm.innerHTML = icon("x"); rm.title = title;
  rm.setAttribute("aria-label", title);
  rm.addEventListener("click", onClick);
  return rm;
}

// The "any colour" swatch: a colour picker when signed in, a lock for
// guests. onPick(hex) when a colour is picked.
function ownColorButton(current, onPick) {
  const wrap = document.createElement("label");
  wrap.className = "swatch own" + (current ? " on" : "") + (profileStore.user ? "" : " locked");
  wrap.title = profileStore.user ? "Any colour" : "Any colour: sign in to use it";
  if (current) wrap.style.background = current;
  else wrap.innerHTML = icon(profileStore.user ? "palette" : "lock");
  if (!profileStore.user) {
    wrap.setAttribute("role", "button");
    wrap.addEventListener("click", () => toast("Sign in (at the bottom of your profile) to pick any colour you like."));
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
  el.appendChild(ballCanvas(44, me.ballHex, me.pattern, me.look("hat")));
  const name = me.ownColor ? "Your own colour" : me.color === null ? "Any colour" : PALETTE[me.color][0];
  const extras = ["trail", "hat"].filter((k) => me.look(k) !== "none").map((k) => looks.name(k, me.look(k)).toLowerCase());
  $("home-ball-label").textContent = [name, looks.name("pattern", me.pattern).toLowerCase(), ...extras].join(", ");
  if (typeof renderMeHead === "function") renderMeHead();  // (settings.js, loaded after this)
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
  $("profile-unlock").textContent = profileStore.user || !looks.catalog ? ""
    : "The locked ones are for signed-in players: sign in below to use them.";
  $("profile-preview").innerHTML = "";
  $("profile-preview").appendChild(ballCanvas(72, me.ballHex, me.pattern, me.look("hat")));
}
$("edit-ball").addEventListener("click", () => openMe("ball"));  // (settings.js)

// A seat card: the ball, the name with what they are under it (you, host,
// bot), and room on the right for buttons
function seat(color, label, tag, you, pattern = "plain", own = null, hat = "none") {
  const li = document.createElement("li");
  li.className = "seat" + (you ? " you" : "");
  const ball = ballCanvas(34, own || (color === null ? T.faint : app.welcome.colors[color]), pattern, hat);
  ball.classList.add("ball");
  const who = document.createElement("span");
  who.className = "who";
  who.textContent = label;
  const t = document.createElement("span");
  t.className = "tag";
  t.textContent = tag;
  const text = document.createElement("span");
  text.className = "seat-text";
  text.append(who, t);
  li.append(ball, text);
  return li;
}

// The map, small, as it looks at the start (the server sends its shapes in
// "welcome"). Flat colours: a picture to recognise it by, not the game's art.
function drawMapPreview(canvas, mapInfo) {
  const key = mapInfo ? mapInfo.name : "";
  if (canvas.dataset.map === key) return;
  canvas.dataset.map = key;
  const g = canvas.getContext("2d");
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth || 340;
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(w * (H / W) * dpr);
  g.setTransform(canvas.width / W, 0, 0, canvas.height / H, 0, 0);
  const sky = g.createLinearGradient(0, 0, 0, H);
  sky.addColorStop(0, T.bgTop); sky.addColorStop(1, T.bgBottom);
  g.fillStyle = sky; g.fillRect(0, 0, W, H);
  for (const sh of (mapInfo && mapInfo.preview) || []) {
    // In the critter colours (draw.js: materialOf), grass shown green
    const m = sh.c && sh.t !== "line" ? materialOf(sh) : null;
    const c = m ? (m === MATERIALS.grass ? "#8fd694" : m.deep) : sh.c || T.rail;
    g.fillStyle = c;
    g.strokeStyle = c;
    if (sh.t === "rect") {
      const [x1, y1, x2, y2] = sh.r;
      g.fillRect(Math.min(x1, x2), Math.min(y1, y2), Math.max(3, Math.abs(x2 - x1)), Math.max(3, Math.abs(y2 - y1)));
    } else if (sh.t === "poly") {
      g.beginPath(); sh.p.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.closePath(); g.fill();
    } else if (sh.t === "ball") {
      g.beginPath(); g.arc(sh.x, sh.y, sh.r, 0, Math.PI * 2); g.fill();
    } else if (sh.t === "line") {
      g.lineWidth = sh.w * 1.5; g.beginPath(); g.moveTo(...sh.a); g.lineTo(...sh.b); g.stroke();
    } else if (sh.t === "rail") {
      g.strokeStyle = T.rail; g.lineWidth = 4; g.beginPath(); g.moveTo(sh.x1, sh.y); g.lineTo(sh.x2, sh.y); g.stroke();
    } else if (sh.t === "pivot") {
      g.fillStyle = T.rope; g.beginPath(); g.arc(sh.x, sh.y, 6, 0, Math.PI * 2); g.fill();
    } else if (sh.t === "edges") {
      g.strokeStyle = "rgba(255,110,140,0.5)"; g.lineWidth = 8; g.strokeRect(0, 0, W, H);
    }
  }
}

$("map").addEventListener("change", () => send({ type: "settings", map: $("map").value }));
$("first-to").addEventListener("change", () => send({ type: "settings", first_to: +$("first-to").value }));
$("mode").addEventListener("change", () => send({ type: "settings", mode: $("mode").value }));
$("round-time").addEventListener("change", () => send({ type: "settings", round_time: JSON.parse($("round-time").value) }));
$("gravity").addEventListener("change", () => send({ type: "settings", gravity: $("gravity").value }));
$("speed").addEventListener("change", () => send({ type: "settings", speed: $("speed").value }));
$("power-ups").addEventListener("change", () => send({ type: "settings", power_ups: $("power-ups").checked }));
$("quick-map").addEventListener("change", () => send({ type: "settings", map: $("quick-map").value }));
$("quick-mode").addEventListener("change", () => send({ type: "settings", mode: $("quick-mode").value }));
$("quick-power-ups").addEventListener("change", () => send({ type: "settings", power_ups: $("quick-power-ups").checked }));

// Copy a dropdown's options (text, disabled, which is picked) into another
function mirrorSelect(from, to) {
  const opts = Array.from(from.options, (o) => [o.value, o.textContent, o.disabled]);
  const key = JSON.stringify(opts);
  if (to.dataset.key !== key) {
    to.dataset.key = key;
    to.replaceChildren(...opts.map(([value, text, disabled]) => {
      const o = document.createElement("option");
      o.value = value;
      o.textContent = text;
      o.disabled = disabled;
      return o;
    }));
  }
  to.value = from.value;
  to.disabled = from.disabled;
}

// Which power-ups can turn up: a chip each (the room needs at least one)
function chosenKinds(all, s) {
  return s.power_kinds || all.map((k) => k.id);
}

function drawPowerKinds(all, s, host) {
  const box = $("power-kinds");
  const chosen = chosenKinds(all, s);
  box.classList.toggle("off", !s.power_ups);
  if (box.children.length !== all.length) {
    box.replaceChildren(...all.map((k) => {
      const b = document.createElement("button");
      b.type = "button";
      b.dataset.kind = k.id;
      b.className = k.super ? "super" : "";
      b.title = POWER_HINTS[k.id] || k.title;
      b.append(`${POWER_ICONS[k.id] || ""} ${k.title}`);
      if (k.super) { const t = document.createElement("span"); t.className = "tag"; t.textContent = "SUPER"; b.append(t); }
      b.addEventListener("click", () => {
        const now = chosenKinds(all, app.lobby.settings);
        const next = now.includes(k.id) ? now.filter((x) => x !== k.id) : [...now, k.id];
        if (!next.length) { toast("Keep at least one power-up"); return; }
        send({ type: "settings", power_kinds: next });
      });
      return b;
    }));
  }
  for (const b of box.children) {
    b.setAttribute("aria-pressed", String(chosen.includes(b.dataset.kind)));
    b.disabled = !host || !s.power_ups;
  }
}

// "Power-ups off", "Power-ups on", or the ones picked ("Power-ups ⚡ ✈️")
function powerSummary(all, s) {
  if (!s.power_ups) return "Power-ups off";
  const chosen = chosenKinds(all, s);
  if (!all.length || chosen.length === all.length) return "Power-ups on";
  return `Power-ups ${chosen.map((k) => POWER_ICONS[k] || k).join(" ")}`;
}
$("room-name-input").addEventListener("change", () => send({ type: "settings", name: $("room-name-input").value.trim() || null }));
$("room-name-input").addEventListener("input", (e) => { e.target.size = Math.max(6, e.target.value.length + 1); });
$("room-name-input").addEventListener("keydown", (e) => { if (e.key === "Enter") e.target.blur(); });
for (const b of $("privacy").querySelectorAll("button")) {
  b.addEventListener("click", () => {
    const priv = b.dataset.private === "1";
    if (priv !== !!app.lobby.settings.password) send({ type: "settings", password: priv ? true : null });
  });
}
// The room code and password chips copy what they show
async function copyText(text, what) {
  try { await navigator.clipboard.writeText(text); toast(`${what} copied`); } catch (e) { toast(text); }
}
$("room-code-chip").addEventListener("click", () => copyText(app.room, "Room code"));
$("password-row").addEventListener("click", () => copyText(app.lobby.settings.password || "", "Room password"));

// The Game settings dialog
const openGameSettings = () => { $("game-settings").classList.remove("hidden"); $("game-settings-done").focus(); };
const closeGameSettings = () => $("game-settings").classList.add("hidden");
$("open-game-settings").addEventListener("click", openGameSettings);
$("open-game-settings-map").addEventListener("click", openGameSettings);
$("game-settings-done").addEventListener("click", closeGameSettings);
$("game-settings").addEventListener("click", (e) => { if (e.target === $("game-settings")) closeGameSettings(); });
$("switch-team").addEventListener("click", () => {
  const mine = app.lobby.seats.find((x) => x.id === me.id);
  if (mine) send({ type: "team", team: 1 - mine.team });
});
$("add-needed").addEventListener("click", (e) => {
  const short = +e.target.dataset.short || 1;
  send({ type: "settings", bots: [...app.lobby.settings.bots, ...Array(short).fill("bot:medium")] });
});
$("start").addEventListener("click", () => send({ type: "start" }));
$("again").addEventListener("click", () => send({ type: "start" }));
$("vote").addEventListener("click", () => send({ type: "vote" }));
$("to-lobby").addEventListener("click", () => send({ type: "lobby" }));
$("copy-link").addEventListener("click", async () => {
  const link = location.origin + roomLink(app.room, app.password);  // (core.js)
  try {
    await navigator.clipboard.writeText(link);
    toast("Invite link copied");
  } catch (e) {
    toast(link);
  }
});
