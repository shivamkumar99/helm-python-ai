"""HTML for the MCP Apps (SEP-1865) releases dashboard.

Rendered by hosts that support the ``io.modelcontextprotocol/ui``
extension (Claude, and other MCP Apps hosts) in a sandboxed iframe; the
host posts the tool result via ``postMessage`` and the page renders it as
a table. Hosts without the extension simply show the JSON text result.
"""

from __future__ import annotations

__all__ = ["RELEASES_APP_HTML", "RELEASES_APP_URI"]

RELEASES_APP_URI = "ui://helm/releases.html"

RELEASES_APP_HTML = """\
<!doctype html>
<html>
<head>
<meta charset="utf-8">
<style>
  :root { color-scheme: light dark; }
  body { margin: 0; padding: 12px; font: 13px/1.45 system-ui, sans-serif; }
  h2 { margin: 0 0 2px; font-size: 15px; }
  .sub { opacity: .65; margin-bottom: 10px; font-size: 12px; }
  table { border-collapse: collapse; width: 100%; }
  th, td { text-align: left; padding: 5px 10px 5px 0; white-space: nowrap; }
  th { font-size: 11px; text-transform: uppercase; letter-spacing: .04em;
       opacity: .6; border-bottom: 1px solid rgba(128,128,128,.35); }
  td { border-bottom: 1px solid rgba(128,128,128,.15); }
  .badge { display: inline-block; padding: 1px 8px; border-radius: 999px;
           font-size: 11px; font-weight: 600; }
  .ok { background: rgba(46,160,67,.18); color: #2ea043; }
  .bad { background: rgba(248,81,73,.18); color: #f85149; }
  .other { background: rgba(128,128,128,.18); }
  .empty { opacity: .6; padding: 18px 0; }
</style>
</head>
<body>
<h2>Helm releases</h2>
<div class="sub" id="sub">waiting for data…</div>
<div id="out"></div>
<script>
  function esc(s) {
    return String(s ?? "").replace(/[&<>"]/g,
      c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
  }
  function badge(status) {
    const cls = status === "deployed" ? "ok"
      : /failed|superseded|unknown/.test(status || "") ? "bad" : "other";
    return '<span class="badge ' + cls + '">' + esc(status || "?") + "</span>";
  }
  function render(releases) {
    const sub = document.getElementById("sub");
    const out = document.getElementById("out");
    if (!Array.isArray(releases) || releases.length === 0) {
      sub.textContent = "0 releases";
      out.innerHTML = '<div class="empty">No releases found.</div>';
      return;
    }
    const deployed = releases.filter(r => r.status === "deployed").length;
    sub.textContent = releases.length + " release(s), " + deployed + " deployed";
    const rows = releases.map(r => "<tr>"
      + "<td><strong>" + esc(r.name) + "</strong></td>"
      + "<td>" + esc(r.namespace) + "</td>"
      + "<td>" + badge(r.status) + "</td>"
      + "<td>" + esc(r.revision ?? r.version) + "</td>"
      + "<td>" + esc(r.chart || ((r.chart_name || "") + "-" + (r.chart_version || ""))) + "</td>"
      + "<td>" + esc(r.app_version) + "</td>"
      + "<td>" + esc(String(r.updated || "").slice(0, 19).replace("T", " ")) + "</td>"
      + "</tr>").join("");
    out.innerHTML = "<table><thead><tr><th>Name</th><th>Namespace</th>"
      + "<th>Status</th><th>Rev</th><th>Chart</th><th>App</th><th>Updated</th>"
      + "</tr></thead><tbody>" + rows + "</tbody></table>";
  }
  window.addEventListener("message", (event) => {
    try {
      const content = event.data && event.data.result && event.data.result.content;
      const text = content && content[0] && content[0].text;
      if (text) render(JSON.parse(text));
    } catch (err) {
      document.getElementById("sub").textContent = "could not parse result: " + err;
    }
  });
</script>
</body>
</html>
"""
