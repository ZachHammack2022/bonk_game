// bonk web client: Chat, in the lobby (a panel) and during a match (a few
// lines in the bottom corner that fade, and a box that opens with Enter or T).
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

// ---------------------------------------------------------------------------
// Everyone in the room sees the same chat. The server stars out offensive
// words (moderation.py) and keeps the last few dozen lines for people who
// join. Muted people's lines don't show on your screen (people.js).
// ---------------------------------------------------------------------------
const CHAT_KEPT = 100;      // lines kept here
const CHAT_FEED = 6;        // lines shown over the match
const CHAT_FADE = 10000;    // ms a line stays over the match (while the box is closed)

const chat = {
  lines: [],
  timer: null,

  reset(lines) {
    this.lines = (lines || []).map((l) => ({ ...l, seen: 0 }));
    this.render();
  },
  add(line) {
    this.lines.push({ ...line, seen: performance.now() });
    if (this.lines.length > CHAT_KEPT) this.lines.shift();
    this.render();
    // Over the match, the line fades on its own: draw again once it has
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.renderFeed(), CHAT_FADE + 50);
  },
  shown() {
    return this.lines.filter((l) => l.system || !isMuted(l.id));  // (people.js)
  },
  render() {
    this.renderLog();
    this.renderFeed();
  },

  // The lobby's panel: everything, newest at the bottom
  renderLog() {
    const log = $("chat-log");
    const atBottom = log.scrollHeight - log.scrollTop - log.clientHeight < 30;
    log.replaceChildren(...this.shown().map((l) => chatLine(l)));
    if (!log.children.length) {
      const empty = document.createElement("li");
      empty.className = "chat-empty dim small";
      empty.textContent = "No messages yet. Say hi!";
      log.appendChild(empty);
    }
    if (atBottom) log.scrollTop = log.scrollHeight;
  },

  // Over the match: the last few lines, each for a few seconds (all of them
  // while you're typing). Off if you turned chat off in settings.
  renderFeed() {
    const feed = $("chat-feed");
    const open = !$("chat-game-form").classList.contains("hidden");
    const now = performance.now();
    const lines = prefs.chat === false ? [] : this.shown().filter((l) => open || now - l.seen < CHAT_FADE);
    feed.replaceChildren(...lines.slice(-(open ? CHAT_FEED * 2 : CHAT_FEED)).map((l) => chatLine(l)));
    $("chat-overlay").classList.toggle("open", open);
  },
};

function chatLine(l) {
  const li = document.createElement("li");
  if (l.system) {
    li.className = "chat-system";
    li.textContent = l.text;
    return li;
  }
  if (app.welcome && l.id === me.id) li.className = "chat-you";
  const who = document.createElement("b");
  who.textContent = shownName(l.id, l.name) + ": ";
  // Their ball's colour, if they're in the room
  const seat = app.lobby && app.lobby.seats.find((x) => x.id === l.id);
  if (seat && app.welcome) who.style.color = seat.own_color || app.welcome.colors[seat.color];
  const text = document.createElement("span");
  text.textContent = l.text;
  li.append(who, text);
  return li;
}

function sendChat(input) {
  const text = input.value.trim();
  if (!text) return false;
  send({ type: "chat", text });
  input.value = "";
  return true;
}

// The lobby's box
$("chat-form").addEventListener("submit", (e) => {
  e.preventDefault();
  sendChat($("chat-input"));
});

// During a match: Enter or T opens the box (input.js), Enter sends and
// closes it, Esc closes it. Your ball lets go of every key while you type.
function openGameChat() {
  if (prefs.chat === false) { toast("Chat is off: turn it on in settings."); return; }
  held.keys.clear();
  sendInput(true);
  $("chat-game-form").classList.remove("hidden");
  chat.renderFeed();
  $("chat-game-input").focus();
}
function closeGameChat() {
  $("chat-game-form").classList.add("hidden");
  $("chat-game-input").blur();
  chat.renderFeed();
}
$("chat-game-form").addEventListener("submit", (e) => {
  e.preventDefault();
  sendChat($("chat-game-input"));
  closeGameChat();
});
$("chat-game-input").addEventListener("keydown", (e) => {
  if (e.code === "Escape") { e.preventDefault(); e.stopPropagation(); closeGameChat(); }
});
$("chat-game-input").addEventListener("blur", () => setTimeout(() => {
  if (document.activeElement !== $("chat-game-input") && !$("chat-game-input").value) closeGameChat();
}, 0));
$("open-chat").addEventListener("click", (e) => { e.currentTarget.blur(); openGameChat(); });
