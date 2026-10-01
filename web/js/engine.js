// 시간표 탐색 엔진 — ttwizard/ (travel.py · evaluate.py · search.py)를 브라우저로 옮긴 것.
// 같은 입력이면 파이썬과 같은 비용이 나와야 한다(tests/test_web.py 가 node 로 확인).

export const DAY_KO = "월화수목금토일";
export const WEIGHTS = { travel: 1.0, late: 2.0, campusDay: 0.0, gap: 0.0 };

// ---------------------------------------------------------------- 자료

/** courses.json → [{id, name, dept, credit, cls, program, sections: [{key, courseId, no, name, instructor, status, meetings}]}] */
export function parseCourses(json) {
  return json.courses.map(([id, name, dept, credit, cls, program, secs]) => ({
    id, name, dept, credit, cls, program,
    sections: secs.map(([no, instructor, status, meetings]) => ({
      key: `${id}-${no}`, courseId: id, no, name, instructor, status,
      meetings: meetings.map(([day, start, end, building, room]) => ({ day, start, end, building, room })),
    })),
  }));
}

export function sectionBuildings(s) {
  return s.meetings.map((m) => m.building).filter(Boolean);
}

function haversineM(lat1, lon1, lat2, lon2) {
  const r = 6371000.0, rad = Math.PI / 180;
  const p1 = lat1 * rad, p2 = lat2 * rad, dp = p2 - p1, dl = (lon2 - lon1) * rad;
  const a = Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * r * Math.asin(Math.sqrt(a));
}

// ---------------------------------------------------------------- 이동시간 행렬 (travel.py)

export class TravelMatrix {
  constructor({ table = new Map(), buildings = {}, walkKmh = 4.0, detour = 1.35, defaultMinutes = 15.0, sameBuilding = 0.0 } = {}) {
    Object.assign(this, { table, buildings, walkKmh, detour, defaultMinutes, sameBuilding });
    this.misses = new Set();
  }

  /** campus.json 과 'slope' 또는 'flat' → 행렬. 경사 반영이 없으면 평지로. */
  static fromCampus(campus, mode = "slope") {
    const dense = campus[mode] || campus.flat;
    const table = new Map();
    campus.ids.forEach((a, i) => campus.ids.forEach((b, j) => {
      const v = dense ? dense[i][j] : null;
      if (i !== j && v !== null && v !== undefined) table.set(a + "|" + b, v);
    }));
    const e = campus.estimate || {};
    return new TravelMatrix({
      table, buildings: campus.buildings,
      walkKmh: e.walk_kmh ?? 4.0, detour: e.detour ?? 1.35, defaultMinutes: e.default_minutes ?? 15.0,
    });
  }

  estimate(a, b) {
    const ba = this.buildings[a], bb = this.buildings[b];
    if (!ba || !bb || ba[1] == null || bb[1] == null) return null;
    return haversineM(ba[1], ba[2], bb[1], bb[2]) * this.detour / (this.walkKmh * 1000 / 60);
  }

  minutes(a, b) {
    if (a === b) return this.sameBuilding;
    let v = this.table.get(a + "|" + b);
    if (v !== undefined) return v;
    v = this.table.get(b + "|" + a); // 대칭 가정 (파이썬 symmetric=True)
    if (v !== undefined) return v;
    this.misses.add(a + "|" + b);
    const est = this.estimate(a, b);
    return est === null ? this.defaultMinutes : est;
  }

  /** ids 사이를 다른 지점을 거쳐 가는 경우까지 줄인 행렬(Floyd–Warshall). 하한 계산용. */
  closure(ids) {
    ids = [...new Set(ids)];
    const n = ids.length, d = [];
    const misses = new Set(this.misses);
    for (let i = 0; i < n; i++) {
      d.push(new Float64Array(n));
      for (let j = 0; j < n; j++) d[i][j] = i === j ? 0 : this.minutes(ids[i], ids[j]);
    }
    this.misses = misses;
    for (let k = 0; k < n; k++) {
      const dk = d[k];
      for (let i = 0; i < n; i++) {
        const di = d[i], dik = di[k];
        for (let j = 0; j < n; j++) {
          const v = dik + dk[j];
          if (v < di[j]) di[j] = v;
        }
      }
    }
    const table = new Map();
    for (let i = 0; i < n; i++) for (let j = 0; j < n; j++) if (i !== j) table.set(ids[i] + "|" + ids[j], d[i][j]);
    return new TravelMatrix({ ...this, table });
  }
}

