from __future__ import annotations

import datetime as dt
import json
import re
from pathlib import Path

from bs4 import BeautifulSoup
from jinja2 import Environment, select_autoescape

_env = Environment(autoescape=select_autoescape(["html", "xml"]))
_env.trim_blocks = True

_TEXT_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


def description_text(html: str, limit: int = 4000) -> str:
    if not html:
        return ""
    text = BeautifulSoup(html, "html.parser").get_text("\n")
    text = _WS.sub(" ", text)
    return text.strip()[:limit]


def collect_reports(reports_dir: str | Path) -> dict:
    d = Path(reports_dir)
    runs = []
    jobs_by_id: dict[str, dict] = {}
    for run_dir in sorted(d.iterdir()):
        if not run_dir.is_dir():
            continue
        jf = run_dir / "report.json"
        if not jf.exists():
            continue
        ts = run_dir.name
        try:
            parsed = json.loads(jf.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        runs.append({"ts": ts, "count": len(parsed)})
        for j in parsed:
            j["_run_ts"] = ts
            key = j.get("job_id_hash") or j.get("title", "") + "|" + j.get("company", "")
            jobs_by_id[key] = j
    return {"runs": runs, "jobs": list(jobs_by_id.values())}


def _fmt_ts(ts: str) -> str:
    try:
        return dt.datetime.strptime(ts, "%Y%m%d-%H%M%S").strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return ts


def _score(val) -> str:
    try:
        return f"{float(val):.2f}"
    except (TypeError, ValueError):
        return str(val or "")


def compute_stats(jobs: list[dict]) -> dict:
    statuses = {}
    decisions = {}
    sources = {}
    new_count = closed_count = remote_count = 0
    total_score = 0.0
    score_n = 0
    first_seen = last_seen = None
    for j in jobs:
        status = j.get("authentic_status") or "UNKNOWN"
        statuses[status] = statuses.get(status, 0) + 1
        decision = j.get("decision") or "NONE"
        decisions[decision] = decisions.get(decision, 0) + 1
        for s in j.get("seen_sources") or []:
            sources[s] = sources.get(s, 0) + 1
        if j.get("genuinely_new") and status != "CLOSED":
            new_count += 1
        if status == "CLOSED":
            closed_count += 1
        if j.get("remote"):
            remote_count += 1
        ms = j.get("match_score")
        if isinstance(ms, (int, float)):
            total_score += float(ms)
            score_n += 1
        for f in (j.get("first_seen_at"), j.get("posted_at")):
            if f:
                try:
                    d = dt.datetime.fromtimestamp(float(f))
                except (TypeError, ValueError, OSError):
                    continue
                if first_seen is None or d < first_seen:
                    first_seen = d
                if last_seen is None or d > last_seen:
                    last_seen = d
    return {
        "statuses": dict(sorted(statuses.items(), key=lambda kv: -kv[1])),
        "decisions": dict(sorted(decisions.items(), key=lambda kv: -kv[1])),
        "sources": dict(sorted(sources.items(), key=lambda kv: -kv[1])),
        "new_count": new_count,
        "closed_count": closed_count,
        "remote_count": remote_count,
        "avg_match": round(total_score / score_n, 2) if score_n else 0.0,
        "first_seen": first_seen.strftime("%Y-%m-%d %H:%M") if first_seen else "",
        "last_seen": last_seen.strftime("%Y-%m-%d %H:%M") if last_seen else "",
    }


DASHBOARD_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Job Harness Dashboard</title>
<style>
*{box-sizing:border-box}
body{font-family:system-ui,-apple-system,sans-serif;margin:0;background:#f5f6f8;color:#1c1e21}
header{background:#10233f;color:#fff;padding:18px 28px;display:flex;flex-wrap:wrap;gap:12px;align-items:center;justify-content:space-between}
header h1{margin:0;font-size:1.25rem}
header .sub{font-size:.8rem;opacity:.75}
main{padding:20px 28px;max-width:1400px;margin:0 auto}
.cards{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin:16px 0}
.card{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px}
.card .num{font-size:1.6rem;font-weight:700}
.card .lbl{font-size:.72rem;text-transform:uppercase;letter-spacing:.06em;color:#6b7280}
.card .hint{font-size:.72rem;color:#9ca3af;margin-top:4px}
.bars{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:12px;margin:16px 0}
.bar-card{background:#fff;border:1px solid #e3e6ea;border-radius:10px;padding:14px 16px}
.bar-card h3{margin:0 0 10px;font-size:.85rem;color:#374151}
.bar-row{display:flex;align-items:center;gap:8px;margin:5px 0;font-size:.78rem}
.bar-row .k{width:110px;flex:none;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:#4b5563}
.bar-row .track{flex:1;background:#eef1f5;border-radius:6px;height:14px;overflow:hidden}
.bar-row .fill{height:100%;border-radius:6px;background:#2563eb}
.bar-row .v{width:44px;flex:none;text-align:right;color:#374151}
.toolbar{display:flex;flex-wrap:wrap;gap:8px;margin:16px 0;align-items:center}
.toolbar input[type=search]{flex:1;min-width:200px;padding:9px 12px;border:1px solid #d1d5db;border-radius:8px;font-size:.85rem}
.toolbar select{padding:9px 10px;border:1px solid #d1d5db;border-radius:8px;font-size:.85rem;background:#fff}
.toolbar label{font-size:.8rem;color:#4b5563;display:flex;align-items:center;gap:5px}
table{width:100%;border-collapse:collapse;background:#fff;border:1px solid #e3e6ea;border-radius:10px;overflow:hidden;font-size:.82rem}
th,td{padding:9px 10px;border-bottom:1px solid #eef1f5;text-align:left;vertical-align:top}
th{background:#f8fafc;font-size:.72rem;text-transform:uppercase;letter-spacing:.04em;color:#6b7280;cursor:pointer;white-space:nowrap;user-select:none}
th:hover{color:#111827}
tbody tr{cursor:pointer}
tbody tr:hover{background:#f0f6ff}
tr.closed{opacity:.55}
tr.closed .title-cell{text-decoration:line-through}
.badge{display:inline-block;padding:2px 8px;border-radius:99px;font-size:.68rem;font-weight:600}
.b-AUTO_ACCEPT{background:#dcfce7;color:#166534}
.b-REVIEW{background:#fef9c3;color:#854d0e}
.b-REJECT{background:#fee2e2;color:#991b1b}
.b-NONE{background:#f3f4f6;color:#4b5563}
.b-AUTHENTIC{background:#dbeafe;color:#1e40af}
.b-CLOSED{background:#fee2e2;color:#991b1b}
.b-BLOCKED{background:#f3f4f6;color:#4b5563}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:5px}
.dot-new{background:#16a34a}.dot-dup{background:#d1d5db}
a.btn{display:inline-block;padding:4px 10px;background:#1a73e8;color:#fff;text-decoration:none;border-radius:6px;font-size:.75rem}
.count{margin:8px 0;font-size:.8rem;color:#6b7280}
.empty{text-align:center;padding:40px;color:#9ca3af;font-size:.9rem}
.drawer-bg{position:fixed;inset:0;background:rgba(15,23,42,.55);display:none;z-index:40}
.drawer{position:fixed;top:0;right:-720px;width:min(720px,100vw);height:100vh;background:#fff;z-index:50;transition:right .22s ease;box-shadow:-8px 0 30px rgba(0,0,0,.18);overflow-y:auto}
.drawer.open{right:0}
.drawer .head{position:sticky;top:0;background:#10233f;color:#fff;padding:14px 18px;display:flex;justify-content:space-between;align-items:flex-start;gap:10px;z-index:1}
.drawer .head h2{margin:0;font-size:1.05rem;line-height:1.3}
.drawer .head .company{opacity:.8;font-size:.85rem;margin-top:3px}
.drawer .close{background:none;border:none;color:#fff;font-size:1.3rem;cursor:pointer;line-height:1}
.drawer .body{padding:18px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin:10px 0}
.chip{padding:3px 9px;border-radius:99px;font-size:.72rem;background:#eef1f5;color:#374151}
.desc{background:#f8fafc;border:1px solid #e3e6ea;border-radius:8px;padding:12px;font-size:.84rem;line-height:1.55;white-space:pre-wrap;word-break:break-word;max-height:340px;overflow-y:auto}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:8px;margin:12px 0}
.kv{background:#f8fafc;border:1px solid #eef1f5;border-radius:8px;padding:8px 10px;font-size:.76rem;word-break:break-word}
.kv .k{color:#6b7280;text-transform:uppercase;font-size:.66rem;letter-spacing:.04em;margin-bottom:2px}
.kv .v{color:#111827}
a{color:#1a73e8}
h3.sec{font-size:.9rem;margin:20px 0 6px;color:#374151;border-bottom:1px solid #eef1f5;padding-bottom:6px}
.footer{text-align:center;color:#9ca3af;font-size:.75rem;padding:24px}
@media (max-width:720px){main{padding:12px}table{font-size:.74rem}th,td{padding:6px}}
</style></head><body>
<header>
  <div>
    <h1>Job Harness Dashboard</h1>
    <div class="sub">{{ runs|length }} run(s) &middot; {{ jobs|length }} unique jobs &middot; generated {{ generated_at }}</div>
  </div>
  <a class="btn" style="background:#16a34a" href="{{ latest_run }}/report.html" target="_blank">Latest report</a>
</header>
<main>
  <div class="cards">
    <div class="card"><div class="num">{{ jobs|length }}</div><div class="lbl">Unique jobs</div><div class="hint">across {{ runs|length }} runs</div></div>
    <div class="card"><div class="num">{{ stats.new_count }}</div><div class="lbl">Genuinely new</div><div class="hint">fresh, not closed</div></div>
    <div class="card"><div class="num">{{ stats.closed_count }}</div><div class="lbl">Closed</div><div class="hint">unreachable / expired</div></div>
    <div class="card"><div class="num">{{ stats.remote_count }}</div><div class="lbl">Remote</div><div class="hint">postings</div></div>
    <div class="card"><div class="num">{{ stats.avg_match }}</div><div class="lbl">Avg match</div><div class="hint">BM25 score</div></div>
    <div class="card"><div class="num">{{ stats.statuses.get('AUTHENTIC', 0) }}</div><div class="lbl">Authentic</div><div class="hint">reachable now</div></div>
  </div>

  <div class="bars">
    <div class="bar-card"><h3>Decision</h3>
      {% for k, v in stats.decisions.items() %}
      <div class="bar-row"><span class="k">{{ k }}</span><div class="track"><div class="fill" style="width:{{ (100*v/stats.decisions.values()|sum)|round(1) }}%;background:{{ {'AUTO_ACCEPT':'#16a34a','REVIEW':'#eab308','REJECT':'#ef4444'}.get(k,'#6b7280') }}"></div></div><span class="v">{{ v }}</span></div>
      {% endfor %}
    </div>
    <div class="bar-card"><h3>Source</h3>
      {% for k, v in stats.sources.items() %}
      <div class="bar-row"><span class="k">{{ k }}</span><div class="track"><div class="fill" style="width:{{ (100*v/stats.sources.values()|sum)|round(1) }}%;background:#2563eb"></div></div><span class="v">{{ v }}</span></div>
      {% endfor %}
    </div>
    <div class="bar-card"><h3>Status</h3>
      {% for k, v in stats.statuses.items() %}
      <div class="bar-row"><span class="k">{{ k }}</span><div class="track"><div class="fill" style="width:{{ (100*v/stats.statuses.values()|sum)|round(1) }}%;background:#6b7280"></div></div><span class="v">{{ v }}</span></div>
      {% endfor %}
    </div>
  </div>

  <div class="toolbar">
    <input type="search" id="q" placeholder="Search title, company, location, tech...">
    <select id="fDecision"><option value="">All decisions</option>{% for k in stats.decisions %}<option>{{ k }}</option>{% endfor %}</select>
    <select id="fStatus"><option value="">All statuses</option>{% for k in stats.statuses %}<option>{{ k }}</option>{% endfor %}</select>
    <select id="fSource"><option value="">All sources</option>{% for k in stats.sources %}<option>{{ k }}</option>{% endfor %}</select>
    <label><input type="checkbox" id="fRemote"> remote only</label>
    <label><input type="checkbox" id="fNew"> new only</label>
  </div>

  <div class="count" id="count"></div>
  <table id="tbl">
    <thead><tr>
      <th data-k="freshness">Fresh</th><th data-k="title">Title</th><th data-k="company">Company</th>
      <th data-k="location">Location</th><th data-k="date_posted">Date</th><th data-k="salary_if_present">Salary</th>
      <th data-k="match_score">Match</th><th data-k="decision">Decision</th><th data-k="authentic_status">Status</th>
      <th data-k="source_name">Source</th><th>Apply</th>
    </tr></thead>
    <tbody></tbody>
  </table>
  <div class="empty" id="empty" style="display:none">No jobs match the current filters.</div>
</main>
<div class="drawer-bg" id="bg"></div>
<div class="drawer" id="drawer"><div class="head"><div><h2 id="dTitle"></h2><div class="company" id="dCompany"></div></div><button class="close" id="dClose">&times;</button></div><div class="body" id="dBody"></div></div>
<div class="footer">jobharness dashboard &middot; data from reports/*/report.json &middot; no fabricated fields</div>
<script>
const JOBS = {{ jobs_json|safe }};
const FIELDS = ["role","title","company","location","remote","experience_needed","date_posted","freshness","salary_if_present","seniority","tech_stack_keywords","apply_url_direct","source_url","source_name","posted_at","first_seen_at","job_id_hash","authentic_status","confidence_score","valid_through","employer_domain","missing_fields","genuinely_new","seen_sources","original_url","canonical_url","final_url","posting_id","canonical_job_id","block_key","possible_duplicate_of","identity_score","authenticity_score","match_score","decision","matched_via","description_fingerprint","source_authority","job_version","evidence","negative_evidence","reason","_run_ts"];
const fmt = v => v === null || v === undefined ? "" : String(v);
const esc = s => fmt(s).replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const badge = (v, cls) => v ? `<span class="badge ${cls}${esc(v)}">${esc(v)}</span>` : "";
const pct = v => { const n = parseFloat(v); return isFinite(n) ? n.toFixed(2) : ""; };
let sortKey = "", sortDir = 1;

function rowHtml(j) {
  const loc = j.location + (j.remote ? " <span class='chip'>remote</span>" : "");
  const freshDot = j.genuinely_new && j.authentic_status !== "CLOSED" ? "<span class='dot dot-new'></span>" : "<span class='dot dot-dup'></span>";
  return `<tr class="${j.authentic_status === "CLOSED" ? "closed" : ""}" data-i="${JOBS.indexOf(j)}">
    <td>${freshDot}${esc(j.freshness)}</td>
    <td class="title-cell">${esc(j.title)}<br><small style="color:#6b7280">${esc(j.role)}</small></td>
    <td>${esc(j.company)}</td><td>${loc}</td><td>${esc(j.date_posted)}</td>
    <td>${esc(j.salary_if_present)}</td><td>${pct(j.match_score)}</td>
    <td>${badge(j.decision, "b-")}</td><td>${badge(j.authentic_status, "b-")}</td>
    <td>${esc(j.source_name)}</td>
    <td>${j.apply_url_direct ? `<a class="btn" href="${esc(j.apply_url_direct)}" target="_blank" onclick="event.stopPropagation()">Apply</a>` : ""}</td>
  </tr>`;
}

function render() {
  const q = document.getElementById("q").value.trim().toLowerCase();
  const fd = document.getElementById("fDecision").value;
  const fs = document.getElementById("fStatus").value;
  const fsrc = document.getElementById("fSource").value;
  const fr = document.getElementById("fRemote").checked;
  const fn = document.getElementById("fNew").checked;
  let list = JOBS.filter(j => {
    if (fd && j.decision !== fd) return false;
    if (fs && j.authentic_status !== fs) return false;
    if (fsrc && j.source_name !== fsrc && !(j.seen_sources || []).includes(fsrc)) return false;
    if (fr && !j.remote) return false;
    if (fn && !(j.genuinely_new && j.authentic_status !== "CLOSED")) return false;
    if (q) {
      const hay = [j.title, j.company, j.location, j.role, (j.tech_stack_keywords||[]).join(" "), j.salary_if_present, j.experience_needed, j.employer_domain].join(" ").toLowerCase();
      if (!hay.includes(q)) return false;
    }
    return true;
  });
  if (sortKey) {
    list.sort((a, b) => {
      let x = a[sortKey], y = b[sortKey];
      if (sortKey === "match_score" || sortKey === "confidence_score") { x = parseFloat(x)||0; y = parseFloat(y)||0; }
      else { x = fmt(x).toLowerCase(); y = fmt(y).toLowerCase(); }
      return (x < y ? -1 : x > y ? 1 : 0) * sortDir;
    });
  }
  document.querySelector("#tbl tbody").innerHTML = list.map(rowHtml).join("");
  document.getElementById("empty").style.display = list.length ? "none" : "block";
  document.getElementById("count").textContent = list.length + " of " + JOBS.length + " jobs";
}

function escFor(t){ return t.replace(/"/g, "&quot;").replace(/</g, "&lt;"); }

function openJob(j) {
  document.getElementById("dTitle").textContent = j.title || "(untitled)";
  document.getElementById("dCompany").innerHTML = `${escFor(j.company || "")} &middot; ${escFor(j.location || "")} ${j.remote ? "&middot; REMOTE" : ""}`;
  const chips = [];
  chips.push(`<span class="badge b-${esc(j.decision)}">${esc(j.decision || "NONE")}</span>`);
  chips.push(`<span class="badge b-${esc(j.authentic_status)}">${esc(j.authentic_status || "UNKNOWN")}</span>`);
  if (j.genuinely_new) chips.push(`<span class="badge b-AUTO_ACCEPT">NEW</span>`);
  if (j.freshness) chips.push(`<span class="chip">${esc(j.freshness)}</span>`);
  if (j.seniority) chips.push(`<span class="chip">${esc(j.seniority)}</span>`);
  (j.tech_stack_keywords || []).forEach(t => chips.push(`<span class="chip">${esc(t)}</span>`));
  (j.seen_sources || []).forEach(s => chips.push(`<span class="chip">source: ${esc(s)}</span>`));
  const chipsHtml = `<div class="chips">${chips.join("")}</div>`;
  const desc = esc(j.description || "(no description stored)");
  const links = [];
  if (j.apply_url_direct) links.push(`<a class="btn" href="${esc(j.apply_url_direct)}" target="_blank">Apply</a>`);
  if (j.original_url) links.push(`<a href="${esc(j.original_url)}" target="_blank">original</a>`);
  if (j.source_url) links.push(`<a href="${esc(j.source_url)}" target="_blank">source</a>`);
  if (j.canonical_url) links.push(`<a href="${esc(j.canonical_url)}" target="_blank">canonical</a>`);
  const kv = FIELDS.filter(f => !["description"].includes(f)).map(f => {
    let v = j[f];
    if (f === "match_score" || f === "identity_score" || f === "authenticity_score") v = pct(v);
    if (f === "first_seen_at") v = v ? new Date(parseFloat(v) * 1000).toISOString() : "";
    if (Array.isArray(v)) v = v.join(", ");
    if (v === undefined || v === null || v === "" || v === false) return "";
    if (f === "remote") v = "true";
    return `<div class="kv"><div class="k">${f}</div><div class="v">${esc(String(v))}</div></div>`;
  }).join("");
  const sec = (t, body) => body ? `<h3 class="sec">${t}</h3>${body}` : "";
  document.getElementById("dBody").innerHTML =
    chipsHtml +
    `<div style="margin:8px 0">${links.join(" ")}</div>` +
    sec("Scores", `<div class="grid2"><div class="kv"><div class="k">match</div><div class="v">${pct(j.match_score)}</div></div><div class="kv"><div class="k">identity</div><div class="v">${pct(j.identity_score)}</div></div><div class="kv"><div class="k">authenticity</div><div class="v">${pct(j.authenticity_score)}</div></div><div class="kv"><div class="k">confidence</div><div class="v">${esc(j.confidence_score)}</div></div></div>`) +
    sec("Reasons", (j.reason || []).map(r => `<span class="chip">${esc(r)}</span>`).join("")) +
    sec("Evidence", (j.evidence || []).map(r => `<span class="chip">${esc(r)}</span>`).join("")) +
    (j.negative_evidence && j.negative_evidence.length ? sec("Negative evidence", j.negative_evidence.map(r => `<span class="chip">${esc(r)}</span>`).join("")) : "") +
    (j.missing_fields && j.missing_fields.length ? sec("Missing fields", j.missing_fields.map(r => `<span class="chip">${esc(r)}</span>`).join("")) : "") +
    sec("Description", `<div class="desc">${desc}</div>`) +
    sec("All fields", `<div class="grid2">${kv}</div>`);
  document.getElementById("drawer").classList.add("open");
  document.getElementById("bg").style.display = "block";
}

document.addEventListener("click", e => {
  const tr = e.target.closest("tbody tr");
  if (tr) openJob(JOBS[parseInt(tr.dataset.i)]);
  if (e.target.closest("#dClose") || e.target.id === "bg") {
    document.getElementById("drawer").classList.remove("open");
    document.getElementById("bg").style.display = "none";
  }
});
document.querySelectorAll("th").forEach(th => th.addEventListener("click", () => {
  const k = th.dataset.k;
  if (sortKey === k) sortDir *= -1; else { sortKey = k; sortDir = 1; }
  render();
}));
["q", "fDecision", "fStatus", "fSource", "fRemote", "fNew"].forEach(id =>
  document.getElementById(id).addEventListener(id === "q" ? "input" : "change", render));
render();
</script></body></html>"""


def build_dashboard(reports_dir: str | Path, out_path: str | Path) -> dict:
    data = collect_reports(reports_dir)
    jobs = data["jobs"]
    for j in jobs:
        j["_description_text"] = description_text(j.get("description") or "")
        j["_score_match"] = _score(j.get("match_score"))
        j["_score_identity"] = _score(j.get("identity_score"))
        j["_score_authenticity"] = _score(j.get("authenticity_score"))
        j["_run_ts_fmt"] = _fmt_ts(j.get("_run_ts") or "")
    stats = compute_stats(jobs)
    for j in jobs:
        j["match_score"] = j.pop("_score_match")
        j["identity_score"] = j.pop("_score_identity")
        j["authenticity_score"] = j.pop("_score_authenticity")
        j["description"] = j.pop("_description_text")
    html = _env.from_string(DASHBOARD_HTML).render(
        jobs=jobs,
        runs=data["runs"],
        stats=stats,
        latest_run=data["runs"][-1]["ts"] if data["runs"] else "",
        jobs_json=json.dumps(jobs).replace("</", "<\\/"),
        generated_at=dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return {"out": str(out), "jobs": len(jobs), "runs": len(data["runs"]), "stats": stats}
