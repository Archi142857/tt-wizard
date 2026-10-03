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

/** 비용을 견주는 단위(백만분의 1분). 같은 구간을 더하는 순서만 달라 생기는 부동소수점 차이는 동점으로 본다 */
const costKey = (cost) => Math.round(cost * 1e6);

/**
 * 백트래킹 + 분기 한정. courses = [{sections: [...]}], 반환 {ranked, stats}.
 * 부분 비용은 closure() 행렬로 잰다: 원래 행렬은 삼각부등식을 어겨 수업을 더 넣으면 비용이 줄 수도 있다.
 * onProgress(done) 를 주면 progressMs 마다 끝낸 몫(0~1, 탐색 나무의 앞 세 층 기준 추정)을 알린다. 결과는 같다.
 *
 * 순위는 비용이 낮은 순, 비용이 같으면 먼저 찾은 순(과목·분반 차례)이다. topK 와 상관없이 정해지는 차례라서
 * topK 를 키워 다시 부르면 앞쪽은 그대로이고 그 뒤 순위가 이어 붙는다(화면의 '더 찾기').
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
  // kept: 지금까지의 상위 topK 개 {q, seq, ev}. 가장 나쁜 것(비용이 큰 것, 같으면 늦게 찾은 것)이 맨 앞에 오는 힙
  const kept = [];
  let seq = 0;
  let worstQ = topK >= 1 ? Infinity : -Infinity; // topK 개가 찼을 때 그중 가장 나쁜 비용. 이보다 낮아야 들어온다
  const worse = (a, b) => a.q > b.q || (a.q === b.q && a.seq > b.seq);
  const chosen = [];

  function keep(ev, q) {
    const item = { q, seq: seq++, ev };
    let i;
    if (kept.length < topK) {
      for (i = kept.push(item) - 1; i > 0; ) { // 끝에 넣고 위로
        const up = (i - 1) >> 1;
        if (!worse(item, kept[up])) break;
        kept[i] = kept[up];
        i = up;
      }
    } else {
      for (i = 0; ; ) { // 가장 나쁜 것 자리에 넣고 아래로
        let down = 2 * i + 1;
        if (down >= kept.length) break;
        if (down + 1 < kept.length && worse(kept[down + 1], kept[down])) down++;
        if (!worse(kept[down], item)) break;
        kept[i] = kept[down];
        i = down;
      }
    }
    kept[i] = item;
    if (kept.length >= topK) worstQ = kept[0].q;
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
      const q = costKey(ev.cost);
      if (q < worstQ) keep(ev, q); // 비용이 같으면 먼저 찾은 것이 남는다
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
        if (costKey(partial.cost) >= worstQ) { stats.prunedBound++; chosen.pop(); continue; }
      }
      backtrack(depth + 1);
      chosen.pop();
    }
  }

  backtrack(0);
  stats.ms = now() - t0;
  if (onProgress) onProgress(1);
  return { ranked: kept.sort((a, b) => a.q - b.q || a.seq - b.seq).map((k) => k.ev), stats };
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
 * search 결과와 같은 단위다. 반환 {count, exact}. budgetMs 안에 다 못 세면 exact=false 이고 count 는 그때까지 센 수다(실제는 그보다 많다).
 * limit 을 주면 그보다 많다는 걸 아는 대로 멈추고 {count: limit, exact: false}(기본은 끝까지 센다).
 *
 * 조합을 하나씩 세지 않는다. 요일·시각이 같은 분반(건물만 다른 것)은 한 덩이로 묶어 분반 수를 곱하고, 남은 과목에서 못 고르게 된
 * 덩이가 같은 가지는 한 번만 센다(앞에서 무엇을 골랐든 남은 과목에는 같은 상태다). 겹침 판정은 conflicts 그대로라 하나씩 센 것과 같은
 * 수가 나온다. 수는 Number 라 2^53(약 9천조)을 넘으면 어림값이다.
 */