// ---------------------------------------------------------------- 평가 (evaluate.py)

/** 분반 조합 → 요일별 경로(집 → 수업들 → 집)와 비용. */
export function evaluate(sections, travel, home, w = WEIGHTS) {
  const byDay = new Map();
  for (const s of sections) {
    for (const m of s.meetings) {
      if (!byDay.has(m.day)) byDay.set(m.day, []);
      byDay.get(m.day).push({ ...m, section: s });
    }
  }
  const days = [...byDay.keys()].sort((a, b) => a - b);
  const ev = { sections: [...sections], travel: 0, late: 0, gap: 0, campusDays: days.length, legs: [], days: {}, cost: 0 };
  for (const d of days) {
    const meetings = byDay.get(d).sort((x, y) => x.start - y.start || x.end - y.end);
    ev.days[d] = meetings;
    let prevLoc = home, prevEnd = null;
    let placed = false; // 그날 위치 확정 수업을 이미 지났는지
    let spare = 0; // 마지막 위치 확정 수업 뒤, 강의실 미정 수업들 앞의 쉬는 시간 합
    for (const m of meetings) {
      if (!m.building) {
        // 강의실 미정: 어디서 열리는지 모르므로 이동도 지각도 만들지 않고, 앞의 쉬는 시간만 다음 이동에 보탠다
        if (placed) spare += m.start - prevEnd;
        ev.legs.push({ day: d, from: prevLoc, to: prevLoc, depart: prevEnd, arriveBy: m.start, minutes: 0, slack: null, meeting: m });
        prevEnd = m.end;
        continue;
      }
      const t = travel.minutes(prevLoc, m.building);
      const slack = placed ? spare + m.start - prevEnd - t : null; // 그날 첫 위치 확정 수업은 집에서 오는 길이라 제약 없음
      ev.legs.push({ day: d, from: prevLoc, to: m.building, depart: prevEnd, arriveBy: m.start, minutes: t, slack, meeting: m });
      ev.travel += t;
      if (slack !== null) {
        if (slack < 0) ev.late += -slack;
        else ev.gap += slack;
      }
      prevLoc = m.building;
      prevEnd = m.end;
      placed = true;
      spare = 0;
    }
    const t = travel.minutes(prevLoc, home);
    ev.legs.push({ day: d, from: prevLoc, to: home, depart: prevEnd, arriveBy: null, minutes: t, slack: null, meeting: null });
    ev.travel += t;
  }
  ev.cost = w.travel * ev.travel + w.late * ev.late + w.campusDay * ev.campusDays + w.gap * ev.gap;
  return ev;
}

// ---------------------------------------------------------------- 탐색 (search.py)

function overlaps(a, b) {
  return a.day === b.day && a.start < b.end && b.start < a.end;
}

export function conflicts(s, t) {
  for (const a of s.meetings) for (const b of t.meetings) if (overlaps(a, b)) return true;
  return false;
}

const now = () => (typeof performance !== "undefined" ? performance.now() : Date.now());

/**
 * 백트래킹 + 분기 한정. courses = [{sections: [...]}], 반환 {ranked, stats}.
 * 부분 비용은 closure() 행렬로 잰다: 원래 행렬은 삼각부등식을 어겨 수업을 더 넣으면 비용이 줄 수도 있다.
 * onProgress(done) 를 주면 progressMs 마다 끝낸 몫(0~1, 탐색 나무의 앞 세 층 기준 추정)을 알린다. 결과는 같다.
 */
