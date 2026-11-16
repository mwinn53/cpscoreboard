// Expandable rows on the scoreboard: the ▸ button under a team inserts a row with this
// round's sparklines (/partials/spark/<team>). Open rows survive the board's auto-refresh:
// they're re-inserted from the last copy at once, then refreshed in the background.
// The watched teams' rows (the first table) open by default; one the viewer closes stays closed.
(function () {
  "use strict";
  var open = new Set();   // "tableIndex:team"
  var closed = new Set(); // watched rows the viewer closed
  var cache = {};         // team -> last HTML

  function keyOf(btn) {
    var tables = Array.prototype.slice.call(document.querySelectorAll("#board table.board"));
    return tables.indexOf(btn.closest("table")) + ":" + btn.dataset.team;
  }

  function load(row, team) {
    fetch("/partials/spark/" + encodeURIComponent(team), { credentials: "same-origin" })
      .then(function (r) { return r.ok ? r.text() : Promise.reject(r.status); })
      .then(function (html) { cache[team] = html; row.firstChild.innerHTML = html; })
      .catch(function () { if (!cache[team]) row.firstChild.textContent = "Couldn't load the trend."; });
  }

  function expand(btn) {
    var tr = btn.closest("tr"), team = btn.dataset.team;
    var row = document.createElement("tr");
    row.className = "spark-row";
    var td = document.createElement("td");
    td.colSpan = tr.children.length;
    td.innerHTML = cache[team] || '<span class="muted small">Loading…</span>';
    row.appendChild(td);
    tr.after(row);
    btn.setAttribute("aria-expanded", "true");
    load(row, team);
  }

  function collapse(btn) {
    var next = btn.closest("tr").nextElementSibling;
    if (next && next.classList.contains("spark-row")) next.remove();
    btn.setAttribute("aria-expanded", "false");
  }

  document.addEventListener("click", function (e) {
    var btn = e.target.closest("#board button.expand");
    if (!btn) return;
    var key = keyOf(btn);
    if (btn.getAttribute("aria-expanded") === "true") { collapse(btn); open.delete(key); closed.add(key); }
    else { expand(btn); open.add(key); closed.delete(key); }
  });

  function restore() {
    document.querySelectorAll("#board table.watch-table button.expand").forEach(function (btn) {
      var key = keyOf(btn);
      if (!closed.has(key)) open.add(key);
    });
    document.querySelectorAll("#board button.expand").forEach(function (btn) {
      if (open.has(keyOf(btn)) && btn.getAttribute("aria-expanded") !== "true") expand(btn);
    });
  }

  document.body.addEventListener("htmx:afterSwap", function (e) {
    if (e.detail.target && e.detail.target.id === "board") restore();
  });
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", restore);
  else restore();
})();
