// Hover and tap tooltips for the Analysis charts (app/analysis_charts.py): any mark with a
// data-tip inside a .chart-wrap[data-tips] shows its text in the wrap's .chart-tip.
(function () {
  "use strict";
  document.querySelectorAll(".chart-wrap[data-tips]").forEach(function (wrap) {
    var tip = wrap.querySelector(".chart-tip"), current = null;
    function show(el, e) {
      if (current && current !== el) current.classList.remove("hover");
      current = el;
      el.classList.add("hover");
      tip.textContent = el.getAttribute("data-tip");
      tip.hidden = false;
      var r = wrap.getBoundingClientRect();
      var x = e.clientX - r.left, y = e.clientY - r.top;
      var half = tip.offsetWidth / 2;
      tip.style.left = Math.min(Math.max(x, half + 4), r.width - half - 4) + "px";
      tip.style.top = Math.max(y - 40, 0) + "px";
    }
    function hide() {
      if (current) current.classList.remove("hover");
      current = null;
      tip.hidden = true;
    }
    function find(e) {
      var el = e.target.closest ? e.target.closest("[data-tip]") : null;
      return el && wrap.contains(el) ? el : null;
    }
    wrap.addEventListener("pointermove", function (e) { var el = find(e); if (el) show(el, e); else hide(); });
    wrap.addEventListener("pointerdown", function (e) { var el = find(e); if (el) show(el, e); });
    wrap.addEventListener("pointerleave", hide);
  });
})();