export function search(courses, travel, home, { topK = 5, weights = WEIGHTS, useBound = true, onProgress = null, progressMs = 200 } = {}) {
  const t0 = now();
  courses = courses.filter((c) => c.sections.length);
  const order = courses.map((_, i) => i).sort((i, j) => courses[i].sections.length - courses[j].sections.length); // MRV
  const lens = order.map((i) => courses[i].sections.length);
  const pos = order.map(() => 0); // 지금 가지의 층마다 몇 번째 분반인지
  let lastTick = t0;
  const done = (depth) => {
    let f = 0, w = 1;
    for (let d = 0; d < Math.min(depth, 3); d++) { w /= lens[d]; f += pos[d] * w; }
    return f;
  };
  useBound = useBound && weights.gap === 0;
  let boundTravel = null;
  if (useBound) {
    const ids = new Set([home]);
    for (const c of courses) for (const s of c.sections) for (const b of sectionBuildings(s)) ids.add(b);
    boundTravel = travel.closure([...ids].sort());
  }
  const stats = { nCombinations: courses.reduce((p, c) => p * c.sections.length, 1), nodes: 0, leaves: 0, prunedConflict: 0, prunedBound: 0, ms: 0 };
  const kept = []; // {cost, seq, ev}
  let seq = 0;
  const worst = () => (kept.length >= topK ? Math.max(...kept.map((k) => k.cost)) : Infinity);
  const chosen = [];

  function keep(ev) {
    const item = { cost: ev.cost, seq: seq++, ev };
    if (kept.length < topK) { kept.push(item); return; }
    // 파이썬 heapreplace 처럼 가장 나쁜 것(같으면 먼저 들어온 것)을 뺀다
    let w = 0;
    for (let i = 1; i < kept.length; i++) {
      if (kept[i].cost > kept[w].cost || (kept[i].cost === kept[w].cost && kept[i].seq < kept[w].seq)) w = i;
    }
    kept[w] = item;
  }

  function backtrack(depth) {
    stats.nodes++;
    if (onProgress && (stats.nodes & 255) === 0) {
      const t = now();
      if (t - lastTick >= progressMs) { lastTick = t; onProgress(done(depth)); }
    }
    if (depth === order.length) {
      const ev = evaluate(chosen, travel, home, weights);
      stats.leaves++;
      if (ev.cost < worst()) keep(ev);
      return;
    }
    const sections = courses[order[depth]].sections;
    for (let i = 0; i < sections.length; i++) {
      pos[depth] = i;
      const s = sections[i];
      if (chosen.some((c) => conflicts(c, s))) { stats.prunedConflict++; continue; }
      chosen.push(s);
      if (useBound && kept.length >= topK) {
        const partial = evaluate(chosen, boundTravel, home, weights);
        if (partial.cost >= worst()) { stats.prunedBound++; chosen.pop(); continue; }
      }
      backtrack(depth + 1);
      chosen.pop();
    }
  }

  backtrack(0);
  stats.ms = now() - t0;
  if (onProgress) onProgress(1);
  return { ranked: kept.sort((a, b) => a.cost - b.cost || a.seq - b.seq).map((k) => k.ev), stats };
}

/** 시간이 겹치지 않는 조합이 하나라도 있는지. 찾으면 바로 멈춘다. */
export function feasible(courses) {
  courses = courses.filter((c) => c.sections.length);
  const order = courses.map((_, i) => i).sort((i, j) => courses[i].sections.length - courses[j].sections.length);
  const chosen = [];
  return (function rec(depth) {
    if (depth === order.length) return true;
    for (const s of courses[order[depth]].sections) {
      if (chosen.some((c) => conflicts(c, s))) continue;
      chosen.push(s);
      if (rec(depth + 1)) return true;
      chosen.pop();
    }
    return false;
  })(0);
}

