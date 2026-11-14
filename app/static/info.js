// (i) help buttons (templates/_info.html): click to open or close the bubble;
// Escape or a click anywhere else closes it.
(function () {
  "use strict";
  function bubble(btn) { return document.getElementById(btn.getAttribute("aria-controls")); }
  function close(btn) { btn.setAttribute("aria-expanded", "false"); bubble(btn).hidden = true; }
  document.addEventListener("click", function (e) {
    var btn = e.target.closest(".info-btn");
    document.querySelectorAll('.info-btn[aria-expanded="true"]').forEach(function (b) {
      if (b !== btn && !bubble(b).contains(e.target)) close(b);
    });
    if (!btn) return;
    if (btn.getAttribute("aria-expanded") === "true") return close(btn);
    btn.setAttribute("aria-expanded", "true");
    bubble(btn).hidden = false;
  });
  document.addEventListener("keydown", function (e) {
    if (e.key === "Escape") document.querySelectorAll('.info-btn[aria-expanded="true"]').forEach(close);
  });
})();
