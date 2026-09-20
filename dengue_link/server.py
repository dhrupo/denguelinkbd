import hashlib
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from dengue_link.pipeline import run

ROOT = Path(".")
# Changes whenever the page design changes, so browsers drop copies saved from an older design.
VERSION = hashlib.sha256(
    b"".join((Path(__file__).parent / f).read_bytes() for f in ("map_template.html", "mapview.py", "server.py"))
).hexdigest()[:12]
VALID_SECONDS = 24 * 60 * 60
_building = threading.Lock()
_state = {}

LOADING = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Dengue Link — loading</title>
<script>try { var t = localStorage.getItem("dl-theme"); if (t) document.documentElement.setAttribute("data-theme", t); } catch (e) {}</script>
<style>
:root { --bg:#F8FAFC; --fg:#0F172A; --muted:#475569; --bar:#1E40AF; --track:#DBEAFE; }
@media (prefers-color-scheme: dark) { :root:not([data-theme="light"]) { --bg:#0B1220; --fg:#E2E8F0; --muted:#A3B1C6; --bar:#93C5FD; --track:#26324A; } }
:root[data-theme="dark"] { --bg:#0B1220; --fg:#E2E8F0; --muted:#A3B1C6; --bar:#93C5FD; --track:#26324A; }
body { margin:0; padding:24px 16px; background:var(--bg); color:var(--fg); font:16px/1.5 system-ui,sans-serif; }
main { max-width:560px; margin:10vh auto 0; }
progress { width:100%; height:14px; appearance:none; border:0; border-radius:7px; background:var(--track); overflow:hidden; }
progress::-webkit-progress-bar { background:var(--track); }
progress::-webkit-progress-value { background:var(--bar); transition:width .3s; }
progress::-moz-progress-bar { background:var(--bar); }
.pct { font-size:2rem; font-weight:700; font-variant-numeric:tabular-nums; margin:8px 0 0; }
.muted { color:var(--muted); font-size:.9375rem; }
@media (prefers-reduced-motion: reduce) { progress::-webkit-progress-value { transition:none; } }
</style></head>
<body><main>
<h1 id="title">Dengue Link</h1>
<label for="bar" class="muted" id="what">Getting today's dengue figures…</label>
<progress id="bar" max="100" value="0">0%</progress>
<p class="pct" id="pct">0%</p>
<p id="status" aria-live="polite"></p>
<p class="muted" id="elapsed" aria-hidden="true"></p>
<p class="muted" id="once">This only happens once a day. After that the map opens straight away.</p>
</main>
<script>
var DAY = 24 * 60 * 60 * 1000;
var VERSION = "__VERSION__";
var BN = false;
try { BN = (localStorage.getItem("dl-lang") || ((navigator.language || "").indexOf("bn") === 0 ? "bn" : "en")) === "bn"; } catch (e) {}
var W = BN ? {
  title: "ডেঙ্গু লিংক", what: "আজকের ডেঙ্গুর তথ্য আনা হচ্ছে…", once: "দিনে একবারই এটা হয়। এরপর মানচিত্র সঙ্গে সঙ্গে খুলবে।",
  start: "শুরু হচ্ছে…", collect: "বিভিন্ন উৎস থেকে হিসাব আনা হচ্ছে…", forecast: "পূর্বাভাস তৈরি হচ্ছে…", done: "হয়ে গেছে",
  secs: function (n) { return n.toLocaleString("bn-BD") + " সেকেন্ড হলো (সাধারণত ২০ সেকেন্ডের মতো লাগে)"; },
  fail: "আজকের তথ্য আনা যায়নি। আবার চেষ্টা করতে পাতাটি রিলোড করুন।", num: function (n) { return n.toLocaleString("bn-BD"); }
} : {
  title: "Dengue Link", what: "Getting today's dengue figures…", once: "This only happens once a day. After that the map opens straight away.",
  start: "Starting…", collect: "Collecting the figures from each source…", forecast: "Working out the forecast…", done: "Done",
  secs: function (n) { return n + " seconds so far (it usually takes about 20)"; },
  fail: "Couldn't get today's figures. Please reload the page to try again.", num: function (n) { return String(n); }
};
document.documentElement.lang = BN ? "bn" : "en";
document.getElementById("title").textContent = W.title;
document.getElementById("what").textContent = W.what;
document.getElementById("once").textContent = W.once;
document.getElementById("status").textContent = W.start;

function openStore() {
  return new Promise(function (resolve, reject) {
    var req = indexedDB.open("dengue-link", 1);
    req.onupgradeneeded = function () { req.result.createObjectStore("pages"); };
    req.onsuccess = function () { resolve(req.result); };
    req.onerror = function () { reject(req.error); };
  });
}
function load(db) {
  return new Promise(function (resolve) {
    var req = db.transaction("pages").objectStore("pages").get("map");
    req.onsuccess = function () { resolve(req.result); };
    req.onerror = function () { resolve(null); };
  });
}
function save(db, record) {
  try { db.transaction("pages", "readwrite").objectStore("pages").put(record, "map"); } catch (e) {}
}
function show(html) { document.open(); document.write(html); document.close(); }

function setProgress(pct) {
  document.getElementById("bar").value = pct;
  document.getElementById("bar").textContent = pct + "%";
  document.getElementById("pct").textContent = W.num(pct) + "%";
  document.getElementById("status").textContent = pct >= 100 ? W.done : pct >= 88 ? W.forecast : pct >= 10 ? W.collect : W.start;
}

function fetchFresh(db) {
  var started = Date.now();
  var poll = setInterval(function () {
    document.getElementById("elapsed").textContent = W.secs(Math.round((Date.now() - started) / 1000));
    fetch("/progress").then(function (r) { return r.json(); }).then(function (s) { setProgress(s.pct); }).catch(function () {});
  }, 1000);
  fetch("/map").then(function (r) {
    if (!r.ok) throw new Error("build failed");
    var builtAt = Number(r.headers.get("X-Built-At")) || 0;
    return r.text().then(function (html) { return { html: html, fetchedAt: builtAt, version: VERSION }; });
  }).then(function (record) {
    clearInterval(poll);
    setProgress(100);
    if (db && record.fetchedAt) save(db, record);
    show(record.html);
  }).catch(function () {
    clearInterval(poll);
    document.getElementById("status").textContent = W.fail;
  });
}

openStore().then(function (db) {
  return load(db).then(function (rec) {
    if (rec && rec.version === VERSION && Date.now() - rec.fetchedAt < DAY) show(rec.html);
    else fetchFresh(db);
  });
}).catch(function () { fetchFresh(null); });
</script></body></html>
"""


def _progress(pct, msg):
    _state.update(pct=pct, msg=msg)


def _map():
    with _building:
        if "html" in _state and time.time() - _state["built_at"] < VALID_SECONDS:
            return _state["html"], _state["built_at"]
        _progress(0, "Starting")
        out, model, _ = run(ROOT, progress=_progress)
        html = out.read_text(encoding="utf-8")
        _progress(100, "Done")
        if model is None:
            return html, None
        _state.update(html=html, built_at=time.time())
        return html, _state["built_at"]


class Handler(BaseHTTPRequestHandler):
    def _send(self, status, body, content_type="text/html; charset=utf-8", headers=()):
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        for k, v in headers:
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/":
            self._send(200, LOADING.replace("__VERSION__", VERSION))
        elif self.path == "/progress":
            self._send(200, json.dumps({"pct": _state.get("pct", 0), "msg": _state.get("msg", "Waiting")}), "application/json")
        elif self.path == "/map":
            try:
                html, built_at = _map()
                self._send(200, html, headers=[("X-Built-At", str(int(built_at * 1000)))] if built_at else [])
            except Exception as e:
                _progress(0, f"Build failed: {type(e).__name__}")
                self._send(500, f"<p>Build failed: {type(e).__name__}</p>")
        else:
            self._send(404, "Not found")

    def log_message(self, *args):
        pass


def make_server(port=8000):
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)