/**
 * 겹치지 않는 조합이 없을 때 그 까닭인 과목들의 id. 이 과목들만 담아도 조합이 없고, 하나라도 빼면 생기는 가장 작은 묶음이다.
 * 화면은 이 과목 행에 '시간 겹침' 을 단다. 모든 분반이 서로 겹치는 두 과목이 있으면 그 둘, 없으면 하나씩 빼 보며 줄인다.
 * 조합이 있으면 [].
 */
export function findConflicts(courses) {
  let set = courses.filter((c) => c.sections.length);
  if (feasible(set)) return [];
  for (let a = 0; a < set.length; a++) {
    for (let b = a + 1; b < set.length; b++) {
      if (set[a].sections.every((s) => set[b].sections.every((t) => conflicts(s, t)))) return [set[a].id, set[b].id];
    }
  }
  for (const c of [...set]) {
    const rest = set.filter((x) => x !== c);
    if (!feasible(rest)) set = rest;
  }
  return set.map((c) => c.id);
}

/**
 * 시간이 겹치지 않는 조합 수(결과 제목의 '전체 조합 n개'). 분반은 받은 그대로 센다: 화면이 같은 시간·건물 분반을 묶어서 넘기면
 * search 결과와 같은 단위다. limit 개를 넘거나 budgetMs 안에 다 못 세면 멈추고 exact=false(count 개보다 많다는 뜻).
 */
export function countFeasible(courses, { limit = 10000, budgetMs = 300 } = {}) {
  courses = courses.filter((c) => c.sections.length);
  if (!courses.length) return { count: 0, exact: true };
  const order = courses.map((_, i) => i).sort((i, j) => courses[i].sections.length - courses[j].sections.length);
  const last = order.length - 1;
  const t0 = now();
  const chosen = [];
  let count = 0, nodes = 0, exact = true;
  (function rec(depth) {
    if ((++nodes & 1023) === 0 && now() - t0 > budgetMs) { exact = false; return; }
    for (const s of courses[order[depth]].sections) {
      if (!exact) return;
      if (chosen.some((c) => conflicts(c, s))) continue;
      if (depth === last) {
        if (++count > limit) { count = limit; exact = false; return; } // limit 개보다 많다
        continue;
      }
      chosen.push(s);
      rec(depth + 1);
      chosen.pop();
    }
  })(0);
  return { count, exact };
}

/** 검증용 완전탐색 (search 와 결과가 같아야 한다). */
export function bruteForce(courses, travel, home, weights = WEIGHTS) {
  courses = courses.filter((c) => c.sections.length);
  const out = [];
  const combo = [];
  (function rec(i) {
    if (i === courses.length) {
      for (let a = 0; a < combo.length; a++) for (let b = a + 1; b < combo.length; b++) if (conflicts(combo[a], combo[b])) return;
      out.push(evaluate(combo, travel, home, weights));
      return;
    }
    for (const s of courses[i].sections) { combo.push(s); rec(i + 1); combo.pop(); }
  })(0);
  return out.sort((a, b) => a.cost - b.cost);
}

// ---------------------------------------------------------------- 지도 선

/** Google polyline(소수 5자리) → [[lat, lon], ...] */
export function decodePolyline(text) {
  const out = [];
  let i = 0, lat = 0, lon = 0;
  while (i < text.length) {
    const vals = [];
    for (let k = 0; k < 2; k++) {
      let shift = 0, result = 0, b;
      do {
        b = text.charCodeAt(i++) - 63;
        result |= (b & 0x1f) << shift;
        shift += 5;
      } while (b >= 0x20);
      vals.push(result & 1 ? ~(result >> 1) : result >> 1);
    }
    lat += vals[0];
    lon += vals[1];
    out.push([lat / 1e5, lon / 1e5]);
  }
  return out;
}

/** routes.json 에서 a → b 경로 좌표. 없으면 null. */
export function routeLine(routes, a, b) {
  if (!routes || !routes.paths) return null;
  let p = routes.paths[a + "|" + b];
  if (p) return decodePolyline(p);
  p = routes.paths[b + "|" + a];
  return p ? decodePolyline(p).reverse() : null;
}
