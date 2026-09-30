import json, re, time, unicodedata
from datetime import datetime, timezone
from pathlib import Path
from curl_cffi import requests

TEAM_ID = 1984
DATA_FILE = Path("data/latest.json")
BASES = [
    "https://www.sofascore.com/api/v1",
    "https://api.sofascore.com/api/v1",
]

session = requests.Session(impersonate="chrome")
session.headers.update({
    "accept": "application/json,text/plain,*/*",
    "accept-language": "pt-BR,pt;q=0.9,en;q=0.8",
    "origin": "https://www.sofascore.com",
    "referer": "https://www.sofascore.com/",
    "x-requested-with": "tigredata",
})

def now_iso():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

def get_json(path, optional=False):
    last = None
    for base in BASES:
        try:
            r = session.get(base + path, timeout=20)
            if r.status_code == 200:
                return r.json()
            last = RuntimeError(f"{base}{path}: HTTP {r.status_code}")
            if optional and r.status_code in (400, 404):
                return None
        except Exception as e:
            last = e
    if optional:
        return None
    raise last or RuntimeError(path)

def norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(ch for ch in s if unicodedata.category(ch) != "Mn")
    s = re.sub(r"[^a-z0-9 ]+", " ", s.lower())
    return re.sub(r"\s+", " ", s).strip()

def same_name(a, b):
    A, B = norm(a), norm(b)
    if not A or not B:
        return False
    if A == B or A in B or B in A:
        return True
    aa, bb = A.split(), B.split()
    return len(aa[-1]) >= 4 and aa[-1] == bb[-1]

def n(v):
    return v if isinstance(v, (int, float)) and not isinstance(v, bool) else None

def mapped_stats(s):
    return {
        "rating": n(s.get("rating")),
        "minutesPlayed": n(s.get("minutesPlayed")),
        "goals": n(s.get("goals")),
        "goalAssist": n(s.get("goalAssist")),
        "totalShots": n(s.get("totalShots")),
        "shotsOnTarget": n(s.get("onTargetScoringAttempt")),
        "blockedShots": n(s.get("blockedScoringAttempt")),
        "expectedGoals": n(s.get("expectedGoals")),
        "expectedAssists": n(s.get("expectedAssists")),
        "touches": n(s.get("touches")),
        "accuratePass": n(s.get("accuratePass")),
        "totalPass": n(s.get("totalPass")),
        "keyPass": n(s.get("keyPass")),
        "accurateCross": n(s.get("accurateCross")),
        "totalCross": n(s.get("totalCross")),
        "successfulDribble": n(s.get("successfulDribble")),
        "totalContest": n(s.get("totalContest")),
        "duelWon": n(s.get("duelWon")),
        "totalDuel": n(s.get("totalDuel")),
        "aerialWon": n(s.get("aerialWon")),
        "totalAerial": n(s.get("totalAerial")),
        "tackles": n(s.get("totalTackle")),
        "interceptions": n(s.get("interceptionWon")),
        "clearances": n(s.get("totalClearance")),
        "blockedShotsDefensive": n(s.get("blockedShot")),
        "possessionLostCtrl": n(s.get("possessionLostCtrl")),
        "fouls": n(s.get("fouls")),
        "wasFouled": n(s.get("wasFouled")),
        "saves": n(s.get("saves")),
        "goalsPrevented": n(s.get("goalsPrevented")),
    }

def event_feed(e):
    home = (e.get("homeTeam") or {}).get("id") == TEAM_ID
    ts = e.get("startTimestamp")
    kickoff = datetime.fromtimestamp(ts, tz=timezone.utc).isoformat().replace("+00:00","Z") if ts else None
    return {
        "sofaEventId": e.get("id"),
        "leagueName": (e.get("tournament") or {}).get("name"),
        "matchRound": (e.get("roundInfo") or {}).get("round"),
        "kickoffUtc": kickoff,
        "homeTeamName": (e.get("homeTeam") or {}).get("name"),
        "awayTeamName": (e.get("awayTeam") or {}).get("name"),
        "matchStatus": (e.get("status") or {}).get("type"),
        "homeTeamFtScore": (e.get("homeScore") or {}).get("current"),
        "awayTeamFtScore": (e.get("awayScore") or {}).get("current"),
        "criciumaSide": "home" if home else "away",
        "dataSource": "Sofascore",
        "source": "Sofascore complementar",
    }

