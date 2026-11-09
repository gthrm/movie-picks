# movie-picks

Daily film recommendations built from your Letterboxd taste, picked by Claude
(via the Claude Code CLI on a subscription), delivered by email with a
one-click **Download** button that sends the film to Radarr.

Runs on a Raspberry Pi next to Radarr, Prowlarr, Bazarr and qBittorrent.

## How it works

1. **Sync taste** — pulls your Letterboxd films (RSS + public pages, or a data
   export `.zip` dropped into `lists/`) and IMDb list CSVs into Postgres.
   *Liked* = a Letterboxd ♥ or a rating above 3 stars; films from IMDb lists
   count as liked unless rated below 3.5.
2. **Pick** (`app/selection.py`) — diversity-first selection:
   - taste is split once into distinct *facets*, stored in Postgres;
   - every evening each facet gets random anchor films, a rotating "lens"
     (era, region, debut, …) and a curator persona;
   - Claude proposes long-tail candidates with probabilities, the code samples them;
   - popularity tiers by IMDb votes: at most 2 canon films, at least 3 deep cuts;
   - already-seen, already-sent, already-in-Radarr and canon films are filtered out.
3. **Email** — HTML email with poster, why-you'd-like-it, trailer and a signed
   download link (HMAC, expiring).
4. **Download page** (`serve`) — the link opens a small page; *Download* adds the
   film to Radarr (1080p, ≤ 5 GB) and shows search/download progress.
5. **Watcher** (`watch`) — every 30 min checks the queue; a torrent with < 2 %
   progress in 2 hours is blocklisted and Radarr searches for another release.

## Layout

```
app/movie_picks.py     CLI: pick | serve | watch | sync; Radarr, email, web handler
app/selection.py       diversity-first recommendation logic
setup/configure_arr.py one-time Radarr + Prowlarr setup (root folder, qBittorrent,
                       "1080p ≤5GB" profile, public indexers)
docker-compose.yml     Radarr, Prowlarr, Bazarr
deploy/                systemd units and timers
reports/, research_notes/  research behind the selection design (RU/EN)
```

## Setup

Requirements: Python 3 (tested on 3.14), `psycopg` (v3), PostgreSQL with an empty
database for `DATABASE_URL` (tables are created on first run), Docker, qBittorrent,
the [Claude Code](https://claude.com/claude-code) CLI logged in
(`~/.local/bin/claude`), a Gmail app password for SMTP.

```sh
cp .env.example .env            # fill in values
docker network create --subnet 172.31.77.0/24 media   # if it doesn't exist
# media dir must exist: /mnt/backup/media (edit docker-compose.yml for your path)
docker compose up -d

mkdir -p state
# API keys from each app's Settings → General
echo <radarr key>   > state/radarr.key
echo <prowlarr key> > state/prowlarr.key
python3 setup/configure_arr.py   # also writes state/radarr_profile_id

python3 app/movie_picks.py sync
python3 app/movie_picks.py pick --dry-run   # writes state/last_email.html
```

Expose the web handler (`127.0.0.1:$WEB_PORT`) at `PUBLIC_URL`, e.g. with a
Cloudflare Tunnel, then install the units:

```sh
sudo cp deploy/* /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now movie-picks.timer movie-picks-watch.timer movie-picks-web.service
```

Paths in the units assume the repo lives at `/home/user/movie-picks` and runs as
`user`; the Claude CLI is looked up at `~/.local/bin/claude` of that user — adjust to your setup.

## Commands

| Command | What it does |
|---|---|
| `movie_picks.py pick [--dry-run]` | build today's picks and email them |
| `movie_picks.py serve` | run the download-link web handler |
| `movie_picks.py watch` | replace stalled torrents |
| `movie_picks.py sync` | pull new Letterboxd ratings |

## Not in the repo

`.env`, `state/` (API keys), `lists/` (personal lists), `pgdata/`, and the
`radarr/`, `prowlarr/`, `bazarr/` config folders are gitignored.
