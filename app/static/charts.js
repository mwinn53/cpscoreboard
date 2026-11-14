// Crosshair + tooltip for the step charts on /teams/<n> (app/charts.py).
// Each .chart-wrap has data-points = [[x, y, label], ...] in SVG units and
// data-plot = "left,right,top,bottom,width,height". A step chart holds each value
// until the next change, so the hovered value is the last point at or before x.
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  document.querySelectorAll(".chart-wrap[data-points]").forEach(function (wrap) {
    var pts = JSON.parse(wrap.dataset.points);
    var plot = wrap.dataset.plot.split(",").map(Number);
    var svg = wrap.querySelector("svg"), tip = wrap.querySelector(".chart-tip");
    if (!pts.length) return;
    var line = document.createElementNS(NS, "line");
    line.setAttribute("class", "crosshair");
    line.setAttribute("y1", plot[2]); line.setAttribute("y2", plot[3]);
    var dot = document.createElementNS(NS, "circle");
    dot.setAttribute("class", "hover-dot"); dot.setAttribute("r", 5);
    line.style.display = dot.style.display = "none";
    svg.appendChild(line); svg.appendChild(dot);

    function show(clientX) {
      var r = svg.getBoundingClientRect();
      var x = (clientX - r.left) * plot[4] / r.width;
      if (x < plot[0] || x > plot[1]) return hide();
      var p = pts[0];
      for (var i = 0; i < pts.length && pts[i][0] <= x; i++) p = pts[i];
      line.setAttribute("x1", x); line.setAttribute("x2", x);
      dot.setAttribute("cx", x); dot.setAttribute("cy", p[1]);
      line.style.display = dot.style.display = "";
      tip.textContent = p[2];
      tip.hidden = false;
      var left = x * r.width / plot[4], top = p[1] * r.height / plot[5];
      tip.style.left = Math.min(Math.max(left, 60), r.width - 60) + "px";
      tip.style.top = Math.max(top - 34, 0) + "px";
    }
    function hide() { line.style.display = dot.style.display = "none"; tip.hidden = true; }
    svg.addEventListener("pointermove", function (e) { show(e.clientX); });
    svg.addEventListener("pointerdown", function (e) { show(e.clientX); });
    svg.addEventListener("pointerleave", hide);
  });
})();
