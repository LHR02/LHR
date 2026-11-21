#!/usr/bin/env python3
"""Actualités — lecteur d'actualités en français.

Lancement :  python3 actualites.py        puis ouvrir http://localhost:8000
Option    :  python3 actualites.py 9000   (autre port)

Aucune dépendance : uniquement la bibliothèque standard de Python 3.8+.
Les flux RSS de franceinfo et du Monde sont récupérés côté serveur,
mis en cache 5 minutes, puis affichés par catégorie.
"""
import html
import json
import re
import sys
import threading
import time
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

CACHE_SECONDS = 300

CATEGORIES = {
    "une": "À la une",
    "politique": "Politique",
    "monde": "Monde",
    "economie": "Économie",
    "sport": "Sport",
    "culture": "Culture",
    "sciences": "Sciences",
}

FEEDS = {
    "une": [
        ("franceinfo", "https://www.francetvinfo.fr/titres.rss"),
        ("Le Monde", "https://www.lemonde.fr/rss/une.xml"),
    ],
    "politique": [
        ("franceinfo", "https://www.francetvinfo.fr/politique.rss"),
        ("Le Monde", "https://www.lemonde.fr/politique/rss_full.xml"),
    ],
    "monde": [
        ("franceinfo", "https://www.francetvinfo.fr/monde.rss"),
        ("Le Monde", "https://www.lemonde.fr/international/rss_full.xml"),
    ],
    "economie": [
        ("franceinfo", "https://www.francetvinfo.fr/economie.rss"),
        ("Le Monde", "https://www.lemonde.fr/economie/rss_full.xml"),
    ],
    "sport": [
        ("franceinfo", "https://www.francetvinfo.fr/sports.rss"),
        ("Le Monde", "https://www.lemonde.fr/sport/rss_full.xml"),
    ],
    "culture": [
        ("franceinfo", "https://www.francetvinfo.fr/culture.rss"),
        ("Le Monde", "https://www.lemonde.fr/culture/rss_full.xml"),
    ],
    "sciences": [
        ("franceinfo", "https://www.francetvinfo.fr/sciences.rss"),
        ("Le Monde", "https://www.lemonde.fr/sciences/rss_full.xml"),
    ],
}

_cache = {}
_lock = threading.Lock()
TAG = re.compile(r"<[^>]+>")


def clean(text):
    return html.unescape(TAG.sub("", text or "")).strip()


def parse_feed(xml_bytes, source):
    root = ET.fromstring(xml_bytes)
    items = []
    for it in root.iter("item"):
        title = clean(it.findtext("title"))
        link = (it.findtext("link") or "").strip()
        if not title or not link:
            continue
        ts = 0
        raw = it.findtext("pubDate")
        if raw:
            try:
                ts = int(parsedate_to_datetime(raw).timestamp())
            except (TypeError, ValueError):
                pass
        image = ""
        for child in it:
            name = child.tag.split("}")[-1]
            if name in ("enclosure", "content", "thumbnail") and child.get("url"):
                if name != "enclosure" or "image" in (child.get("type") or "image"):
                    image = child.get("url")
                    break
        items.append({
            "title": title,
            "summary": clean(it.findtext("description"))[:320],
            "link": link,
            "source": source,
            "time": ts,
            "image": image,
        })
    return items


def fetch_one(source, url):
    req = urllib.request.Request(url, headers={"User-Agent": "Actualites/1.0"})
    with urllib.request.urlopen(req, timeout=10) as resp:
        return parse_feed(resp.read(), source)


def get_news(cat):
    now = time.time()
    with _lock:
        hit = _cache.get(cat)
        if hit and now - hit["at"] < CACHE_SECONDS:
            return hit["data"]
    items, errors = [], []
    feeds = FEEDS[cat]
    with ThreadPoolExecutor(max_workers=len(feeds)) as pool:
        futures = [(s, pool.submit(fetch_one, s, u)) for s, u in feeds]
        for source, fut in futures:
            try:
                items.extend(fut.result())
            except Exception as exc:  # réseau, XML invalide, etc.
                errors.append(f"{source} : {exc}")
    seen, unique = set(), []
    for item in sorted(items, key=lambda i: i["time"], reverse=True):
        if item["link"] not in seen:
            seen.add(item["link"])
            unique.append(item)
    data = {"items": unique, "errors": errors, "updated": int(now)}
    if unique:  # on ne met en cache que les réussites
        with _lock:
            _cache[cat] = {"at": now, "data": data}
    return data


