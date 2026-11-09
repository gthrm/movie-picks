"""Diversity-first selection (see reports/Разнообразие LLM рекомендаций фильмов.md):

1. never repeat: code filters seen/sent/in-Radarr/canon; sent history + canon also go into the prompt
2. taste facets are generated ONCE and stored in Postgres; each evening code picks random shuffled
   anchors per facet and a rotating "lens", plus a rotating curator persona
3. verbalized sampling: 6 tail candidates per facet with probabilities (<0.10); code samples
4. popularity tiers by IMDb votes: at most 2 "canon" (>300k votes), at least 3 "deep" (<50k)
"""
import datetime as dt
import json
import random
import urllib.request

import movie_picks as mp

CANON_VOTES = 300_000
DEEP_VOTES = 50_000
MAX_CANON = 2
MIN_DEEP = 3

CANON_EXTRA = """Possession (1981); Holy Motors (2012); Chungking Express (1994); Mulholland Drive (2001);
Wings of Desire (1987); Perfect Blue (1997); In the Mood for Love (2000); Stalker (1979); Persona (1966);
Videodrome (1983); Ghost in the Shell (1995); Akira (1988); Eraserhead (1977); Paris, Texas (1984);
The Conversation (1974); Burning (2018); Taste of Cherry (1997); Happy Together (1997); 8½ (1963);
La Haine (1995); Chungking Express (1994); Lost Highway (1997); Solaris (1972); Seconds (1966)"""

LENSES = [
    "outside Europe and the US", "made before 1980", "made in 2015 or later", "Asian cinema",
    "a genre film (thriller/horror/sci-fi/comedy)", "Latin American or African cinema",
    "a debut feature", "under 100 minutes", "directed by a woman", "Eastern European or Nordic",
    "the 1990s-2000s", "a comedy or something light", "made in the last 3 years",
]
PERSONAS = [
    "You are a festival programmer who hunts for overlooked films from every continent.",
    "You are a video-store clerk with deep, eclectic, unpretentious taste across genres.",
    "You are a film critic who champions under-seen films over the usual canon.",
    "You are a cinematheque curator who builds surprising double bills.",
    "You are a genre-film fan who also loves auteur cinema and knows world cinema deeply.",
]


def ensure_tables(c):
    c.execute("""create table if not exists facets (
        id serial primary key, name text not null, films text[] not null,
        films_count int not null, created_at timestamptz default now())""")
    c.execute("""create table if not exists candidates (
        id bigserial primary key, batch date not null, facet text, lens text, title text, year int,
        tmdb int, votes int, probability real, picked boolean default false, reason text)""")


def canon_set():
    """IMDb Top 250 (via Radarr's public metadata server) + a hand-written canon list."""
    titles = {mp.fkey(t.split(" (")[0], int(t.rsplit("(", 1)[1].rstrip(");"))) for t in
              [x.strip() for x in CANON_EXTRA.replace("\n", " ").split(";") if x.strip()]}
    tmdb = set()
    try:
        req = urllib.request.Request("https://api.radarr.video/v1/list/imdb/top250",
                                     headers={"User-Agent": "movie-picks"})
        for m in json.load(urllib.request.urlopen(req, timeout=30)):
            tmdb.add(m["TmdbId"])
    except Exception as e:  # noqa: BLE001
        mp.log("top250 fetch failed:", e)
    names = [x.strip() for x in CANON_EXTRA.replace("\n", " ").split(";") if x.strip()]
    return titles, tmdb, names