def main():
    feed = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    checked = now_iso()

    try:
        roster_data = get_json(f"/team/{TEAM_ID}/players")
        events = []
        for page in range(3):
            d = get_json(f"/team/{TEAM_ID}/events/last/{page}", optional=True)
            if not d or not d.get("events"):
                break
            events.extend(d["events"])
            if not d.get("hasNextPage"):
                break
            time.sleep(0.25)
    except Exception as e:
        st = feed.setdefault("sourceState", {})
        # Se já existe fallback web verificado, não o invalida e não gera commit
        # repetitivo apenas porque o datacenter do GitHub foi bloqueado.
        if st.get("sofascoreWebFallback"):
            print(f"Sofascore API bloqueada no GitHub; preservando fallback web: {e}")
            return
        st["sofascore"] = "FETCH_ERROR"
        st["sofascoreCheckedAt"] = checked
        st["sofascoreError"] = str(e)[:300]
        feed["checkedAt"] = checked
        DATA_FILE.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return

    roster = []
    for item in roster_data.get("players", roster_data.get("teamPlayers", [])):
        p = item.get("player", item)
        if p.get("id") and p.get("name"):
            roster.append(p)

    completed = [
        e for e in events
        if e.get("id") and ((e.get("status") or {}).get("type") == "finished" or (e.get("status") or {}).get("code") == 100)
    ]
    completed.sort(key=lambda e: e.get("startTimestamp") or 0, reverse=True)

    details = []
    for e in completed[:8]:
        lu = get_json(f"/event/{e['id']}/lineups", optional=True)
        if not lu:
            continue
        side = "home" if (e.get("homeTeam") or {}).get("id") == TEAM_ID else "away" if (e.get("awayTeam") or {}).get("id") == TEAM_ID else None
        if side:
            details.append((e, (lu.get(side) or {}).get("players", [])))
        time.sleep(0.2)

    out = []
    for p in feed.get("players", []):
        roster_match = next((sp for sp in roster if same_name(p.get("name"), sp.get("name"))), None)
        appearance = None
        for e, items in details:
            it = next((x for x in items if same_name(p.get("name"), (x.get("player") or {}).get("name"))), None)
            if it:
                appearance = (e, it)
                break

        sofa_id = (roster_match or {}).get("id")
        if not sofa_id and appearance:
            sofa_id = (appearance[1].get("player") or {}).get("id")
        sofa_id = sofa_id or p.get("sofaId")

        item_stats = (appearance[1].get("statistics") if appearance else None)
        if item_stats:
            p["stats"] = mapped_stats(item_stats)
            p["statsSource"] = "Sofascore"
            p["statsCheckedAt"] = checked
        p["sofaId"] = sofa_id
        if sofa_id and not p.get("image"):
            p["image"] = f"https://api.sofascore.com/api/v1/player/{sofa_id}/image"
        if appearance:
            p["lastMatch"] = event_feed(appearance[0])
        if roster_match:
            p["sofascoreName"] = roster_match.get("name")
        elif appearance:
            p["sofascoreName"] = (appearance[1].get("player") or {}).get("name")

        if sofa_id and (p.get("lastMatch") or {}).get("sofaEventId"):
            heat = get_json(f"/event/{p['lastMatch']['sofaEventId']}/player/{sofa_id}/heatmap", optional=True)
            pts = (heat or {}).get("heatmap")
            if isinstance(pts, list) and pts:
                p["heatmap"] = [{"x": n(pt.get("x")), "y": n(pt.get("y"))} for pt in pts if n(pt.get("x")) is not None and n(pt.get("y")) is not None]
                p["heatmapSource"] = "Sofascore"
                p["heatmapCheckedAt"] = checked
            time.sleep(0.12)

        out.append(p)

    feed["players"] = out
    feed["sofascore"] = {
        "teamId": TEAM_ID,
        "checkedAt": checked,
        "recentEvents": [event_feed(e) for e in completed[:10]],
    }
    st = feed.setdefault("sourceState", {})
    st.update({
        "sofascore": "OK",
        "sofascoreCheckedAt": checked,
        "sofascoreTeamId": TEAM_ID,
        "sofascoreCommercialApproved": False,
        "sofascoreUsage": "complementary-public-endpoints",
    })
    st.pop("sofascoreError", None)
    feed["checkedAt"] = checked
    DATA_FILE.write_text(json.dumps(feed, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

if __name__ == "__main__":
    main()