export function countFeasible(courses, { limit = Infinity, budgetMs = 300 } = {}) {
  const t0 = now();
  courses = courses.filter((c) => c.sections.length);
  if (!courses.length) return { count: 0, exact: true };

  // 과목마다 시간이 같은 분반을 한 덩이로({s: 대표 분반, n: 분반 수}). 덩이가 많은 과목부터 고른다:
  // 깊이 들어갈수록 남은 덩이가 적어 같은 상태를 다시 만나기 쉽다(실제 자료에서 적은 과목부터 고를 때보다 가지가 훨씬 적다)
  const groups = courses.map((c) => {
    const bySig = new Map();
    for (const s of c.sections) {
      const sig = s.meetings.map((m) => `${m.day},${m.start},${m.end}`).sort().join(";");
      const g = bySig.get(sig);
      if (g) g.n++;
      else bySig.set(sig, { s, n: 1 });
    }
    return [...bySig.values()];
  }).sort((a, b) => b.length - a.length);
  const D = groups.length, last = D - 1;

  // 덩이마다 비트 하나. 뒤에 고르는 과목일수록 낮은 비트라, 깊이 d 에서는 아래 words[d] 워드(남은 과목의 덩이)만 보면 된다
  const base = new Array(D), words = new Array(D), topMask = new Array(D);
  for (let d = last, bit = 0; d >= 0; d--) {
    base[d] = bit;
    bit += groups[d].length;
    words[d] = (bit + 31) >>> 5;
    topMask[d] = bit & 31 ? (1 << (bit & 31)) - 1 : -1;
  }
  // conf[d][i]: 깊이 d 의 i 번째 덩이를 고르면 못 고르게 되는 뒤 과목 덩이들
  const conf = [];
  for (let d = 0; d < last; d++) {
    if (now() - t0 >= budgetMs) return { count: 0, exact: false };
    conf.push(groups[d].map((g) => {
      const mask = new Uint32Array(words[d + 1]);
      for (let e = d + 1; e < D; e++) {
        const ge = groups[e];
        for (let j = 0; j < ge.length; j++) {
          if (conflicts(g.s, ge[j].s)) { const bit = base[e] + j; mask[bit >>> 5] |= 1 << (bit & 31); }
        }
      }
      return mask;
    }));
  }
  const blocked = groups.map((_, d) => new Uint32Array(words[d])); // 깊이마다 지금 가지에서 막힌 덩이(남은 과목 것만)

  // 기억: 깊이마다 해시표 하나(형식 배열이라 Map 보다 메모리를 1/3쯤 쓴다). 열쇠 = 막힌 덩이 비트(kw 워드), 값 = 그 아래 조합 수(빈 칸 -1)
  const table = (kw, size) => ({ kw, size, used: 0, keys: new Uint32Array(size * kw), vals: new Float64Array(size).fill(-1) });
  const tables = groups.map((_, d) => table(words[d], 64));
  const MEMO_MAX = 250000; // 적어 둘 상태 수(다 차면 더 적지 않고 다시 센다). 꽉 차도 형식 배열이 20MB 안쪽이다
  /** 열쇠 key 가 든 칸. 없으면 들어갈 빈 칸 */
  const slotOf = (t, key) => {
    const { kw, keys, vals } = t, mask = t.size - 1;
    let h = 0;
    for (let w = 0; w < kw; w++) { h = Math.imul(h ^ key[w], 0x9e3779b1); h ^= h >>> 15; }
    h = Math.imul(h, 0x85ebca6b);
    for (let slot = (h ^ (h >>> 13)) & mask; ; slot = (slot + 1) & mask) {
      if (vals[slot] < 0) return slot;
      let w = 0;
      while (w < kw && keys[slot * kw + w] === key[w]) w++;
      if (w === kw) return slot;
    }
  };
  const remember = (t, key, val) => {
    if (t.used * 2 >= t.size) { // 반이 차면 두 배로 늘려 옮긴다
      const big = table(t.kw, t.size * 2);
      for (let s = 0; s < t.size; s++) {
        if (t.vals[s] < 0) continue;
        const k = t.keys.subarray(s * t.kw, (s + 1) * t.kw);
        const to = slotOf(big, k);
        big.keys.set(k, to * t.kw);
        big.vals[to] = t.vals[s];
      }
      t.size = big.size; t.keys = big.keys; t.vals = big.vals;
    }
    const slot = slotOf(t, key);
    t.keys.set(key, slot * t.kw);
    t.vals[slot] = val;
    t.used++;
  };

  let count = 0, nodes = 0, memoSize = 0, stop = false;
  const add = (n) => {
    count += n;
    if (count > limit) { count = limit; stop = true; } // limit 개보다 많다
  };

  /** 깊이 d 부터 끝까지 고르는 방법 수. mult = 여기까지 고른 덩이들의 분반 수를 곱한 값 */
  function rec(d, mult) {
    if ((nodes++ & 255) === 0 && now() - t0 >= budgetMs) { stop = true; return 0; }
    const cur = blocked[d], gs = groups[d], b0 = base[d];
    if (d === last) {
      let sum = 0;
      for (let i = 0; i < gs.length; i++) if (!(cur[(b0 + i) >>> 5] & (1 << ((b0 + i) & 31)))) sum += gs[i].n;
      add(mult * sum);
      return sum;
    }
    const t = tables[d];
    const seen = t.vals[slotOf(t, cur)];
    if (seen >= 0) { add(mult * seen); return seen; }
    const next = blocked[d + 1], nw = next.length, tm = topMask[d + 1], cf = conf[d];
    let sum = 0;
    for (let i = 0; i < gs.length; i++) {
      if (cur[(b0 + i) >>> 5] & (1 << ((b0 + i) & 31))) continue;
      const c = cf[i];
      for (let w = 0; w < nw; w++) next[w] = cur[w] | c[w];
      next[nw - 1] &= tm;
      sum += gs[i].n * rec(d + 1, mult * gs[i].n);
      if (stop) return sum; // 다 못 센 가지는 적어 두지 않는다
    }
    if (memoSize < MEMO_MAX) { remember(t, cur, sum); memoSize++; }
    return sum;
  }

  rec(0, 1);
  return { count, exact: !stop };
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