def get_facets(c, films, n):
    row = c.execute("select films_count from facets order by created_at desc limit 1").fetchone()
    if row and len(films) - row[0] < 10:
        latest = c.execute("select max(created_at) from facets").fetchone()[0]
        return [{"name": r[0], "films": r[1]}
                for r in c.execute("select name, films from facets where created_at=%s", (latest,))]
    listing = "\n".join(f"{f['name']} ({f.get('year') or '?'})" for f in films.values())
    facets = mp.run_claude(f"""Here is one person's film list:
{listing}

Split ALL of these films into exactly {n} taste facets that are as different from each other as possible
(genre, era, region, tone, energy). Every film goes into exactly one facet; each facet needs at least 3 films.
At most 2 facets may be mostly pre-1980 cinema. Facet names: 2-4 words, concrete (e.g. "Cyberpunk & hackers").
Respond with ONLY JSON: [{{"facet": "name", "films": ["Title (Year)", ...]}}, ...]""")
    now = dt.datetime.now(dt.timezone.utc)
    for f in facets:
        c.execute("insert into facets(name, films, films_count, created_at) values (%s,%s,%s,%s)",
                  (f["facet"], f["films"], len(films), now))
    mp.log(f"facets regenerated: {[f['facet'] for f in facets]}")
    return [{"name": f["facet"], "films": f["films"]} for f in facets]


def ask(facets, films, exclude, canon_names, rng, per_facet=6):
    lenses = rng.sample(LENSES, k=min(len(LENSES), len(facets)))
    blocks = []
    for f, lens in zip(facets, lenses):
        anchors = rng.sample(f["films"], k=min(len(f["films"]), rng.randint(4, 6)))
        f["lens"] = lens
        blocks.append(f'- Facet "{f["name"]}". Anchors: {"; ".join(anchors)}. Tonight\'s lens: {lens}.')
    picked = [f"{x['name']} ({x.get('year')})" for x in films.values() if x.get("source") == "download"]
    rng.shuffle(blocks)
    prompt = f"""Recommend films for one person, facet by facet. For each facet, the anchors are films from their
list; the lens is a HARD constraint for that facet tonight.
{chr(10).join(blocks)}

{('Films they recently CHOSE to watch (strongest taste signal): ' + '; '.join(picked)) if picked else ''}

Do NOT suggest any film from their list, anything already suggested before, or these over-recommended canon films:
{'; '.join(exclude + canon_names)}

For EACH facet give {per_facet} candidates sampled from the TAILS of the distribution: every candidate's
probability (how typical a pick it would be for this facet) must be below 0.10. No famous "greatest films" canon.
Only real, released feature films with exact titles and years.

Respond with ONLY JSON:
[{{"facet": "facet name", "candidates": [{{"title": "English title", "original_title": "original title",
   "year": 1999, "director": "Name", "country": "Country", "probability": 0.05, "why": "..."}}]}}]

Rules for "why" (max 30 words, plain English, no hype): one concrete sentence on what the film is (premise,
style, tone); optionally "Close to <anchor>" naming ONE anchor and the shared quality. Never claim what they
felt. Only state facts you are certain about."""
    return mp.run_claude(prompt, system=rng.choice(PERSONAS))


