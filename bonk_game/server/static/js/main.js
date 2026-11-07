// bonk web client: start up. Loaded last (see index.html).
"use strict";

updateHelp();
// Testing with a pretend network (netsim.js): say so, so it isn't forgotten
if (NET_SIM) { $("netsim").textContent = BonkNetSim.describe(NET_SIM); $("netsim").classList.remove("hidden"); }
renderHomeBall();
// The logo's "o": a critter (redrawn once the font's in, so it sits right)
for (const el of document.querySelectorAll(".logo-ball")) {
  const c = ballCanvas(54, "#ff6b6b", "plain");
  c.style.width = c.style.height = "100%";
  el.replaceChildren(c);
}
route();
