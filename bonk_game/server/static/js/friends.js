// bonk web client: Friends (signed-in players). The Friends tab of your
// profile: friend requests to say yes or no to, your friends (who's playing
// now, and where, with a button to join them) and the requests you've sent.
// You ask someone to be friends from their card in a room (people.js,
// "befriend"); the server keeps the lot (accounts.py) and says where your
// friends are (GET /api/friends).
// Plain scripts sharing one global scope; index.html loads them in order.
"use strict";

const FRIENDS_EVERY = 15000;  // ms between checks, on the start page and the game browser

const friends = {
  data: null,      // the last /api/friends answer (null: signed out, or not asked yet)
  timer: null,

  async refresh() {
    if (!profileStore.user) { this.data = null; this.render(); return; }
    try {
      const r = await fetch("/api/friends", { cache: "no-store" });
      this.data = r.ok ? await r.json() : null;
    } catch (e) {
      return;  // (offline for a moment: keep what we had)
    }
    this.toastNew();
    this.render();
  },

  // Check now and then while you're on the start page or the game browser
  watch(on) {
    clearInterval(this.timer);
    this.timer = on ? setInterval(() => { if (!document.hidden) this.refresh(); }, FRIENDS_EVERY) : null;
    if (on) this.refresh();
  },

  async act(method, id) {
    try {
      const r = await fetch(`/api/friends/${encodeURIComponent(id)}`, { method });
      if (!r.ok) throw new Error(r.status);
      const body = await r.json();
      if (body.result === "full") toast("You have too many friends to add more.", true);
    } catch (e) {
      toast("Couldn't do that just now. Try again in a moment.", true);
    }
    this.refresh();
  },

  join(where) {
    closeMe();  // (settings.js)
    if (app.room === where.room) return;
    if (app.room) leaveRoom(false);
    openRoom(where.room, true);  // (core.js: a private room asks for its password)
  },

  // A request that came in since we last looked (on the start page, where
  // there's no room to hear it in): the same toast as in a room, with
  // Accept / No thanks. (The ones waiting when the page opens are just
  // counted on the Friends button.)
  toastNew() {
    if (!this.data) return;
    const ids = this.data.incoming.map((f) => f.id);
    if (this.seen) {
      const fresh = this.data.incoming.find((f) => !this.seen.has(f.id));
      if (fresh) {
        toast(`${fresh.name} wants to be friends.`, false, [
          { label: "Accept", primary: true, onClick: () => this.act("POST", fresh.id) },
          { label: "No thanks", onClick: () => this.act("DELETE", fresh.id) },
        ]);
      }
    }
    this.seen = new Set(ids);
  },
  seen: null,      // the requests we've shown (or counted) already

  // The start page's Friends button shows how many requests are waiting
  renderCount() {
    // (No sign-in on this server: no friends either)
    $("open-friends").classList.toggle("hidden", !account.on);
    document.querySelector('#me-tabs [data-tab="friends"]').classList.toggle("hidden", !account.on);
    const n = this.data ? this.data.incoming.length : 0;
    const badge = $("friends-count");
    badge.textContent = n ? String(n) : "";
    badge.classList.toggle("hidden", !n);
    const tab = document.querySelector('#me-tabs [data-tab="friends"]');
    tab.textContent = n ? `Friends (${n})` : "Friends";
  },

  render() {
    this.renderCount();
    if (typeof meTab === "undefined" || meTab !== "friends" || $("me").classList.contains("hidden")) return;
    const pane = $("friends-body");
    pane.innerHTML = "";
    if (!profileStore.user) {
      pane.append(frText("p", "dim", "Sign in to add friends, see when they're playing and join their games."));
      const b = document.createElement("button");
      b.className = "primary";
      b.textContent = "Sign in with Google";
      b.addEventListener("click", () => account.signIn());
      pane.append(b);
      return;
    }
    const d = this.data;
    if (!d) { pane.append(frText("p", "dim", "Loading…")); return; }
    if (d.incoming.length) {
      pane.append(frText("h3", "", "Friend requests"));
      pane.append(frList(d.incoming, (f) => [
        frButton("Accept", "primary", () => this.act("POST", f.id)),
        frButton("No thanks", "ghost", () => this.act("DELETE", f.id)),
      ]));
    }
    pane.append(frText("h3", "", d.friends.length ? `Friends (${d.friends.filter((f) => f.online).length} playing)` : "Friends"));
    if (!d.friends.length) {
      pane.append(frText("p", "dim small", "No friends yet. In a game, open someone's card (⋯ next to their name) and press Add friend."));
    } else {
      pane.append(frList(d.friends, (f) => {
        const out = [];
        if (f.where && f.where.room !== app.room) out.push(frButton("Join", "primary", () => this.join(f.where)));
        out.push(frButton("Remove", "ghost small-btn", () => {
          if (confirm(`Remove ${f.name} from your friends?`)) this.act("DELETE", f.id);
        }));
        return out;
      }, (f) => {
        if (!f.where) return "Not playing";
        const what = f.where.playing ? "Playing" : "In the lobby";
        return `${what}: ${f.where.title}${f.where.locked ? " (private)" : ""}${f.where.room === app.room ? " · here" : ""}`;
      }));
    }
    if (d.outgoing.length) {
      pane.append(frText("h3", "", "Sent"));
      pane.append(frList(d.outgoing, (f) => [frButton("Cancel", "ghost", () => this.act("DELETE", f.id))],
        () => "Waiting for them to say yes"));
    }
  },
};

function frText(tag, cls, t) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  e.textContent = t;
  return e;
}

function frButton(label, cls, onClick) {
  const b = document.createElement("button");
  b.className = cls;
  b.textContent = label;
  b.addEventListener("click", onClick);
  return b;
}

// A list of people: their ball, name, a line under it, and buttons
function frList(people, buttons, line) {
  const ul = document.createElement("ul");
  ul.className = "friend-list";
  for (const f of people) {
    const li = document.createElement("li");
    li.className = "friend" + (f.online ? " online" : "");
    li.dataset.id = f.id;
    const who = document.createElement("span");
    who.className = "friend-who";
    const name = frText("b", "", f.name);
    const text = document.createElement("span");
    text.className = "friend-text";
    text.append(name);
    if (line) text.append(frText("span", "dim small", line(f)));
    who.append(boardBall(f.ball), text);  // (rating.js)
    const acts = document.createElement("span");
    acts.className = "friend-acts";
    acts.append(...buttons(f));
    li.append(who, acts);
    ul.append(li);
  }
  return ul;
}

$("open-friends").addEventListener("click", () => openMe("friends"));
