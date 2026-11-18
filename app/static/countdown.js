// Live countdowns: <span class="countdown" data-deadline="ISO time">. Re-reads the page every
// second, so countdowns that htmx swaps in (the Analysis collection panel) keep ticking.
(function () {
  "use strict";
  function fmt(ms) {
    if (ms <= 0) return "a moment (due now)";
    var s = Math.floor(ms / 1000), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), sec = s % 60;
    function pad(n) { return (n < 10 ? "0" : "") + n; }
    return h + ":" + pad(m) + ":" + pad(sec);
  }
  function tick() {
    document.querySelectorAll(".countdown[data-deadline]").forEach(function (el) {
      el.textContent = fmt(new Date(el.dataset.deadline) - new Date());
    });
  }
  tick();
  setInterval(tick, 1000);
})();
