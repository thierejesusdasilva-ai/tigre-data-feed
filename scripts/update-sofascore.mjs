import fs from "node:fs/promises";

const BASE = "https://api.sofascore.com/api/v1";
const TEAM_ID = 1984;
const DATA_FILE = "data/latest.json";
const USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/153 Safari/537.36";

const sleep = (ms) => new Promise(r => setTimeout(r, ms));

async function getJson(path, optional = false) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), 15000);
  try {
    const res = await fetch(`${BASE}${path}`, {
      headers: {
        "user-agent": USER_AGENT,
        "accept": "application/json,text/plain,*/*",
        "referer": "https://www.sofascore.com/"
      },
      signal: controller.signal
    });
    if (!res.ok) {
      if (optional && [400, 403, 404].includes(res.status)) return null;
      throw new Error(`${path}: HTTP ${res.status}`);
    }
    return await res.json();
  } catch (err) {
    if (optional) return null;
    throw err;
  } finally {
    clearTimeout(timer);
  }
}

function norm(s = "") {
  return String(s)
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9 ]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function sameName(a, b) {
  const A = norm(a), B = norm(b);
  if (!A || !B) return false;
  if (A === B) return true;
  const aa = A.split(" "), bb = B.split(" ");
  const al = aa.at(-1), bl = bb.at(-1);
  if (al && bl && al === bl && al.length >= 4) return true;
  return A.includes(B) || B.includes(A);
}

function imageUrl(id) {
  return id ? `${BASE}/player/${id}/image` : null;
}

