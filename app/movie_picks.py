#!/usr/bin/env python3
"""movie-picks: daily film recommendations from Letterboxd taste, via Claude Code
(subscription), emailed with one-click download through Radarr.

  movie_picks.py pick [--dry-run]   build today's picks and email them
  movie_picks.py serve              run the download-link web handler
  movie_picks.py sync               pull new Letterboxd ratings (liked = rated > 3 stars)
"""
import csv
import datetime as dt
import hashlib
import hmac
import html
import io
import json
import os
import pathlib
import re
import smtplib
import subprocess
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from email.message import EmailMessage
from email.utils import make_msgid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ROOT = pathlib.Path(__file__).resolve().parent.parent
STATE = ROOT / "state"
UA = "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"


def load_env():
    env = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    env.setdefault("RADARR_URL", "http://127.0.0.1:7878")
    env.setdefault("CLAUDE_MODEL", "opus")
    env.setdefault("PICKS_PER_DAY", "3")
    env.setdefault("SMTP_HOST", "smtp.gmail.com")
    env.setdefault("SMTP_PORT", "465")
    env["RADARR_KEY"] = (STATE / "radarr.key").read_text().strip()
    env["RADARR_PROFILE"] = (STATE / "radarr_profile_id").read_text().strip()
    return env


CFG = load_env()


SCHEMA = """
create table if not exists films (
  key text primary key, name text not null, year int, imdb text, tmdb int,
  liked boolean default false, rating real, original text, director text, slug text,
  updated_at timestamptz default now());
create table if not exists sent (
  id bigserial primary key, sent_at timestamptz default now(), batch date not null,
  tmdb int not null, title text, year int, facet text, director text, why text,
  genres text[], imdb_rating real, recipients text[]);
create index if not exists sent_tmdb on sent(tmdb);
alter table films add column if not exists source text;
create table if not exists events (
  id bigserial primary key, at timestamptz default now(), tmdb int not null,
  kind text not null, detail jsonb);
create index if not exists events_tmdb on events(tmdb);
"""
FILM_COLS = ["name", "year", "imdb", "tmdb", "liked", "rating", "original", "director", "slug", "source"]


def db():
    import psycopg
    conn = psycopg.connect(CFG["DATABASE_URL"], autocommit=True)
    conn.execute(SCHEMA)
    return conn


def event(tmdb, kind, **detail):
    try:
        import psycopg.types.json as pj
        with db() as c:
            c.execute("insert into events(tmdb, kind, detail) values (%s,%s,%s)", (tmdb, kind, pj.Jsonb(detail)))
    except Exception as e:  # noqa: BLE001
        log("event log failed:", e)


def add_liked(m):
    """Film the user chose to download -> their list, liked, strongest taste signal."""
    try:
        with db() as c:
            c.execute(
                "insert into films(key, name, year, imdb, tmdb, liked, original, source) "
                "values (%s,%s,%s,%s,%s,true,%s,'download') "
                "on conflict (key) do update set liked=true, source='download', tmdb=excluded.tmdb, "
                "imdb=coalesce(excluded.imdb, films.imdb), updated_at=now()",
                (fkey(m["title"], m.get("year")), m["title"], m.get("year"), m.get("imdbId") or None,
                 m["tmdbId"], m.get("originalTitle")))
    except Exception as e:  # noqa: BLE001
        log("add_liked failed:", e)


def log(*a):
    print(dt.datetime.now().strftime("%H:%M:%S"), *a, flush=True)


