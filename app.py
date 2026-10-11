"""
ABHI.DEV V2 // CORE
Next-gen portfolio: Streamlit + Three.js + MongoDB Atlas (with local JSON fallback).

Run:    streamlit run app.py
Needs:  streamlit, pymongo, pandas
Secrets (optional): MONGO_URI, ADMIN_PASSCODE   (or same names as environment variables)
"""

import datetime
import hmac
import html
import json
import os
import threading
import time
import uuid

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

try:
    from pymongo import MongoClient

    HAS_PYMONGO = True
except Exception:  # pymongo missing -> JSON fallback only
    MongoClient = None
    HAS_PYMONGO = False

st.set_page_config(
    page_title="Abhishek Singh // ABHI.DEV V2",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ----------------------------------------------------------------------------
# CONSTANTS
# ----------------------------------------------------------------------------
try:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    BASE_DIR = os.getcwd()

DB_NAME = "abhi_dev_v2"
JSON_PATH = os.path.join(BASE_DIR, "v2_db.json")

PORTAL_USER = "🚀 User View (3D Portfolio)"
PORTAL_ADMIN = "🛡️ Admin Command Center"

CATEGORIES = ["Industrial Automation", "Data & MIS", "Web App", "Excel VBA"]
BASE_TAGS = [
    "Python",
    "Streamlit",
    "Excel VBA / Macros",
    "OpenPyXL",
    "Node.js",
    "SQL",
    "MIS Systems",
]
DEFAULT_ADMIN_PASSCODE = "admin123"

DEFAULT_META = {
    "name": "Abhishek Singh",
    "title": "Full-Stack Developer & Data Automation Engineer",
    "bio": (
        "I build industrial-grade automation, MIS dashboards and data-driven web apps, "
        "turning shop-floor and warehouse data into decisions that ship."
    ),
    "avatar_url": "",
    "resume_url": "",
    "linkedin_url": "",
    "github_url": "https://github.com/abhibhdauriya",
    "email": "singha36161@gmail.com",
}


def now_iso():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds")


def now_ts():
    return datetime.datetime.now(datetime.timezone.utc).timestamp()


def default_projects():
    base = now_ts()
    gh = DEFAULT_META["github_url"]
    return [
        {
            "pid": uuid.uuid4().hex[:12],
            "title": "Industrial CNC Shop-Floor Production Tracker",
            "category": "Industrial Automation",
            "tech": ["Excel VBA", "OpenPyXL", "KPI Dashboards", "CNC Monitoring"],
            "description": (
                "Shop-floor production tracker monitoring 28+ CNC lines. Excel VBA macros and "
                "OpenPyXL automation feed live KPI dashboards for output, downtime and efficiency."
            ),
            "link": gh,
            "file_url": "",
            "created_ts": base,
        },
        {
            "pid": uuid.uuid4().hex[:12],
            "title": "Warehouse Operations & MIS Handover Dashboard",
            "category": "Data & MIS",
            "tech": ["Python", "Pandas", "Dispatch SLAs", "Floor Reconciliation", "MIS Systems"],
            "description": (
                "Python + Pandas dashboard that tracks dispatch SLAs and reconciles floor counts "
                "against system records for clean shift-to-shift MIS handovers."
            ),
            "link": gh,
            "file_url": "",
            "created_ts": base + 0.001,
        },
        {
            "pid": uuid.uuid4().hex[:12],
            "title": "Financial & Statement Analytics Engine",
            "category": "Web App",
            "tech": ["Streamlit", "Pandas", "UPI Statement Parser", "Python"],
            "description": (
                "Streamlit analytics engine that parses UPI and bank statements with Pandas, "
                "categorises transactions and surfaces spending trends and summaries."
            ),
            "link": gh,
            "file_url": "",
            "created_ts": base + 0.002,
        },
    ]


# ----------------------------------------------------------------------------
# SMALL HELPERS (escaping / URLs / parsing)
# ----------------------------------------------------------------------------
def esc(value):
    """HTML-escape everything dynamic. '$' is escaped so Streamlit never starts LaTeX."""
    text = "" if value is None else str(value)
    return html.escape(text, quote=True).replace("$", "&#36;")


def safe_url(url):
    """Return a cleaned http(s) URL or '' if unsafe/invalid."""
    u = str(url or "").strip().replace(" ", "%20")
    if u.lower().startswith(("http://", "https://")) and len(u) > 8:
        return u
    return ""


def valid_email(value):
    v = str(value or "").strip()
    if not v or " " in v or v.count("@") != 1:
        return False
    local, domain = v.split("@")
    return bool(local) and "." in domain and not domain.startswith(".") and not domain.endswith(".")


def as_list(value):
    if isinstance(value, str):
        return [t.strip() for t in value.split(",") if t.strip()]
    if isinstance(value, (list, tuple)):
        return [str(t).strip() for t in value if str(t).strip()]
    return []


def parse_tech(raw):
    seen, out = set(), []
    for t in as_list(raw):
        t = t[:40]
        if t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:12]


def tech_matches(tech, tag):
    a, b = str(tech).strip().lower(), str(tag).strip().lower()
    if not a or not b:
        return False
    if a == b:
        return True
    if len(a) >= 3 and a in b:
        return True
    if len(b) >= 3 and b in a:
        return True
    return False


def btn(label, url, kind="ghost", blank=True):
    if not url:
        return f'<span class="btn {kind} disabled">{esc(label)}</span>'
    target = ' target="_blank" rel="noopener noreferrer"' if blank else ""
    return f'<a class="btn {kind}" href="{esc(url)}"{target}>{esc(label)}</a>'


def flash(message, kind="success"):
    st.session_state["_flash"] = (kind, message)


def show_flash():
    item = st.session_state.pop("_flash", None)
    if item:
        kind, message = item
        if kind == "error":
            st.error(message)
        else:
            st.success(message)


def get_mongo_uri():
    try:
        uri = st.secrets["MONGO_URI"]
        if uri:
            return str(uri).strip()
    except Exception:
        pass
    return os.environ.get("MONGO_URI", "").strip()


def get_admin_passcode():
    try:
        code = st.secrets["ADMIN_PASSCODE"]
        if code:
            return str(code)
    except Exception:
        pass
    return os.environ.get("ADMIN_PASSCODE", "").strip() or DEFAULT_ADMIN_PASSCODE