def choose(films, history):
    n = int(mp.CFG["PICKS_PER_DAY"])
    rng = random.Random()
    today = dt.date.today()
    watched_keys = set(films) | {mp.fkey(f["original"], f.get("year")) for f in films.values() if f.get("original")}
    watched_imdb = {f.get("imdb") for f in films.values() if f.get("imdb")}
    watched_tmdb = {f.get("tmdb") for f in films.values() if f.get("tmdb")}
    sent_tmdb = {h["tmdb"] for h in history}
    in_radarr = {m["tmdbId"] for m in mp.radarr("GET", "/movie")}
    canon_keys, canon_tmdb, canon_names = canon_set()
    exclude = [f"{h['title']} ({h['year']})" for h in history]

    with mp.db() as c:
        ensure_tables(c)
        facets = get_facets(c, films, n)
        answer = ask(facets, films, exclude, canon_names, rng)
        lens_of = {f["name"]: f.get("lens", "") for f in facets}
        picks, logrows = [], []

        def votes(m):
            return ((m.get("ratings") or {}).get("imdb") or {}).get("votes") or 0

        def resolve(cand):
            k1 = mp.fkey(cand.get("title", ""), cand.get("year"))
            k2 = mp.fkey(cand.get("original_title", ""), cand.get("year"))
            if k1 in watched_keys or k2 in watched_keys:
                return None, "seen"
            if k1 in canon_keys or k2 in canon_keys:
                return None, "canon-list"
            try:
                m = mp.lookup_title(cand["title"], cand.get("year")) or (
                    cand.get("original_title") and mp.lookup_title(cand["original_title"], cand.get("year")))
            except Exception as e:  # noqa: BLE001
                return None, f"lookup error {e}"
            if not m:
                return None, "not found"
            t = m["tmdbId"]
            if m.get("imdbId") in watched_imdb or t in watched_tmdb or mp.fkey(m["title"], m["year"]) in watched_keys:
                return None, "seen"
            if t in sent_tmdb:
                return None, "already sent"
            if t in in_radarr:
                return None, "in radarr"
            if t in canon_tmdb:
                return None, "imdb top250"
            if any(p["tmdb"] == t for p in picks):
                return None, "duplicate"
            return m, "ok"

        def fits(m, cand):
            dec = (m.get("year") or 0) // 10
            g = (m.get("genres") or ["?"])[0]
            d = mp.norm(cand.get("director", ""))
            country = mp.norm(cand.get("country", ""))
            v = votes(m)
            return (sum(p["year"] // 10 == dec for p in picks) < 3
                    and sum((p["genres"] or ["?"])[0] == g for p in picks) < 3
                    and sum(mp.norm(p.get("country", "")) == country for p in picks) < 3
                    and not (d and any(mp.norm(p["director"]) == d for p in picks))
                    and not (v > CANON_VOTES and sum(p["votes"] > CANON_VOTES for p in picks) >= MAX_CANON))

        groups = [g for g in answer if g.get("candidates")]
        rng.shuffle(groups)
        for gi, g in enumerate(groups):
            if len(picks) >= n:
                break
            cands = list(g["candidates"])
            # sample order from the verbalized distribution
            w = [max(float(x.get("probability") or 0.05), 0.005) for x in cands]
            order = []
            while cands:
                i = rng.choices(range(len(cands)), weights=w)[0]
                order.append(cands.pop(i)); w.pop(i)
            resolved = []
            for cand in order:
                m, why = resolve(cand)
                logrows.append([today, g.get("facet"), lens_of.get(g.get("facet"), ""), cand.get("title"),
                                cand.get("year"), m and m["tmdbId"], m and votes(m), cand.get("probability"), False, why])
                if m:
                    resolved.append((m, cand, len(logrows) - 1))
            deep_have = sum(p["votes"] < DEEP_VOTES for p in picks)
            facets_left = len(groups) - gi
            if deep_have < MIN_DEEP and facets_left <= MIN_DEEP - deep_have:
                resolved.sort(key=lambda r: votes(r[0]) >= DEEP_VOTES)
            choice = next((r for r in resolved if fits(r[0], r[1])), resolved[0] if resolved else None)
            if not choice:
                continue
            m, cand, li = choice
            logrows[li][8] = True
            picks.append({"tmdb": m["tmdbId"], "title": m["title"], "year": m["year"], "facet": g.get("facet", ""),
                          "original_title": m.get("originalTitle") or cand.get("original_title") or m["title"],
                          "director": cand.get("director", ""), "country": cand.get("country", ""),
                          "why": cand.get("why", ""), "overview": m.get("overview", ""),
                          "runtime": m.get("runtime") or 0, "genres": m.get("genres", [])[:3],
                          "poster": mp.poster_url(m), "imdb": m.get("imdbId") or "",
                          "trailer": m.get("youTubeTrailerId") or "", "votes": votes(m),
                          "imdb_rating": ((m.get("ratings") or {}).get("imdb") or {}).get("value"),
                          "language": (m.get("originalLanguage") or {}).get("name", "")})
        with c.cursor() as cur:
            cur.executemany("insert into candidates(batch, facet, lens, title, year, tmdb, votes, probability, picked, reason) "
                            "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", logrows)
    mp.log(f"candidates: {len(logrows)}, picked: {len(picks)}, "
           f"canon: {sum(p['votes'] > CANON_VOTES for p in picks)}, deep: {sum(p['votes'] < DEEP_VOTES for p in picks)}")
    return picks
