// bonk web client: Signing in with Google (optional) and your account.
// Plain scripts sharing one global scope; index.html loads them in order.
//
// Guests play as before: their profile stays in this browser. Signing in
// (bonk_game/server/auth.py) keeps the profile on the server instead, so it's
// the same on every device:
// - The first time you sign in on a browser, its profile is added to your
//   account, and the browser starts a fresh guest profile (same name, ball
//   and settings) so those matches aren't counted twice.
// - While signed in, changes to your name, ball and settings are sent to
//   the server (push), and the server records your matches.
// - Signing out goes back to this browser's guest profile.
"use strict";

const account = {
  on: false,          // the server has sign-in set up
  timer: null,
  pending: null,

  async api(method, path, body) {
    const opts = { method, headers: {}, credentials: "same-origin" };
    if (body !== undefined) { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    const r = await fetch(path, opts);
    if (!r.ok) throw new Error(`${method} ${path}: ${r.status}`);
    return r.json();
  },

  // On load: are we signed in? Then make sure this browser has the account's
  // profile (reloading once so settings and sound pick it up)
  async init() {
    this.signinMessage();
    let me;
    try { me = await this.api("GET", "/api/me"); } catch (e) { return; /* offline: carry on as we are */ }
    this.on = !!me.accounts;
    const had = profileStore.user;
    if (!me.user) {
      // Signed out (here or elsewhere, or the sign-in ran out): back to the guest profile
      if (had) { store.remove(profileStore.ACCOUNT_KEY); location.reload(); return; }
      this.render();
      return;
    }
    if (!had || had.id !== me.user.id) {
      // Just signed in on this browser: add its profile to the account
      const guest = profileStore.loadGuest();
      let res;
      try {
        res = await this.api("POST", "/api/me/merge", guest);
      } catch (e) {
        // Use the account for now, and try adding this browser's profile next time
        profileStore.user = me.user;
        profileStore.current = BonkProfile.validate(me.profile) || profileStore.current;
        this.render();
        return;
      }
      // A fresh guest profile from now on (its matches are in the account)
      store.set(profileStore.KEY, JSON.stringify({ ...BonkProfile.empty(randomToken()),
        name: guest.name, color: guest.color, pattern: guest.pattern, muted: guest.muted, prefs: guest.prefs }));
      store.set(profileStore.ACCOUNT_KEY, JSON.stringify({ user: res.user, profile: res.profile }));
      location.reload();
      return;
    }
    // Signed in already: take the server's copy (another device may have changed it)
    profileStore.user = me.user;
    const p = BonkProfile.validate(me.profile);
    if (p) {
      profileStore.current = p;
      store.set(profileStore.ACCOUNT_KEY, JSON.stringify({ user: me.user, profile: p }));
      if (!$("name").matches(":focus")) $("name").value = p.name;
      renderHomeBall();
    }
    this.render();
  },

  // Send name, ball and settings changes (a moment later: typing a name
  // sends once)
  push(p) {
    this.pending = { name: p.name, color: p.color, pattern: p.pattern, muted: p.muted, prefs: p.prefs };
    clearTimeout(this.timer);
    this.timer = setTimeout(() => this.flush(), 600);
  },
  async flush() {
    const changes = this.pending;
    this.pending = null;
    if (!changes || !profileStore.user) return;
    try { await this.api("PUT", "/api/me/profile", changes); } catch (e) { /* kept here; sent with the next change */ }
  },

  // After a match: the server's copy, with the match it recorded
  refreshSoon() {
    setTimeout(async () => {
      try {
        const me = await this.api("GET", "/api/me");
        const p = me.user && BonkProfile.validate(me.profile);
        if (p && profileStore.user && me.user.id === profileStore.user.id) {
          profileStore.current = { ...p, name: profileStore.get().name, prefs: profileStore.get().prefs };
          store.set(profileStore.ACCOUNT_KEY, JSON.stringify({ user: me.user, profile: profileStore.current }));
        }
      } catch (e) { /* next time */ }
    }, 1500);
  },

  // A profile file, added to the account. Returns the matches it added.
  async merge(other) {
    const res = await this.api("POST", "/api/me/merge", other);
    const p = BonkProfile.validate(res.profile);
    if (p) {
      profileStore.current = p;
      store.set(profileStore.ACCOUNT_KEY, JSON.stringify({ user: res.user, profile: p }));
    }
    return res.added || 0;
  },

  signIn() {
    location.href = "/auth/google?next=" + encodeURIComponent(location.pathname);
  },
  async signOut() {
    await this.flush();
    try { await this.api("POST", "/auth/logout"); } catch (e) { /* the cookie goes anyway when it runs out */ }
    store.remove(profileStore.ACCOUNT_KEY);
    location.reload();
  },
  async remove() {
    if (!confirm("Delete your account? Your stats and match history on the server go for good. (You can save them to a file first.)")) return;
    try { await this.api("DELETE", "/api/me"); } catch (e) { toast("Couldn't delete it just now. Try again in a moment.", true); return; }
    store.remove(profileStore.ACCOUNT_KEY);
    location.reload();
  },

  // Coming back from Google: say if it didn't work
  signinMessage() {
    const q = new URLSearchParams(location.search);
    const why = q.get("signin");
    if (!why) return;
    const text = { cancelled: "Sign-in cancelled. You can play as a guest.",
                   expired: "Sign-in took too long. Try again.",
                   failed: "Sign-in didn't work. Try again, or play as a guest." }[why];
    if (text) toast(text, why !== "cancelled");
    history.replaceState({}, "", location.pathname);
  },

  render() {
    const user = profileStore.user;
    $("account").classList.toggle("hidden", !this.on && !user);
    $("account-out").classList.toggle("hidden", !!user);
    $("account-in").classList.toggle("hidden", !user);
    if (user) $("account-who").textContent = user.email || user.name || "your account";
    $("delete-account").classList.toggle("hidden", !user);
    $("stats-where").textContent = user
      ? "Saved to your account: the same on every device you sign in on."
      : "Kept in this browser. Sign in to keep them on every device, or move them with a file.";
  },
};

$("sign-in").addEventListener("click", () => account.signIn());
$("sign-out").addEventListener("click", () => account.signOut());
$("delete-account").addEventListener("click", () => account.remove());
window.addEventListener("pagehide", () => { if (account.pending) account.flush(); });
account.init();
