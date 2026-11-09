"""One-time (idempotent) configuration of Radarr + Prowlarr for movie-picks."""
import json
import pathlib
import urllib.request

STATE = pathlib.Path(__file__).resolve().parent.parent / "state"
RK = (STATE / "radarr.key").read_text().strip()
PK = (STATE / "prowlarr.key").read_text().strip()
R = "http://127.0.0.1:7878/api/v3"
P = "http://127.0.0.1:9696/api/v1"


def call(base, key, method, path, body=None):
    req = urllib.request.Request(
        base + path, method=method,
        data=json.dumps(body).encode() if body is not None else None,
        headers={"X-Api-Key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=60) as r:
        raw = r.read()
        return json.loads(raw) if raw else None


def radarr(m, p, b=None):
    return call(R, RK, m, p, b)


def prowlarr(m, p, b=None):
    return call(P, PK, m, p, b)


def fill(schema, values):
    for f in schema["fields"]:
        if f["name"] in values:
            f["value"] = values[f["name"]]
    return schema


# --- Radarr: root folder ---
if not any(r["path"] == "/media/movies" for r in radarr("GET", "/rootfolder")):
    radarr("POST", "/rootfolder", {"path": "/media/movies"})
print("root folder ok")

# --- Radarr: qBittorrent download client ---
if not any(c["name"] == "qBittorrent" for c in radarr("GET", "/downloadclient")):
    s = next(x for x in radarr("GET", "/downloadclient/schema") if x["implementation"] == "QBittorrent")
    fill(s, {"host": "172.31.77.5", "port": 8080, "movieCategory": "radarr"})
    s.update(name="qBittorrent", enable=True, priority=1)
    radarr("POST", "/downloadclient", s)
print("download client ok")

# --- Radarr: custom format rejecting releases over 5 GB ---
cfs = radarr("GET", "/customformat")
cf = next((c for c in cfs if c["name"] == "Over 5GB"), None)
if not cf:
    spec = next(x for x in radarr("GET", "/customformat/schema") if x["implementation"] == "SizeSpecification")
    fill(spec, {"min": 5, "max": 1000})
    spec.update(name="size", negate=False, required=True)
    cf = radarr("POST", "/customformat", {"name": "Over 5GB", "includeCustomFormatWhenRenaming": False,
                                          "specifications": [spec]})
print("custom format ok")

# --- Radarr: quality profile "1080p ≤5GB" (based on 'HD - 720p/1080p') ---
prof = next(p for p in radarr("GET", "/qualityprofile") if p["name"] in ("HD - 720p/1080p", "1080p ≤5GB"))
prof["name"] = "1080p ≤5GB"
prof["upgradeAllowed"] = False
prof["minFormatScore"] = 0
prof["formatItems"] = [{"format": cf["id"], "name": cf["name"], "score": -10000}] + [
    {"format": c["id"], "name": c["name"], "score": 0} for c in cfs if c["id"] != cf["id"]]
radarr("PUT", f"/qualityprofile/{prof['id']}", prof)
(STATE / "radarr_profile_id").write_text(str(prof["id"]))
print("profile ok", prof["id"])

# --- Prowlarr: Radarr application (syncs indexers into Radarr) ---
if not any(a["name"] == "Radarr" for a in prowlarr("GET", "/applications")):
    s = next(x for x in prowlarr("GET", "/applications/schema") if x["implementation"] == "Radarr")
    fill(s, {"prowlarrUrl": "http://172.31.77.11:9696", "baseUrl": "http://172.31.77.10:7878", "apiKey": RK})
    s.update(name="Radarr", syncLevel="fullSync")
    prowlarr("POST", "/applications", s)
print("prowlarr app ok")

# --- Prowlarr: public indexers ---
existing = {i["definitionName"] for i in prowlarr("GET", "/indexer")}
schemas = prowlarr("GET", "/indexer/schema")
for name in ["yts", "thepiratebay", "limetorrents", "Knaben", "uindex", "TorrentsCSV"]:
    if name in existing:
        continue
    s = next((x for x in schemas if x["definitionName"] == name), None)
    if not s:
        print("no schema", name)
        continue
    s.update(enable=True, appProfileId=1, priority=25)
    try:
        prowlarr("POST", "/indexer", s)
        print("indexer added", name)
    except urllib.error.HTTPError as e:
        print("indexer FAILED", name, e.code, e.read()[:300])