function safeNum(v) {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

function mapStats(s = {}) {
  return {
    rating: safeNum(s.rating),
    minutesPlayed: safeNum(s.minutesPlayed),
    goals: safeNum(s.goals),
    goalAssist: safeNum(s.goalAssist),
    totalShots: safeNum(s.totalShots),
    shotsOnTarget: safeNum(s.onTargetScoringAttempt),
    blockedShots: safeNum(s.blockedScoringAttempt),
    expectedGoals: safeNum(s.expectedGoals),
    expectedAssists: safeNum(s.expectedAssists),
    touches: safeNum(s.touches),
    accuratePass: safeNum(s.accuratePass),
    totalPass: safeNum(s.totalPass),
    keyPass: safeNum(s.keyPass),
    accurateCross: safeNum(s.accurateCross),
    totalCross: safeNum(s.totalCross),
    successfulDribble: safeNum(s.successfulDribble),
    totalContest: safeNum(s.totalContest),
    duelWon: safeNum(s.duelWon),
    totalDuel: safeNum(s.totalDuel),
    aerialWon: safeNum(s.aerialWon),
    totalAerial: safeNum(s.totalAerial),
    tackles: safeNum(s.totalTackle),
    interceptions: safeNum(s.interceptionWon),
    clearances: safeNum(s.totalClearance),
    blockedShotsDefensive: safeNum(s.blockedShot),
    possessionLostCtrl: safeNum(s.possessionLostCtrl),
    fouls: safeNum(s.fouls),
    wasFouled: safeNum(s.wasFouled),
    saves: safeNum(s.saves),
    goalsPrevented: safeNum(s.goalsPrevented)
  };
}

function eventToFeed(e) {
  const home = e.homeTeam?.id === TEAM_ID;
  return {
    sofaEventId: e.id ?? null,
    leagueName: e.tournament?.name ?? null,
    matchRound: e.roundInfo?.round ?? null,
    kickoffUtc: e.startTimestamp ? new Date(e.startTimestamp * 1000).toISOString() : null,
    homeTeamName: e.homeTeam?.name ?? null,
    awayTeamName: e.awayTeam?.name ?? null,
    matchStatus: e.status?.type ?? null,
    homeTeamFtScore: e.homeScore?.current ?? null,
    awayTeamFtScore: e.awayScore?.current ?? null,
    criciumaSide: home ? "home" : "away",
    dataSource: "Sofascore",
    source: "Sofascore complementar"
  };
}

async function main() {
  const raw = await fs.readFile(DATA_FILE, "utf8");
  const feed = JSON.parse(raw);
  const now = new Date().toISOString();

  let rosterPayload = null;
  let recentEvents = [];
  try {
    rosterPayload = await getJson(`/team/${TEAM_ID}/players`);
    for (let page = 0; page < 3; page++) {
      const data = await getJson(`/team/${TEAM_ID}/events/last/${page}`, true);
      if (!data?.events?.length) break;
      recentEvents.push(...data.events);
      if (!data.hasNextPage) break;
      await sleep(250);
    }
  } catch (err) {
    feed.sourceState = {
      ...(feed.sourceState || {}),
      sofascore: "FETCH_ERROR",
      sofascoreCheckedAt: now,
      sofascoreError: String(err?.message || err).slice(0, 300)
    };
    feed.checkedAt = now;
    await fs.writeFile(DATA_FILE, JSON.stringify(feed, null, 2) + "\n");
    process.exitCode = 0;
    return;
  }

  const rosterItems = rosterPayload?.players ?? rosterPayload?.teamPlayers ?? [];
  const sofaPlayers = rosterItems
    .map(x => x.player || x)
    .filter(x => x?.id && x?.name);

  const completed = [...recentEvents]
    .filter(e => e?.id && (e.status?.type === "finished" || e.status?.code === 100))
    .sort((a,b) => (b.startTimestamp || 0) - (a.startTimestamp || 0));

  const eventDetails = [];
  for (const event of completed.slice(0, 8)) {
    const lineup = await getJson(`/event/${event.id}/lineups`, true);
    if (!lineup) continue;
    const side = event.homeTeam?.id === TEAM_ID ? "home" : event.awayTeam?.id === TEAM_ID ? "away" : null;
    if (!side) continue;
    eventDetails.push({ event, players: lineup?.[side]?.players ?? [] });
    await sleep(250);
  }

  feed.players = (feed.players || []).map(p => {
    const rosterMatch = sofaPlayers.find(sp => sameName(p.name, sp.name));
    const appearance = eventDetails
      .map(x => ({...x, item: x.players.find(lp => sameName(p.name, lp?.player?.name))}))
      .find(x => x.item);

    const sofaId = rosterMatch?.id ?? appearance?.item?.player?.id ?? p.sofaId ?? null;
    const matchStats = appearance?.item?.statistics ? mapStats(appearance.item.statistics) : null;

    return {
      ...p,
      sofaId,
      image: p.image || imageUrl(sofaId),
      stats: matchStats || p.stats || null,
      statsSource: matchStats ? "Sofascore" : (p.statsSource || null),
      statsCheckedAt: matchStats ? now : (p.statsCheckedAt || null),
      lastMatch: appearance ? eventToFeed(appearance.event) : (p.lastMatch || null),
      sofascoreName: rosterMatch?.name ?? appearance?.item?.player?.name ?? p.sofascoreName ?? null
    };
  });

  for (const p of feed.players) {
    if (!p.sofaId || !p.lastMatch?.sofaEventId) continue;
    const heat = await getJson(`/event/${p.lastMatch.sofaEventId}/player/${p.sofaId}/heatmap`, true);
    if (Array.isArray(heat?.heatmap) && heat.heatmap.length) {
      p.heatmap = heat.heatmap
        .map(pt => ({x: safeNum(pt.x), y: safeNum(pt.y)}))
        .filter(pt => pt.x !== null && pt.y !== null);
      p.heatmapSource = "Sofascore";
      p.heatmapCheckedAt = now;
    }
    await sleep(180);
  }

  feed.sofascore = {
    teamId: TEAM_ID,
    checkedAt: now,
    recentEvents: completed.slice(0, 10).map(eventToFeed)
  };

  feed.sourceState = {
    ...(feed.sourceState || {}),
    sofascore: "OK",
    sofascoreCheckedAt: now,
    sofascoreTeamId: TEAM_ID,
    sofascoreCommercialApproved: false,
    sofascoreUsage: "complementary-public-endpoints"
  };
  feed.checkedAt = now;

  await fs.writeFile(DATA_FILE, JSON.stringify(feed, null, 2) + "\n");
}

main().catch(async err => {
  console.error(err);
  process.exitCode = 1;
});