# ---------------------------------------------------------------- Radarr
def radarr(method, path, body=None):
    req = urllib.request.Request(
        CFG["RADARR_URL"] + "/api/v3" + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-Api-Key": CFG["RADARR_KEY"], "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def lookup_tmdb(tmdb_id):
    return radarr("GET", f"/movie/lookup/tmdb?tmdbId={int(tmdb_id)}")


def lookup_title(title, year):
    res = radarr("GET", "/movie/lookup?term=" + urllib.parse.quote(f"{title} {year}"))
    votes = lambda m: ((m.get("ratings") or {}).get("imdb") or {}).get("votes") or 0
    exact = [m for m in res if year and abs(int(m.get("year") or 0) - int(year)) <= 1 and (
        norm(m["title"]) == norm(title) or norm(m.get("originalTitle", "")) == norm(title))]
    if exact:
        return max(exact, key=votes)
    for m in res:
        if year and int(m.get("year") or 0) == int(year):
            return m
    return None


def poster_url(m, size="w500"):
    for i in m.get("images", []):
        if i.get("coverType") == "poster" and i.get("remoteUrl"):
            return i["remoteUrl"].replace("/original/", f"/{size}/")
    return ""


# ---------------------------------------------------------------- Letterboxd
def norm(s):
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()
    s = s.replace("&", "and")
    return re.sub(r"[^a-z0-9]+", "", s)


def fkey(name, year):
    return f"{norm(name)}|{year or ''}"


def http_get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Language": "en"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode("utf-8", "replace")


def merge(films, name, year, **kw):
    k = fkey(name, year)
    f = films.setdefault(k, {"name": name, "year": year})
    for a, b in kw.items():
        if b not in (None, "", False):
            f[a] = b
    return f


def scrape_letterboxd(films, user):
    """Recent watched films (first page of /films/) + RSS diary. Deeper pages are
    behind a Cloudflare challenge; the full history comes from the data export."""
    try:
        page = http_get(f"https://letterboxd.com/{user}/films/")
        for chunk in page.split('class="griditem')[1:]:
            m = re.search(r'data-item-name="([^"]+)"', chunk)
            if not m:
                continue
            full = html.unescape(m.group(1))
            ym = re.match(r"^(.*) \((\d{4})\)$", full)
            name, year = (ym.group(1), int(ym.group(2))) if ym else (full, None)
            slug = re.search(r'data-item-slug="([^"]+)"', chunk)
            rating = re.search(r"rated-(\d+)", chunk)
            f = merge(films, name, year, slug=slug and slug.group(1),
                      rating=rating and int(rating.group(1)) / 2)
            if rating:
                f["liked"] = int(rating.group(1)) / 2 > 3   # liked = rated above 3 stars
        log("letterboxd films page ok")
    except Exception as e:  # noqa: BLE001
        log("letterboxd films page failed:", e)
    try:
        ns = {"letterboxd": "https://letterboxd.com", "tmdb": "https://themoviedb.org"}
        root = ET.fromstring(http_get(f"https://letterboxd.com/{user}/rss/"))
        for it in root.iter("item"):
            name = it.findtext("letterboxd:filmTitle", namespaces=ns)
            if not name:
                continue
            year = it.findtext("letterboxd:filmYear", namespaces=ns)
            rating = it.findtext("letterboxd:memberRating", namespaces=ns)
            f = merge(films, name, int(year) if year else None,
                  rating=float(rating) if rating else None,
                  tmdb=int(it.findtext("tmdb:movieId", namespaces=ns) or 0) or None)
            if rating:
                f["liked"] = float(rating) > 3
        log("letterboxd rss ok")
    except Exception as e:  # noqa: BLE001
        log("letterboxd rss failed:", e)


def read_imdb_lists(films):
    """IMDb list/watchlist/ratings CSV exports dropped into ~/movie-picks/lists/.
    Every title counts as taste signal and is never recommended."""
    for p in sorted((ROOT / "lists").glob("*.csv")):
        with p.open(encoding="utf-8-sig") as fh:
            for r in csv.DictReader(fh):
                if not r.get("Const") or not r.get("Title"):
                    continue
                if r.get("Title Type") and r["Title Type"] not in ("Movie", "TV Movie", "Short", "Video"):
                    continue
                year = int(r["Year"]) if (r.get("Year") or "").isdigit() else None
                rating = float(r["Your Rating"]) / 2 if r.get("Your Rating") else None
                f = merge(films, r["Title"], year, imdb=r["Const"], liked=rating is None or rating >= 3.5,
                          rating=rating, director=r.get("Directors"))
                orig = r.get("Original Title")
                if orig and norm(orig) != norm(r["Title"]):
                    f["original"] = orig
        log("imdb list ok:", p.name)


def read_export(films):
    """Letterboxd data export (Settings → Data → Export) dropped as a .zip into
    ~/movie-picks/lists/. Uses watched.csv, likes/films.csv, ratings.csv."""
    read_imdb_lists(films)
    zips = sorted((ROOT / "lists").glob("*.zip"), key=lambda p: p.stat().st_mtime)
    if not zips:
        return
    with zipfile.ZipFile(zips[-1]) as z:
        def rows(suffix):
            for n in z.namelist():
                if n.endswith(suffix):
                    yield from csv.DictReader(io.TextIOWrapper(z.open(n), "utf-8"))
                    return

        for r in rows("watched.csv"):
            merge(films, r["Name"], int(r["Year"]) if r.get("Year") else None)
        for r in rows("likes/films.csv"):
            merge(films, r["Name"], int(r["Year"]) if r.get("Year") else None, liked=True)
        for r in rows("ratings.csv"):
            merge(films, r["Name"], int(r["Year"]) if r.get("Year") else None,
                  rating=float(r["Rating"]) if r.get("Rating") else None)
    log("letterboxd export ok:", zips[-1].name)


def load_films():
    with db() as c:
        films = {r[0]: {k: v for k, v in zip(FILM_COLS, r[1:]) if v is not None}
                 for r in c.execute("select key, " + ", ".join(FILM_COLS) + " from films")}
        read_export(films)
        scrape_letterboxd(films, CFG["LETTERBOXD_USER"])
        cols = ", ".join(FILM_COLS)
        upd = ", ".join(f"{k}=coalesce(excluded.{k}, films.{k})" for k in FILM_COLS) + ", updated_at=now()"
        with c.cursor() as cur:
            cur.executemany(
                f"insert into films(key, {cols}) values (%s, {', '.join(['%s'] * len(FILM_COLS))}) "
                f"on conflict (key) do update set {upd}",
                [(k, *[f.get(col) for col in FILM_COLS]) for k, f in films.items()])
    return films


def load_history():
    with db() as c:
        return [{"tmdb": r[0], "title": r[1], "year": r[2]}
                for r in c.execute("select tmdb, title, year from sent order by sent_at")]


# ---------------------------------------------------------------- Claude
def run_claude(prompt, system=None):
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    out = subprocess.run(
        [os.path.expanduser("~/.local/bin/claude"), "-p", prompt, "--output-format", "json",
         "--model", CFG["CLAUDE_MODEL"], "--tools", "", "--strict-mcp-config", "--no-session-persistence",
         *(["--append-system-prompt", system] if system else [])],
        capture_output=True, text=True, timeout=1200, env=env, cwd=STATE)
    if out.returncode != 0:
        raise RuntimeError(f"claude failed: {out.stderr[-2000:]} {out.stdout[-2000:]}")
    text = json.loads(out.stdout)["result"]
    return json.loads(re.search(r"\[.*\]", text, re.S).group(0))


def ask_claude(films, exclude, n):
    """Split the user's list into n maximally different taste facets and propose
    3 ranked candidates per facet. Returns [{facet, anchors, picks:[...]}]."""
    fmt = lambda f: (f"{f['name']} ({f.get('year') or '?'})" + (f" ★{f['rating']}" if f.get("rating") else "")
                     + (" [CHOSE TO WATCH - strongest signal]" if f.get("source") == "download" else ""))
    seen = [fmt(f) for f in films.values()]
    prompt = f"""You are a film curator with very broad taste. One person's film list (saved/watched; no ratings):
{chr(10).join(seen)}

Never recommend (already seen or already suggested):
{chr(10).join(exclude) or '(none)'}

Step 1. Split their list into exactly {n} taste facets that are as DIFFERENT from each other as possible
(genre, era, region, tone, energy: e.g. cyberpunk / anime / 60s-70s European psychological / cozy
contemporary indie / club culture / modern thrillers / body horror / romance / comedy / recent festival films).
Each facet must be anchored by at least 2 films from the list. At most 2 facets may be about pre-1980 cinema.

Step 2. For each facet propose 3 ranked unseen feature films that a fan of that facet's anchors would enjoy.
- Prefer non-obvious picks: skip the famous "greatest films" canon; at least one candidate per facet should be
  little-known (well under 50k IMDb votes).
- Across the FIRST candidates of all facets: at least 4 films from 2010 or later, at most 3 before 1980,
  at least 5 different countries, no director twice, no two films with the same premise/tone.
- Only released films that exist. Use exact titles and years.

Respond with ONLY a JSON array, no prose:
[{{"facet": "short facet name, 2-4 words", "anchors": ["Film A", "Film B"],
   "picks": [{{"title": "English title", "original_title": "original-language title", "year": 1999,
              "director": "Name", "country": "Country", "why": "..."}}, ...3 items]}}, ...{n} facets]

Rules for "why" (max 30 words, plain English, no hype):
- One concrete sentence about what the film actually is (premise, style, tone).
- Optionally: "Close to <anchor>" naming ONE anchor film of that facet and the concrete shared quality.
- Never claim what they felt ("you loved", "you'll adore"). No marketing adjectives.
- Only state facts you are certain about (adaptations, remakes, influences); if unsure, leave it out."""
    return run_claude(prompt)


def choose(films, history):
    n = int(CFG["PICKS_PER_DAY"])
    watched_keys = set(films) | {fkey(f["original"], f.get("year")) for f in films.values() if f.get("original")}
    watched_imdb = {f.get("imdb") for f in films.values() if f.get("imdb")}
    watched_tmdb = {f.get("tmdb") for f in films.values() if f.get("tmdb")}
    sent_tmdb = {h["tmdb"] for h in history}
    in_radarr = {m["tmdbId"] for m in radarr("GET", "/movie")}
    picks = []
    max_per_decade = max(2, -(-n * 3 // 10))   # 3 for 10 picks
    max_per_genre = max(2, -(-n * 3 // 10))

    def resolve(c):
        if fkey(c["title"], c.get("year")) in watched_keys or fkey(c.get("original_title", ""), c.get("year")) in watched_keys:
            return None
        try:
            m = lookup_title(c["title"], c.get("year")) or (
                c.get("original_title") and lookup_title(c["original_title"], c.get("year")))
        except Exception as e:  # noqa: BLE001
            log("lookup failed", c["title"], e)
            return None
        if not m:
            log("not found in metadata:", c["title"], c.get("year"))
            return None
        t = m["tmdbId"]
        if (m.get("imdbId") in watched_imdb or t in watched_tmdb or t in sent_tmdb or t in in_radarr
                or any(p["tmdb"] == t for p in picks)
                or fkey(m["title"], m["year"]) in watched_keys
                or fkey(m.get("originalTitle", ""), m["year"]) in watched_keys):
            return None
        return m

    def fits(m, c):
        dec = (m.get("year") or 0) // 10
        g = (m.get("genres") or ["?"])[0]
        d = norm(c.get("director", ""))
        return (sum(1 for p in picks if p["year"] // 10 == dec) < max_per_decade
                and sum(1 for p in picks if (p["genres"] or ["?"])[0] == g) < max_per_genre
                and not (d and any(norm(p["director"]) == d for p in picks)))

    def add(m, c, facet):
        picks.append({"tmdb": m["tmdbId"], "title": m["title"], "year": m["year"], "facet": facet,
                      "original_title": m.get("originalTitle") or c.get("original_title") or m["title"],
                      "director": c.get("director", ""), "why": c.get("why", ""),
                      "overview": m.get("overview", ""), "runtime": m.get("runtime") or 0,
                      "genres": m.get("genres", [])[:3], "poster": poster_url(m),
                      "imdb": m.get("imdbId") or "", "trailer": m.get("youTubeTrailerId") or "",
                      "imdb_rating": ((m.get("ratings") or {}).get("imdb") or {}).get("value"),
                      "language": (m.get("originalLanguage") or {}).get("name", "")})

    exclude = [f"{h['title']} ({h['year']})" for h in history]
    for attempt in range(2):
        need = n - len(picks)
        if need <= 0:
            break
        facets = ask_claude(films, exclude + [f"{p['title']} ({p['year']})" for p in picks], need if attempt else n)
        for f in facets:
            if len(picks) >= n:
                break
            fallback = None
            for c in f.get("picks", []):
                m = resolve(c)
                if not m:
                    continue
                if fits(m, c):
                    add(m, c, f.get("facet", ""))
                    fallback = None
                    break
                fallback = fallback or (m, c)
            else:
                if fallback and len(picks) < n:
                    add(*fallback, f.get("facet", ""))
    return picks


# ---------------------------------------------------------------- links
def sign(tmdb, exp):
    return hmac.new(CFG["LINK_SECRET"].encode(), f"{tmdb}:{exp}".encode(), hashlib.sha256).hexdigest()[:24]


def download_link(tmdb):
    exp = int(time.time()) + 60 * 86400
    return f"{CFG['PUBLIC_URL']}/d/{tmdb}/{exp}/{sign(tmdb, exp)}"


def verify(tmdb, exp, sig):
    return exp.isdigit() and int(exp) > time.time() and hmac.compare_digest(sign(tmdb, exp), sig)


# ---------------------------------------------------------------- email
E = html.escape


def fmt_runtime(m):
    return f"{m // 60}h {m % 60:02d}m" if m else ""


def render_email(picks, date):
    cards = []
    for p in picks:
        meta = " · ".join(x for x in [str(p["year"]), fmt_runtime(p["runtime"]), ", ".join(p["genres"]),
                                       f"IMDb {p['imdb_rating']}" if p.get("imdb_rating") else ""] if x)
        orig = ""
        if norm(p["original_title"]) != norm(p["title"]):
            orig = (f'<div style="font-size:15px;color:#a8a29e;font-style:italic;margin:2px 0 0">'
                    f'{E(p["original_title"])}</div>')
        director = f'<div style="font-size:13px;color:#a8a29e;margin-top:2px">dir. {E(p["director"])}</div>' if p["director"] else ""
        poster = (f'<img src="{E(p["poster"])}" width="120" alt="{E(p["title"])} poster" '
                  f'style="display:block;width:120px;max-width:120px;height:auto;border-radius:6px;border:0">'
                  if p["poster"] else "")
        lb = f"https://letterboxd.com/tmdb/{p['tmdb']}/"
        trailer_url = (f"https://www.youtube.com/watch?v={p['trailer']}" if p.get("trailer") else
                       "https://www.youtube.com/results?search_query=" + urllib.parse.quote(f"{p['title']} {p['year']} trailer"))
        trailer = (f'&nbsp;<a href="{E(trailer_url)}" style="display:inline-block;border:1px solid #44403c;color:#e7e5e4;'
                   f'text-decoration:none;font-size:14px;padding:8px 14px;border-radius:6px">▶ Trailer</a>')
        imdb = f'&nbsp;&nbsp;<a href="https://www.imdb.com/title/{E(p["imdb"])}/" style="color:#a8a29e;font-size:13px">IMDb</a>' if p["imdb"] else ""
        cards.append(f"""
<tr><td style="padding:0 0 16px">
 <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#1c1917;border-radius:10px">
  <tr>
   <td valign="top" width="120" style="padding:16px 0 16px 16px;width:120px">{poster}</td>
   <td valign="top" style="padding:16px">
    <div style="font-size:11px;color:#f59e0b;text-transform:uppercase;letter-spacing:.08em;font-weight:700;margin-bottom:4px">{E(p.get('facet', ''))}</div>
    <div style="font-size:20px;line-height:1.25;font-weight:700;color:#fafaf9">{E(p['title'])}</div>
    {orig}{director}
    <div style="font-size:12px;color:#78716c;margin-top:6px;text-transform:uppercase;letter-spacing:.04em">{E(meta)}</div>
    <div style="font-size:14px;line-height:1.5;color:#e7e5e4;margin-top:10px">{E(p['why'])}</div>
    <div style="font-size:13px;line-height:1.5;color:#a8a29e;margin-top:8px">{E(p['overview'][:320])}</div>
    <div style="margin-top:14px">
     <a href="{E(download_link(p['tmdb']))}" style="display:inline-block;background:#f59e0b;color:#1c1917;text-decoration:none;font-weight:700;font-size:14px;padding:9px 16px;border-radius:6px">⬇ Download</a>
     &nbsp;<a href="{lb}" style="display:inline-block;border:1px solid #44403c;color:#e7e5e4;text-decoration:none;font-size:14px;padding:8px 14px;border-radius:6px">+ Letterboxd</a>{trailer}{imdb}
    </div>
   </td>
  </tr>
 </table>
</td></tr>""")
    return f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="dark"><meta name="supported-color-schemes" content="dark"></head>
<body style="margin:0;padding:0;background:#0c0a09">
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#0c0a09">
 <tr><td align="center" style="padding:24px 12px">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:620px;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif">
   <tr><td style="padding:0 4px 18px">
    <div style="font-size:12px;color:#f59e0b;letter-spacing:.12em;text-transform:uppercase;font-weight:700">Movie Picks</div>
    <div style="font-size:24px;color:#fafaf9;font-weight:700;margin-top:4px">{len(picks)} films for tonight</div>
    <div style="font-size:13px;color:#78716c;margin-top:4px">{date:%A, %d %B %Y} · one from each side of your taste</div>
   </td></tr>
   {''.join(cards)}
   <tr><td style="padding:8px 4px;font-size:12px;color:#57534e">“Download” sends the film to Radarr (1080p, up to 5&nbsp;GB).</td></tr>
  </table>
 </td></tr>
</table></body></html>"""


def render_text(picks):
    out = []
    for p in picks:
        out.append(f"{p['title']} ({p['year']})" + (f" / {p['original_title']}" if norm(p['original_title']) != norm(p['title']) else ""))
        out.append(p["why"])
        if p.get("trailer"):
            out.append("Trailer: https://www.youtube.com/watch?v=" + p["trailer"])
        out.append("Download: " + download_link(p["tmdb"]))
        out.append("")
    return "\n".join(out)


def send_email(subject, html_body, text_body):
    rcpts = [r.strip() for r in CFG.get("RECIPIENTS", "").split(",") if r.strip()]
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = CFG["MAIL_FROM"]
    msg["To"] = ", ".join(rcpts)
    msg["Message-ID"] = make_msgid(domain=CFG["MAIL_FROM"].rsplit("@", 1)[-1].strip(">"))
    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype="html")
    with smtplib.SMTP_SSL(CFG["SMTP_HOST"], int(CFG["SMTP_PORT"]), timeout=60) as s:
        s.login(CFG["SMTP_USER"], CFG["SMTP_PASSWORD"].replace(" ", ""))
        s.send_message(msg)
    log("email sent to", rcpts)


def cmd_pick(dry_run=False):
    history = load_history()
    films = load_films()
    log(f"films known: {len(films)}, liked: {sum(1 for f in films.values() if f.get('liked'))}")
    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
    import selection
    picks = selection.choose(films, history)
    if not picks:
        raise SystemExit("no picks produced")
    today = dt.date.today()
    body = render_email(picks, today)
    (STATE / "last_email.html").write_text(body)
    subject = f"{len(picks)} films tonight: " + " · ".join(p["title"] for p in picks[:3]) + (" …" if len(picks) > 3 else "")
    log(subject)
    if dry_run or not CFG.get("SMTP_PASSWORD"):
        log("dry run / no SMTP_PASSWORD: saved to", STATE / "last_email.html")
        return
    send_email(subject, body, render_text(picks))
    rcpts = [r.strip() for r in CFG.get("RECIPIENTS", "").split(",") if r.strip()]
    with db() as c, c.cursor() as cur:
        cur.executemany(
            "insert into sent(batch, tmdb, title, year, facet, director, why, genres, imdb_rating, recipients) "
            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
            [(today, p["tmdb"], p["title"], p["year"], p.get("facet"), p["director"], p["why"],
              p["genres"], p.get("imdb_rating"), rcpts) for p in picks])


# ---------------------------------------------------------------- web
PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Movie Picks</title>{refresh}
<style>
:root{{--bg:#0c0a09;--card:#1c1917;--fg:#fafaf9;--mut:#a8a29e;--acc:#f59e0b}}
body{{margin:0;background:var(--bg);color:var(--fg);font:16px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif}}
main{{max-width:520px;margin:0 auto;padding:24px 16px}}
.card{{background:var(--card);border-radius:12px;padding:16px;display:flex;gap:16px}}
img{{width:120px;border-radius:8px;flex:none;align-self:flex-start}}
h1{{font-size:20px;margin:0}} .o{{color:var(--mut);font-style:italic}} .m{{color:var(--mut);font-size:14px}}
button{{margin-top:14px;background:var(--acc);color:#1c1917;border:0;border-radius:8px;padding:12px 18px;font-weight:700;font-size:16px;cursor:pointer}}
.s{{margin-top:14px;font-weight:600}} .bar{{height:8px;background:#292524;border-radius:4px;margin-top:8px;overflow:hidden}}
.bar i{{display:block;height:100%;background:var(--acc)}}
</style></head><body><main><div class="card">{poster}<div>
<h1>{title}</h1>{orig}<div class="m">{meta}</div>{body}</div></div></main></body></html>"""


def movie_status(m):
    if m.get("hasFile"):
        size = (m.get("movieFile") or {}).get("size") or m.get("sizeOnDisk") or 0
        return f'<div class="s">✓ Downloaded — on the SSD ({size / 1e9:.1f} GB)</div>', False
    q = radarr("GET", f"/queue?movieIds={m['id']}&pageSize=10").get("records", [])
    if q:
        r = q[0]
        pct = 100 * (1 - (r.get("sizeleft") or 0) / r["size"]) if r.get("size") else 0
        left = f" · {r['timeleft']} left" if r.get("timeleft") else ""
        return (f'<div class="s">Downloading: {pct:.0f}%{left}</div><div class="m">{E(r.get("title", ""))}</div>'
                f'<div class="bar"><i style="width:{pct:.0f}%"></i></div>'), True
    if recent_stall(m["tmdbId"]):
        return ('<div class="s">The previous torrent stalled (no seeders).</div>'
                '<div class="m">Looking for another release — this page refreshes by itself.</div>'), True
    added = dt.datetime.fromisoformat(m["added"].replace("Z", "+00:00"))
    if (dt.datetime.now(dt.timezone.utc) - added).total_seconds() < 600:
        return '<div class="s">Searching for a release (1080p, ≤ 5 GB)…</div>', True
    return ('<div class="s">No suitable release found yet.</div>'
            '<div class="m">Radarr keeps watching the trackers and will grab it when one appears.</div>'), False


class Handler(BaseHTTPRequestHandler):
    server_version = "movie-picks"

    def log_message(self, fmt, *args):
        log("web", self.address_string(), fmt % args)

    def reply(self, code, body, ctype="text/html; charset=utf-8", headers=None):
        b = body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(b)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Robots-Tag", "noindex")
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(b)

    def parse(self):
        m = re.fullmatch(r"/d/(\d+)/(\d+)/([0-9a-f]{24})", urllib.parse.urlparse(self.path).path)
        if not m or not verify(*m.groups()):
            self.reply(404, "<h1>Link expired or invalid</h1>")
            return None
        return int(m.group(1))

    def page(self, meta_movie, body, refresh=False):
        p = meta_movie
        orig = (f'<div class="o">{E(p.get("originalTitle", ""))}</div>'
                if norm(p.get("originalTitle", "")) != norm(p["title"]) else "")
        meta = " · ".join(x for x in [str(p.get("year", "")), fmt_runtime(p.get("runtime") or 0),
                                       ", ".join(p.get("genres", [])[:3])] if x)
        poster = f'<img src="{E(poster_url(p, "w342"))}" alt="">' if poster_url(p) else ""
        self.reply(200, PAGE.format(refresh='<meta http-equiv="refresh" content="15">' if refresh else "",
                                    poster=poster, title=E(p["title"]), orig=orig, meta=E(meta), body=body))

    def do_GET(self):
        if self.path == "/healthz":
            return self.reply(200, "ok", "text/plain")
        tmdb = self.parse()
        if tmdb is None:
            return
        try:
            existing = radarr("GET", f"/movie?tmdbId={tmdb}")
            if existing:
                body, refresh = movie_status(existing[0])
                return self.page(existing[0], body, refresh)
            m = lookup_tmdb(tmdb)
            event(tmdb, "open", ua=self.headers.get("User-Agent", "")[:200])
            self.page(m, '<form method="post"><button type="submit">⬇ Download</button></form>'
                         '<div class="m" style="margin-top:8px">1080p, up to 5 GB, saved to the SSD.</div>')
        except Exception as e:  # noqa: BLE001
            log("web error", e)
            self.reply(502, "<h1>Radarr is unavailable</h1>")

    def do_POST(self):
        tmdb = self.parse()
        if tmdb is None:
            return
        try:
            if not radarr("GET", f"/movie?tmdbId={tmdb}"):
                m = lookup_tmdb(tmdb)
                m.update(qualityProfileId=int(CFG["RADARR_PROFILE"]), rootFolderPath="/media/movies",
                         monitored=True, minimumAvailability="released",
                         addOptions={"searchForMovie": True, "monitor": "movieOnly"})
                radarr("POST", "/movie", m)
                log("added to radarr:", m["title"], m.get("year"))
                event(tmdb, "download", title=m["title"])
            self.reply(303, "", headers={"Location": self.path})
        except Exception as e:  # noqa: BLE001
            log("web error", e)
            self.reply(502, "<h1>Could not add the film to Radarr</h1>")


STALL_HOURS = 2
STALL_MIN_PROGRESS = 0.02   # less than 2% of the file in STALL_HOURS -> stalled


def cmd_watch():
    """Replace stalled torrents: blocklist the release and let Radarr grab another one."""
    with db() as c:
        c.execute("""create table if not exists dl_progress (
            download_id text primary key, tmdb int, title text, size bigint,
            checkpoint_at timestamptz not null, checkpoint_left bigint not null)""")
        queue = radarr("GET", "/queue?pageSize=100&includeMovie=true").get("records", [])
        live = set()
        for r in queue:
            did, size, left = r.get("downloadId"), r.get("size") or 0, r.get("sizeleft") or 0
            if not did or not size:
                continue
            live.add(did)
            row = c.execute("select checkpoint_at, checkpoint_left from dl_progress where download_id=%s", (did,)).fetchone()
            if not row:
                c.execute("insert into dl_progress values (%s,%s,%s,%s,now(),%s)",
                          (did, r["movie"]["tmdbId"], r.get("title"), size, left))
                continue
            at, cleft = row
            hours = (dt.datetime.now(dt.timezone.utc) - at).total_seconds() / 3600
            if hours < STALL_HOURS:
                continue
            if left == 0 or cleft - left >= STALL_MIN_PROGRESS * size:
                c.execute("update dl_progress set checkpoint_at=now(), checkpoint_left=%s where download_id=%s", (left, did))
                continue
            log(f"stalled {hours:.1f}h: {r.get('title')} — blocklisting and searching another release")
            radarr("DELETE", f"/queue/{r['id']}?removeFromClient=true&blocklist=true&skipRedownload=false")
            event(r["movie"]["tmdbId"], "stalled", release=r.get("title"), hours=round(hours, 1))
            c.execute("delete from dl_progress where download_id=%s", (did,))
        if live:
            c.execute("delete from dl_progress where not (download_id = any(%s))", (list(live),))
        else:
            c.execute("delete from dl_progress")


def recent_stall(tmdb):
    try:
        with db() as c:
            return c.execute("select 1 from events where tmdb=%s and kind='stalled' and at > now() - interval '1 day'",
                             (tmdb,)).fetchone() is not None
    except Exception:  # noqa: BLE001
        return False


def cmd_serve():
    port = int(CFG.get("WEB_PORT", "8790"))
    log("listening on 127.0.0.1:%d" % port)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        cmd_serve()
    elif len(sys.argv) > 1 and sys.argv[1] == "watch":
        cmd_watch()
    elif len(sys.argv) > 1 and sys.argv[1] == "sync":
        f = load_films()
        log(f"letterboxd sync: {len(f)} films, liked {sum(1 for x in f.values() if x.get('liked'))}")
    elif len(sys.argv) > 1 and sys.argv[1] == "pick":
        cmd_pick(dry_run="--dry-run" in sys.argv)
    else:
        print(__doc__)
