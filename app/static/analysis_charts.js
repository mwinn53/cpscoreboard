// Interactive Analysis charts (app/analysis_charts.py, #65). Small and framework-free; the
// tables on the page stay the accessible view of the same numbers.
//
// * Tooltips: any mark with a data-tip inside a .chart-wrap[data-tips] shows its text.
// * Team highlight: click a mark or table row with a data-team, or type a team number in
//   the report's search box, to highlight that team in every chart (again, or Esc, clears).
// * Teams we follow (the report's data-follow, #67) get the "followed" class: a ring on their
//   dots and a star in table rows.
// * Legend toggles: .legend-toggle[data-toggle] shows or hides that selector's marks in its
//   chart card; [data-group] shows or hides a team group's dots on the whole page. The
//   direct labels on percentile lines (.label-toggle) toggle their line.
// * Zoom: drag across a .chart-wrap[data-zoom] (or use its Zoom form) and the server draws
//   that x range (/analysis/reports/{id}/charts/{name}); "Reset zoom" restores it.
// * Projection: .projection-toggle shows or hides the State Round projection (remembered).
// * Export: .export-print opens the print dialog on the print layout (style.css); while printing,
//   the page title is the bar's data-filename, which browsers use to name a saved PDF (#69).
(function () {
  "use strict";
  var NS = "http://www.w3.org/2000/svg";
  var tools = document.querySelector("[data-report]");
  var picked = null;
  var original = {};
  var follow = {};
  ((tools && tools.getAttribute("data-follow")) || "").split(" ").forEach(function (n) { if (n) follow[n] = true; });

  function store(key, value) {
    try {
      if (value === undefined) return window.localStorage.getItem(key);
      window.localStorage.setItem(key, value);
    } catch (e) { /* private window: not remembered */ }
    return null;
  }

  // --- tooltips ---
  function tips(wrap) {
    if (!wrap.hasAttribute("data-tips")) return;
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
  }

  // --- team highlight ---
  var input = document.getElementById("team-find");
  var status = document.getElementById("team-status");
  var known = {};
  document.querySelectorAll("#team-list option").forEach(function (o) { known[o.value] = o.label || ""; });

  function applyPick(root) {
    (root || document).querySelectorAll("[data-team]").forEach(function (el) {
      var team = el.getAttribute("data-team");
      el.classList.toggle("picked", team === picked);
      el.classList.toggle("followed", follow[team] === true);
    });
    document.body.classList.toggle("has-pick", picked !== null);
  }
  function pick(team) {
    picked = team && team !== picked ? team : null;
    applyPick();
    if (input) input.value = picked || "";
    if (!status) return;
    if (!picked) { status.textContent = ""; return; }
    var marks = document.querySelectorAll('svg.chart [data-team="' + picked + '"]').length;
    status.textContent = picked + (known[picked] ? " (" + known[picked] + ")" : "") + " highlighted" +
      (marks ? "" : "; it isn't drawn in these charts") + ".";
  }
  function findTeam() {
    var v = input.value.trim();
    if (!v) { pick(null); return; }
    if (Object.prototype.hasOwnProperty.call(known, v)) { if (v !== picked) pick(v); }
    else if (status) status.textContent = "No team " + v + " in this data set.";
  }
  if (input) {
    input.addEventListener("change", findTeam);
    input.addEventListener("keydown", function (e) { if (e.key === "Enter") { e.preventDefault(); findTeam(); } });
    var clear = document.getElementById("team-clear");
    if (clear) clear.addEventListener("click", function () { pick(null); input.focus(); });
  }
  document.addEventListener("keydown", function (e) { if (e.key === "Escape" && picked) pick(null); });

  // --- legend toggles ---
  function setToggle(card, button, on) {
    button.setAttribute("aria-pressed", on ? "true" : "false");
    card.querySelectorAll(".chart-wrap svg").forEach(function (svg) {
      svg.querySelectorAll(button.getAttribute("data-toggle")).forEach(function (el) {
        el.classList.toggle("off", !on);
      });
    });
  }
  function applyToggles(card) {
    if (!card) return;
    card.querySelectorAll('.legend-toggle[data-toggle][aria-pressed="false"]').forEach(function (b) {
      setToggle(card, b, false);
    });
  }
  function labelToggle(g) {
    var on = g.getAttribute("aria-pressed") !== "true";
    g.setAttribute("aria-pressed", on ? "true" : "false");
    var slot = g.getAttribute("data-series");
    g.ownerSVGElement.querySelectorAll(".series." + slot + ", .end." + slot).forEach(function (el) {
      el.classList.toggle("off", !on);
    });
  }

  document.addEventListener("click", function (e) {
    var t = e.target && e.target.closest ? e.target : null;
    if (!t) return;
    var b = t.closest(".legend-toggle");
    if (b) {
      var on = b.getAttribute("aria-pressed") !== "true";
      if (b.hasAttribute("data-toggle")) {
        setToggle(b.closest(".chart-card") || document, b, on);
      } else {
        var group = b.getAttribute("data-group");
        document.body.classList.toggle("hide-" + group, !on);
        document.querySelectorAll('.legend-toggle[data-group="' + group + '"]').forEach(function (x) {
          x.setAttribute("aria-pressed", on ? "true" : "false");
        });
      }
      return;
    }
    var label = t.closest(".label-toggle");
    if (label) { labelToggle(label); return; }
    if (t.closest("a, button, input, select, textarea, label, summary")) return;
    var el = t.closest("[data-team]");
    if (el && !document.body.classList.contains("brushing")) pick(el.getAttribute("data-team"));
  });
  document.addEventListener("keydown", function (e) {
    var g = e.target && e.target.closest && e.target.closest(".label-toggle");
    if (g && (e.key === "Enter" || e.key === " ")) { e.preventDefault(); labelToggle(g); }
  });

  // --- zoom ---
  function zoomTo(wrap, lo, hi) {
    if (!tools || !(hi > lo)) return;
    var name = wrap.getAttribute("data-zoom");
    var url = "/analysis/reports/" + tools.getAttribute("data-report") + "/charts/" + encodeURIComponent(name) +
      "?lo=" + lo.toFixed(2) + "&hi=" + hi.toFixed(2) + "&state=" + encodeURIComponent(tools.getAttribute("data-state"));
    wrap.classList.add("loading");
    fetch(url, { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.text() : ""; })
      .then(function (html) { wrap.classList.remove("loading"); if (html) replace(wrap, html); })
      .catch(function () { wrap.classList.remove("loading"); });
  }
  function replace(wrap, html) {
    var holder = document.createElement("div");
    holder.innerHTML = html.trim();
    var next = holder.firstElementChild;
    if (!next) return;
    wrap.replaceWith(next);
    init(next);
  }
  function zoomControls(wrap) {
    var card = wrap.closest(".chart-card");
    if (!card || card.querySelector(".zoom-controls")) return;
    var name = wrap.getAttribute("data-zoom");
    var box = document.createElement("div");
    box.className = "zoom-controls small";
    box.innerHTML = '<span class="muted">Drag across the chart to zoom.</span> ' +
      '<details><summary>Zoom to…</summary><form><label>From <input name="lo" type="number" step="any" required></label> ' +
      '<label>to <input name="hi" type="number" step="any" required></label> <button type="submit">Zoom</button>' +
      '<span class="muted"> ' + (name === "score_hist" ? "points" : "minutes") + '</span></form></details> ' +
      '<button type="button" class="link zoom-reset" hidden>Reset zoom</button>';
    card.appendChild(box);
    box.querySelector("form").addEventListener("submit", function (e) {
      e.preventDefault();
      var f = e.target, cur = card.querySelector(".chart-wrap[data-zoom]");
      if (cur) zoomTo(cur, Number(f.lo.value), Number(f.hi.value));
    });
    box.querySelector(".zoom-reset").addEventListener("click", function () {
      var cur = card.querySelector(".chart-wrap[data-zoom]");
      if (cur && original[name]) replace(cur, original[name]);
    });
  }
  function zoomable(wrap) {
    var name = wrap.getAttribute("data-zoom");
    if (!name || !tools) return;
    if (!wrap.hasAttribute("data-zoomed")) original[name] = wrap.outerHTML;
    zoomControls(wrap);
    var card = wrap.closest(".chart-card");
    if (card) card.querySelector(".zoom-reset").hidden = !wrap.hasAttribute("data-zoomed");
    var svg = wrap.querySelector("svg"), x = wrap.getAttribute("data-x").split(",").map(Number);
    var vb = svg.viewBox.baseVal, start = null, rect = null;
    svg.style.touchAction = "pan-y";
    function svgX(e) { var r = svg.getBoundingClientRect(); return (e.clientX - r.left) * vb.width / r.width; }
    function clamp(px) { return Math.min(Math.max(px, x[2]), x[3]); }
    function domain(px) { return x[0] + (px - x[2]) / (x[3] - x[2]) * (x[1] - x[0]); }
    function move(e) {
      if (start === null) return;
      var px = clamp(svgX(e));
      rect.setAttribute("x", Math.min(px, start));
      rect.setAttribute("width", Math.abs(px - start));
      if (Math.abs(px - start) > 4) document.body.classList.add("brushing");
    }
    function up(e) {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      if (start === null) return;
      var px = clamp(svgX(e)), a = Math.min(px, start), b = Math.max(px, start);
      rect.remove();
      start = null;
      setTimeout(function () { document.body.classList.remove("brushing"); }, 0);
      if (b - a >= 6) zoomTo(wrap, domain(a), domain(b));
    }
    svg.addEventListener("pointerdown", function (e) {
      if (e.button) return;
      var px = svgX(e);
      if (px < x[2] || px > x[3]) return;
      start = px;
      rect = document.createElementNS(NS, "rect");
      rect.setAttribute("class", "brush");
      rect.setAttribute("x", px); rect.setAttribute("width", 0);
      rect.setAttribute("y", 20); rect.setAttribute("height", Math.max(vb.height - 54, 1));
      svg.appendChild(rect);
      window.addEventListener("pointermove", move);
      window.addEventListener("pointerup", up);
    });
  }

  // --- the projection ---
  var pt = document.querySelector(".projection-toggle");
  if (pt) {
    var block = document.getElementById(pt.getAttribute("aria-controls"));
    var showProjection = function (on) {
      block.hidden = !on;
      pt.setAttribute("aria-pressed", on ? "true" : "false");
      pt.textContent = on ? "Hide the projection" : "Show the projection";
      store("cpsb-projection", on ? "on" : "off");
    };
    pt.hidden = false;
    showProjection(store("cpsb-projection") !== "off");
    pt.addEventListener("click", function () { showProjection(block.hidden); });
  }

  function init(wrap) {
    tips(wrap);
    if (wrap.hasAttribute("data-points") && window.chartCrosshair) window.chartCrosshair(wrap);
    zoomable(wrap);
    applyToggles(wrap.closest(".chart-card"));
    applyPick(wrap);
  }
  document.querySelectorAll(".chart-wrap").forEach(function (wrap) {
    tips(wrap);
    zoomable(wrap);
  });
  applyPick();

  // --- print or save as PDF (#69): the browser's dialog; the page title names the PDF ---
  var bar = document.querySelector(".export-bar"), pageTitle = document.title;
  if (bar) {
    bar.querySelector(".export-print").addEventListener("click", function () { window.print(); });
    window.addEventListener("beforeprint", function () { document.title = bar.getAttribute("data-filename") || pageTitle; });
    window.addEventListener("afterprint", function () { document.title = pageTitle; });
  }
  document.querySelectorAll(".js-only").forEach(function (el) { el.hidden = false; });
})();