# ----------------------------------------------------------------------------
# DATABASE LAYER  (MongoDB Atlas primary, local JSON fallback)
# ----------------------------------------------------------------------------
class JsonStore:
    """Local JSON database (v2_db.json). Memory is source of truth, file is best-effort."""

    kind = "json"

    def __init__(self, path):
        self.path = path
        self.lock = threading.RLock()
        self.data = self._read_file()

    def _read_file(self):
        data = {}
        try:
            with open(self.path, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, ValueError):
            data = {}
        if not isinstance(data.get("meta"), dict):
            data["meta"] = {}
        if not isinstance(data.get("projects"), list):
            data["projects"] = []
        if not isinstance(data.get("messages"), list):
            data["messages"] = []
        return data

    def _persist(self):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as fh:
                json.dump(self.data, fh, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError:
            pass  # read-only filesystem: keep working from memory

    @staticmethod
    def _clone(obj):
        return json.loads(json.dumps(obj))

    def get_meta(self):
        with self.lock:
            return self._clone(self.data["meta"])

    def set_meta(self, meta):
        with self.lock:
            self.data["meta"] = self._clone(meta)
            self._persist()

    def list_projects(self):
        with self.lock:
            items = self._clone(self.data["projects"])
        return sorted(items, key=lambda p: p.get("created_ts", 0))

    def add_project(self, doc):
        with self.lock:
            self.data["projects"].append(self._clone(doc))
            self._persist()

    def update_project(self, pid, fields):
        with self.lock:
            for p in self.data["projects"]:
                if p.get("pid") == pid:
                    p.update(self._clone(fields))
                    break
            self._persist()

    def delete_project(self, pid):
        with self.lock:
            self.data["projects"] = [p for p in self.data["projects"] if p.get("pid") != pid]
            self._persist()

    def list_messages(self):
        with self.lock:
            items = self._clone(self.data["messages"])
        return sorted(items, key=lambda m: m.get("timestamp", ""), reverse=True)

    def add_message(self, doc):
        with self.lock:
            self.data["messages"].append(self._clone(doc))
            self._persist()


class MongoStore:
    """MongoDB Atlas backend: collections meta / projects / messages."""

    kind = "mongo"

    def __init__(self, uri):
        self.client = MongoClient(uri, serverSelectionTimeoutMS=5000, connectTimeoutMS=5000)
        self.client.admin.command("ping")
        self.db = self.client[DB_NAME]

    def get_meta(self):
        return self.db["meta"].find_one({"_id": "profile"}, {"_id": 0}) or {}

    def set_meta(self, meta):
        self.db["meta"].replace_one({"_id": "profile"}, dict(meta), upsert=True)

    def list_projects(self):
        return list(self.db["projects"].find({}, {"_id": 0}).sort("created_ts", 1))

    def add_project(self, doc):
        self.db["projects"].insert_one(dict(doc))

    def update_project(self, pid, fields):
        self.db["projects"].update_one({"pid": pid}, {"$set": dict(fields)})

    def delete_project(self, pid):
        self.db["projects"].delete_one({"pid": pid})

    def list_messages(self):
        return list(self.db["messages"].find({}, {"_id": 0}).sort("timestamp", -1))

    def add_message(self, doc):
        self.db["messages"].insert_one(dict(doc))


def seed_store(backend):
    """Fill missing profile keys and seed default projects when the DB is empty."""
    try:
        meta = backend.get_meta() or {}
        merged = {**DEFAULT_META, **meta}
        if merged != meta:
            backend.set_meta(merged)
        if not backend.list_projects():
            for project in default_projects():
                backend.add_project(project)
    except Exception:
        pass


class Store:
    """Facade: tries MongoDB first, silently falls back to local JSON. Never crashes the app."""

    def __init__(self):
        self.note = ""
        self.mongo = None
        self.uri = get_mongo_uri()
        self.json = JsonStore(JSON_PATH)
        seed_store(self.json)
        if self.uri and HAS_PYMONGO:
            try:
                self.mongo = MongoStore(self.uri)
                seed_store(self.mongo)
            except Exception as exc:
                self.mongo = None
                self.note = f"MongoDB unreachable ({type(exc).__name__}). Using local JSON."
        elif self.uri and not HAS_PYMONGO:
            self.note = "pymongo not installed. Using local JSON."

    @property
    def mode(self):
        return "mongo" if self.mongo is not None else "json"

    def _call(self, name, *args):
        if self.mongo is not None:
            try:
                return getattr(self.mongo, name)(*args)
            except Exception as exc:
                self.note = f"MongoDB error ({type(exc).__name__}). Switched to local JSON."
                self.mongo = None
        return getattr(self.json, name)(*args)

    def get_meta(self):
        return self._call("get_meta")

    def set_meta(self, meta):
        return self._call("set_meta", meta)

    def list_projects(self):
        return self._call("list_projects")

    def add_project(self, doc):
        return self._call("add_project", doc)

    def update_project(self, pid, fields):
        return self._call("update_project", pid, fields)

    def delete_project(self, pid):
        return self._call("delete_project", pid)

    def list_messages(self):
        return self._call("list_messages")

    def add_message(self, doc):
        return self._call("add_message", doc)


@st.cache_resource(show_spinner=False)
def get_store():
    return Store()


def load_meta(store):
    try:
        return {**DEFAULT_META, **(store.get_meta() or {})}
    except Exception:
        return dict(DEFAULT_META)


def load_projects(store):
    try:
        return store.list_projects()
    except Exception:
        return []


# ----------------------------------------------------------------------------
# THEME / CSS
# ----------------------------------------------------------------------------
CSS = """
@import url('https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&family=JetBrains+Mono:wght@400;600&display=swap');
:root{
  --bg:#08090d; --cyan:#00f0ff; --violet:#7000ff;
  --glass:rgba(255,255,255,0.04); --border:rgba(255,255,255,0.10);
  --text:#e8ecf4; --muted:#8f98ad;
  --mono:'JetBrains Mono','Courier New',monospace;
}
.stApp{
  background:
    radial-gradient(1100px 560px at 8% -8%, rgba(112,0,255,.20), transparent 60%),
    radial-gradient(900px 480px at 100% 0%, rgba(0,240,255,.12), transparent 55%),
    #08090d;
  color:var(--text);
  font-family:'Space Grotesk',system-ui,-apple-system,'Segoe UI',sans-serif;
}
header[data-testid="stHeader"]{background:transparent;}
#MainMenu,footer{visibility:hidden;}
.block-container{padding-top:2.6rem;padding-bottom:4rem;max-width:1200px;}
[data-testid="stSidebar"]{
  background:rgba(10,12,18,.78);
  backdrop-filter:blur(18px);-webkit-backdrop-filter:blur(18px);
  border-right:1px solid var(--border);
}
[data-testid="stSidebar"] > div:first-child{background:transparent;}
[data-testid="stMarkdownContainer"] p{color:var(--text);}
[data-testid="stWidgetLabel"] p{
  color:#aab3c8!important;font-family:var(--mono);font-size:.74rem;
  letter-spacing:.08em;text-transform:uppercase;
}
.stRadio div[role="radiogroup"] label p{color:var(--text)!important;text-transform:none;letter-spacing:0;font-family:inherit;font-size:.95rem;}

/* glass */
.glass{
  background:var(--glass);
  backdrop-filter:blur(16px);-webkit-backdrop-filter:blur(16px);
  border:1px solid var(--border);border-radius:18px;padding:1.25rem;
  transition:border-color .25s,box-shadow .25s,transform .25s;
}
.glass:hover{
  border-color:rgba(0,240,255,.5);
  box-shadow:0 0 0 1px rgba(0,240,255,.14),0 10px 40px rgba(0,240,255,.12),0 0 60px rgba(112,0,255,.14);
}

/* brand + sidebar */
.brand{
  display:flex;flex-direction:column;gap:.15rem;padding:.9rem 1rem;margin-bottom:1rem;
  border:1px solid rgba(0,240,255,.35);border-radius:14px;
  background:linear-gradient(135deg,rgba(0,240,255,.08),rgba(112,0,255,.16));
  box-shadow:0 0 28px rgba(0,240,255,.12);
}
.brand-main{font-family:var(--mono);font-weight:600;font-size:1.15rem;letter-spacing:.14em;color:var(--cyan);}
.brand-ver{font-family:var(--mono);font-size:.72rem;letter-spacing:.22em;color:#b99cff;}
.side-title{font-family:var(--mono);font-size:.72rem;letter-spacing:.2em;color:var(--muted);margin:1rem 0 .5rem 0;}
.db-status{
  font-family:var(--mono);font-size:.72rem;letter-spacing:.08em;padding:.5rem .7rem;margin-top:.6rem;
  border:1px solid var(--border);border-radius:10px;background:rgba(255,255,255,.03);color:var(--text);
}
.dot{display:inline-block;width:8px;height:8px;border-radius:50%;margin-right:.45rem;vertical-align:middle;}
.dot.live{background:#00ff9d;box-shadow:0 0 10px #00ff9d;}
.dot.fallback{background:#ffb800;box-shadow:0 0 10px #ffb800;}
.side-links .btn{width:100%;box-sizing:border-box;margin-bottom:.5rem;}

/* buttons */
.btn{
  display:inline-flex;align-items:center;justify-content:center;gap:.35rem;
  padding:.55rem .95rem;border-radius:12px;font-size:.84rem;font-weight:600;line-height:1.2;
  text-decoration:none!important;border:1px solid var(--border);color:var(--text)!important;
  background:rgba(255,255,255,.04);transition:all .22s ease;cursor:pointer;
}
.btn:hover{transform:translateY(-2px);border-color:var(--cyan);box-shadow:0 0 22px rgba(0,240,255,.25);}
.btn.primary{border-color:rgba(0,240,255,.6);color:var(--cyan)!important;background:rgba(0,240,255,.08);}
.btn.primary:hover{background:var(--cyan);color:#04141a!important;}
.btn.violet{border-color:rgba(112,0,255,.85);color:#c9a8ff!important;background:rgba(112,0,255,.14);}
.btn.violet:hover{background:var(--violet);color:#fff!important;border-color:var(--violet);box-shadow:0 0 22px rgba(112,0,255,.5);}
.btn.disabled{opacity:.38;pointer-events:none;cursor:default;}
.actions{display:flex;flex-wrap:wrap;gap:.55rem;margin-top:1rem;}

/* hero profile card */
.status-pill{
  display:inline-block;font-family:var(--mono);font-size:.68rem;letter-spacing:.2em;color:var(--cyan);
  border:1px solid rgba(0,240,255,.4);border-radius:999px;padding:.25rem .7rem;background:rgba(0,240,255,.07);
}
.avatar{position:relative;width:112px;height:112px;border-radius:50%;margin:1rem 0 1.1rem 0;}
.avatar::before{
  content:"";position:absolute;inset:-4px;border-radius:50%;
  background:conic-gradient(from 0deg,#00f0ff,#7000ff,#00f0ff);animation:spin 6s linear infinite;
}
.avatar .core{
  position:absolute;inset:0;border-radius:50%;background:#0d0f16;z-index:1;overflow:hidden;
  display:flex;align-items:center;justify-content:center;font-size:2.1rem;font-weight:700;color:var(--cyan);
}
.avatar img{width:100%;height:100%;object-fit:cover;}
@keyframes spin{to{transform:rotate(360deg);}}
@keyframes rise{from{opacity:0;transform:translateY(14px);}to{opacity:1;transform:none;}}
.hero-name{
  font-size:2.5rem;font-weight:700;line-height:1.1;margin:0;
  background:linear-gradient(90deg,#ffffff 0%,#00f0ff 55%,#7000ff 100%);
  -webkit-background-clip:text;background-clip:text;-webkit-text-fill-color:transparent;color:transparent;
}
.hero-title{font-family:var(--mono);font-size:.9rem;color:var(--cyan);margin:.5rem 0 .8rem 0;letter-spacing:.04em;}
.hero-bio{color:#c3cadb;line-height:1.6;font-size:1rem;margin:0;}
.stats{display:grid;grid-template-columns:repeat(3,1fr);gap:.6rem;margin-top:1.1rem;}
.stat{border:1px solid var(--border);border-radius:12px;padding:.6rem .5rem;text-align:center;background:rgba(255,255,255,.03);}
.stat b{display:block;font-size:1.15rem;color:var(--cyan);}
.stat span{font-family:var(--mono);font-size:.62rem;letter-spacing:.12em;color:var(--muted);}

/* sections */
.sec{margin:2.6rem 0 1rem 0;}
.sec-tag{font-family:var(--mono);font-size:.74rem;letter-spacing:.24em;color:var(--violet);}
.sec-title{font-size:1.65rem;font-weight:700;margin:.2rem 0 0 0;color:var(--text);}
.sec-sub{color:var(--muted);font-size:.92rem;margin-top:.3rem;}

/* projects */
.proj-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,300px),1fr));gap:1rem;}
.proj{display:flex;flex-direction:column;animation:rise .5s ease both;}
.proj-cat{font-family:var(--mono);font-size:.7rem;letter-spacing:.18em;color:#b99cff;text-transform:uppercase;}
.proj-title{font-size:1.15rem;font-weight:700;margin:.45rem 0 .7rem 0;color:var(--text);line-height:1.3;}
.chips{display:flex;flex-wrap:wrap;gap:.4rem;}
.chip{
  font-family:var(--mono);font-size:.7rem;padding:.2rem .55rem;border-radius:999px;
  color:var(--cyan);border:1px solid rgba(0,240,255,.35);background:rgba(0,240,255,.07);
}
.proj-desc{color:#b7bfd1;font-size:.93rem;line-height:1.6;margin:.9rem 0 0 0;flex:1;}
.empty{text-align:center;color:var(--muted);font-family:var(--mono);}

/* admin */
.admin-row{display:flex;flex-direction:column;gap:.35rem;}
.msg-meta{font-family:var(--mono);font-size:.72rem;color:var(--muted);letter-spacing:.06em;}
.msg-name{font-weight:700;color:var(--text);}
.msg-body{color:#c3cadb;margin-top:.5rem;line-height:1.6;}
.foot{text-align:center;color:var(--muted);font-family:var(--mono);font-size:.72rem;letter-spacing:.18em;margin-top:3rem;}

/* streamlit widgets */
.stTextInput input,.stTextArea textarea{
  background:rgba(255,255,255,.04)!important;color:var(--text)!important;
  border:1px solid var(--border)!important;border-radius:12px!important;
}
.stTextInput input:focus,.stTextArea textarea:focus{
  border-color:var(--cyan)!important;box-shadow:0 0 0 1px var(--cyan),0 0 18px rgba(0,240,255,.25)!important;
}
div[data-baseweb="select"] > div{
  background:rgba(255,255,255,.04)!important;border:1px solid var(--border)!important;
  border-radius:12px!important;color:var(--text)!important;
}
[data-testid="stForm"]{
  border:1px solid var(--border)!important;border-radius:18px!important;
  background:rgba(255,255,255,.03);backdrop-filter:blur(14px);padding:1.1rem!important;
}
[data-testid="stExpander"]{border:1px solid var(--border)!important;border-radius:14px!important;background:rgba(255,255,255,.03);}
.stButton > button,[data-testid="stFormSubmitButton"] > button,.stDownloadButton > button{
  background:linear-gradient(135deg,rgba(0,240,255,.14),rgba(112,0,255,.24))!important;
  color:#e8fbff!important;border:1px solid rgba(0,240,255,.45)!important;border-radius:12px!important;
  font-weight:600!important;transition:all .22s ease!important;
}
.stButton > button:hover,[data-testid="stFormSubmitButton"] > button:hover,.stDownloadButton > button:hover{
  border-color:var(--cyan)!important;box-shadow:0 0 22px rgba(0,240,255,.3)!important;transform:translateY(-1px);
}
.stTabs [data-baseweb="tab-list"]{gap:.4rem;border-bottom:1px solid var(--border);}
.stTabs [data-baseweb="tab"]{color:var(--muted);}
.stTabs [aria-selected="true"]{color:var(--cyan)!important;}
button[data-testid="stBaseButton-pills"],button[kind="pills"]{
  background:rgba(255,255,255,.04)!important;border:1px solid var(--border)!important;
  color:var(--text)!important;border-radius:999px!important;font-family:var(--mono)!important;
}
button[data-testid="stBaseButton-pillsActive"],button[kind="pillsActive"]{
  background:rgba(0,240,255,.15)!important;border:1px solid var(--cyan)!important;
  color:var(--cyan)!important;border-radius:999px!important;box-shadow:0 0 16px rgba(0,240,255,.3);
}

@media (max-width:640px){
  .block-container{padding:2.4rem .85rem 3rem!important;}
  .hero-name{font-size:1.9rem;}
  .sec-title{font-size:1.35rem;}
}
"""


def inject_css():
    st.markdown("<style>" + CSS + "</style>", unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# THREE.JS HERO (WebGL)
# ----------------------------------------------------------------------------
THREE_HTML = """<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  html,body{margin:0;height:100%;background:#08090d;overflow:hidden;font-family:'Courier New',monospace;}
  #wrap{position:relative;width:100%;height:100%;box-sizing:border-box;border-radius:18px;overflow:hidden;
        border:1px solid rgba(255,255,255,.10);
        background:radial-gradient(circle at 50% 42%,rgba(112,0,255,.22),rgba(8,9,13,0) 68%),#08090d;}
  canvas{display:block;width:100%;height:100%;touch-action:pan-y;cursor:grab;}
  canvas:active{cursor:grabbing;}
  .hud{position:absolute;pointer-events:none;font-size:11px;letter-spacing:.2em;text-transform:uppercase;}
  .hud.a{left:14px;bottom:12px;color:#00f0ff;opacity:.85;}
  .hud.b{right:14px;top:12px;color:#a574ff;opacity:.9;}
  #fb{display:none;position:absolute;inset:0;align-items:center;justify-content:center;text-align:center;
      color:#8f98ad;font-size:12px;letter-spacing:.14em;padding:20px;}
</style>
</head>
<body>
<div id="wrap">
  <canvas id="c"></canvas>
  <div class="hud a">drag to orbit // webgl core online</div>
  <div class="hud b">ABHI.DEV // V2</div>
  <div id="fb">WEBGL UNAVAILABLE ON THIS DEVICE</div>
</div>
<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>
<script>
(function () {
  var wrap = document.getElementById('wrap');
  var canvas = document.getElementById('c');
  var fb = document.getElementById('fb');
  if (typeof THREE === 'undefined') { fb.style.display = 'flex'; return; }

  var renderer;
  try {
    renderer = new THREE.WebGLRenderer({ canvas: canvas, antialias: true, alpha: true });
  } catch (e) { fb.style.display = 'flex'; return; }
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));

  var CYAN = 0x00f0ff, VIOLET = 0x7000ff;
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
  var idle = reduce ? 0.0015 : 0.004;

  var scene = new THREE.Scene();
  var camera = new THREE.PerspectiveCamera(55, 1, 0.1, 100);
  camera.position.set(0, 0, 6.2);

  var group = new THREE.Group();
  scene.add(group);

  var coreGeo = new THREE.IcosahedronGeometry(1.7, 1);
  var core = new THREE.LineSegments(
    new THREE.WireframeGeometry(coreGeo),
    new THREE.LineBasicMaterial({ color: CYAN, transparent: true, opacity: 0.9 })
  );
  group.add(core);

  var inner = new THREE.LineSegments(
    new THREE.WireframeGeometry(new THREE.OctahedronGeometry(1.0, 0)),
    new THREE.LineBasicMaterial({ color: VIOLET, transparent: true, opacity: 0.95 })
  );
  group.add(inner);

  var nodes = new THREE.Points(
    coreGeo,
    new THREE.PointsMaterial({ color: 0xffffff, size: 0.07, transparent: true, opacity: 0.9 })
  );
  group.add(nodes);

  var ringA = new THREE.Mesh(
    new THREE.TorusGeometry(2.7, 0.012, 8, 160),
    new THREE.MeshBasicMaterial({ color: VIOLET, transparent: true, opacity: 0.65 })
  );
  ringA.rotation.x = Math.PI / 2.3;
  group.add(ringA);

  var ringB = new THREE.Mesh(
    new THREE.TorusGeometry(3.1, 0.008, 8, 180),
    new THREE.MeshBasicMaterial({ color: CYAN, transparent: true, opacity: 0.4 })
  );
  ringB.rotation.x = Math.PI / 1.7;
  ringB.rotation.y = Math.PI / 5;
  group.add(ringB);

  var COUNT = window.innerWidth < 520 ? 900 : 1700;
  var pos = new Float32Array(COUNT * 3);
  var col = new Float32Array(COUNT * 3);
  var cA = new THREE.Color(CYAN), cB = new THREE.Color(VIOLET), tmp = new THREE.Color();
  for (var i = 0; i < COUNT; i++) {
    var r = 3.3 + Math.random() * 4.6;
    var th = Math.random() * Math.PI * 2;
    var ph = Math.acos(2 * Math.random() - 1);
    pos[i * 3]     = r * Math.sin(ph) * Math.cos(th);
    pos[i * 3 + 1] = r * Math.sin(ph) * Math.sin(th) * 0.7;
    pos[i * 3 + 2] = r * Math.cos(ph);
    tmp.copy(cA).lerp(cB, Math.random());
    col[i * 3] = tmp.r; col[i * 3 + 1] = tmp.g; col[i * 3 + 2] = tmp.b;
  }
  var pGeo = new THREE.BufferGeometry();
  pGeo.setAttribute('position', new THREE.BufferAttribute(pos, 3));
  pGeo.setAttribute('color', new THREE.BufferAttribute(col, 3));
  var nebula = new THREE.Points(pGeo, new THREE.PointsMaterial({
    size: 0.04, vertexColors: true, transparent: true, opacity: 0.85,
    depthWrite: false, blending: THREE.AdditiveBlending, sizeAttenuation: true
  }));
  scene.add(nebula);

  var dragging = false, lastX = 0, lastY = 0, velX = 0, velY = 0, px = 0, py = 0;

  canvas.addEventListener('pointerdown', function (e) {
    dragging = true; lastX = e.clientX; lastY = e.clientY;
    try { canvas.setPointerCapture(e.pointerId); } catch (err) {}
  });
  canvas.addEventListener('pointermove', function (e) {
    var rect = canvas.getBoundingClientRect();
    px = ((e.clientX - rect.left) / rect.width) * 2 - 1;
    py = ((e.clientY - rect.top) / rect.height) * 2 - 1;
    if (dragging) {
      velY += (e.clientX - lastX) * 0.004;
      velX += (e.clientY - lastY) * 0.004;
      lastX = e.clientX; lastY = e.clientY;
    }
  });
  function endDrag(e) {
    dragging = false;
    try { canvas.releasePointerCapture(e.pointerId); } catch (err) {}
  }
  canvas.addEventListener('pointerup', endDrag);
  canvas.addEventListener('pointercancel', endDrag);
  canvas.addEventListener('pointerleave', function () { px = 0; py = 0; });

  function resize() {
    var w = wrap.clientWidth || 300;
    var h = wrap.clientHeight || 300;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.position.z = camera.aspect < 1 ? 7.8 : 6.2;
    camera.updateProjectionMatrix();
  }
  window.addEventListener('resize', resize);
  if (window.ResizeObserver) { new ResizeObserver(resize).observe(wrap); }
  resize();

  var clock = new THREE.Clock();
  function tick() {
    requestAnimationFrame(tick);
    if (document.hidden) { return; }
    var t = clock.getElapsedTime();

    group.rotation.y += velY + idle;
    group.rotation.x += velX;
    velX *= 0.93; velY *= 0.93;
    group.rotation.x += (Math.sin(t * 0.4) * 0.25 - group.rotation.x) * 0.002;

    core.rotation.y += idle * 0.6;
    inner.rotation.y -= idle * 2.2;
    inner.rotation.x += idle * 1.4;
    ringA.rotation.z += idle * 1.2;
    ringB.rotation.z -= idle * 0.9;
    group.scale.setScalar(1 + Math.sin(t * 1.2) * 0.03);

    nebula.rotation.y = t * 0.03 + px * 0.2;
    nebula.rotation.x = py * 0.12;

    camera.position.x += (px * 0.9 - camera.position.x) * 0.05;
    camera.position.y += (-py * 0.6 - camera.position.y) * 0.05;
    camera.lookAt(0, 0, 0);

    renderer.render(scene, camera);
  }
  tick();
})();
</script>
</body>
</html>
"""


# ----------------------------------------------------------------------------
# USER VIEW
# ----------------------------------------------------------------------------
def profile_card_html(meta, n_projects, n_tech, db_label):
    name = meta.get("name") or DEFAULT_META["name"]
    initials = "".join(w[0] for w in name.split()[:2]).upper() or "AS"
    avatar = safe_url(meta.get("avatar_url"))
    if avatar:
        core = f'<img src="{esc(avatar)}" alt="{esc(name)}" loading="lazy" referrerpolicy="no-referrer">'
    else:
        core = f"<span>{esc(initials)}</span>"

    email = str(meta.get("email") or "").strip()
    mail_href = f"mailto:{email}" if valid_email(email) else ""

    actions = (
        btn("LinkedIn", safe_url(meta.get("linkedin_url")), "primary")
        + btn("GitHub", safe_url(meta.get("github_url")), "primary")
        + btn("Email", mail_href, "primary", blank=False)
        + btn("Download Resume (PDF)", safe_url(meta.get("resume_url")), "violet")
    )

    return (
        '<div class="glass">'
        '<span class="status-pill">● SYSTEM ONLINE</span>'
        f'<div class="avatar"><div class="core">{core}</div></div>'
        f'<div class="hero-name">{esc(name)}</div>'
        f'<div class="hero-title">{esc(meta.get("title"))}</div>'
        f'<p class="hero-bio">{esc(meta.get("bio"))}</p>'
        f'<div class="actions">{actions}</div>'
        '<div class="stats">'
        f'<div class="stat"><b>{n_projects}</b><span>PROJECTS</span></div>'
        f'<div class="stat"><b>{n_tech}</b><span>TECH TAGS</span></div>'
        f'<div class="stat"><b>{esc(db_label)}</b><span>DATA LAYER</span></div>'
        "</div>"
        "</div>"
    )


def project_card_html(p):
    techs = "".join(f'<span class="chip">{esc(t)}</span>' for t in as_list(p.get("tech")))
    link = safe_url(p.get("link"))
    file_url = safe_url(p.get("file_url"))
    actions = ""
    if link:
        actions += btn("View Project / Repo ↗", link, "primary")
    if file_url:
        actions += btn("Download Excel VBA / File 💾", file_url, "violet")
    desc = esc(p.get("description")).replace("\r", "").replace("\n", "<br>")
    return (
        '<div class="glass proj">'
        f'<div class="proj-cat">{esc(p.get("category") or "Project")}</div>'
        f'<div class="proj-title">{esc(p.get("title"))}</div>'
        f'<div class="chips">{techs}</div>'
        f'<p class="proj-desc">{desc}</p>'
        f'<div class="actions">{actions}</div>'
        "</div>"
    )


def section_header(tag, title, sub=""):
    sub_html = f'<div class="sec-sub">{esc(sub)}</div>' if sub else ""
    st.markdown(
        f'<div class="sec"><div class="sec-tag">{esc(tag)}</div>'
        f'<div class="sec-title">{esc(title)}</div>{sub_html}</div>',
        unsafe_allow_html=True,
    )


def tech_filter(options):
    key = "tech_sel"
    current = st.session_state.get(key)
    if current is not None and current not in options:
        del st.session_state[key]
    if hasattr(st, "pills"):
        selected = st.pills(
            "Tech filter",
            options,
            selection_mode="single",
            default="All",
            key=key,
            label_visibility="collapsed",
        )
    else:
        selected = st.radio("Tech filter", options, horizontal=True, key=key, label_visibility="collapsed")
    return selected or "All"


def render_user(store, meta):
    projects = load_projects(store)
    all_tech = []
    for p in projects:
        for t in as_list(p.get("tech")):
            if t.lower() not in [x.lower() for x in all_tech]:
                all_tech.append(t)

    db_label = "ATLAS" if store.mode == "mongo" else "JSON"

    # ---- Hero ----
    col_a, col_b = st.columns([1.15, 1], gap="large")
    with col_a:
        components.html(THREE_HTML, height=480, scrolling=False)
    with col_b:
        st.markdown(profile_card_html(meta, len(projects), len(all_tech), db_label), unsafe_allow_html=True)

    # ---- Tech Matrix ----
    section_header("// 01", "Tech Matrix", "Filter the project grid by stack.")
    extras = []
    for t in all_tech:
        if not any(tech_matches(t, b) for b in BASE_TAGS) and t not in extras:
            extras.append(t)
    options = ["All"] + BASE_TAGS + extras[:10]
    selected = tech_filter(options)

    # ---- Projects ----
    if selected == "All":
        shown = projects
    else:
        shown = [p for p in projects if any(tech_matches(t, selected) for t in as_list(p.get("tech")))]

    section_header("// 02", "Project Grid", f"{len(shown)} of {len(projects)} deployed systems  ·  filter: {selected}")
    if shown:
        st.markdown(
            '<div class="proj-grid">' + "".join(project_card_html(p) for p in shown) + "</div>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            '<div class="glass empty">NO PROJECTS IN THIS STACK YET</div>',
            unsafe_allow_html=True,
        )

    # ---- Contact ----
    section_header("// 03", "Open a Transmission", "Drop a message. It lands straight in the command center inbox.")
    left, right = st.columns([1, 1.5], gap="large")
    with left:
        email = str(meta.get("email") or "").strip()
        mail_btn = btn("Email directly", f"mailto:{email}" if valid_email(email) else "", "primary", blank=False)
        st.markdown(
            '<div class="glass"><div class="proj-cat">CHANNEL // OPEN</div>'
            '<div class="proj-title">Let&#39;s build something sharp.</div>'
            '<p class="proj-desc">Automation, MIS dashboards, data apps or a custom Excel VBA system. '
            "Send the details and I will get back to you.</p>"
            f'<div class="actions">{mail_btn}</div></div>',
            unsafe_allow_html=True,
        )
    with right:
        with st.form("contact_form", clear_on_submit=True):
            c_name = st.text_input("Your name", max_chars=80)
            c_email = st.text_input("Your email", max_chars=120)
            c_msg = st.text_area("Message", height=140, max_chars=2000)
            sent = st.form_submit_button("⚡ Transmit")
        if sent:
            if not c_name.strip() or not c_msg.strip():
                st.error("Name and message are required.")
            elif not valid_email(c_email):
                st.error("Please enter a valid email address.")
            elif len(c_msg.strip()) < 5:
                st.error("Message is too short.")
            elif time.time() - st.session_state.get("last_msg_ts", 0) < 20:
                st.warning("Transmission cooldown active. Try again in a few seconds.")
            else:
                try:
                    store.add_message(
                        {
                            "mid": uuid.uuid4().hex[:12],
                            "name": c_name.strip()[:80],
                            "email": c_email.strip()[:120],
                            "message": c_msg.strip()[:2000],
                            "timestamp": now_iso(),
                        }
                    )
                except Exception as exc:
                    st.error(f"Transmission failed ({type(exc).__name__}). Please try again.")
                else:
                    st.session_state["last_msg_ts"] = time.time()
                    st.success("Transmission received. Thanks, I'll reply soon.")

    st.markdown(
        f'<div class="foot">ABHI.DEV V2 // CORE  ·  © {datetime.date.today().year}</div>',
        unsafe_allow_html=True,
    )


# ----------------------------------------------------------------------------
# ADMIN VIEW
# ----------------------------------------------------------------------------
def clean_project_fields(title, category, tech_raw, description, link, file_url):
    errors = []
    title = (title or "").strip()
    link = (link or "").strip()
    file_url = (file_url or "").strip()
    if not title:
        errors.append("Title is required.")
    if link and not safe_url(link):
        errors.append("Project URL must start with http:// or https://")
    if file_url and not safe_url(file_url):
        errors.append("File URL must start with http:// or https://")
    fields = {
        "title": title[:140],
        "category": category,
        "tech": parse_tech(tech_raw),
        "description": (description or "").strip()[:1500],
        "link": safe_url(link) if link else "",
        "file_url": safe_url(file_url) if file_url else "",
    }
    return errors, fields


def admin_profile_tab(store, meta):
    st.markdown("##### Profile & Social Controller")
    with st.form("meta_form"):
        c1, c2 = st.columns(2)
        with c1:
            name = st.text_input("Name", value=meta.get("name", ""))
            linkedin = st.text_input("LinkedIn URL", value=meta.get("linkedin_url", ""))
            email = st.text_input("Email", value=meta.get("email", ""))
            avatar = st.text_input("Avatar / Photo URL", value=meta.get("avatar_url", ""))
        with c2:
            title = st.text_input("Title", value=meta.get("title", ""))
            github = st.text_input("GitHub URL", value=meta.get("github_url", ""))
            resume = st.text_input("Resume download URL (PDF)", value=meta.get("resume_url", ""))
        bio = st.text_area("Headline / Bio", value=meta.get("bio", ""), height=110)
        saved = st.form_submit_button("💾 Save profile")

    if saved:
        errors = []
        if not name.strip():
            errors.append("Name is required.")
        if not title.strip():
            errors.append("Title is required.")
        for label, val in (
            ("LinkedIn URL", linkedin),
            ("GitHub URL", github),
            ("Resume URL", resume),
            ("Avatar URL", avatar),
        ):
            if val.strip() and not safe_url(val):
                errors.append(f"{label} must start with http:// or https://")
        if email.strip() and not valid_email(email):
            errors.append("Email format looks invalid.")
        if errors:
            for e in errors:
                st.error(e)
            return
        new_meta = {
            "name": name.strip()[:80],
            "title": title.strip()[:140],
            "bio": bio.strip()[:600],
            "avatar_url": safe_url(avatar) if avatar.strip() else "",
            "resume_url": safe_url(resume) if resume.strip() else "",
            "linkedin_url": safe_url(linkedin) if linkedin.strip() else "",
            "github_url": safe_url(github) if github.strip() else "",
            "email": email.strip()[:120],
        }
        try:
            store.set_meta(new_meta)
        except Exception as exc:
            st.error(f"Save failed ({type(exc).__name__}).")
        else:
            flash("Profile updated live.")
            st.rerun()


def admin_projects_tab(store):
    st.markdown("##### Project Inventory Manager")
    fk = st.session_state.get("proj_form_n", 0)

    with st.form(f"proj_form_{fk}"):
        c1, c2 = st.columns(2)
        with c1:
            p_title = st.text_input("Project title", key=f"p_title_{fk}")
            p_cat = st.selectbox("Category", CATEGORIES, key=f"p_cat_{fk}")
            p_tech = st.text_input("Tech stack (comma-separated)", key=f"p_tech_{fk}", placeholder="Python, Pandas, Streamlit")
        with c2:
            p_link = st.text_input("Project demo / repo URL", key=f"p_link_{fk}")
            p_file = st.text_input("File download URL (Excel VBA .xlsm / workbook)", key=f"p_file_{fk}")
        p_desc = st.text_area("Description", height=100, key=f"p_desc_{fk}")
        add = st.form_submit_button("➕ Add project")

    if add:
        errors, fields = clean_project_fields(p_title, p_cat, p_tech, p_desc, p_link, p_file)
        if errors:
            for e in errors:
                st.error(e)
        else:
            doc = {"pid": uuid.uuid4().hex[:12], "created_ts": now_ts(), **fields}
            try:
                store.add_project(doc)
            except Exception as exc:
                st.error(f"Could not add project ({type(exc).__name__}).")
            else:
                st.session_state["proj_form_n"] = fk + 1
                flash(f"Project '{fields['title']}' added.")
                st.rerun()

    st.markdown("---")
    projects = load_projects(store)
    st.markdown(f"**Live inventory: {len(projects)} project(s)**")
    if not projects:
        st.info("No projects in the database yet.")

    for p in projects:
        pid = p.get("pid", "")
        techs = "".join(f'<span class="chip">{esc(t)}</span>' for t in as_list(p.get("tech")))
        row_l, row_r = st.columns([5, 1])
        with row_l:
            st.markdown(
                '<div class="glass admin-row">'
                f'<div class="proj-cat">{esc(p.get("category"))}</div>'
                f'<div class="proj-title" style="margin:.2rem 0">{esc(p.get("title"))}</div>'
                f'<div class="chips">{techs}</div></div>',
                unsafe_allow_html=True,
            )
        with row_r:
            if st.button("🗑️ Delete", key=f"del_{pid}"):
                try:
                    store.delete_project(pid)
                except Exception as exc:
                    st.error(f"Delete failed ({type(exc).__name__}).")
                else:
                    flash(f"Deleted '{p.get('title', '')}'.")
                    st.rerun()

        with st.expander(f"✏️ Edit: {p.get('title', '')}"):
            cat = p.get("category") or CATEGORIES[0]
            cat_options = CATEGORIES if cat in CATEGORIES else CATEGORIES + [cat]
            with st.form(f"edit_form_{pid}"):
                e_title = st.text_input("Title", value=p.get("title", ""), key=f"et_{pid}")
                e_cat = st.selectbox("Category", cat_options, index=cat_options.index(cat), key=f"ec_{pid}")
                e_tech = st.text_input("Tech stack (comma-separated)", value=", ".join(as_list(p.get("tech"))), key=f"etech_{pid}")
                e_link = st.text_input("Project demo / repo URL", value=p.get("link", ""), key=f"el_{pid}")
                e_file = st.text_input("File download URL", value=p.get("file_url", ""), key=f"ef_{pid}")
                e_desc = st.text_area("Description", value=p.get("description", ""), height=100, key=f"ed_{pid}")
                upd = st.form_submit_button("Save changes")
            if upd:
                errors, fields = clean_project_fields(e_title, e_cat, e_tech, e_desc, e_link, e_file)
                if errors:
                    for e in errors:
                        st.error(e)
                else:
                    try:
                        store.update_project(pid, fields)
                    except Exception as exc:
                        st.error(f"Update failed ({type(exc).__name__}).")
                    else:
                        flash(f"Project '{fields['title']}' updated.")
                        st.rerun()


def admin_inbox_tab(store):
    st.markdown("##### Transmission Inbox")
    try:
        msgs = store.list_messages()
    except Exception as exc:
        st.error(f"Could not load messages ({type(exc).__name__}).")
        return

    m1, m2 = st.columns(2)
    m1.metric("Total transmissions", len(msgs))
    m2.metric("Data layer", "MongoDB Atlas" if store.mode == "mongo" else "Local JSON")

    if not msgs:
        st.info("Inbox is empty. No transmissions yet.")
        return

    st.download_button(
        "⬇️ Export messages as JSON",
        data=json.dumps(msgs, indent=2, ensure_ascii=False),
        file_name=f"abhi_dev_v2_messages_{datetime.date.today().isoformat()}.json",
        mime="application/json",
    )

    with st.expander("📊 Table view"):
        df = pd.DataFrame(msgs).reindex(columns=["timestamp", "name", "email", "message"])
        st.dataframe(df, hide_index=True)

    for m in msgs:
        body = esc(m.get("message")).replace("\r", "").replace("\n", "<br>")
        st.markdown(
            '<div class="glass" style="margin-bottom:.8rem">'
            f'<div class="msg-meta">{esc(m.get("timestamp"))}</div>'
            f'<div><span class="msg-name">{esc(m.get("name"))}</span> '
            f'<span class="msg-meta">&lt;{esc(m.get("email"))}&gt;</span></div>'
            f'<div class="msg-body">{body}</div></div>',
            unsafe_allow_html=True,
        )


def render_admin(store, meta):
    st.markdown(
        '<div class="sec" style="margin-top:0"><div class="sec-tag">// RESTRICTED</div>'
        '<div class="sec-title">🛡️ Admin Command Center</div></div>',
        unsafe_allow_html=True,
    )
    if not st.session_state.get("admin_ok"):
        st.markdown(
            '<div class="glass empty">🔒 CONSOLE LOCKED<br><br>'
            "Enter the passcode in the sidebar to unlock.<br>"
            "(On mobile, open the sidebar with the arrow at the top-left.)</div>",
            unsafe_allow_html=True,
        )
        return

    if get_admin_passcode() == DEFAULT_ADMIN_PASSCODE:
        st.warning("Default passcode is active. Set ADMIN_PASSCODE in secrets before going public.")
    show_flash()

    tab1, tab2, tab3 = st.tabs(["👤 Profile & Social", "🗂️ Project Inventory", "📡 Transmission Inbox"])
    with tab1:
        admin_profile_tab(store, meta)
    with tab2:
        admin_projects_tab(store)
    with tab3:
        admin_inbox_tab(store)


# ----------------------------------------------------------------------------
# SIDEBAR
# ----------------------------------------------------------------------------
def render_sidebar(store, meta):
    with st.sidebar:
        st.markdown(
            '<div class="brand"><span class="brand-main">ABHI.DEV</span>'
            '<span class="brand-ver">V2 // CORE</span></div>',
            unsafe_allow_html=True,
        )
        portal = st.radio(
            "Portal",
            [PORTAL_USER, PORTAL_ADMIN],
            key="portal",
            label_visibility="collapsed",
        )

        if store.mode == "mongo":
            status = '<span class="dot live"></span>MONGODB ATLAS // LIVE'
        else:
            status = '<span class="dot fallback"></span>LOCAL JSON // FALLBACK'
        st.markdown(f'<div class="db-status">{status}</div>', unsafe_allow_html=True)
        if store.note:
            st.caption(store.note)
        if store.mode == "json" and store.uri:
            if st.button("↻ Retry Atlas link", key="retry_db"):
                st.cache_resource.clear()
                st.rerun()

        email = str(meta.get("email") or "").strip()
        st.markdown('<div class="side-title">// QUICK LINKS</div>', unsafe_allow_html=True)
        st.markdown(
            '<div class="side-links">'
            + btn("🔗 LinkedIn", safe_url(meta.get("linkedin_url")), "primary")
            + btn("🐙 GitHub", safe_url(meta.get("github_url")), "primary")
            + btn("✉️ Email", f"mailto:{email}" if valid_email(email) else "", "primary", blank=False)
            + btn("📄 Resume (PDF)", safe_url(meta.get("resume_url")), "violet")
            + "</div>",
            unsafe_allow_html=True,
        )

        if portal == PORTAL_ADMIN:
            st.markdown('<div class="side-title">// ADMIN ACCESS</div>', unsafe_allow_html=True)
            if st.session_state.get("admin_ok"):
                st.success("Access granted")
                if st.button("Lock console", key="logout"):
                    st.session_state["admin_ok"] = False
                    st.rerun()
            else:
                with st.form("auth_form"):
                    code = st.text_input("Passcode", type="password", key="auth_code")
                    go = st.form_submit_button("Unlock")
                if go:
                    now = time.time()
                    lock_until = st.session_state.get("lock_until", 0)
                    if now < lock_until:
                        st.error(f"Too many attempts. Wait {int(lock_until - now) + 1}s.")
                    elif hmac.compare_digest(code.encode("utf-8"), get_admin_passcode().encode("utf-8")):
                        st.session_state["admin_ok"] = True
                        st.session_state["fails"] = 0
                        st.rerun()
                    else:
                        fails = st.session_state.get("fails", 0) + 1
                        if fails >= 5:
                            st.session_state["lock_until"] = now + 30
                            fails = 0
                        st.session_state["fails"] = fails
                        st.error("Invalid passcode.")
    return portal


# ----------------------------------------------------------------------------
# MAIN
# ----------------------------------------------------------------------------
def main():
    inject_css()
    store = get_store()
    meta = load_meta(store)
    portal = render_sidebar(store, meta)
    if portal == PORTAL_ADMIN:
        render_admin(store, meta)
    else:
        render_user(store, meta)


main()
