// The web app: "Add bonk to your home screen" on the home page.
//
// Chrome, Edge and Android ask with their own prompt (beforeinstallprompt);
// iPhone and iPad have no prompt, so the button shows how (Share, then Add to
// Home Screen). Hidden once installed (installedApp(), core.js), and for two
// weeks after "Not now". Opened from the home screen, the page fills the
// screen (manifest.webmanifest) and keeps clear of the notch (style.css).
const INSTALL_SNOOZE_DAYS = 14;
const install = {
  prompt: null,  // Chrome's install prompt, saved for the button
  ios: /iPhone|iPad|iPod/.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1),
};

function installSnoozed() {
  const t = Number(store.get("bonk.install-snoozed", 0));
  return t > 0 && Date.now() - t < INSTALL_SNOOZE_DAYS * 86400e3;
}

function showInstall() {
  const offer = !installedApp() && !installSnoozed() && (install.prompt || install.ios);
  $("install").classList.toggle("hidden", !offer);
}

function hideInstall(snooze) {
  if (snooze) store.set("bonk.install-snoozed", String(Date.now()));
  $("install").classList.add("hidden");
}

if (installedApp()) document.documentElement.classList.add("installed-app");

window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();  // our own button, not the browser's mini-bar
  install.prompt = e;
  showInstall();
});
window.addEventListener("appinstalled", () => { install.prompt = null; hideInstall(false); });

$("install-button").addEventListener("click", async () => {
  if (install.prompt) {
    const p = install.prompt;
    install.prompt = null;
    p.prompt();
    const choice = await p.userChoice.catch(() => null);
    if (choice && choice.outcome === "accepted") hideInstall(false);
    else showInstall();
    return;
  }
  // iPhone / iPad: there's no prompt, so say how
  const steps = $("install-steps");
  steps.textContent = "Tap the Share button (the square with an arrow, at the bottom or top of the screen), " +
    "then “Add to Home Screen”.";
  steps.classList.toggle("hidden");
});
$("install-close").addEventListener("click", () => hideInstall(true));

showInstall();