PAGE = r"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Actualités</title>
<style>
:root{--bg:#f6f5f2;--card:#fff;--fg:#1b1d21;--muted:#6a6f78;--line:#e3e1db;--accent:#0b5fa5;--accent-fg:#fff;--star:#d98a00}
@media(prefers-color-scheme:dark){:root:not([data-theme=light]){--bg:#14161a;--card:#1d2026;--fg:#ecebe7;--muted:#9aa0aa;--line:#2c3038;--accent:#5aa9ec;--accent-fg:#0c1118;--star:#f0b43a}}
:root[data-theme=dark]{--bg:#14161a;--card:#1d2026;--fg:#ecebe7;--muted:#9aa0aa;--line:#2c3038;--accent:#5aa9ec;--accent-fg:#0c1118;--star:#f0b43a}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 Georgia,"Times New Roman",serif}
header{position:sticky;top:0;z-index:5;background:var(--bg);border-bottom:1px solid var(--line)}
.bar{max-width:1000px;margin:auto;padding:12px 16px;display:flex;gap:12px;align-items:center;flex-wrap:wrap}
h1{margin:0;font:700 1.4rem/1 system-ui,sans-serif;letter-spacing:-.02em;flex:1 1 auto}
h1 small{font-weight:400;color:var(--muted);font-size:.8rem;margin-left:8px}
input[type=search]{flex:1 1 220px;max-width:320px;padding:8px 12px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg);font:inherit;font-size:.95rem}
button{font:600 .85rem system-ui,sans-serif;border:1px solid var(--line);background:var(--card);color:var(--fg);padding:8px 12px;border-radius:8px;cursor:pointer}
button:focus-visible,a:focus-visible,input:focus-visible{outline:2px solid var(--accent);outline-offset:2px}
nav{max-width:1000px;margin:auto;padding:0 16px 10px;display:flex;gap:6px;overflow-x:auto}
nav button{white-space:nowrap;border-radius:999px}
nav button[aria-pressed=true]{background:var(--accent);color:var(--accent-fg);border-color:var(--accent)}
main{max-width:1000px;margin:auto;padding:20px 16px 60px}
.status{font:.85rem system-ui,sans-serif;color:var(--muted);margin-bottom:14px}
.err{color:#b3261e}
ul{list-style:none;margin:0;padding:0;display:grid;gap:14px}
li{display:grid;grid-template-columns:1fr;gap:12px;background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px}
li.has-img{grid-template-columns:1fr 160px}
li img{width:160px;height:107px;object-fit:cover;border-radius:6px;background:var(--line)}
.meta{font:.78rem system-ui,sans-serif;color:var(--muted);display:flex;gap:8px;align-items:center;text-transform:uppercase;letter-spacing:.05em}
h2{font-size:1.15rem;line-height:1.3;margin:4px 0 6px;text-wrap:balance}
h2 a{color:inherit;text-decoration:none}
h2 a:hover{color:var(--accent);text-decoration:underline}
p{margin:0;color:var(--muted);font-size:.95rem}
.star{margin-left:auto;border:0;background:none;font-size:1.2rem;padding:0 4px;color:var(--muted)}
.star[aria-pressed=true]{color:var(--star)}
@media(max-width:560px){li.has-img{grid-template-columns:1fr}li img{width:100%;height:auto;aspect-ratio:3/2;order:-1}}
</style>
</head>
<body>
<header>
  <div class="bar">
    <h1>Actualités<small id="date"></small></h1>
    <input id="q" type="search" placeholder="Rechercher un mot…" aria-label="Rechercher">
    <button id="refresh" title="Recharger les flux">Actualiser</button>
    <button id="theme" title="Changer de thème">Thème</button>
  </div>
  <nav id="tabs" aria-label="Catégories"></nav>
</header>
<main>
  <div class="status" id="status"></div>
  <ul id="list"></ul>
</main>
<script>
const CATS = __CATS__;
const $ = id => document.getElementById(id);
const store = {
  get(k, d){ try{ const v = localStorage.getItem(k); return v ? JSON.parse(v) : d }catch(e){ return d } },
  set(k, v){ try{ localStorage.setItem(k, JSON.stringify(v)) }catch(e){} }
};
let cat = store.get('cat', 'une');
let favs = store.get('favs', {});
let items = [];
let info = '';

$('date').textContent = new Date().toLocaleDateString('fr-FR', {weekday:'long', day:'numeric', month:'long'});

function tabs(){
  const entries = Object.entries(CATS).concat([['favoris', 'Favoris ★']]);
  $('tabs').replaceChildren(...entries.map(([k, label]) => {
    const b = document.createElement('button');
    b.textContent = label; b.setAttribute('aria-pressed', String(k === cat));
    b.onclick = () => { cat = k; store.set('cat', k); tabs(); load(false) };
    return b;
  }));
}

function ago(ts){
  if(!ts) return '';
  const m = Math.round((Date.now()/1000 - ts)/60);
  if(m < 1) return "à l'instant";
  if(m < 60) return `il y a ${m} min`;
  const h = Math.round(m/60);
  if(h < 24) return `il y a ${h} h`;
  return new Date(ts*1000).toLocaleDateString('fr-FR', {day:'numeric', month:'short'});
}

function render(){
  const q = $('q').value.trim().toLowerCase();
  let rows = cat === 'favoris' ? Object.values(favs) : items;
  if(q) rows = rows.filter(i => (i.title + ' ' + i.summary).toLowerCase().includes(q));
  $('status').replaceChildren();
  const s = document.createElement('span'); s.textContent = `${rows.length} article${rows.length > 1 ? 's' : ''}` + (info ? ' · ' + info : '');
  $('status').append(s);
  $('list').replaceChildren(...rows.map(i => {
    const li = document.createElement('li');
    if(i.image) li.className = 'has-img';
    const box = document.createElement('div');
    const meta = document.createElement('div'); meta.className = 'meta';
    const src = document.createElement('span'); src.textContent = i.source;
    const t = document.createElement('span'); t.textContent = ago(i.time);
    const st = document.createElement('button'); st.className = 'star'; st.textContent = '★';
    st.setAttribute('aria-pressed', String(!!favs[i.link])); st.title = 'Mettre en favori';
    st.onclick = () => { if(favs[i.link]) delete favs[i.link]; else favs[i.link] = i; store.set('favs', favs); render() };
    meta.append(src, t, st);
    const h = document.createElement('h2'); const a = document.createElement('a');
    a.href = i.link; a.target = '_blank'; a.rel = 'noopener noreferrer'; a.textContent = i.title; h.append(a);
    box.append(meta, h);
    if(i.summary){ const p = document.createElement('p'); p.textContent = i.summary; box.append(p) }
    li.append(box);
    if(i.image){ const im = document.createElement('img'); im.src = i.image; im.alt = ''; im.loading = 'lazy'; im.referrerPolicy = 'no-referrer'; li.append(im) }
    return li;
  }));
}

async function load(force){
  if(cat === 'favoris'){ info = ''; render(); return }
  $('status').textContent = 'Chargement…';
  try{
    const r = await fetch(`/api/news?cat=${cat}` + (force ? '&force=1' : ''));
    const d = await r.json();
    items = d.items;
    info = 'mis à jour à ' + new Date(d.updated*1000).toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit'});
    render();
    if(d.errors.length){
      const e = document.createElement('div'); e.className = 'err'; e.textContent = 'Flux indisponible : ' + d.errors.join(' ; ');
      $('status').append(e);
    }
  }catch(e){
    $('status').textContent = 'Impossible de charger les actualités. Le serveur tourne-t-il toujours ?';
  }
}

$('q').oninput = render;
$('refresh').onclick = () => load(true);
$('theme').onclick = () => {
  const dark = document.documentElement.dataset.theme === 'dark' ||
    (!document.documentElement.dataset.theme && matchMedia('(prefers-color-scheme:dark)').matches);
  document.documentElement.dataset.theme = dark ? 'light' : 'dark';
};
tabs(); load(false);
setInterval(() => load(false), 5*60*1000);
</script>
</body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    def _send(self, code, body, ctype):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/":
            page = PAGE.replace("__CATS__", json.dumps(CATEGORIES, ensure_ascii=False))
            self._send(200, page.encode(), "text/html; charset=utf-8")
        elif url.path == "/api/news":
            qs = parse_qs(url.query)
            cat = qs.get("cat", ["une"])[0]
            if cat not in FEEDS:
                return self._send(404, b'{"error":"categorie inconnue"}', "application/json")
            if qs.get("force"):
                with _lock:
                    _cache.pop(cat, None)
            body = json.dumps(get_news(cat), ensure_ascii=False).encode()
            self._send(200, body, "application/json; charset=utf-8")
        else:
            self._send(404, b"Introuvable", "text/plain; charset=utf-8")

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Actualités prêtes : http://localhost:{port}  (Ctrl+C pour arrêter)")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nArrêt.")
