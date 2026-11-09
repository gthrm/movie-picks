# Free data sources for grounded film candidates on a Raspberry Pi (state as of 2026-11-08)

Method: official docs fetched on 2026-11-08, plus live probes from the Pi itself (Raspberry Pi, 4 cores, 7.7 GiB RAM, about 2.8 GiB available, Python 3.14) against the Radarr metadata server, Wikidata, TasteDive and Letterboxd. "Live probe" findings are first-hand results from this session, not documentation.

## 1. TMDB API v3: endpoints, key, limits, terms, recommendations vs similar

### Takeaway
TMDB v3 is the most capable free source for structured candidate generation: `/discover/movie` with keyword, country, year, vote-count and watch-provider filters, plus `/similar`, `/recommendations` and `/find`. It is free for non-commercial use and has a soft limit of about 40 req/s. The terms carry three constraints that matter here: attribution (logo plus disclaimer), a 6-month cache cap, and an explicit clause against use "in connection with" ML/AI systems, which applies to an LLM-driven recommender.

### Cited Findings
- **Rate limit:** the upper limit sits "somewhere in the 40 requests per second range" and "could change at any time". The old limit of 40 requests per 10 seconds was disabled on 2019-12-16. — [TMDB rate limiting](https://developer.themoviedb.org/docs/rate-limiting)
- **Key registration:** click the API link in your account settings, accept the terms of use, and use a desktop browser because registration is "not optimized for mobile devices". The page describes no approval step. — [TMDB Getting started](https://developer.themoviedb.org/docs/getting-started)
- **Terms** (last updated 2023-10-20; no 2024–2026 changes listed):
  - No commercial use without a separate agreement.
  - Must show the TMDB logo, less prominent than your own branding, plus the notice "uses TMDB and the TMDB APIs but is not endorsed, certified, or otherwise approved by TMDB".
  - No caching of TMDB data for longer than 6 months.
  - Prohibits using the APIs or content "in connection with, including for training, a machine learning (ML)" system. Training or validating AI/LLMs is listed as an example of commercial use.
  - TMDB may change the terms by posting notice.
  - Source: [TMDB API Terms of Use](https://www.themoviedb.org/api-terms-of-use)
- **`GET /3/movie/{movie_id}/similar`** (params `language`, `page`): it "only looks for other items based on genres and plot keywords" and results "are not always going to be" accurate. The example response is very long (total_results 7269, 364 pages), so the long tail is noise. — [TMDB movie-similar reference](https://developer.themoviedb.org/reference/movie-similar)
- **`GET /3/movie/{movie_id}/recommendations`** (params `language`, `page`): the official reference gives no description of the algorithm. The response schema is empty in the docs. — [TMDB movie-recommendations reference](https://developer.themoviedb.org/reference/movie-recommendations)
- Third-party descriptions say similar is a keyword/genre match and "not the same as the Recommendation system you see on the website". Recommendations are described as based on what users who liked a title also liked. These are unofficial. — [Educative TMDB course](https://educative.io/courses/movie-database-api-python/movie-suggestions); [glama MCP tool description](https://glama.ai/mcp/servers/ryanxili/tmdb-mcp/tools/movie_recommendations)
- **Recommendation quality, live probe:** the Radarr metadata server's `Recommendations` field returns 10 TMDB recommendations per film (see section 2). They are strongly popularity-biased and often wrong for arthouse seeds:
  - Stalker (1979) → Inception, Edge of Tomorrow, Guardians of the Galaxy, The Creator, Oblivion, Valerian, Allegiant, The Dark Tower, The Giver, The Time Machine.
  - Parasite → Joker, Nightcrawler, No Other Choice, I Care a Lot, Kinds of Kindness…
  - Fight Club → Trainspotting, Sin City, Lost Highway, Requiem for a Dream, A History of Violence, plus noise such as "The Punisher: One Last Kill".
  - Source: live probe `POST https://api.radarr.video/v1/movie/bulk` with `[1398,550,496243,872585]`, 2026-11-08.
  - Caveat: it is not verified that these 10 are exactly TMDB's `/recommendations` page 1.
- **`GET /3/discover/movie` parameters:**
  - Dates and certification: `primary_release_year`, `primary_release_date.gte/lte`, `release_date.gte/lte`, `year`, `region`, `with_release_type`, `certification*`.
  - Votes and runtime: `vote_average.gte/lte`, `vote_count.gte/lte`, `with_runtime.gte/lte`.
  - People and companies: `with_cast`, `with_crew`, `with_people`, `with_companies`, `without_companies`.
  - Content: `with_genres`, `without_genres`, `with_keywords`, `without_keywords`, `with_origin_country`, `with_original_language`.
  - Availability: `watch_region`, `with_watch_providers`, `without_watch_providers`, `with_watch_monetization_types` (flatrate, free, ads, rent, buy).
  - Output: `sort_by` (default `popularity.desc`; also `vote_count.*`, `vote_average.*`, `revenue.*`, `primary_release_date.*`, `title.*`, `original_title.*`), `include_adult`, `page`.
  - Comma means AND and pipe means OR for cast, crew, companies, genres, keywords, people, release type, monetization types and providers.
  - Source: [TMDB discover-movie reference](https://developer.themoviedb.org/reference/discover-movie)
- **`GET /3/movie/{id}/watch/providers`:** per-country `results` with `flatrate` / `rent` / `buy` / `ads` lists (`provider_id`, `provider_name`, `logo_path`) and a TMDB `link`. The data comes from TMDB's "partnership with JustWatch", and "you must attribute the source of the data as JustWatch". — [TMDB movie-watch-providers reference](https://developer.themoviedb.org/reference/movie-watch-providers)

### Inferences
- **Useful v3 calls for this project:**
  - `GET /3/find/{tt…}?external_source=imdb_id` maps the 90 IMDb IDs to TMDB IDs. Radarr's `movie/imdb/{tt}` already does this without a key (section 2).
  - `GET /3/movie/{id}/keywords` and `GET /3/search/keyword?query=` return keyword IDs for `with_keywords`.
  - `GET /3/movie/{id}?append_to_response=recommendations,similar,keywords,credits,watch/providers` fetches everything in one call.
  - Auth is `?api_key=` or a `Authorization: Bearer <read access token>` header.
  - These are standard v3 endpoints, but their reference pages were not fetched in this session.
- **Quality ranking:** `/recommendations` is more useful than `/similar` (co-engagement signal vs crude genre/keyword overlap). Both lean toward popular English-language titles, so the "avoid canon" goal needs post-filtering or `discover` with `vote_count.lte`.
- **Best TMDB lever for diversity:** `discover` combining a seed's keyword IDs (pipe-OR), plus `with_origin_country` / `with_original_language`, a year window, and a vote-count band (e.g. `vote_count.gte=200&vote_count.lte=3000`), sorted by `vote_average.desc`.
- **Python stdlib:** works with `urllib.request` and `json`. At 90 seeds × 1–3 calls per seed, the rate limit is irrelevant.
- **Terms risk:** feeding TMDB results to an LLM to produce recommendations is arguably "in connection with" an ML system under the terms. For private personal use the risk is practical, not legal enforcement, but it is a gray area to state openly. The 6-month cache cap means a local cache needs a TTL.

### Gaps
- No official description of the TMDB `/recommendations` algorithm was found.
- The discover page cap (believed to be 500 pages) was not confirmed in the fetched docs.
- Whether "personal app" registration still asks for app URL/description fields was not confirmed.

## 2. Radarr/Servarr metadata server ("Skyhook", api.radarr.video): what is usable without a key

### Takeaway
Yes, and it is the biggest finding. `https://api.radarr.video/v1/` is publicly reachable without any key. Each movie record carries TMDB `Recommendations` (10 TMDB IDs plus titles), `Keywords` (text), full `Credits` (30 cast, 30 crew with TMDB person IDs and jobs), `Popularity`, and multi-source `MovieRatings` (TMDB, IMDb with vote count, Metacritic, RT, Trakt). It also has a `movie/bulk` POST and ready-made popular/trending/top-250 lists. It offers no discover/keyword search and no watch providers.

### Cited Findings
- **Endpoints Radarr itself calls** (from source):
  - `movie/{tmdbId}`
  - `movie/imdb/{imdbId}`
  - `movie/bulk` (POST JSON array of TMDB IDs)
  - `movie/collection/{tmdbId}`
  - `search?q=&year=`
  - `list/tmdb/popular`
  - `list/tmdb/trending`
  - `movie/changed?since=`
  - Radarr maps `Recommendations` to a list of TMDB IDs and `Keywords` to a string list. Credits are mapped only from the `movie/{tmdbId}` path.
  - Source: [Radarr SkyHookProxy.cs](https://raw.githubusercontent.com/Radarr/Radarr/develop/src/NzbDrone.Core/MetadataSource/SkyHook/SkyHookProxy.cs)
- **Fields on `GET /v1/movie/550` (live probe, HTTP 200, no auth):**
  - Identity: `TmdbId`, `ImdbId`, `Title`, `OriginalTitle`, `OriginalLanguage`, `Year`, `Runtime`, `Genres`, `Studio`, `Collection`, `Homepage`, `Status`.
  - Release dates: `Premier`, `InCinema`, `PhysicalRelease`, `DigitalRelease`.
  - Descriptive: `Overview`, `Keywords`, `AlternativeTitles`, `Translations`, `Certifications`, `YoutubeTrailerId`, `Images`.
  - Signals: `Popularity`, `Ratings`, `MovieRatings`, `Recommendations`, `Credits`.
  - Example Fight Club `MovieRatings`: Tmdb 8.437 / 33,280 votes; Imdb 8.8 / 2,679,974 votes; Metacritic 67; RottenTomatoes 81; Trakt 8.69 / 45,684.
  - Example `Keywords`: "nihilism", "dissociative identity disorder"…
  - Crew entries: `{Name, Job, Department, TmdbId}`, e.g. David Fincher / Director / 7467.
  - Source: live probe `https://api.radarr.video/v1/movie/550`, 2026-11-08.
- **Bulk call:** `POST /v1/movie/bulk` with 4 TMDB IDs returned in 0.42 s, each with 10 recommendations, keywords, IMDb vote counts and credits. — live probe, 2026-11-08
- **Responses are Cloudflare-cached** (`cache-control: public,s-maxage=2591961`, i.e. about 30 days; `cf-cache-status: HIT`). Cached records can be up to about a month stale. — live probe headers, 2026-11-08
- **Lists that work (live probe):**
  - `GET /v1/list/tmdb/popular` → 20 items (e.g. The Dark Knight, Coco, Project Hail Mary 2026).
  - `GET /v1/list/tmdb/trending` → 20 items.
  - `GET /v1/list/imdb/top250` → 250 items with IMDb IDs.
  - `GET /v1/list/imdb/popular` → 100 items (seasonally horror-heavy on probe date).
  - `GET /v1/movie/collection/119` → LOTR collection, 3 parts.
  - `search?q=stalker&year=1979` → 1 hit.
  - **404:** `list/imdb/ls…` (arbitrary IMDb user lists), `list/tmdb/upcoming`, `list/tmdb/toprated`, `list/trakt/trending`.
  - Source: live probes, 2026-11-08
- Third-party tools say TMDB popular/trending presets need your own free TMDB key. Radarr's built-in TMDB list import uses the v3 API, which caps lists at about 500 movies. — [Listarr docs](https://docs.elfhosted.com/app/listarr/); [radarr_netimport Docker notes](https://hub.docker.com/r/thundermagic/radarr_netimport)

### Inferences
- **Practical keyless pipeline:** IMDb ID → `movie/imdb/{tt}` → TMDB ID. Then one `movie/bulk` POST for all 90 seeds yields up to 900 recommendation edges with titles. Hydrate the candidates with another bulk call to get IMDb vote counts, year, genres and director, which supports popularity-tier filtering without a TMDB key.
- **Via the local Radarr v6 instance:** its `/api/v3/movie/lookup/tmdb?tmdbId=` and `/api/v3/movie/lookup/imdb?imdbId=` proxy the same data. The user's existing Radarr API key is the only credential needed.
- **Terms:** api.radarr.video is infrastructure for Radarr clients with no published public-use terms. Heavy direct use is "borrowing" Radarr's TMDB access. Keep volume low (hundreds of calls per run) and send a clear User-Agent, or go through local Radarr. This is a judgment call, not a documented rule.
- **Limits:** recommendations are capped at 10 per film and inherit TMDB's popularity bias (see the Stalker example). There is no keyword-ID or country discover, so it cannot replace `/discover` for "avoid canon" exploration.

### Gaps
- No documented rate limit or ToS for api.radarr.video was found.
- Radarr's "Discover" page and its use of `Recommendations` in v6 was not checked in source.
- There is no keyless way to import an arbitrary IMDb list (Radarr's IMDb list import routes were not verified).

## 3. Trakt API (free app key): related, popularity, terms

### Takeaway
Trakt is free (Standard tier) for personal and commercial use. It needs a Client ID from an app registered with a verified GitHub account, and allows 500 GET calls per 5 minutes unauthenticated. Its updated API Use Policy (2026-10-20) explicitly permits using "related titles" to power in-app personalized recommendations. It is a good second source of item-item neighbors and popularity, mapped by IMDb ID.

### Cited Findings
- **Rate limits** (doc updated 2026-10-13):
  - `UNAUTHED_API_GET_LIMIT` (client ID + public IP) and `AUTHED_API_GET_LIMIT`: 500 calls every 5 minutes.
  - `AUTHED_API_POST_LIMIT`: 1 call/s.
  - A 429 comes with `X-Ratelimit` JSON and `Retry-After` headers.
  - Premium apps use `apiz.trakt.tv` with higher limits.
  - Source: [Trakt rate-limiting guide](https://raw.githubusercontent.com/trakt/trakt-api/HEAD/projects/developer/src/lib/guides/rate-limiting.md)
- **Required headers:** `Content-Type: application/json`, `User-Agent` (e.g. `MyApp/1.0.0`), `trakt-api-key: <client_id>`, `trakt-api-version: 2`. — [Trakt required-headers](https://raw.githubusercontent.com/trakt/trakt-api/HEAD/projects/developer/src/lib/guides/required-headers.md)
- **App registration** (updated 2026-10-01):
  - Needs a verified GitHub account connected in the developer panel.
  - Branding requirements apply.
  - Use "only documented API methods" and "don't scrape the website".
  - Cache effectively.
  - Source: [Trakt create-an-app](https://raw.githubusercontent.com/trakt/trakt-api/HEAD/projects/developer/src/lib/guides/create-an-app.md)
- **API Use Policy** (updated 2026-10-20):
  - "You may use related titles and other permitted API results to support recommendations within your app, including personalized recommendations based on titles a user follows or enjoys."
  - Standard access "is free for commercial and noncommercial use".
  - VIP is not required to create an app.
  - Prohibited: bulk harvesting or catalog mirroring, redistribution as datasets.
  - No fixed maximum cache duration.
  - "We will automatically delete API app registrations after 30 consecutive days with no usage."
  - Source: [Trakt API use policy](https://raw.githubusercontent.com/trakt/trakt-api/HEAD/projects/developer/src/lib/guides/api-use-policy.md)
- **Embedded objects may be cached snapshots:** list and activity endpoints (`/movies/anticipated`, `/movies/watched/{period}`, `/movies/played/{period}`, `/movies/collected/{period}`, `/movies/favorited/{period}`) may return stale nested movie objects. `GET /movies/{id}?extended=full` is the canonical metadata source. — [Trakt caching guide](https://raw.githubusercontent.com/trakt/trakt-api/HEAD/projects/developer/src/lib/guides/caching-and-fresh-data.md)
- Some endpoints are marked "Limited Access" and may need prior approval. — [Trakt limited-access](https://raw.githubusercontent.com/trakt/trakt-api/HEAD/projects/developer/src/lib/guides/limted-access.md)
- **2025 consumer changes:** free accounts limited to one connected third-party "Community App"; VIP renewal price doubled ($30 → $60/yr reported). — [AlternativeTo Feb 2025](https://alternativeto.net/news/2025/2/trakt-tv-has-set-stricter-limits-for-free-users-and-raised-vip-subscription-prices-by-100-); [AlternativeTo May 2025](https://alternativeto.net/news/2025/5/trakt-announces-all-vip-renewals-will-switch-to-a-new-standard-rate-doubling-prices)
- The old Apiary docs (trakt.docs.apiary.io) now return only a title shell. Current docs are at developer.trakt.tv, with source in [github.com/trakt/trakt-api](https://github.com/trakt/trakt-api). — fetch of [trakt.docs.apiary.io](https://trakt.docs.apiary.io/), 2026-11-08

### Inferences
- **Endpoints for this use case** (long-standing v2 API; names partly confirmed in the caching guide):
  - `GET /movies/{id}/related` (id = trakt ID, slug, or IMDb tt ID; paginated with `page`/`limit`).
  - `GET /search/imdb/{tt}?type=movie` for ID mapping.
  - Popularity: `/movies/popular`, `/movies/trending`, `/movies/watched/{period}`, `/movies/anticipated`.
  - `?extended=full` adds overview, runtime, rating, votes, country and language.
- **Volume:** 90 seeds × related ≈ 90 calls, well under 500 per 5 min. Fine with `urllib`.
- **Quality:** Trakt's related list is believed to be largely TMDB-like metadata similarity, so it may overlap with TMDB. Not verified in this session.
- **Free tier's one-app limit:** applies to user OAuth connections, not to keyless public GETs with a client ID. Irrelevant if no user OAuth is used.

### Gaps
- `/movies/{id}/related` could not be probed live (no client ID) or its reference page fetched. Its algorithm and quality are undocumented in the sources read.
- The Trakt branding requirements page was not read.

## 4. Wikidata SPARQL: structured neighbors (director, cinematographer, movement, influenced-by)

### Takeaway
It is free, keyless and license-clean (CC0 data). A single UNION query per seed film for same-director, same-cinematographer, same-movement and influenced-by neighbors runs in about 12 s from the Pi. Coverage is excellent for director and cinematographer (88k films with P344), sparse for film movements (only about 1k films with P135), and thin for "influenced by". The endpoint is migrating to a new backend in 2026-2027.

### Cited Findings
- **WDQS limits:**
  - Hard 60 s query timeout.
  - Each client (UA + IP) gets 60 s of processing time per 60 s.
  - 30 error queries per minute.
  - 5 parallel queries per IP.
  - 429 with `Retry-After` when exceeded.
  - Non-descriptive User-Agents "may be blocked completely".
  - GET is cached and POST is not.
  - Banner: "In 2026-2027, the Wikidata Query Service is migrating to a new backend. This migration includes new endpoint URLs for v2, and may require you to revise existing queries."
  - Source: [WDQS User Manual](https://www.mediawiki.org/wiki/Wikidata_Query_Service/User_Manual)
- **Live probe, query shape:** seed `?src wdt:P345 "tt0079944"` (Stalker). UNION of `P57` director, `P344` director of photography, `P135` movement, and `P737` influenced-by in both directions. Restricted with `?film wdt:P31 wd:Q11424 ; wdt:P345 ?imdb`. — live probe against `https://query.wikidata.org/sparql`, 2026-11-08
- **Live probe, results:** HTTP 200 in 11.9 s with 57 rows: 8 via director (Solaris, Mirror, Nostalghia, Sacrifice, Andrei Rublev, Ivan's Childhood…) and 49 via cinematographer (many obscure Soviet films). There were 0 rows via movement or influenced-by for this film. — live probe, 2026-11-08
- **Performance pitfall:** the same query with `wdt:P31/wdt:P279*` (subclass closure) timed out with HTTP 504 after 65 s. — live probe, 2026-11-08
- **Coverage counts** (live COUNT queries): 1,064 film items (`P31 Q11424`) have a `P135` movement; 88,109 have a `P344` cinematographer. — live probe, 2026-11-08

### Inferences
- **Good for "auteur/crew graph" candidates** that TMDB recommendations miss, such as same-DP and same-screenwriter (`P58`), composer (`P86`), country (`P495`), original language (`P364`), and award received (`P166`). Label resolution can return bare QIDs (e.g. "Q4057252") for items without an English label, so request `ru` and `en` labels and fall back.
- **Movement and "influenced by" are too sparse to be primary signals.** Use them as a bonus when present.
- **Pi feasibility:** stdlib `urllib` GET with a descriptive UA, sequential (well under 5 parallel), about 12 s each, so 90 seeds take about 20 min per full refresh. Batch several seeds with `VALUES ?imdbSeed {…}` to cut overhead. Cache results locally (CC0, no cache limits).
- **Ranking:** Wikidata gives no popularity. Join candidates' `P345` IMDb IDs to IMDb `title.ratings` (section 6) or Radarr `MovieRatings` for vote-count tiers. Avoid `P279*` closures.

### Gaps
- New WDQS v2 endpoint URLs and the cutover date were not found.
- The scholarly/main graph split was not mentioned on the fetched page. It is not relevant for films but may affect the endpoint URL.

## 5. MovieLens datasets (ml-latest-small, ml-32m, Tag Genome)

### Takeaway
ml-32m (ratings to 2023-10-12, 87,585 movies, links.csv to IMDb/TMDB IDs) and Tag Genome 2021 (9,734 movies × 1,084 tags) are the only freely downloadable sources of real collaborative-filtering and semantic-tag similarity. Both are feasible on this Pi if computation is restricted to the 90 seeds. Drawbacks: the license is framed as "research purposes", nothing after October 2023 is covered (the genome stops around 2021), and no newer release exists as of November 2026.

### Cited Findings
- **Catalogue, no release newer than 32M:**
  - 32M: 239 MB zip, 32M ratings, 87,585 movies, 200,948 users, 2M tag applications; collected 10/2023, released 05/2024.
  - Tag Genome 2021: 1.8 GB, 9,734 movies, 1,084 tags, 10.5M relevance scores; released 12/2021.
  - ml-latest-small: 1 MB, 100k ratings, 9k movies, last updated 9/2018.
  - ml-latest (full): 335 MB, last updated 9/2018.
  - Source: [GroupLens MovieLens page](https://grouplens.org/datasets/movielens/)
- **ml-32m README:**
  - Usage: "may be used for any research purposes under the following conditions". Commercial or revenue-bearing use needs prior permission. No implied endorsement. Cite Harper & Konstan (2015). Redistribution allowed under the same license.
  - Files: `links.csv` (`movieId, imdbId, tmdbId`), `movies.csv` (`movieId, title (year), genres` pipe-separated), `ratings.csv` (`userId, movieId, rating 0.5–5, timestamp`), `tags.csv`.
  - Ratings span 1995-01-09 to 2023-10-12.
  - Source: [ml-32m README](https://files.grouplens.org/datasets/movielens/ml-32m-README.html)

### Inferences
- **License:** personal, non-commercial private use is not explicitly "research". It is low-risk but technically outside the stated grant, so flag it as a gray area. There is no ML/AI prohibition, unlike TMDB.
- **Pi feasibility (estimates):**
  - ratings.csv is about 0.9 GB uncompressed for 32M rows. Do not load it into Python lists, which would take several GB.
  - Stream the file once with `csv`. Keep a per-user buffer of liked items (rating ≥ 4), since ratings are grouped by userId. For each user who liked any of the 90 seeds, add co-like counts to a `dict[(seed, item)]`.
  - That is one O(32M) pass, roughly 5–15 min of pure-Python CPU on a Pi 4/5 core, with memory in the hundreds of MB.
  - Normalize by item popularity (e.g. lift or cosine = co / sqrt(n_seed × n_item)) to suppress the canon.
- **Tag Genome 2021:** 10.5M scores, manageable when streamed and kept only for seed and candidate vectors. Cosine similarity between 90 seed vectors (1,084-dim) and 9,734 movies is about 1B multiply-adds. That is slow in pure Python (minutes to tens of minutes) but a one-off. The `array` module can store vectors compactly. numpy, if allowed, makes it seconds.
- **Freshness:** films released after mid-2023 have little or no data in ml-32m, and the genome covers only about 9.7k mostly pre-2021 films. Combine with TMDB, Radarr or Trakt for recent titles.
- **ml-latest-small (2018, 9k movies) is too small and stale** to be useful except for prototyping.

### Gaps
- Exact uncompressed sizes of ml-32m files and Tag Genome 2021 file layout (e.g. `tag_scores` as CSV vs JSON) were not verified.
- No benchmark on Pi hardware was found. Timing figures above are estimates.

## 6. Other sources: TasteDive, OMDb, IMDb datasets, JustWatch, Letterboxd similar, Criterion/Sight & Sound, Mubi

### Takeaway
- **IMDb non-commercial TSV datasets:** the best free popularity and vote-count source (daily refresh, explicitly personal/non-commercial OK).
- **OMDb:** a small free key (1,000 requests/day) for ratings or plot backfill.
- **TasteDive:** the API endpoint is behind a Cloudflare challenge from the Pi, so it is effectively unusable for scripts.
- **Letterboxd `/film/*/similar/`:** also behind a Cloudflare challenge, so it is off-limits.
- **JustWatch:** no public API, but its data is available legitimately through TMDB `watch/providers` with attribution.
- **Criterion / Sight & Sound / Mubi:** no API; treat them as manual or curated seed lists, not live sources.

### Cited Findings
- **IMDb datasets:**
  - Files: `title.basics`, `title.ratings`, `title.crew`, `title.principals`, `title.akas`, `title.episode`, `name.basics`; gzipped TSV, `\N` for nulls, refreshed daily.
  - Fields: `title.basics` (tconst, titleType, primaryTitle, originalTitle, isAdult, startYear, endYear, runtimeMinutes, genres), `title.ratings` (tconst, averageRating, numVotes), `title.crew` (tconst, directors, writers).
  - "provided for personal and non-commercial use"; local copies allowed.
  - Download from `https://datasets.imdbws.com/`. The docs URL has moved from developer.imdb.com to data.imdb.com.
  - Source: [IMDb Non-Commercial Datasets](https://data.imdb.com/non-commercial-datasets/)
- **OMDb:** free key with a "1,000 daily limit", plus a Patreon tier. Content is licensed CC BY-NC 4.0. — [OMDb API key page](https://www.omdbapi.com/apikey.aspx)
- **TasteDive:** `GET https://tastedive.com/api/similar?q=movie:fight+club&type=movie` from the Pi returned a Cloudflare "Attention Required!" HTML page instead of JSON. — live probe, 2026-11-08
  - A third-party listing still describes the API as live with a `k=` key parameter. No official 2025–2026 status was found. — [Jentic TasteDive listing](https://jentic.com/apis/tastedive.com/tastedive.md)
- **Letterboxd:** `GET https://letterboxd.com/film/stalker/similar/` returned HTTP 403 "Just a moment..." (Cloudflare challenge) from the Pi. — live probe, 2026-11-08
- **JustWatch via TMDB:** TMDB `watch/providers` data comes from its JustWatch partnership and requires JustWatch attribution. — [TMDB watch providers reference](https://developer.themoviedb.org/reference/movie-watch-providers)

### Inferences
- **IMDb `title.ratings`:** about 1.5M rows, small enough to load into a stdlib `dict` (tconst → votes, rating) of perhaps 150–300 MB. Filter to IDs of interest while streaming to keep RAM low.
- **Popularity tiers from `numVotes`:** e.g. canon above 300k votes, known 50k–300k, deep cut 5k–50k, obscure below 5k. These are illustrative thresholds, not sourced.
- **`title.crew` plus `title.principals`:** a fully offline same-director or same-writer neighbor graph keyed on tt IDs, complementary to Wikidata.
- **OMDb at 1,000/day:** enough for about 90 seeds plus several hundred candidates per day. Mostly redundant with Radarr `MovieRatings`, which already includes IMDb, RT and Metacritic.
- **TasteDive:** treat as unavailable. Calling it would require Cloudflare circumvention, which is disallowed.
- **Criterion Collection, BFI Sight & Sound and Mubi:** no documented free APIs were found (not researched in depth). The project could hand-curate their lists as "canon" exclusion sets or as diversity seeds. Wikidata has some list-membership data, e.g. `P1343` "described by source", for some canon lists.

### Gaps
- No official TasteDive status page or announcement was found. It is unclear whether the API works from other IPs with a key.
- Current Mubi/Criterion API availability and terms were not researched.
- IMDb's full non-commercial licence text was not fetched.

## 7. Which sources are best for (a) item-item candidates, (b) popularity tiers / avoiding canon, (c) availability/year filtering

### Takeaway
- **(a) Item-item:** Radarr Skyhook `Recommendations` (keyless, today) + TMDB `/recommendations` and `/discover` by keyword (free key) + Wikidata crew graph + MovieLens 32M co-likes (pre-2024 only). Trakt `related` is an optional extra.
- **(b) Popularity:** IMDb `title.ratings` numVotes (offline, daily) or Radarr `MovieRatings.Imdb.Count` per candidate. TMDB `discover` `vote_count.lte` to generate non-canon directly.
- **(c) Availability/year:** TMDB `discover` (`primary_release_date.*`, `with_watch_providers` + `watch_region`, JustWatch attribution required) and Radarr's release-date fields (`InCinema`, `DigitalRelease`, `PhysicalRelease`).

### Cited Findings
- Radarr Skyhook returns 10 TMDB recommendations, keywords, credits and IMDb vote counts per film without a key. — live probe [api.radarr.video/v1/movie/550](https://api.radarr.video/v1/movie/550); [SkyHookProxy.cs](https://raw.githubusercontent.com/Radarr/Radarr/develop/src/NzbDrone.Core/MetadataSource/SkyHook/SkyHookProxy.cs)
- TMDB `similar` uses only genres and plot keywords. — [TMDB movie-similar](https://developer.themoviedb.org/reference/movie-similar)
- TMDB discover supports `vote_count.gte/lte`, `with_keywords` (OR via `|`), `with_origin_country`, `with_original_language`, release-date ranges and watch-provider filters. — [TMDB discover-movie](https://developer.themoviedb.org/reference/discover-movie)
- IMDb `title.ratings.numVotes` is refreshed daily and licensed for personal non-commercial use. — [IMDb datasets](https://data.imdb.com/non-commercial-datasets/)
- MovieLens 32M ratings end 2023-10-12. — [ml-32m README](https://files.grouplens.org/datasets/movielens/ml-32m-README.html)
- Trakt explicitly permits using related titles for in-app personalized recommendations. — [Trakt API use policy](https://raw.githubusercontent.com/trakt/trakt-api/HEAD/projects/developer/src/lib/guides/api-use-policy.md)
- Wikidata has dense director and cinematographer data (88k films with P344) but sparse movements (about 1k films with P135). — live probe, 2026-11-08

### Inferences
- **Recommended stack, in priority order:**
  1. **Keyless today:** Radarr/Skyhook bulk for seed hydration plus 10 recs each, Wikidata crew-graph neighbors, and IMDb TSVs for vote tiers and the director graph.
  2. **After registering a free TMDB key:** keyword/country/vote-band `discover` for deliberate non-canon exploration, plus `watch/providers` for availability.
  3. **Optional:** Trakt related, and MovieLens 32M or Tag Genome offline similarity for pre-2024 films.
- **Hand only verified candidates to the LLM.** Grounding means the LLM selects and explains from candidates that carry verified tt IDs, instead of inventing titles.
- **Canon bias is inherent** in TMDB recommendations (the Stalker → Inception/Guardians example). Always re-rank with popularity normalization (IMDb votes) and diversity constraints such as country, decade and director.
- **Licence-cleanest sources for LLM-mediated use:** Wikidata (CC0) and IMDb TSV (personal non-commercial). Trakt's policy explicitly allows recommendations. TMDB's ML clause is the main terms friction.

### Gaps
- No side-by-side quality evaluation of TMDB recommendations vs Trakt related vs MovieLens co-likes for arthouse seeds was found. This project would need to measure it on the user's 90 films.
