// bonk web client: start up. Loaded last (see index.html).
"use strict";

updateHelp();
// Testing with a pretend network (netsim.js): say so, so it isn't forgotten
if (NET_SIM) { $("netsim").textContent = BonkNetSim.describe(NET_SIM); $("netsim").classList.remove("hidden"); }
renderHomeBall();
route();
