// TT Wizard 화면(디자인 규칙 v3). 자료(data/*.json)는 scripts/export_web.py 가 만들고, 탐색은 engine.js 가 브라우저에서 한다.
// 화면은 입력 · 결과 · 정보 셋이고 전체 화면 지도, 자료 출처·오픈소스 라이선스가 그 위에 뜬다. 화면만 방문 기록(pushState)을
// 남기고 시트(<dialog>)는 남기지 않는다. 화면 문구는 디자인 규칙 '문구'를 따른다(문장은 해요체 한 줄, 그 밖에는 명사구).
import { DAY_KO, parseCourses, TravelMatrix, search, findConflicts, countFeasible, routeLine } from "./engine.js";
import { indexCourses as indexSearch, searchCourses, splitMarks, normKey } from "./search.js";

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- 어디서 도는지: 웹, 설치한 PWA, 스토어 앱(Capacitor 의 android·ios)
// 앱마다 다른 것(설치 안내, 서비스 워커와 새 버전 알림, 외부 링크, 햅틱)은 이 값으로만 가른다. CSS 는 html[data-shell] 을 본다.
// 스토어 앱은 안드로이드·iOS 모두 Capacitor 다(10/1 update34, TWA 는 쓰지 않는다). 앱 연결 스크립트(js/native.js, 백엔드 몫)가
// 이 파일보다 먼저 돌며 자료 받기, 안드로이드 뒤로 가기(열린 시트 닫기 → 이전 화면 → 앱 내리기), <html data-platform> 을 맡는다
const capacitor = window.Capacitor;
const SHELL = capacitor?.isNativePlatform?.() ? (capacitor.getPlatform?.() === "android" ? "android" : "ios")
  : (matchMedia("(display-mode: standalone)").matches || navigator.standalone) ? "pwa" : "web";
const IN_APP = SHELL === "android" || SHELL === "ios"; // 스토어 앱: 서비스 워커·설치 안내·새 버전 알림 없음, 외부 링크는 Capacitor Browser
document.documentElement.dataset.shell = SHELL;

// ---------------------------------------------------------------- 설정

const APP_VERSION = "0.6.0";
// 정보 화면 링크. 주소가 정해지면 넣는다(비어 있으면 그 행을 보이지 않는다)
const PRIVACY_URL = ""; // 개인정보 처리방침 공개 페이지(스토어에 적는 주소와 같게)
const CONTACT_URL = ""; // 문의 페이지(App Store 지원 URL과 같은 곳)
const REVIEW_URL = { android: "", ios: "" }; // 스토어 앱 페이지(스토어 앱에서만 '리뷰 남기기')
const TOP_K = 20; // 처음 찾는 조합 수이자 '더 찾기' 한 번에 목록에 붙는 수. 처음 찾은 것은 6개씩 보인다(넓은 화면의 2·3열이 꽉 차게)
const RESULTS_STEP = 8; // 폰 검색 결과: 처음 개수이자 '더 보기' 한 번에 더 보이는 개수
// 넓은 화면 결과 카드(검색 결과, 과목 둘러보기)는 더 보기 없이 다 보인다(10/2 사용자). 처음엔 FEED_STEP 개를 그리고 끝의 FEED_LEAD 개 행
// 가운데 하나가 보이면 다음 FEED_STEP 개를 이어 붙인다(결과 2천 개를 한 번에 그리지 않게, 한 글자 칠 때 16개만. 카드 안 스크롤은 style.css)
const FEED_STEP = 16, FEED_LEAD = 6;
const RANKS_STEP = 6; // 후보 카드 처음 개수이자 '더 보기' 한 번에 더 보이는 개수
// 워커를 못 쓰는 브라우저에서 화면 스레드로 계산할 때: 조합 수 어림(과목마다 분반 묶음 수를 곱한 것)이 이보다 크면
// 스피너를 먼저 띄우고 계산한다(계산하는 동안에는 500ms 뒤에 스피너를 그릴 수 없다)
const HEAVY = 100000;
const LONG_MS = 10000; // 계산이 이보다 길어질 것 같으면 진행 정도와 '취소'를 보인다
const TERMS = { 1: "1학기", S: "여름학기", 2: "2학기", W: "겨울학기" };
const TERM_ORDER = ["1", "S", "2", "W"]; // 한 해 안의 학기 순서(학기 선택칸)
// 교과구분 색 묶음. 색은 style.css 의 cls-* 토큰, 메타 줄에는 원래 이름(일선, 교직)을 쓰고 색 묶음만 '기타'
const CLS_GROUPS = [["전필", "req"], ["전선", "elec"], ["교양", "gen"], ["기타", "etc"]];
const reduceMotion = matchMedia("(prefers-reduced-motion: reduce)");
const coarsePointer = matchMedia("(pointer: coarse)");
const finePointer = matchMedia("(hover: hover) and (pointer: fine)"); // 마우스: 지도 확대·축소 버튼, 휠, 끌기

const state = {
  campus: null, routes: null, routesLoading: null, travel: {},
  current: "", semesters: [], semester: "", semesterMeta: {}, cache: new Map(), loading: false, loaded: false,
  courses: [], byId: new Map(),
  // 담은 과목 [{id, excluded: Set<분반 키>, name, cls, credit, dept}]. 이름 등은 자료에서 사라진 과목을 보이려고 함께 저장한다
  picks: [],
  overrides: {}, // 분반 키 → {rooms: {수업 번호: 건물}, times: [[요일, 시작, 끝, 건물]]} 강의실·시간 미정을 직접 넣은 것
  home: "", homeOther: "", homeDorm: "", mode: "slope", // 출발·도착의 처음 값은 자료(campus.homes)의 첫 항목이다(지금은 정문)
  errors: { noSections: new Set(), overlap: new Set(), general: null }, // 주요 버튼을 누른 뒤의 오류
  result: null, rank: 0, day: 0, ranksShown: RANKS_STEP, reveal: false,
};

// ---------------------------------------------------------------- 작은 도구

function h(tag, attrs = {}, ...children) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v === null || v === undefined || v === false) continue;
    if (k === "class") el.className = v;
    else if (k === "style") for (const [p, x] of Object.entries(v)) el.style.setProperty(p, x);
    else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v === true ? "" : v);
  }
  for (const c of children.flat(Infinity)) if (c !== null && c !== undefined && c !== false) el.append(c.nodeType ? c : String(c));
  return el;
}

function svg(markup) {
  const t = document.createElement("template");
  t.innerHTML = markup.trim();
  return t.content.firstChild;
}

// 아이콘: 2px 선, 둥근 끝, 채움 없음(디자인 규칙 '아이콘')
const I = {
  x: '<path d="M6 6l12 12M18 6L6 18"/>',
  check: '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  right: '<path d="M9 6l6 6-6 6"/>',
  out: '<path d="M8 16L16 8M9.5 8H16v6.5"/>',
  down: '<path d="M6 9l6 6 6-6"/>',
};
const icon = (paths, size = 24) => svg(`<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">${paths}</svg>`);
const HOME_PIN = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 11l8-7 8 7v9H4z"></path></svg>';

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
const uid = (s) => String(s).replace(/[^A-Za-z0-9_-]/g, "_");
const pad2 = (n) => String(n).padStart(2, "0");
const hm = (m) => `${pad2(Math.floor(m / 60))}:${pad2(m % 60)}`;
const range = (a, b, step = 1) => { const out = []; for (let x = a; x <= b; x += step) out.push(x); return out; };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const nextPaint = () => new Promise((r) => requestAnimationFrame(() => setTimeout(r, 0)));

const store = {
  get(k, d) { try { const v = localStorage.getItem("ttw." + k); return v === null ? d : JSON.parse(v); } catch { return d; } },
  set(k, v) { try { localStorage.setItem("ttw." + k, JSON.stringify(v)); } catch { /* 저장이 안 돼도 화면은 돈다(알리지 않는다) */ } },
  del(k) { try { localStorage.removeItem("ttw." + k); } catch { /* 무시 */ } },
};
// 담은 과목·직접 넣은 강의실과 시간은 학기마다 따로 둔다(같은 교과목번호·분반 번호라도 학기마다 다른 강좌다)
const semKey = (k, sem = state.semester) => `${k}@${sem}`;

/** 알림 영역(role=status, role=alert)에 읽을 문구. 같은 문구도 다시 읽히게 비웠다가 채운다. */
const liveTimers = {};
function announce(text, kind = "status") {
  const el = $(kind);
  el.textContent = "";
  clearTimeout(liveTimers[kind]);
  liveTimers[kind] = setTimeout(() => { el.textContent = text; }, 60);
}

// ---------------------------------------------------------------- 표기 (디자인 규칙 '형식')

const fmtCredit = (x) => (x === null || x === undefined || x === "" ? "" : `${+x}학점`);
function semLabel(sem) {
  const [y, t] = String(sem || "").split("-");
  return TERMS[t] ? `${y}년 ${TERMS[t]}` : String(sem || "");
}
function dateParts(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(iso || "");
  return m ? { mo: +m[2], d: +m[3], t: `${m[4]}:${m[5]}` } : null;
}
const asofShort = (iso) => { const p = dateParts(iso); return p ? `${p.mo}월 ${p.d}일 기준` : ""; };
const asofLong = (iso) => { const p = dateParts(iso); return p ? `${p.mo}월 ${p.d}일 ${p.t} 기준` : ""; };

function buildingLabel(b) {
  if (!b) return "강의실 미정";
  if (b === "GATE") return "정문";
  return `${b}동`;
}
// 기숙사 동(update40 자료): campus.json 의 dorms = [[동, 종류]]. ids 에 없는 동은 이동시간 지점이 아니라 고를 수도, 지도 번호로 쓸 수도 없다:
// 10/3(update44)부터 919 가 그렇다(919A~D 네 동으로 나뉘었고, 919 는 화면이 건물 번호로 그리지 않게 dorms 에만 남는다)
const DORM_NAME = { 학부: "학부생활관", 대학원: "대학원생활관", 글로벌: "글로벌생활관", 가족: "가족생활관", BK: "BK국제관" }; // 지도에 쓰는 이름(자료의 건물 이름 대신 종류로)
const dormKind = (b) => ((state.campus?.dorms || []).find(([id]) => id === b) || [])[1] || "";
const isDorm = (b) => !!dormKind(b);
/** 지도에 쓰는 건물 이름(많이 확대했을 때 번호 아래). */
const buildingName = (b) => DORM_NAME[dormKind(b)] || ((state.campus?.buildings || {})[b] || [])[0] || "";
/** 출발·도착 이름: 기숙사 동은 어느 동이든 '기숙사'(어느 동인지는 입력 화면 선택칸과 결과 화면 조건 줄만 밝힌다), 정문, 그 밖은 건물. */
function placeLabel(b) {
  if (isDorm(b)) return "기숙사";
  const home = (state.campus?.homes || []).find(([id]) => id === b);
  return home ? home[1] : buildingLabel(b);
}
/** 강의실: 301동 118호, 호수가 글자면 301동 강당, 건물만 알면 301동, 직접 넣은 건물은 301동 (직접 입력). */
function roomLabel(m) {
  if (!m.building) return "강의실 미정";
  if (m.manual) return `${m.building}동 (직접 입력)`;
  if (!m.room) return `${m.building}동`;
  return /^[A-Za-z]?\d/.test(m.room) ? `${m.building}동 ${m.room}호` : `${m.building}동 ${m.room}`;
}
const daysLabel = (days) => days.map((d) => DAY_KO[d]).join("·");

/** 분반 표기는 어디서나 061(나민애). 교수가 없으면 061(교수 미정). 번호와 교수를 따로 칠할 때는 sectionParts(이어 붙이면 같다). */
function instructorOf(s) {
  return String(s.instructor || "").trim() || "교수 미정";
}
function sectionParts(s) {
  return [String(s.no), `(${instructorOf(s)})`];
}
function sectionLabel(s) {
  return sectionParts(s).join("");
}

/** 시간표 칸처럼 좁은 곳에 쓰는 과목명: 끝의 부제 괄호를 뺀다. '글로벌 공학기술 교류 특강 2 (국제 물류)' → '… 특강 2' */
function shortName(name) {
  const s = String(name || "").replace(/\s*\([^()]*\)\s*$/, "");
  return s || name;
}

function clsKey(cls) {
  const g = CLS_GROUPS.find(([n]) => n === cls);
  return g ? g[1] : "etc";
}
const clsColor = (cls) => `var(--cls-${clsKey(cls)})`;
const clsFill = (cls) => `var(--cls-${clsKey(cls)}-bg)`;

// ---------------------------------------------------------------- 강의실·시간 미정 직접 입력

/** 직접 넣은 강의실·시간을 반영한 수업 목록. */
function effMeetings(s) {
  const o = state.overrides[s.key];
  if (!s.meetings.length) {
    return ((o && o.times) || []).map(([day, start, end, building]) => ({ day, start, end, building: building || "", room: "", manual: true }));
  }
  return s.meetings.map((m, i) => (!m.building && o && o.rooms && o.rooms[i] ? { ...m, building: o.rooms[i], room: "", manual: true } : m));
}

/** 강의실이나 시간이 아직 미정인 분반(직접 넣은 것까지 본다). */
function isUndecided(s) {
  const ms = effMeetings(s);
  return !ms.length || ms.some((m) => !m.building);
}

/** 같은 시각·장소 수업을 한 줄로: [{days, start, end, building, room, indices}] */
function meetingGroups(meetings) {
  const groups = new Map();
  meetings.forEach((m, i) => {
    const k = `${m.start}|${m.end}|${m.building}|${m.room}`;
    if (!groups.has(k)) groups.set(k, { days: [], start: m.start, end: m.end, building: m.building, room: m.room, indices: [] });
    const g = groups.get(k);
    g.days.push(m.day);
    g.indices.push(i);
  });
  return [...groups.values()].sort((a, b) => a.days[0] - b.days[0] || a.start - b.start);
}

const natKey = (b) => b.split(/(\d+)/).map((x) => (/^\d+$/.test(x) ? x.padStart(5, "0") : x)).join("");
let buildingOpts = null, dormOpts = null;
/** 고를 수 있는 기숙사 동: 이동시간 지점(ids)인 동을 번호순으로, 번호만(사는 사람은 번호로 찾는다). [[동, '919A동']]
 *  919동은 919A~D 네 동이 따로다(10/3 자료). 옛 자료(dorms 없음)면 빈 목록이라 예전처럼 기숙사 = 919 하나이고 선택칸이 없다. */
function dormOptions() {
  if (!dormOpts) {
    const ids = new Set(state.campus.ids);
    dormOpts = (state.campus.dorms || []).filter(([b]) => ids.has(b))
      .sort(([a], [b]) => natKey(a).localeCompare(natKey(b)))
      .map(([b]) => [b, buildingLabel(b)]);
  }
  return dormOpts;
}
/** 고를 수 있는 건물: 이동시간 자료(경로·경사)가 있는 강의 건물. 출발 후보(기숙사·정문)와 기숙사 동은 뺀다(기숙사는 '기숙사'에서 고른다). [[건물, '301동 제1공학관']] */
function buildingOptions() {
  if (!buildingOpts) {
    const skip = new Set((state.campus.homes || []).map(([id]) => id).concat("GATE"));
    buildingOpts = state.campus.ids
      .filter((b) => !skip.has(b) && !isDorm(b))
      .sort((a, b) => natKey(a).localeCompare(natKey(b)))
      .map((b) => { const name = (state.campus.buildings[b] || [""])[0]; return [b, `${b}동${name ? " " + name : ""}`]; });
  }
  return buildingOpts;
}

function buildingSelect(value, attrs) {
  const opts = buildingOptions();
  // 전에 넣어 둔 건물이 목록에서 빠졌어도(기숙사 동) 고른 값은 그대로 보인다
  const kept = value && !opts.some(([b]) => b === value) ? [[value, buildingLabel(value)]] : [];
  const el = h("select", attrs, h("option", { value: "" }, "미정"), kept.concat(opts).map(([b, text]) => h("option", { value: b }, text)));
  el.value = value || "";
  return el;
}

// ---------------------------------------------------------------- 불러오기

async function getJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url} ${r.status}`);
  return r.json();
}

async function start() {
  hideBanner();
  state.loading = true;
  renderLoadState();
  try {
    const [campus, index] = await Promise.all([getJson("data/campus.json"), getJson("data/semesters.json").catch(() => null)]);
    state.campus = campus;
    buildingOpts = dormOpts = null;
    state.current = (index && index.current) || (campus.meta || {}).semester || "";
    state.semesters = index && index.list && index.list.length ? index.list : [[state.current, "courses.json"]];
    migrateStore(state.current);
    // 출발·도착: 지난번 값, 처음에는 자료의 첫 출발 후보(homes 차례가 곧 세그먼트 차례다: 정문 · 기숙사. 차례와 처음 값을 여기에 따로 적지 않는다)
    const homes = (campus.homes || []).map(([b]) => b);
    const known = (b) => homes.includes(b) || campus.ids.includes(b);
    const saved = store.get("home", ""), savedDorm = store.get("homeDorm", "");
    // 저장된 값이 지금 자료에 없는 기숙사 동이면(919 → 919A~D, 10/3 update44) 기숙사를 고른 채 처음 동(homes 의 기숙사 동, 919A)으로 옮긴다.
    // 정문으로 떨어뜨리면 그 사람의 걷는 시간이 다 달라진다. 묻지도 않는다(10/3 디자인: 선택칸에 동이 보여 한 번에 바꾼다).
    // 없는 기숙사 동 = 기숙사 동 목록(dorms)에는 남아 있거나(919) 기숙사 동으로 골라 두었던 값인데 이동시간 지점(ids)이 아닌 것
    const dormHome = homes.find(isDorm) || "";
    const lostDorm = (b) => !!b && !!dormHome && !known(b) && (isDorm(b) || b === savedDorm);
    state.homeOther = store.get("homeOther", "");
    state.homeDorm = lostDorm(savedDorm) ? dormHome : savedDorm;
    state.home = known(saved) ? saved : lostDorm(saved) ? dormHome : homes[0] || campus.ids[0];
    if (lostDorm(saved)) store.set("home", state.home);
    if (lostDorm(savedDorm)) store.set("homeDorm", state.homeDorm);
    state.mode = campus.slope ? store.get("mode", "slope") : "flat";
    renderSettings();
    // 지난번에 보던 학기로 연다. 그사이 새 학기가 올라왔으면 새 학기로
    const last = store.get("semester", null);
    const sem = last && last.current === state.current && state.semesters.some(([x]) => x === last.id) ? last.id : state.current;
    if (!(await loadSemester(sem))) return;
  } catch (e) {
    state.loading = false;
    renderLoadState();
    showBanner("과목 자료를 불러오지 못했어요", start);
    return;
  }
  const y = store.get("scroll", 0);
  if (y > 0 && screen === "input") requestAnimationFrame(() => window.scrollTo(0, y));
  loadRoutes();
}

/** 학기 선택 전에 저장한 담은 과목·직접 입력을 지금 학기 몫으로 옮긴다. */
function migrateStore(cur) {
  for (const k of ["picks", "overrides"]) {
    const old = store.get(k, null);
    if (old !== null && store.get(`${k}@${cur}`, null) === null) store.set(`${k}@${cur}`, old);
    if (old !== null) store.del(k);
  }
}

function readPicks(sem) {
  const raw = store.get(semKey("picks", sem), []);
  return (Array.isArray(raw) ? raw : []).filter((p) => p && p.id).map((p) => ({
    id: p.id, excluded: new Set(p.excluded || []), name: p.name || "", cls: p.cls || "", credit: p.credit ?? null, dept: p.dept || "",
  }));
}
const snapshot = (c) => ({ name: c.name, cls: c.cls, credit: c.credit, dept: c.dept });

function savePicks() {
  store.set(semKey("picks"), state.picks.map((p) => ({ id: p.id, excluded: [...p.excluded], name: p.name, cls: p.cls, credit: p.credit, dept: p.dept })));
}
function saveOverrides() {
  store.set(semKey("overrides"), state.overrides);
}

/** 학기 편람을 불러와 검색·담은 과목을 그 학기로 바꾼다. 그사이 다른 학기를 고르면 늦게 온 쪽은 버린다. */
let loadSeq = 0;
async function loadSemester(sem) {
  const seq = ++loadSeq;
  const entry = state.semesters.find(([x]) => x === sem) || state.semesters[0];
  sem = entry[0];
  state.semester = sem;
  state.loaded = false;
  state.loading = true;
  state.courses = [];
  state.byId = new Map();
  state.semesterMeta = {};
  state.picks = readPicks(sem);
  state.overrides = store.get(semKey("overrides", sem), {}) || {};
  state.result = null;
  clearErrors();
  state.errors.noSections = new Set();
  renderTerm();
  renderLoadState();
  renderResults();
  renderPicked();
  let cj = state.cache.get(sem);
  try {
    if (!cj) {
      cj = await getJson(`data/${entry[1]}`);
      state.cache.set(sem, cj);
    }
  } finally {
    if (seq === loadSeq) state.loading = false;
  }
  if (seq !== loadSeq) return false;
  state.semesterMeta = cj.meta || {};
  state.courses = parseCourses(cj);
  indexCourses();
  state.loaded = true;
  for (const p of state.picks) { const c = state.byId.get(p.id); if (c) Object.assign(p, snapshot(c)); }
  savePicks();
  checkOverlap(); // 지난번에 담아 둔 과목끼리 겹치면 열자마자 보인다
  renderTerm();
  renderLoadState();
  renderResults();
  renderPicked();
  return true;
}

async function switchSemester(sem) {
  if (!state.semesters.some(([x]) => x === sem)) { renderTerm(); return; }
  if (sem === state.semester && (state.loaded || state.loading)) return;
  cancelCompute();
  store.set("semester", { id: sem, current: state.current });
  hideBanner();
  try {
    await loadSemester(sem);
  } catch (e) {
    if (state.semester !== sem) return; // 그사이 다른 학기를 골랐다
    renderLoadState();
    showBanner("이 학기 자료를 불러오지 못했어요", () => switchSemester(sem));
  }
}

function loadRoutes() {
  if (!state.routesLoading) {
    state.routesLoading = fetch("data/routes.json").then((r) => (r.ok ? r.json() : null)).catch(() => null)
      .then((j) => {
        state.routes = j;
        if (j && state.result) { if (screen === "result") renderDay(); if (screen === "map") renderFullMap(); }
        return j;
      });
  }
  return state.routesLoading;
}

// ---------------------------------------------------------------- 학기 줄, 배너, 불러오는 중

/** 연도·학기를 따로 고른다(편람이 있는 학기만). 연도는 목록 순서(최근 먼저), 학기는 한 해 안의 순서. */
function renderTerm() {
  const ySel = $("year"), tSel = $("term");
  const ids = state.semesters.map(([id]) => id).filter((id) => /^\d{4}-[12SW]$/.test(id));
  const ok = ids.includes(state.semester);
  ySel.hidden = tSel.hidden = !ok;
  if (ok) {
    const [y, t] = state.semester.split("-");
    const years = [...new Set(ids.map((id) => id.split("-")[0]))];
    if (ySel.dataset.key !== years.join()) {
      ySel.replaceChildren(...years.map((v) => h("option", { value: v }, `${v}년`)));
      ySel.dataset.key = years.join();
    }
    const terms = TERM_ORDER.filter((k) => ids.includes(`${y}-${k}`));
    if (tSel.dataset.key !== `${y}:${terms.join()}`) {
      tSel.replaceChildren(...terms.map((k) => h("option", { value: k }, TERMS[k])));
      tSel.dataset.key = `${y}:${terms.join()}`;
    }
    ySel.value = y;
    tSel.value = t;
    fitTerm();
  }
  $("past-tag").hidden = !state.current || state.semester === state.current;
  $("asof").textContent = state.loaded ? asofShort(state.semesterMeta.updated) : "";
}

/** 연도를 바꾸면 같은 학기로, 그해에 그 학기가 없으면 그해의 가장 늦은 학기로. */
function onYearChange() {
  const y = $("year").value;
  const t = state.semester.split("-")[1];
  const has = (k) => state.semesters.some(([x]) => x === `${y}-${k}`);
  const term = has(t) ? t : [...TERM_ORDER].reverse().find(has);
  if (term) switchSemester(`${y}-${term}`); else renderTerm();
}

/** 선택칸 폭을 고른 항목 글자에 맞춘다(화살표가 글자 바로 뒤에 오게). CSS field-sizing 은 글자 폭을 모자라게 잡아서 직접 잰다. */
const canvas = document.createElement("canvas").getContext("2d");
function fitSelect(sel) {
  if (sel.hidden) return;
  const cs = getComputedStyle(sel);
  canvas.font = `${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
  const text = sel.selectedIndex >= 0 ? sel.options[sel.selectedIndex].text : "";
  sel.style.width = `${Math.ceil(canvas.measureText(text).width + parseFloat(cs.paddingLeft) + parseFloat(cs.paddingRight) + 2)}px`;
}
const fitTerm = () => { fitSelect($("year")); fitSelect($("term")); fitSelect($("browse-select")); };
if (document.fonts) document.fonts.addEventListener("loadingdone", fitTerm);
window.addEventListener("resize", fitTerm);

function renderLoadState() {
  const q = $("q");
  q.disabled = !state.loaded;
  q.placeholder = state.loading ? "불러오는 중" : "과목명, 교과목번호, 교수";
  $("q-spinner").hidden = !state.loading;
  updateRun();
}

let bannerRetry = null;
function showBanner(text, retry) {
  $("banner-text").textContent = text;
  bannerRetry = retry;
  $("banner").hidden = false;
  announce(text, "alert");
}
function hideBanner() {
  $("banner").hidden = true;
  bannerRetry = null;
}

// ---------------------------------------------------------------- 검색

// 찾는 규칙과 줄 세우기는 search.js(백엔드, docs/search.md): 줄임말·초성 섞기·치는 중인 글자·영문 자판·학과 줄임·특별 낱말
let searchIndex = [];
function indexCourses() {
  state.byId = new Map(state.courses.map((c) => [c.id, c]));
  searchIndex = indexSearch(state.courses);
}

/** 검색창 값 그대로(끝의 띄어쓰기로 다 친 낱말을 안다) → { hits: [{ c, kind, marks }] } 좋은 순 */
function findCourses(raw) {
  return searchCourses(searchIndex, raw);
}

/** 강조 범위([[시작, 끝), ...])를 굵게 */
function marked(text, ranges) {
  return splitMarks(text, ranges).map((p) => (p.mark ? h("b", {}, p.text) : p.text));
}

const isPicked = (id) => state.picks.some((p) => p.id === id);

/** 담기 버튼과 그 행. 누르는 영역은 행 전체(style.css), 담은 과목의 행은 어두운 바탕. */
/** 담기 버튼과 행: 담았으면 어두운 바탕에 '✓ 담음'. 담은 과목이 다른 과목과 시간이 겹쳐 조합을 막으면 버튼 앞에 '시간 겹침'. */
function setAddButton(b, name, picked) {
  const clash = picked && state.errors.overlap.has(b.dataset.id);
  b.classList.toggle("is-on", picked);
  const row = b.closest(".result");
  if (row) {
    row.classList.toggle("is-picked", picked);
    const tag = row.querySelector(".r-clash");
    if (clash && !tag) b.before(h("span", { class: "tag danger r-clash", "aria-hidden": "true" }, "시간 겹침"));
    else if (!clash && tag) tag.remove();
  }
  b.setAttribute("aria-label", `${name} ${picked ? "담음" : "담기"}${clash ? ", 시간 겹침" : ""}`);
  b.replaceChildren(...(picked ? [icon(I.check, 16), "담음"] : ["담기"]));
}

function resultRow({ c, marks }) {
  const title = marked(c.name, marks.name);
  // 메타: 학과 · 교과구분 · 학점. 교수·교과목번호로 찾았으면 학과 자리에 그것을 보인다
  const first = marks.prof ? marked(marks.prof.name, marks.prof.ranges) : marks.id ? marked(c.id, marks.id) : c.dept ? marked(c.dept, marks.dept) : null;
  const rest = [c.cls, fmtCredit(c.credit)].filter(Boolean).join(" · ");
  const btn = h("button", { type: "button", class: "btn-add", "data-id": c.id });
  const row = h("li", { class: "result" },
    h("div", { class: "r-body" }, h("span", { class: "r-title" }, title), h("span", { class: "r-meta" }, first ? [first, rest ? ` · ${rest}` : ""] : rest)),
    btn);
  setAddButton(btn, c.name, isPicked(c.id));
  return row;
}

// 넓은 화면 두 칸(style.css 의 같은 조건): 오른쪽 칸 폭의 스낵바, 자료를 받은 뒤 늘 있는 결과 카드(검색 전에는 최근 검색어와 과목 둘러보기)
const twoPane = matchMedia("(min-width: 42.5em), (horizontal-viewport-segments: 2)");

/** 넓은 화면 목록: items 를 FEED_STEP 개씩 이어 붙인다(끝의 FEED_LEAD 개 행 가운데 하나라도 보이면 다음). 다시 부르면 앞의 것은 멈춘다.
 *  보이는지는 화면 기준으로 보되 카드 안 스크롤에 가려진 행은 안 보이는 것으로 친다(IntersectionObserver 가 조상의 잘림을 따진다).
 *  끝의 여러 행을 보는 것은 스크롤 막대를 끌거나 End 로 한 번에 끝까지 가도(그 사이 행을 건너뛰어도) 멈추지 않게 하려고. */
const feeds = new Map();
function feedList(list, items, row) {
  stopFeed(list);
  let shown = 0;
  const io = new IntersectionObserver((es) => { if (feeds.get(list) === io && es.some((e) => e.isIntersecting)) more(); });
  feeds.set(list, io);
  const more = () => {
    io.disconnect();
    const next = items.slice(shown, shown + FEED_STEP);
    shown += next.length;
    list.append(...next.map(row));
    if (shown < items.length) for (const el of [...list.children].slice(-FEED_LEAD)) io.observe(el);
  };
  list.replaceChildren();
  more();
}
function stopFeed(list) {
  feeds.get(list)?.disconnect();
  feeds.delete(list);
}

// 넓은 화면 검색 전 왼쪽: 과목 둘러보기(10/2 디자인, 최근 검색어로 카드를 채우던 것 대신). 목록 머리의 선택칸(교양 전체·학과)이 곧 목록
// 제목이고, 행은 검색 결과 행과 같다(강조 없이 학과 · 교과구분 · 학점). 학사 과목만(대학원 과목은 검색으로). 교양 전체는 가나다,
// 학과는 전필 → 전선 → 교양 → 그 밖이고 같은 묶음은 가나다. 고른 목록은 이 기기에 기억하고, 그 학기에 없는 학과면 교양 전체
const collator = new Intl.Collator("ko");
const CLS_ORDER = { 전필: 0, 전선: 1, 교양: 2 };
const clsRank = (c) => CLS_ORDER[c.cls] ?? 3;
const NO_MARKS = {};
let browseKey = String(store.get("browse", "교양") || "교양"), browseData = null, browseDepts = [], browseDrawn = "";
function browseCourses() {
  const list = state.courses.filter((c) => c.program === "학사" && (browseKey === "교양" ? c.cls === "교양" : c.dept === browseKey));
  return list.sort((a, b) => (browseKey === "교양" ? 0 : clsRank(a) - clsRank(b)) || collator.compare(a.name, b.name) || collator.compare(a.id, b.id));
}
/** 둘러보기를 보이거나 숨긴다. 학기(자료)나 고른 목록이 바뀌었을 때만 목록을 새로 그리고 true(그대로면 행과 스크롤 자리를 둔다). */
function renderBrowse(show) {
  $("browse").hidden = !show;
  if (!show) return false;
  const sel = $("browse-select");
  if (browseData !== state.courses) {
    browseData = state.courses;
    browseDrawn = "";
    browseDepts = [...new Set(state.courses.filter((c) => c.program === "학사").map((c) => c.dept).filter(Boolean))].sort(collator.compare);
    sel.replaceChildren(h("option", { value: "교양" }, "교양 전체"), h("optgroup", { label: "학과" }, browseDepts.map((d) => h("option", { value: d }, d))));
  }
  if (browseKey !== "교양" && !browseDepts.includes(browseKey)) browseKey = "교양"; // 학기를 바꿔 그 학과가 없으면(기억은 그대로 둔다)
  sel.value = browseKey;
  fitSelect(sel);
  if (browseDrawn === browseKey) return false;
  browseDrawn = browseKey;
  feedList($("browse-list"), browseCourses(), (c) => resultRow({ c, marks: NO_MARKS }));
  return true;
}

// 최근 검색어: 담기로 이어졌거나 Enter 로 낸(결과가 있는) 검색어. 학기와 상관없이 이 기기에 10개까지, 같은 말(띄어쓰기·대소문자 무시)은 하나로
const RECENT_MAX = 10;
let recent = (() => {
  const v = store.get("recent", []);
  return Array.isArray(v) ? v.filter((x) => typeof x === "string" && x.trim()).slice(0, RECENT_MAX) : [];
})();
function saveRecent(raw) {
  const text = String(raw || "").trim().replace(/\s+/g, " ").slice(0, 60);
  if (!text) return;
  const k = normKey(text);
  recent = [text, ...recent.filter((x) => normKey(x) !== k)].slice(0, RECENT_MAX);
  store.set("recent", recent);
}
function setRecent(list) {
  recent = list;
  if (recent.length) store.set("recent", recent); else store.del("recent");
}

/** 검색 전 카드: 최근 검색어 칩(누르면 그 말로 검색, ×로 하나 지우기). 하나도 없으면 두지 않는다(빈 상태 문장 없음, 10/2 디자인).
 *  목록이 그대로면 다시 만들지 않는다(키보드 초점이 칩에 있을 때 다시 그려 초점을 잃지 않게). */
let drawnRecent = "";
function renderIdle(show) {
  const has = show && recent.length > 0;
  $("recent").hidden = !has;
  const key = has ? JSON.stringify(recent) : "";
  if (key === drawnRecent) return;
  drawnRecent = key;
  $("recent-list").replaceChildren(...(has ? recent : []).map((text) => h("li", { class: "chip" },
    h("button", { type: "button", class: "chip-q", "data-q": text }, h("span", {}, text)),
    h("button", { type: "button", class: "chip-x", "data-del": text, "aria-label": `${text} 지우기` }, icon(I.x, 16)))));
}
/** 검색창이나 그 아래 카드(최근 검색어·결과)에 초점이 있다. */
const searchFocused = () => document.activeElement === $("q") || $("results").contains(document.activeElement);

// 넓은 화면은 결과 카드가 스크롤 칸이다(style.css). 새 검색은 맨 위부터, 검색을 지우면 둘러보던 자리로 돌아간다
let resultsShown = RESULTS_STEP, lastQuery = "", countTimer = null, browseTop = 0;
function renderResults({ more = false } = {}) {
  const raw = $("q").value;
  const box = $("results"), list = $("results-list");
  const wide = twoPane.matches;
  // 카드 스크롤 자리는 화면을 바꾸기 전에 읽고 쓴다(바꾼 뒤에 하면 그 자리에서 레이아웃을 다시 계산해 타자가 느려진다)
  if (raw.trim() && state.loaded) {
    if (!lastQuery && !$("browse").hidden) browseTop = box.scrollTop;
    if (wide && raw !== lastQuery && box.scrollTop) box.scrollTop = 0;
  }
  $("q-clear").hidden = !raw;
  if (!raw.trim() || !state.loaded) {
    const fromSearch = lastQuery !== "";
    lastQuery = "";
    clearTimeout(countTimer);
    stopFeed(list);
    list.replaceChildren();
    $("results-empty").hidden = $("results-more").hidden = true;
    // 넓은 화면은 자료를 받은 뒤 카드를 늘 둔다(최근 검색어 + 과목 둘러보기). 폰은 빈 검색창에 초점이 있고 최근 검색어가 있을 때만.
    // 불러오는 중에는 두지 않는다(검색창의 '불러오는 중'과 스피너)
    const idle = state.loaded && (wide || (searchFocused() && recent.length > 0));
    box.hidden = !idle;
    renderIdle(idle);
    const redrawn = renderBrowse(wide && state.loaded);
    if (fromSearch) box.scrollTop = redrawn ? 0 : browseTop;
    return;
  }
  renderIdle(false);
  renderBrowse(false);
  const fresh = raw !== lastQuery;
  if (fresh) { resultsShown = RESULTS_STEP; lastQuery = raw; }
  const found = findCourses(raw);
  box.hidden = false;
  $("results-empty").hidden = found.hits.length > 0;
  if (wide) {
    feedList(list, found.hits, resultRow);
    $("results-more").hidden = true;
  } else {
    const before = more ? list.children.length : 0;
    stopFeed(list);
    list.replaceChildren(...found.hits.slice(0, resultsShown).map((hit) => resultRow(hit)));
    $("results-more").hidden = found.hits.length <= resultsShown;
    if (more) { list.children[before]?.querySelector("button")?.focus(); return; }
  }
  clearTimeout(countTimer);
  countTimer = setTimeout(() => announce(found.hits.length ? `결과 ${found.hits.length}개` : "검색 결과 없음"), 500);
}

function syncAddButtons() {
  for (const b of document.querySelectorAll("#results-list .btn-add, #browse-list .btn-add")) {
    const c = state.byId.get(b.dataset.id);
    if (c) setAddButton(b, c.name, isPicked(c.id));
  }
}

// ---------------------------------------------------------------- 담은 과목

/** 담은 과목·분반·직접 입력이 바뀐 뒤: 저장하고, 그 조합에 대한 오류와 결과를 비운 뒤 겹침을 다시 본다. 새로 겹치게 됐으면 true. */
function changed() {
  const had = state.errors.overlap.size > 0;
  cancelCompute();
  savePicks();
  saveOverrides();
  clearErrors();
  state.result = null;
  return checkOverlap() && !had;
}

function clearErrors() {
  state.errors.overlap = new Set();
  state.errors.general = null;
}

const OVERLAP_TEXT = "겹치지 않는 조합이 없어요";

/**
 * 켠 분반으로 겹치지 않는 조합이 하나도 없으면 시간표 만들기를 누르기 전에, 담을 때 바로 알린다(10/1 사용자).
 * 서로 막는 과목(가장 작은 묶음)에 '시간 겹침'(담은 과목 행과 검색 결과 행), 담은 과목 제목 아래 '겹치지 않는 조합이 없어요'.
 * 50ms 안에 판단이 안 서면(분반이 아주 많을 때) 넘어가고, 그때는 시간표 만들기에서 워커가 알린다. 겹치면 true.
 */
function checkOverlap() {
  if (!state.loaded) return false;
  const live = collectCourses().courses;
  if (live.length < 2) return false;
  const r = countFeasible(live, { limit: 1, budgetMs: 50 });
  if (r.count > 0 || !r.exact) return false;
  state.errors.overlap = new Set(findConflicts(live));
  state.errors.general = { text: OVERLAP_TEXT };
  return true;
}

function addCourse(id) {
  const c = state.byId.get(id);
  if (!c || isPicked(id)) return;
  state.picks.push({ id, excluded: new Set(), ...snapshot(c) });
  const clash = changed();
  renderPicked({ added: id });
  if (clash) announce(`${c.name} 담았어요. ${OVERLAP_TEXT}`, "alert");
  else announce(`${c.name} 담았어요`);
}

function removeCourse(id, { fromList = false } = {}) {
  const i = state.picks.findIndex((p) => p.id === id);
  if (i < 0) return;
  const p = state.picks[i];
  const c = state.byId.get(id);
  const saved = {}; // 되돌리면 분반 선택과 직접 넣은 강의실·시간까지 돌아온다
  for (const s of c ? c.sections : []) {
    if (state.overrides[s.key]) { saved[s.key] = state.overrides[s.key]; delete state.overrides[s.key]; }
  }
  const row = $("picked-list").querySelector(`li[data-id="${CSS.escape(id)}"]`);
  const keyboard = Boolean(row && row.querySelector(":focus-visible"));
  const sib = row && (row.nextElementSibling || row.previousElementSibling);
  const nextId = sib ? sib.dataset.id : null;
  state.picks.splice(i, 1);
  changed();
  renderPickedHead();
  let done = false;
  const finish = () => {
    if (done) return;
    done = true;
    renderPicked();
    if (fromList && keyboard) focusRow(nextId, ".remove") || $("q").focus();
  };
  // 뺀 행은 150ms 동안 사라지고, 숫자는 바로 바뀐다
  if (row && !reduceMotion.matches) {
    row.classList.add("is-leaving");
    row.addEventListener("animationend", finish, { once: true });
    setTimeout(finish, 250);
  } else finish();
  syncAddButtons();
  const name = p.name || (c && c.name) || id;
  announce(`${name} 뺐어요`);
  showSnackbar("과목을 뺐어요", "되돌리기", () => {
    if (isPicked(id)) return;
    state.picks.splice(Math.min(i, state.picks.length), 0, p);
    Object.assign(state.overrides, saved);
    changed();
    renderPicked();
    syncAddButtons();
    focusRow(id, ".course-hit");
  });
}

function focusRow(id, sel) {
  if (!id) return false;
  const el = $("picked-list").querySelector(`li[data-id="${CSS.escape(id)}"] ${sel}`);
  if (el) el.focus({ preventScroll: false });
  return Boolean(el);
}

/** 태그는 한 행에 두 개까지, 위험 → 주의 → 중립 순. [[종류, 글]] */
function courseTags(p, c) {
  const on = c.sections.filter((s) => !p.excluded.has(s.key));
  const tags = [];
  if (state.errors.overlap.has(c.id)) tags.push(["danger", "시간 겹침"]);
  if (on.some((s) => s.status === "폐강대상")) tags.push(["warning", "폐강 대상"]);
  if (on.some(isUndecided)) tags.push(["", "미정"]);
  return tags.slice(0, 2);
}

function courseRow(p, isNew) {
  const c = state.loaded ? state.byId.get(p.id) : null;
  const name = c ? c.name : p.name || p.id;
  const cls = c ? c.cls : p.cls;
  let meta, tags = [], error = "";
  if (c) {
    const on = c.sections.filter((s) => !p.excluded.has(s.key)).length;
    meta = [c.cls, fmtCredit(c.credit), `분반 ${on}/${c.sections.length}`].filter(Boolean).join(" · ");
    tags = courseTags(p, c);
    if (!on && state.errors.noSections.has(c.id)) error = "켠 분반이 없어요";
  } else {
    // 자료를 불러오기 전이거나, 이번 자료에서 사라진 과목(지우지 않고 '없는 과목', 계산에서는 빠진다)
    meta = [cls, fmtCredit(p.credit)].filter(Boolean).join(" · ") || p.id;
    if (state.loaded) tags = [["danger", "없는 과목"]];
  }
  const errId = error ? `err-${uid(p.id)}` : null;
  const hit = h("button", {
    type: "button", class: "course-hit", "data-open": p.id, "aria-describedby": errId, "aria-disabled": state.loaded ? null : "true",
    "aria-label": [name, meta, ...tags.map(([, t]) => t)].join(", "),
  },
  h("span", { class: "dot", "aria-hidden": "true", style: { background: clsColor(cls) } }),
  h("span", { class: "c-body" },
    h("span", { class: "c-title" }, name),
    h("span", { class: "c-meta" }, meta),
    error ? h("span", { class: "c-error", id: errId }, error) : null));
  return h("li", { class: `course${isNew ? " is-new" : ""}`, "data-id": p.id },
    hit,
    tags.length ? h("span", { class: "tags", "aria-hidden": "true" }, tags.map(([k, t]) => h("span", { class: k ? `tag ${k}` : "tag" }, t))) : null,
    h("button", { type: "button", class: "icon-btn remove", "data-remove": p.id, "aria-label": `${name} 빼기` }, icon(I.x, 20)));
}

/** 담은 과목 제목 옆: 과목 수와 총 학점(이번 자료에 없는 과목은 빼고 센다). */
function renderPickedHead() {
  const n = state.picks.length;
  $("picked-count").textContent = n ? String(n) : "";
  let sum = 0;
  for (const p of state.picks) {
    const c = state.loaded ? state.byId.get(p.id) : null;
    if (state.loaded && !c) continue;
    sum += Number((c ? c.credit : p.credit) || 0);
  }
  sum = Math.round(sum * 10) / 10;
  $("picked-credits").textContent = n && sum ? `총 ${sum}학점` : "";
}

function renderPicked({ added = "" } = {}) {
  const n = state.picks.length;
  renderPickedHead();
  $("picked-empty").hidden = n > 0;
  $("picked-legend").hidden = n === 0; // 점 색 풀이는 담은 과목이 있을 때만
  $("picked-list").replaceChildren(...state.picks.map((p) => courseRow(p, p.id === added)));
  renderPickedError();
  syncAddButtons(); // 검색 결과 행의 '시간 겹침'도 같이
  updateRun();
  if (sheetId && $("course-sheet").open) refreshSheetHead();
}

function renderPickedError() {
  const g = state.errors.general;
  $("picked-error").hidden = !g;
  $("picked-error-text").textContent = g ? g.text : "";
  $("picked-retry").hidden = !(g && g.retry);
  if (g) $("run").setAttribute("aria-describedby", "picked-error-text");
  else $("run").removeAttribute("aria-describedby");
}

// ---------------------------------------------------------------- 과목 시트

let sheetId = null;
const edits = new Map(); // 분반 키 → 시간 추가 입력 줄 {open, day, sh, sm, eh, em, b, error}

function editState(key) {
  if (!edits.has(key)) edits.set(key, { open: false, day: 0, sh: 9, sm: 0, eh: 10, em: 15, b: "", error: false });
  return edits.get(key);
}

function openCourseSheet(id, opener) {
  sheetId = id;
  renderCourseSheet();
  openSheet($("course-sheet"), opener);
}

const sheetPick = () => state.picks.find((p) => p.id === sheetId);

function renderCourseSheet() {
  const p = sheetPick();
  if (!p) return;
  const c = state.byId.get(p.id);
  $("cs-title").textContent = c ? c.name : p.name || p.id;
  $("cs-meta").textContent = [p.id, c ? c.dept : p.dept, fmtCredit(c ? c.credit : p.credit)].filter(Boolean).join(" · ");
  const body = $("cs-body");
  if (!c) {
    body.replaceChildren(h("p", {}, "이번 자료에 없는 과목이에요"));
    return;
  }
  body.replaceChildren(
    h("div", { class: "list-head" },
      h("span", { id: "cs-count" }),
      h("label", { class: "check" }, h("input", { type: "checkbox", id: "cs-all", "data-act": "all" }), "전체 선택")),
    h("ul", { class: "list secs" }, c.sections.map((s) => { const li = h("li", { class: "sec", "data-key": s.key }); fillSec(li, p, s); return li; })));
  refreshSheetHead();
}

function refreshSheetHead() {
  const p = sheetPick();
  const c = p && state.byId.get(p.id);
  if (!c || !$("cs-count")) return;
  const on = c.sections.filter((s) => !p.excluded.has(s.key)).length;
  $("cs-count").textContent = `분반 ${on}/${c.sections.length}`;
  const all = $("cs-all");
  all.checked = on === c.sections.length;
  all.indeterminate = on > 0 && on < c.sections.length;
}

function timeChipText(t) {
  return `${DAY_KO[t[0]]} ${hm(t[1])}~${hm(t[2])} · ${t[3] ? buildingLabel(t[3]) : "강의실 미정"}`;
}

/** 분반 행 하나: 체크박스와 001(이주훈) / 요일·시각 · 강의실(미정이면 값 자리를 눌러 고른다) / 태그 / 넣은 시간 / 시간 추가 입력 줄 */
function fillSec(li, p, s) {
  const on = !p.excluded.has(s.key);
  const o = state.overrides[s.key] || {};
  li.className = on ? "sec" : "sec off";
  const parts = [h("label", { class: "sec-pick" },
    h("input", { type: "checkbox", checked: on, "data-act": "toggle" }),
    h("span", { class: "sec-title" }, s.no, h("span", { class: "prof" }, `(${instructorOf(s)})`)))];
  const tags = [];
  if (s.status === "폐강대상") tags.push(h("span", { class: "tag warning" }, "폐강 대상"));
  let extra = [];
  if (s.meetings.length) {
    const groups = meetingGroups(s.meetings);
    const unknown = groups.filter((g) => !g.building);
    let manual = false;
    for (const g of groups) {
      const when = `${daysLabel(g.days)} ${hm(g.start)}~${hm(g.end)}`;
      if (g.building) {
        parts.push(h("div", { class: "sec-when" }, h("span", {}, when), h("span", { "aria-hidden": "true" }, "·"), h("span", {}, roomLabel(g))));
        continue;
      }
      const value = (o.rooms || {})[g.indices[0]] || "";
      if (value) manual = true;
      parts.push(h("div", { class: "sec-when" }, h("span", {}, when), h("span", { "aria-hidden": "true" }, "·"),
        h("span", { class: "sec-value" }, value ? buildingLabel(value) : "강의실 미정", icon(I.down, 16),
          buildingSelect(value, {
            "data-act": "room", "data-idx": g.indices.join(","),
            "aria-label": unknown.length > 1 ? `${s.no} ${daysLabel(g.days)} 강의실` : `${s.no} 강의실`,
          }))));
    }
    if (manual) tags.push(h("span", { class: "tag" }, "직접 입력"));
  } else {
    const times = o.times || [];
    const st = editState(s.key);
    const editId = `edit-${uid(s.key)}`;
    parts.push(h("div", { class: "sec-when" }, h("span", {}, "시간 미정"),
      h("button", { type: "button", class: "btn-text small", "data-act": "add-time", "aria-expanded": String(st.open), "aria-controls": st.open ? editId : null },
        icon(I.plus, 16), "시간 추가")));
    if (times.length) {
      extra.push(h("div", { class: "chips" }, times.map((t, i) => {
        const text = timeChipText(t);
        return h("span", { class: "chip" }, text, h("button", { type: "button", "data-act": "del-time", "data-i": String(i), "aria-label": `${text} 빼기` }, icon(I.x, 16)));
      })));
    }
    if (st.open) extra.push(timeEditor(s, st, editId));
  }
  if (tags.length) parts.push(h("div", { class: "tags" }, tags));
  li.replaceChildren(...parts, ...extra);
}

/** 시간 추가 입력 줄: 요일(월–토), 시작·끝(시·분 선택, 24시간, 5분 단위), 건물(기본 미정), 추가. type="time" 은 쓰지 않는다(AM/PM). */
function timeEditor(s, st, id) {
  const errId = `${id}-err`;
  const hours = range(6, 23).map((x) => [x, pad2(x)]);
  const mins = range(0, 55, 5).map((x) => [x, pad2(x)]);
  const sel = (key, values, label) => {
    const el = h("select", { class: "select", "data-edit": key, "aria-label": label }, values.map(([v, t]) => h("option", { value: String(v) }, t)));
    el.value = String(st[key]);
    if (st.error && (key === "eh" || key === "em")) { el.setAttribute("aria-invalid", "true"); el.setAttribute("aria-describedby", errId); }
    return el;
  };
  const name = `day-${uid(s.key)}`;
  return h("div", { class: "sec-edit", id },
    h("fieldset", { class: "days" }, h("legend", { class: "sr-only" }, "요일"),
      DAY_KO.slice(0, 6).split("").map((d, i) => h("label", {}, h("input", { type: "radio", name, value: String(i), checked: st.day === i, "data-edit": "day" }), d))),
    h("div", { class: "time-row" },
      sel("sh", hours, "시작 시"), h("span", { "aria-hidden": "true" }, ":"), sel("sm", mins, "시작 분"),
      h("span", { "aria-hidden": "true" }, "~"),
      sel("eh", hours, "끝 시"), h("span", { "aria-hidden": "true" }, ":"), sel("em", mins, "끝 분")),
    st.error ? h("p", { class: "error-line", id: errId }, "끝 시각이 시작보다 빨라요") : null,
    buildingSelect(st.b, { class: "select", "data-edit": "b", "aria-label": "건물" }),
    h("div", {}, h("button", { type: "button", class: "btn-add", "data-act": "save-time" }, "추가")));
}

function refillSec(li, focusSel) {
  const p = sheetPick();
  const c = p && state.byId.get(p.id);
  const s = c && c.sections.find((x) => x.key === li.dataset.key);
  if (!s) return;
  fillSec(li, p, s);
  if (focusSel) li.querySelector(focusSel)?.focus();
}

function sectionsChanged() {
  changed();
  refreshSheetHead();
  renderPicked();
}

$("cs-body").addEventListener("change", (e) => {
  const t = e.target;
  const p = sheetPick();
  const c = p && state.byId.get(p.id);
  if (!c) return;
  const li = t.closest(".sec");
  if (t.dataset.act === "all") {
    p.excluded = t.checked ? new Set() : new Set(c.sections.map((s) => s.key));
    for (const row of $("cs-body").querySelectorAll(".sec")) {
      row.classList.toggle("off", !t.checked);
      row.querySelector('input[data-act="toggle"]').checked = t.checked;
    }
    sectionsChanged();
  } else if (t.dataset.act === "toggle") {
    if (t.checked) p.excluded.delete(li.dataset.key); else p.excluded.add(li.dataset.key);
    li.classList.toggle("off", !t.checked);
    sectionsChanged();
  } else if (t.dataset.act === "room") {
    const key = li.dataset.key;
    const o = { ...(state.overrides[key] || {}) };
    const rooms = { ...(o.rooms || {}) };
    for (const i of t.dataset.idx.split(",")) { if (t.value) rooms[i] = t.value; else delete rooms[i]; }
    if (Object.keys(rooms).length) o.rooms = rooms; else delete o.rooms;
    if (o.rooms || (o.times && o.times.length)) state.overrides[key] = o; else delete state.overrides[key];
    changed();
    renderPicked();
    refillSec(li, `select[data-idx="${t.dataset.idx}"]`);
  } else if (t.dataset.edit) {
    const st = editState(li.dataset.key);
    st[t.dataset.edit] = t.dataset.edit === "b" ? t.value : Number(t.value);
    // 오류는 원인이 풀리면 사라진다
    if (st.error && st.eh * 60 + st.em > st.sh * 60 + st.sm) { st.error = false; refillSec(li, `[data-edit="${t.dataset.edit}"]${t.type === "radio" ? ":checked" : ""}`); }
  }
});

$("cs-body").addEventListener("click", (e) => {
  const actEl = e.target.closest("[data-act]");
  const act = actEl && actEl.dataset.act;
  const li = e.target.closest(".sec");
  if (!li) return;
  const key = li.dataset.key;
  if (act === "add-time") {
    const st = editState(key);
    st.open = !st.open;
    refillSec(li, '[data-act="add-time"]');
  } else if (act === "save-time") {
    const st = editState(key);
    const a = st.sh * 60 + st.sm, b = st.eh * 60 + st.em;
    if (b <= a) {
      st.error = true;
      refillSec(li, '[data-edit="eh"]');
      announce("끝 시각이 시작보다 빨라요", "alert");
      return;
    }
    const o = { ...(state.overrides[key] || {}) };
    o.times = [...(o.times || []), [st.day, a, b, st.b]];
    state.overrides[key] = o;
    st.open = false;
    st.error = false;
    changed();
    renderPicked();
    refillSec(li, '[data-act="add-time"]');
  } else if (act === "del-time") {
    const o = { ...(state.overrides[key] || {}) };
    o.times = (o.times || []).filter((_, i) => i !== Number(actEl.dataset.i));
    if (!o.times.length) delete o.times;
    if (o.rooms || o.times) state.overrides[key] = o; else delete state.overrides[key];
    changed();
    renderPicked();
    refillSec(li, '[data-act="add-time"]');
  } else if (!e.target.closest("label, select, button, input, a, .sec-edit, .chips")) {
    // 행 어디를 눌러도 분반이 켜지고 꺼진다(강의실·시간을 넣는 자리는 빼고)
    li.querySelector('input[data-act="toggle"]')?.click();
  }
});

// ---------------------------------------------------------------- 시트 (과목, 이동시간 계산 방법, 홈 화면에 추가)

function openSheet(d, opener) {
  for (const x of document.querySelectorAll("dialog[open]")) x.close(); // 시트 위에 시트를 띄우지 않는다
  d.returnTo = opener || document.activeElement;
  d.style.transform = "";
  d.showModal();
  d.scrollTop = 0;
}

/** 완료·닫기, 바깥 누르기, 아래로 끌기: 200ms 에 내려가며 닫힌다. Esc·Android 뒤로 가기(cancel)는 브라우저가 바로 닫는다. */
function closeSheet(d) {
  if (!d.open || d.closing) return;
  if (reduceMotion.matches || !d.animate) { d.close(); return; }
  d.closing = true;
  const bottom = !matchMedia("(min-width: 37.5em)").matches;
  const opts = { duration: 200, easing: "cubic-bezier(0.3, 0, 0.8, 0.15)", fill: "forwards" }; // dur-exit, ease-exit
  const from = d.style.transform || "translateY(0)";
  const anims = [d.animate([{ transform: from, opacity: 1 }, { transform: bottom ? "translateY(100%)" : "translateY(16px)", opacity: bottom ? 1 : 0 }], opts)];
  try { anims.push(d.animate([{ opacity: 1 }, { opacity: 0 }], { ...opts, pseudoElement: "::backdrop" })); } catch { /* 안 되는 브라우저는 바탕이 바로 사라진다 */ }
  anims[0].finished.catch(() => null).then(() => {
    d.close();
    for (const a of anims) a.cancel();
    d.style.transform = "";
    d.closing = false;
  });
}

function enableSheetDrag(d) {
  const head = d.querySelector(".sheet-head");
  let y0 = null, t0 = 0, dy = 0, dragging = false, pid = null;
  head.addEventListener("pointerdown", (e) => {
    if ((e.pointerType === "mouse" && e.button !== 0) || matchMedia("(min-width: 37.5em)").matches) return; // 가운데 대화상자는 끌지 않는다
    y0 = e.clientY; t0 = e.timeStamp; dy = 0; dragging = false; pid = e.pointerId;
  });
  head.addEventListener("pointermove", (e) => {
    if (y0 === null || e.pointerId !== pid) return;
    dy = Math.max(0, e.clientY - y0);
    if (!dragging && dy > 8) { dragging = true; head.setPointerCapture(pid); }
    if (dragging) d.style.transform = `translateY(${dy}px)`;
  });
  const end = (e) => {
    if (y0 === null || e.pointerId !== pid) return;
    y0 = null;
    if (!dragging) return;
    const speed = dy / Math.max(1, e.timeStamp - t0);
    if (dy > 96 || (dy > 32 && speed > 0.5)) closeSheet(d);
    else if (d.animate && !reduceMotion.matches) {
      d.animate([{ transform: d.style.transform }, { transform: "translateY(0)" }], { duration: 200, easing: "cubic-bezier(0.2, 0, 0, 1)" });
      d.style.transform = "";
    } else d.style.transform = "";
  };
  head.addEventListener("pointerup", end);
  head.addEventListener("pointercancel", end);
}

for (const d of document.querySelectorAll("dialog.sheet")) {
  d.addEventListener("click", (e) => {
    if (e.target.closest("[data-close]")) { closeSheet(d); return; }
    if (e.target === d) { // 바깥(::backdrop) 누르기
      const r = d.getBoundingClientRect();
      if (e.clientY < r.top || e.clientY > r.bottom || e.clientX < r.left || e.clientX > r.right) closeSheet(d);
    }
  });
  d.addEventListener("close", () => {
    const back = d.returnTo;
    d.returnTo = null;
    if (d.id === "course-sheet") {
      const id = sheetId;
      sheetId = null;
      if (back && back.isConnected) back.focus({ preventScroll: true });
      else focusRow(id, ".course-hit");
    } else if (back && back.isConnected) back.focus({ preventScroll: true });
  });
  enableSheetDrag(d);
}

// ---------------------------------------------------------------- 조건

const segItem = (name, value, label, checked) => h("label", {}, h("input", { type: "radio", name, value, checked }), label);

/** 출발·도착이 어느 세그먼트인지: 기숙사 동이면 'dorm'(동은 아래 선택칸에서), 정문 같은 출발 후보면 그 건물, 나머지는 'other'. */
function homeSeg(b) {
  if (isDorm(b)) return "dorm";
  return (state.campus.homes || []).some(([x]) => x === b) ? b : "other";
}

/** 세그먼트 아래 선택칸은 한 자리다(10/2 디자인): '기숙사'면 동(이름 '기숙사 동'), '다른 건물'이면 건물(이름 '건물'), '정문'이면 없다.
 *  세그먼트 라디오는 다시 그리지 않아서, 선택칸이 나타나거나 바뀌어도 초점은 고른 라디오에 남는다. */
function syncHomeSelect() {
  const seg = homeSeg(state.home), sel = $("home-select");
  const kind = seg === "dorm" ? (dormOptions().length > 1 ? "dorm" : "") : seg === "other" ? "other" : "";
  if (kind && sel.dataset.kind !== kind) {
    sel.replaceChildren(...(kind === "dorm" ? dormOptions() : buildingOptions()).map(([b, text]) => h("option", { value: b }, text)));
    sel.setAttribute("aria-label", kind === "dorm" ? "기숙사 동" : "건물");
    sel.dataset.kind = kind;
  }
  sel.hidden = !kind;
  if (kind) sel.value = state.home;
}

function renderSettings() {
  const homes = state.campus.homes || [];
  const seg = homeSeg(state.home);
  // 세그먼트는 자료의 출발 후보 차례 그대로(10/3: 정문 | 기숙사) + 다른 건물. 출발 후보의 기숙사(919A)가 기숙사 동 묶음의 세그먼트다
  $("home-seg").replaceChildren(
    ...homes.map(([b, label]) => { const v = isDorm(b) ? "dorm" : b; return segItem("home", v, label, v === seg); }),
    segItem("home", "other", "다른 건물", seg === "other"));
  $("home-seg").hidden = false;
  delete $("home-select").dataset.kind; // 자료를 새로 받았으면 목록도 새로
  syncHomeSelect();
  for (const r of document.querySelectorAll('input[name="mode"]')) {
    r.checked = r.value === state.mode;
    r.disabled = r.value === "slope" && !state.campus.slope;
  }
}

/** 출발·도착을 바꾼다. 기숙사 동과 다른 건물은 마지막에 고른 것을 따로 기억해, 세그먼트를 오가도 그대로다. */
function setHome(b) {
  cancelCompute();
  state.home = b;
  store.set("home", b);
  const seg = homeSeg(b);
  if (seg === "dorm") { state.homeDorm = b; store.set("homeDorm", b); }
  else if (seg === "other") { state.homeOther = b; store.set("homeOther", b); }
  state.result = null;
  syncHomeSelect();
}

$("home-seg").addEventListener("change", (e) => {
  const v = e.target.value;
  if (v === "dorm") {
    const first = (state.campus.homes || []).map(([b]) => b).find(isDorm); // 처음에는 자료의 기숙사 출발 후보(919A동)
    setHome(dormOptions().some(([b]) => b === state.homeDorm) ? state.homeDorm : first);
  } else if (v === "other") {
    const opts = buildingOptions().map(([b]) => b);
    setHome(opts.includes(state.homeOther) ? state.homeOther : opts[0]);
  } else setHome(v);
});
$("home-select").addEventListener("change", (e) => setHome(e.target.value));
document.querySelector(".settings").addEventListener("change", (e) => {
  if (e.target.name !== "mode") return;
  cancelCompute();
  state.mode = e.target.value;
  store.set("mode", state.mode);
  state.result = null;
});

// ---------------------------------------------------------------- 시간표 만들기

function travelFor(mode) {
  if (!state.travel[mode]) state.travel[mode] = TravelMatrix.fromCampus(state.campus, mode);
  return state.travel[mode];
}

/** 시간·건물이 모두 같은 분반은 동선이 같으므로 하나로 묶어 탐색하고, 나머지는 '같은 시간·건물' 분반으로 보여 준다. */
function groupSections(sections) {
  const groups = new Map();
  for (const s of sections) {
    const sig = s.meetings.map((m) => `${m.day},${m.start},${m.end},${m.building}`).sort().join(";");
    if (!groups.has(sig)) groups.set(sig, { ...s, twins: [] });
    else groups.get(sig).twins.push(s);
  }
  return [...groups.values()];
}

/** 계산할 과목(켠 분반, 직접 넣은 강의실·시간 반영). 자료에 없는 과목은 빠진다. */
function collectCourses() {
  const courses = [], noSections = [];
  for (const p of state.picks) {
    const c = state.byId.get(p.id);
    if (!c) continue;
    const chosen = c.sections.filter((s) => !p.excluded.has(s.key)).map((s) => ({ ...s, meetings: effMeetings(s) }));
    if (!chosen.length) { noSections.push(c.id); continue; }
    courses.push({ ...c, sections: groupSections(chosen) });
  }
  return { courses, noSections };
}

const estimate = (courses) => courses.reduce((n, c) => n * c.sections.length, 1);

// ---------------------------------------------------------------- 탐색 워커
// 계산은 Web Worker(js/search-worker.js, 백엔드 몫)에서 돌려 화면이 멈추지 않게 한다. 워커를 못 쓰면 화면 스레드에서 돈다.
// 워커 → 화면: progress(0.2초마다), result, conflict(서로 겹쳐 조합을 막는 과목), error. 취소는 terminate 후 새 워커
let worker = null, workerHasCampus = false, workerBroken = false, searchId = 0, pending = null;
class Cancelled extends Error {}

function stopWorker() {
  if (worker) worker.terminate();
  worker = null;
  workerHasCampus = false;
}

function startWorker() {
  if (worker || workerBroken || typeof Worker === "undefined") return worker;
  try {
    worker = new Worker(new URL("./search-worker.js", import.meta.url), { type: "module" });
  } catch (e) {
    workerBroken = true;
    return null;
  }
  workerHasCampus = false;
  worker.onmessage = (e) => {
    const m = e.data || {};
    if (!pending || m.id !== pending.id) return;
    if (m.type === "progress") pending.onProgress(m.done, m.ms);
    else if (m.type === "result") settle({ ranked: m.ranked, stats: m.stats, total: m.total || null });
    else if (m.type === "conflict") settle({ ranked: [], conflict: m.courseIds || [] });
    else if (m.type === "error") settle(null, new Error(m.message));
  };
  worker.onerror = (e) => { // 워커 파일을 못 읽었거나 모듈 워커를 모르는 브라우저: 화면 스레드에서 다시
    e.preventDefault();
    workerBroken = true;
    stopWorker();
    const p = pending;
    pending = null;
    if (!p) return;
    if (p.opts.spare) p.reject(new Error("worker")); // 미리 찾던 것은 버린다(화면 스레드에서 돌리면 누르지도 않았는데 화면이 멈춘다)
    else runHere(p.courses, p.opts).then(p.resolve, p.reject);
  };
  return worker;
}

function settle(value, error) {
  const p = pending;
  pending = null;
  if (!p) return;
  if (error) p.reject(error); else p.resolve(value);
}

/** 화면 스레드에서 탐색(워커를 못 쓸 때). 전체 조합 수도 워커와 같게: 찾은 게 topK 보다 적으면 그게 전부다. count: false 면 다시 세지 않는다. */
function runHere(courses, { topK = TOP_K, home = state.home, mode = state.mode, count = true } = {}) {
  return new Promise((resolve) => {
    const res = search(courses, travelFor(mode), home, { topK });
    if (!res.ranked.length) { resolve({ ranked: [], conflict: findConflicts(courses) }); return; }
    res.total = res.ranked.length < topK ? { count: res.ranked.length, exact: true } : count ? countFeasible(courses) : null;
    resolve(res);
  });
}

/**
 * 탐색: {ranked, stats, total} 또는 조합이 없으면 {ranked: [], conflict: [과목 id]}. total = {count, exact}(전체 조합 수).
 * opts = {topK, home, mode, count, spare}. 더 찾기는 결과를 만든 조건(home·mode) 그대로 topK 만 키워 다시 부르고 전체 수는 다시 세지 않는다
 * (count: false. 달라는 것보다 적게 왔을 때만 total 이 온다). spare: 누르기 전에 미리 찾아 두는 탐색이라 워커가 없으면 하지 않는다.
 */
function compute(courses, onProgress, opts = {}) {
  const w = startWorker();
  if (!w) return opts.spare ? Promise.reject(new Error("worker")) : runHere(courses, opts);
  const { topK = TOP_K, home = state.home, mode = state.mode, count = true } = opts;
  return new Promise((resolve, reject) => {
    const id = ++searchId;
    pending = { id, courses, opts, resolve, reject, onProgress };
    const msg = { type: "search", id, courses, home, mode, topK };
    if (!count) msg.total = false;
    if (!workerHasCampus) { msg.campus = state.campus; workerHasCampus = true; }
    w.postMessage(msg);
  });
}

/** 계산 중이면 멈춘다(취소 버튼, 담은 과목·조건이 바뀜, 다른 화면으로 감). */
function cancelCompute() {
  const p = pending;
  if (!p) return;
  pending = null;
  stopWorker();
  p.reject(new Cancelled());
}

function updateRun() {
  if (!busy) $("run").disabled = !state.loaded || !state.picks.length;
}

/** 오류 줄을 띄운 뒤: 첫 오류로 스크롤하고 알림 영역으로 읽는다. */
function reportError(text) {
  const first = $("picked-list").querySelector(".c-error") || ($("picked-error").hidden ? null : $("picked-error"));
  if (first) first.scrollIntoView({ block: "center", behavior: reduceMotion.matches ? "auto" : "smooth" });
  announce(text, "alert");
}

let busy = false;
async function run() {
  if (busy || !state.loaded || !state.picks.length) return;
  clearErrors();
  const { courses: full, noSections } = collectCourses();
  state.errors.noSections = new Set(noSections);
  if (noSections.length) { renderPicked(); reportError("켠 분반이 없어요"); return; }
  if (!full.length) {
    state.errors.general = { text: "시간표를 만들 과목이 없어요" };
    renderPicked();
    reportError(state.errors.general.text);
    return;
  }
  renderPicked();
  // 워커에 보내는 것만 추린다(과목 id·이름·교과구분과 켠 분반)
  const courses = full.map((c) => ({ id: c.id, name: c.name, cls: c.cls, sections: c.sections }));
  busy = true;
  const btn = $("run"), cancel = $("cancel");
  btn.setAttribute("aria-disabled", "true"); // disabled 는 초점을 잃게 해서 쓰지 않는다. 두 번째 누름은 busy 로 무시한다
  let shownAt = 0, long = false;
  const label = (text) => btn.replaceChildren(h("span", { class: "spinner", "aria-hidden": "true" }), text);
  const showSpinner = () => {
    if (shownAt) return;
    shownAt = performance.now();
    label("만드는 중");
    announce("시간표 만드는 중");
  };
  // 10초를 넘을 것 같으면 진행 정도와 '취소'
  const onProgress = (done, ms) => {
    if (!shownAt) return;
    if (!long && (ms > 5000 || (ms > 1000 && (done > 0 ? ms / done : Infinity) > LONG_MS))) {
      long = true;
      cancel.hidden = false;
    }
    const pct = Math.min(99, Math.floor(done * 100));
    if (long && pct >= 1) label(`만드는 중 ${pct}%`);
  };
  let timer = null;
  if (!startWorker() && estimate(courses) > HEAVY) { showSpinner(); await nextPaint(); } else timer = setTimeout(showSpinner, 500);
  loadRoutes();
  let res = null, cancelled = false;
  try {
    res = await compute(courses, onProgress);
  } catch (e) {
    if (e instanceof Cancelled) cancelled = true;
    else console.error(e);
  }
  clearTimeout(timer);
  if (shownAt && !cancelled) { const left = 200 - (performance.now() - shownAt); if (left > 0) await sleep(left); } // 한번 뜬 스피너는 200ms 이상
  const hadFocus = cancel.contains(document.activeElement);
  cancel.hidden = true;
  btn.replaceChildren("시간표 만들기");
  btn.removeAttribute("aria-disabled");
  busy = false;
  updateRun();
  if (hadFocus) btn.focus({ preventScroll: true });
  if (cancelled) return;
  if (!res) {
    state.errors.general = { text: "시간표를 만들지 못했어요", retry: true };
    renderPicked();
    reportError(state.errors.general.text);
    return;
  }
  if (!res.ranked.length) {
    state.errors.overlap = new Set(res.conflict || []);
    state.errors.general = { text: "겹치지 않는 조합이 없어요" };
    renderPicked();
    reportError(state.errors.general.text);
    return;
  }
  showResult(res, full);
}

/** 조합 안의 분반을 담은 과목 차례로 놓는다(고른 카드의 분반 목록 순서). */
function sortSections(ranked, courses) {
  const order = new Map(courses.map((c, i) => [c.id, i]));
  for (const ev of ranked) ev.sections.sort((a, b) => order.get(a.courseId) - order.get(b.courseId));
}

function showResult(res, courses) {
  sortSections(res.ranked, courses);
  // ranked: 목록에 올린 조합(제목의 찾은 수). ahead: 찾아 뒀지만 아직 목록에 올리지 않은 다음 순위('더 찾기'를 눌러야 올린다).
  // full: 마지막 탐색이 달라는 만큼 다 왔다(그 뒤 순위가 더 있을 수 있다). 더 찾기는 아래 '순위'의 findMore
  state.result = { ranked: res.ranked, ahead: [], full: res.ranked.length >= TOP_K, total: res.total || null, courses, home: state.home, mode: state.mode,
    days: weekDays(res.ranked), axis: hourRange(res.ranked) };
  rankMore.failed = rankMore.held = false;
  state.rank = 0;
  state.day = firstDay(res.ranked[0]);
  state.ranksShown = RANKS_STEP;
  state.reveal = true;
  // 이벤트 테마 기간에 처음 시간표를 만든 사람에게는 그 해에 묻지 않는다(10/3 밤 디자인: 기본 테마를 써 본 적이 없어 '돌아갈' 곳이 없다.
  // 정보 화면의 '테마' 행으로는 바꿀 수 있고 다음 해에는 묻는다)
  if (themeOn() && !store.get("made", false)) store.set("themeAsked", season.event);
  store.set("made", true);
  updateInstall();
  go("result");
  // 성공 햅틱은 iOS 앱에서만(디자인 규칙 '햅틱': 안드로이드는 아직 없음. 정하면 조건만 넓힌다)
  if (SHELL === "ios") capacitor?.Plugins?.Haptics?.notification?.({ type: "SUCCESS" })?.catch?.(() => null);
}

// ---------------------------------------------------------------- 결과 화면

const currentEv = () => state.result.ranked[state.rank];

/** 찾아 둔 것(목록에 올린 것 + ahead) 뒤로 조합이 더 있나. 전체 수를 알면 그 수와 견주고, 다 못 센 큰 묶음이거나 수를 모르면(예전 워커)
 *  마지막 탐색이 달라는 만큼 다 왔을 때다. */
const moreBeyond = (R) => (R.total && R.total.exact ? R.total.count > R.ranked.length + R.ahead.length : R.full);
/** 목록에 올리지 않은 조합이 남았나(목록 아래의 '더 찾기', 제목의 '걷는 시간이 짧은 …'). */
const hasMore = (R) => R.ahead.length > 0 || moreBeyond(R);
/** 목록 제목의 큰 덩이(더 찾은 뒤에는 알림 영역도 이 문장을 읽는다). 찾은 수는 목록에 올린 수이고 쉼표만 찍는다('1,020개'). */
const foundText = (R) => `${hasMore(R) ? "걷는 시간이 짧은" : "전체 조합"} ${R.ranked.length.toLocaleString("ko-KR")}개를 찾았어요`;

function firstDay(ev) {
  const days = ev ? Object.keys(ev.days).map(Number) : [];
  return days.length ? Math.min(...days) : 0;
}

/** 요일 탭: 월–금, 토·일 수업이 있으면 그날까지. */
function weekDays(ranked) {
  const used = new Set([0, 1, 2, 3, 4]);
  for (const ev of ranked) for (const d of Object.keys(ev.days)) used.add(Number(d));
  return [...used].sort((a, b) => a - b);
}

/** 시간 축: 찾은 조합들의 한 주 전체에서 가장 이른 정시부터 가장 늦은 정시까지(요일·순위를 바꿔도 움직이지 않는다). 너무 좁으면 네 시간. */
function hourRange(ranked) {
  let lo = Infinity, hi = -Infinity;
  for (const ev of ranked) for (const ms of Object.values(ev.days)) for (const m of ms) { lo = Math.min(lo, m.start); hi = Math.max(hi, m.end); }
  if (!Number.isFinite(lo)) return [9, 18];
  let h0 = Math.floor(lo / 60), h1 = Math.ceil(hi / 60);
  if (h1 - h0 < 4) { h1 = Math.min(24, h0 + 4); h0 = Math.max(0, h1 - 4); }
  return [h0, h1];
}

const lateOf = (l) => (l.slack !== null && l.slack < 0 ? Math.max(0, Math.round(-l.slack)) : 0); // 수치는 반올림한 정수 분

/**
 * 늦는 수업 요약(가이드 형식 '분 + 늦음'). 늦는 분을 더한 합은 뜻이 없어 쓰지 않고(10/1 사용자) 수업마다의 분을 쓴다(10/1 밤 사용자 결정).
 * 한 주(후보 카드)는 같은 분끼리 요일을 묶어 '월수 2분·목 5분 늦음'(요일 글자는 '월화수목 등교'처럼 붙여 쓴다). 같은 요일들에서 늦는
 * 분이 둘이면 요일을 한 번만: '화목 11분·17분 늦음'. 하루(하루 요약 태그)는 그날 늦는 분을 시각 순서로 '2분·5분 늦음'.
 * 늦는 수업이 없으면 ''.
 */
function lateText(legs, withDays) {
  const mins = new Map(); // 분 → 요일(처음 나온 순서). legs 는 요일·시각 순서
  for (const l of legs) {
    const m = lateOf(l);
    if (!m) continue;
    if (!mins.has(m)) mins.set(m, []);
    if (!mins.get(m).includes(l.day)) mins.get(m).push(l.day);
  }
  if (!mins.size) return "";
  if (!withDays) return `${[...mins.keys()].map((m) => `${m}분`).join("·")} 늦음`;
  const byDays = new Map(); // '화목' → [11, 17]
  for (const [m, ds] of mins) {
    const k = ds.map((d) => DAY_KO[d]).join("");
    if (!byDays.has(k)) byDays.set(k, []);
    byDays.get(k).push(m);
  }
  return `${[...byDays].map(([k, ms]) => `${k} ${ms.map((m) => `${m}분`).join("·")}`).join("·")} 늦음`;
}

// 조합 수의 단위: 만 → 억 → 조 → 경(수는 Number 라 9천조쯤부터는 어림값이다)
const COUNT_UNITS = [[1e4, "만"], [1e8, "억"], [1e12, "조"], [1e16, "경"]];

/** 전체 조합 수: 1만 아래는 쉼표('1,234개'), 1만부터는 만 단위 소수 한 자리('2.4만 개', '5.3만 개'), 딱 떨어지면 소수 없이('2만 개').
 *  단위 앞 수가 100 이상이면 소수 없이('142만 개', '1,421만 개'. '1,421.3만 개'는 자리가 넘친다). 1억부터는 억, 1조부터는 조('1.2억 개').
 *  반올림한다(10/3 사용자: 만이 넘어가는 순간부터 2.4만, 5.3만처럼. 딱 떨어지면 2만 개). */
function countLabel(n) {
  if (n < 10000) return `${n.toLocaleString("ko-KR")}개`;
  const num = (x) => x.toLocaleString("ko-KR", { maximumFractionDigits: 1 }); // 2.4 → '2.4', 2 → '2', 1421 → '1,421'
  for (let i = 0; i < COUNT_UNITS.length; i++) {
    const [u, name] = COUNT_UNITS[i];
    const one = Math.round(n / (u / 10)) / 10; // 소수 한 자리
    if (one < 100) return `${num(one)}${name} 개`;
    const whole = Math.round(n / u);
    if (whole < 10000 || i === COUNT_UNITS.length - 1) return `${num(whole)}${name} 개`; // 반올림해 1만이 되면 다음 단위로('1억 개')
  }
  return "";
}

/** 앞자리 하나만 남기고 내린 수(100 아래는 그대로): 456 → 400, 345678 → 300000. */
function roughFloor(n) {
  if (n < 100) return n;
  let lead = 1;
  while (lead * 10 <= n) lead *= 10;
  return Math.floor(n / lead) * lead;
}

/** 다 못 센 조합 수(실제는 그보다 많다)의 어림수: 앞자리 하나만 남기고 내린다(뒤에 '가 넘는'이 붙으니 올리면 틀린 말이 된다).
 *  456 → '400개', 3456 → '3천 개', 10000 → '1만 개', 345678 → '30만 개', 1900000 → '100만 개', 23000000 → '2천만 개', 120000000 → '1억 개',
 *  3.4조 → '3조 개'. 어디까지 세었는지는 기기 속도에 따라 달라서(시간 제한) 소수 자리까지 쓰지 않는다. */
function roughCount(n) {
  const v = roughFloor(n);
  if (v < 1000) return `${v}개`;
  if (v < 10000) return `${v / 1000}천 개`;
  let [u, name] = COUNT_UNITS[0];
  for (const [u2, name2] of COUNT_UNITS) if (v >= u2) [u, name] = [u2, name2];
  const k = Math.round(v / u); // 1~9000(경은 그 위로도)
  return `${k < 1000 ? k : k < 10000 ? `${k / 1000}천` : k.toLocaleString("ko-KR")}${name} 개`;
}

/**
 * 목록 제목: 희미한 '(전체 조합 1,234개 중)' + '걷는 시간이 짧은 20개를 찾았어요'. 찾은 수는 목록에 올린 수라 '더 찾기'로 찾은 만큼 는다('40개').
 * 찾은 것이 전부면(처음부터든 더 찾아서든) '전체 조합 4개를 찾았어요' 하나.
 * total 은 워커가 센 겹치지 않는 조합 수(같은 시간·건물 분반은 하나라 찾은 수와 단위가 같다). 1만부터는 '(전체 조합 2.4만 개 중)'.
 * exact=false 면 그보다 많다는 뜻이라 어림수로 '(1만 개가 넘는 조합 중)'. total 이 없으면(예전 워커) 희미한 부분 없이.
 */
function rankTitle(R) {
  const m = R.ranked.length, t = R.total;
  if (!hasMore(R)) return [foundText(R)];
  const found = h("span", { class: "rank-found" }, foundText(R));
  if (!t || (!t.exact && roughFloor(t.count) <= m)) return [found]; // 다 못 센 수의 어림수가 찾은 수보다 크지 않으면 알려 주는 것이 없다
  const n = Math.max(t.count, m);
  const all = t.exact ? `전체 조합 ${countLabel(n)}` : `${roughCount(n)}가 넘는 조합`;
  return [h("span", { class: "rank-total" }, `(${all} 중)`), " ", found];
}

function renderResult() {
  const R = state.result;
  if (!R) return;
  $("rank-count").replaceChildren(...rankTitle(R));
  // 결과 화면에서 기숙사 동을 밝히는 곳은 이 줄뿐이다: '출발·도착 기숙사 906동 · 경사 반영'(번호표·파선 견본·핀 이름은 어느 동이든 '기숙사')
  $("rank-cond").textContent = `출발·도착 ${isDorm(R.home) ? `기숙사 ${buildingLabel(R.home)}` : placeLabel(R.home)} · ${R.mode === "slope" ? "경사 반영" : "평지"}`;
  $("daytabs").replaceChildren(...R.days.map((d) => h("button", { type: "button", role: "tab", id: `tab-${d}`, "data-day": String(d), "aria-controls": "day-panel" }, DAY_KO[d])));
  updateTabs();
  renderDay({ reveal: state.reveal });
  state.reveal = false;
  renderRanks();
}

function updateTabs() {
  const ev = currentEv();
  for (const b of $("daytabs").children) {
    const d = Number(b.dataset.day);
    const on = d === state.day;
    b.setAttribute("aria-selected", String(on));
    b.tabIndex = on ? 0 : -1;
    b.setAttribute("aria-label", ev.days[d] ? `${DAY_KO[d]}요일` : `${DAY_KO[d]}요일, 수업 없음`);
  }
  $("day-panel").setAttribute("aria-labelledby", `tab-${state.day}`);
}

function selectDay(d) {
  if (d === state.day) return;
  state.day = d;
  updateTabs();
  renderDay({ fade: true });
}

$("daytabs").addEventListener("click", (e) => {
  const b = e.target.closest("[data-day]");
  if (b) selectDay(Number(b.dataset.day));
});
$("daytabs").addEventListener("keydown", (e) => {
  const tabs = [...$("daytabs").children];
  const i = tabs.findIndex((b) => Number(b.dataset.day) === state.day);
  const j = { ArrowRight: (i + 1) % tabs.length, ArrowLeft: (i - 1 + tabs.length) % tabs.length, Home: 0, End: tabs.length - 1 }[e.key];
  if (j === undefined) return;
  e.preventDefault();
  selectDay(Number(tabs[j].dataset.day));
  tabs[j].focus();
});

const drawnSize = new WeakMap(); // 요소 → 그릴 때의 [폭, 높이]
function remember(el) {
  const r = el.getBoundingClientRect();
  drawnSize.set(el, [r.width, r.height]);
}

function renderDay({ reveal = false, fade = false } = {}) {
  const gridPx = sizeTimetable(); // 칸 높이를 먼저 정하고 그 크기를 기억한다(그린 뒤에 길어지면 ResizeObserver 가 다시 그려 첫 결과의 경로 그리기를 끊는다)
  remember($("panes"));
  const ev = currentEv();
  renderTimetable(ev, state.day, gridPx);
  if (!maps.small) maps.small = makeMap($("map"), false);
  if (maps.small) renderMap(maps.small, ev, state.day, { reveal });
  renderSummary(ev, state.day);
  if (fade && !reduceMotion.matches) { // 시간표와 경로는 150ms 교차 페이드
    const p = $("panes");
    p.classList.remove("is-fading");
    void p.offsetWidth;
    p.classList.add("is-fading");
  }
}

const remPx = () => parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;

/** 시간표 높이(px). 한 시간은 tt-hour-min(32px, 글자 크기 설정만큼 더) 이상이다(10/2 사용자: "75분 수업에서 폰트 줄이는 건 용납을
 *  못하겠다. 통일성이 떨어지는 것 같음"): 75분 칸(40px - 사이 2px)에 과목명 한 줄(14px)과 강의실 줄이 늘 들어가고, 50분 칸(약 25px)에도
 *  과목명이 14px 그대로 한 줄 들어간다. 기본 높이(--tt-h: 폰 19.75rem = 316px, 840px부터 26.25rem = 420px)로 모자라면(저녁 수업으로 축이 긴 결과)
 *  시간표가 그만큼 길어지고, 늘어난 만큼을 .panes 의 --tt-extra 로 주어 옆의 지도 칸도 같이 길어진다(style.css).
 *  기본 높이도 글자 크기를 따라간다(10/3 디자인: --tt-h 는 rem. px 로 두면 글자를 키울 때 번호표·출처만 커져 지도가 줄어든다).
 *  축은 결과 전체(hourRange)라서 요일·후보를 바꿔도 높이가 그대로다. */
function sizeTimetable() {
  const cs = getComputedStyle(document.documentElement);
  const rem = remPx();
  const tth = cs.getPropertyValue("--tt-h").trim(); // '19.75rem'
  const base = Math.round(parseFloat(tth) * (tth.endsWith("rem") ? rem : 1) * 100) / 100 || 316;
  const hourMin = parseFloat(cs.getPropertyValue("--tt-hour-min")) || 32;
  const [h0, h1] = state.result.axis;
  const px = Math.max(base, Math.ceil((h1 - h0) * hourMin * (rem / 16)));
  $("panes").style.setProperty("--tt-extra", `${px - base}px`);
  return px;
}

/** 늦는 까닭: 걷는 시간과 쉬는 시간(강의실 미정 수업 앞뒤 쉬는 시간 포함). */
function lateWhy(l) {
  return `${placeLabel(l.from)}에서 ${buildingLabel(l.to)}까지 걷기 ${Math.round(l.minutes)}분, 쉬는 시간 ${Math.round(l.slack + l.minutes)}분`;
}

/** 칸 하나: 교과구분 연한 색 바탕에 과목명(부제 괄호 뺀 것)과 강의실, 늦으면 빨간 'N분 늦음'. */
function renderTimetable(ev, day, gridPx) {
  const box = $("tt");
  if (!(ev.days[day] || []).length) { box.replaceChildren(h("p", { class: "tt-empty" }, "수업 없음")); return; }
  const [h0, h1] = state.result.axis;
  const span = (h1 - h0) * 60;
  const k = remPx() / 16; // 글자 크기 설정만큼 줄 높이도 커진다
  const top = (m) => `${((m - h0 * 60) / span) * 100}%`;
  const hours = h("div", { class: "tt-hours", "aria-hidden": "true" });
  const grid = h("ol", { class: "tt-grid" });
  const step = h1 - h0 > 10 ? 2 : 1;
  for (let x = h0; x <= h1; x++) {
    grid.append(h("li", { class: "tt-line", "aria-hidden": "true", style: { top: top(x * 60) } }));
    if ((x - h0) % step === 0) hours.append(h("span", { style: { top: top(x * 60) } }, String(x)));
  }
  box.replaceChildren(hours, grid);
  const textW = grid.clientWidth - 16; // 칸 안 글자 폭(좌우 여백 8)
  const family = getComputedStyle(grid).fontFamily;
  const titleFont = `500 ${14 * k}px ${family}`, labelFont = `500 ${12 * k}px ${family}`; // t-block, t-label
  const widthOf = (text, font = labelFont) => { canvas.font = font; return canvas.measureText(text).width; };
  const legs = ev.legs.filter((l) => l.day === day);
  let n = 0;
  legs.forEach((l, i) => {
    const m = l.meeting;
    if (!m) return;
    n += 1; // 지도 번호와 같은 순서
    const late = lateOf(l);
    const heightPct = ((m.end - m.start) / span) * 100;
    const px = (heightPct / 100) * gridPx;
    // 강의실은 늘 보이고(10/2 사용자: '동이 왜 안 뜨지? 공간이 없으면 나란히 배치해서라도') 과목명은 어느 칸이나 14px 다(10/2 사용자:
    // 75분 칸만 글자가 작아지면 통일성이 떨어진다. 그래서 한 시간이 32px 이상, sizeTimetable).
    // 쌓는 칸(38px 이상, 75분 이상 수업): 강의실 줄을 늘 두고 과목명은 남는 줄 수만큼(1–3줄, 넘치면 마지막 줄에 말줄임). 과목명 한 줄 +
    // 강의실 줄(34)이 겨우 들어가는 칸(38–40px)은 위아래 여백을 줄여 쓴다.
    // 낮은 칸(38px 미만, 50분 수업): 한 줄에 과목명과 강의실을 나란히(사이 8px, 가운뎃점 없이 크기·색으로 가른다). 넘치면 과목명이 먼저
    // 세 글자 + … 까지 줄고, 그래도 안 들어가면 호수를 빼고 건물만 '43-1동'
    const short = px < 38 * k;
    const title = shortName(m.section.name);
    const need = Math.min(3, textLines(title, titleFont, textW));
    const rooms = [roomLabel(m)];
    if (m.building && rooms[0] !== buildingLabel(m.building)) rooms.push(buildingLabel(m.building));
    const fit = (avail) => {
      const lines = Math.max(1, Math.min(3, Math.floor((avail + 2 - 16 * k) / (18 * k))));
      return { lines, used: Math.min(lines, need) * 18 * k + 16 * k };
    };
    // 늦음 알약은 오른쪽 위. 과목명 첫 줄 옆에 들어가거나(넓은 칸) 가운데 놓인 글이 알약 아래에서 시작하면(높은 칸) 그대로 두고,
    // 둘 다 아니면 과목명 위에 알약 줄을 따로 둔다(과목명이 한 줄 밀린다). 낮은 칸은 한 줄의 오른쪽 끝(글은 알약 앞에서 끝난다)
    let lateRow = 0, pillW = 0;
    if (late) {
      canvas.font = `700 ${12 * k}px ${getComputedStyle(grid).fontFamily}`;
      pillW = canvas.measureText(`${late}분 늦음`).width + 12;
    }
    if (late && !short) {
      const beside = firstLineWidth(title, titleFont, textW) + pillW + 4 <= textW;
      const below = (px - 6 - fit(px - 6).used) / 2 >= 16 * k + 2;
      if (!beside && !below) lateRow = 18 * k;
    }
    // 글 자리(10/2 디자인 '시간표'의 순서). 한 줄에 나란히 둘 때는 캔버스로 잰 폭에 1px 여유를 둔다: 강의실은 줄이지 않으므로(flex: none)
    // 0.1px 만 모자라도 과목명 끝 글자가 … 로 바뀐다
    let room = rooms[0], roomTop = false, pillRow = false, roomOnly = false, lines = 1;
    const gap = 8 * k + 1, tW = widthOf(title, titleFont);
    let head = "", count = 0;
    for (const ch of title) { head += ch; if (ch.trim() && ++count >= 3) break; }
    const minT = Math.min(tW, widthOf(`${head}…`, titleFont)); // 과목명은 세 글자 + … 까지만 줄인다(그 아래로 자르면 읽히지 않는다)
    const roomBeside = (rowW) => rooms.find((r) => tW + gap + widthOf(r) <= rowW) || rooms.find((r) => minT + gap + widthOf(r) <= rowW) || "";
    if (short) {
      // 낮은 칸: 과목명(14px 그대로) 옆에 강의실, 늦으면 줄 끝에 알약(글은 알약 앞에서 끝난다).
      // 알약 옆에 과목명 세 글자와 강의실이 안 들어가면 과목명만, 과목명 세 글자도 안 들어가면 과목명 대신 강의실
      const rowW = textW - (late ? pillW + 6 : 0);
      room = roomBeside(rowW);
      if (!room && minT > rowW) { room = rooms.find((r) => widthOf(r) + 1 <= rowW) || ""; roomOnly = !!room; }
    } else if (lateRow && px - 4 - lateRow < 34 * k) {
      // 알약 줄 밑에 과목명과 강의실 줄이 다 안 들어가는 75분 칸: 강의실을 알약 줄 왼쪽에(비어 있던 자리), 과목명은 그 아래
      room = rooms.find((r) => widthOf(r) + 1 <= textW - pillW - 6) || "";
      if (room) {
        roomTop = true;
        lines = Math.max(1, Math.min(3, Math.floor((px - 6 - lateRow) / (18 * k))));
      } else {
        // 좁은 칸(폰 360)은 알약 옆에 건물 이름도 안 들어간다: 알약 줄은 알약만, 그 아래 줄에 과목명과 강의실을 나란히(낮은 칸처럼)
        pillRow = true;
        room = roomBeside(textW);
      }
    } else ({ lines } = fit(px - 6 - lateRow));
    const cls = state.byId.get(m.section.courseId)?.cls || "";
    const nx = legs[i + 1];
    let next = "";
    if (m.building && nx) {
      if (nx.meeting && nx.meeting.building) next = `다음 수업까지 걷기 ${Math.round(nx.minutes)}분`;
      else if (!nx.meeting) next = `${placeLabel(state.result.home)}까지 걷기 ${Math.round(nx.minutes)}분`;
    }
    const said = [`${n}. ${hm(m.start)}~${hm(m.end)} ${m.section.name}`, roomLabel(m), late ? `${late}분 늦음(${lateWhy(l)})` : "", next].filter(Boolean).join(", ");
    grid.append(h("li", {
      class: `tt-block${short ? " short" : ""}${roomTop ? " room-top" : pillRow ? " is-late pill-row" : lateRow ? " is-late" : ""}`,
      style: { top: top(m.start), height: `calc(${heightPct}% - 2px)`, background: clsFill(cls), "--lines": String(lines),
        ...(late && (short || roomTop) ? { "--late-w": `${Math.ceil(pillW + 6)}px` } : {}) }, // 알약과 같은 줄의 글은 알약 앞에서 끝난다
      title: `${m.section.name} ${hm(m.start)}~${hm(m.end)} ${roomLabel(m)}`,
    },
    h("span", { class: "sr-only" }, said),
    late ? h("span", { class: "tt-late", "aria-hidden": "true", title: lateWhy(l) }, `${late}분 늦음`) : null,
    ...(pillRow ? [h("span", { class: "b-line", "aria-hidden": "true" }, h("span", { class: "b-title" }, title), room ? h("span", { class: "b-room" }, room) : null)]
      : [roomOnly ? null : h("span", { class: "b-title", "aria-hidden": "true" }, title), room ? h("span", { class: "b-room", "aria-hidden": "true" }, room) : null])));
  });
}

/** 첫 줄의 폭 어림(textLines 와 같은 방식으로 줄을 바꾼다). */
function firstLineWidth(text, font, width) {
  canvas.font = font;
  const space = canvas.measureText(" ").width;
  let cur = 0;
  for (const word of String(text).split(/\s+/).filter(Boolean)) {
    const w = canvas.measureText(word).width;
    if (!cur) { if (w >= width) return width; cur = w; continue; }
    if (cur + space + w > width) break;
    cur += space + w;
  }
  return cur;
}

/** 글자가 폭 안에서 몇 줄이 되는지 어림한다(띄어쓰기에서 줄을 바꾸고, 폭보다 긴 낱말은 쪼갠다). */
function textLines(text, font, width) {
  if (!(width > 0)) return 1;
  canvas.font = font;
  const space = canvas.measureText(" ").width;
  let lines = 1, cur = 0;
  for (const word of String(text).split(/\s+/).filter(Boolean)) {
    const w = canvas.measureText(word).width;
    if (cur && cur + space + w <= width) { cur += space + w; continue; }
    if (cur) lines += 1;
    lines += Math.floor(w / width);
    cur = w % width;
  }
  return lines;
}

function renderSummary(ev, day) {
  const box = $("day-summary");
  if (!ev.days[day]) { box.replaceChildren(); return; }
  const legs = ev.legs.filter((l) => l.day === day);
  const walk = Math.round(legs.reduce((s, l) => s + l.minutes, 0));
  const late = lateText(legs, false); // '2분 늦음', 그날 둘이면 '2분·5분 늦음'(더한 값은 쓰지 않는다)
  box.replaceChildren(...[h("span", {}, "걷기 ", h("b", {}, `${walk}분`)),
    late ? h("span", { class: "tag danger" }, h("span", { class: "sr-only" }, ", "), late) : null].filter(Boolean));
}

// ---------------------------------------------------------------- 지도

const maps = { small: null, full: null };
let campusBounds = null;

function coordOf(b) {
  const v = state.campus.buildings[b];
  return v && v[1] !== null && v[1] !== undefined ? [v[1], v[2]] : null;
}

// ---------------------------------------------------------------- 바탕 지도
// 10/1 사용자 결정: OSM 타일 대신 우리 자료(data/basemap.json: 수치지형도 1:5,000 건물·도로·물·등고선 + OSM 숲·길)로 직접 그린다
// (자료 형식은 레포 docs/basemap.md, 그리는 법은 이 절이 기준). 타일 서버를 안 써서 오프라인에서도 바탕이 있고, 다크 모드는 필터가 아니라
// 지도 색(--map-*)으로 그린다. 면·선은 처음 한 번 메르카토르 좌표(0~1)로 풀어 두고, 캔버스 하나에 화면에 걸리는 것만 그린다

let basemap = null, basemapWait = null, dataBounds = null;

/** Google polyline(소수 prec 자리) → [u, v, u, v, …] 메르카토르 좌표(0~1, Leaflet 화소 좌표 = 값 × 256 × 2^배율). */
function decodeWorld(s, prec) {
  const f = 10 ** prec, out = [];
  let i = 0, lat = 0, lon = 0;
  while (i < s.length) {
    for (let k = 0; k < 2; k++) {
      let sh = 0, r = 0, b;
      do { b = s.charCodeAt(i++) - 63; r |= (b & 31) << sh; sh += 5; } while (b >= 32);
      const d = r & 1 ? ~(r >> 1) : r >> 1;
      if (k === 0) lat += d; else lon += d;
    }
    const phi = ((lat / f) * Math.PI) / 180;
    out.push((lon / f + 180) / 360, (1 - Math.log(Math.tan(Math.PI / 4 + phi / 2)) / Math.PI) / 2);
  }
  return Float64Array.from(out);
}

function boxOf(arrays) {
  let x0 = 1, y0 = 1, x1 = 0, y1 = 0;
  for (const a of arrays) {
    for (let i = 0; i < a.length; i += 2) {
      if (a[i] < x0) x0 = a[i];
      if (a[i] > x1) x1 = a[i];
      if (a[i + 1] < y0) y0 = a[i + 1];
      if (a[i + 1] > y1) y1 = a[i + 1];
    }
  }
  return [x0, y0, x1, y1];
}

/** 자료 v1: 면 = [소수 자리, 바깥 고리, 구멍…], 선 = [OSM highway, polyline], 등고선 = [높이 m, polyline]. */
function prepareBasemap(B) {
  const areas = {}, lines = {}, contours = {};
  for (const [k, list] of Object.entries(B.area || {})) {
    areas[k] = list.map(([prec, ...rings]) => { const rs = rings.map((r) => decodeWorld(r, prec)); return { rings: rs, bb: boxOf(rs) }; });
  }
  for (const [k, list] of Object.entries(B.line || {})) lines[k] = list.map(([kind, s]) => { const p = decodeWorld(s, 5); return { kind, pts: p, bb: boxOf([p]) }; });
  // 보행로는 캠퍼스 안 길(footway 등)과 산길(path·track, 거의 다 캠퍼스 밖)로 나눠 보이는 배율을 다르게 한다
  const trail = (f) => f.kind === "path" || f.kind === "track";
  lines.trail = (lines.walk || []).filter(trail);
  lines.foot = (lines.walk || []).filter((f) => !trail(f));
  for (const [k, list] of Object.entries(B.contour || {})) contours[k] = list.map(([z, s]) => { const p = decodeWorld(s, 5); return { z, pts: p, bb: boxOf([p]) }; });
  const [south, west, north, east] = B.bounds;
  return { areas, lines, contours, bounds: L.latLngBounds([south, west], [north, east]) };
}

/** 처음 지도를 만들 때 한 번 받는다(웹은 서비스 워커가 저장, 앱은 앱에 넣은 것). 실패하면 다음에 다시. */
function loadBasemap() {
  if (!basemapWait) {
    basemapWait = getJson("data/basemap.json").then((B) => {
      basemap = prepareBasemap(B);
      dataBounds = basemap.bounds;
      for (const mp of [maps.small, maps.full]) {
        if (!mp) continue;
        mp.map.setMaxBounds(dataBounds);
        applyMinZoom(mp.map);
        mp.base.redraw();
      }
    }).catch(() => { basemapWait = null; });
  }
  return basemapWait;
}

/** 빈 땅이 보이지 않게(사용자 결정): 캠퍼스가 다 들어오는 배율과, 화면이 자료 범위 안에 드는 배율 중 큰 쪽보다 덜 축소하지 않는다.
 *  캠퍼스는 가장자리 MIN_ZOOM_EDGE 를 비우고 들어와야 한다(핀 자리): 폰의 좁고 긴 지도에서 캠퍼스 끝에서 끝까지 걷는 날도 핀이 잘리지 않게 맞출 수 있다. */
const MIN_ZOOM_EDGE = 20;
function mapMinZoom(map) {
  const fit = map.getBoundsZoom(campusBounds, false, L.point(2 * MIN_ZOOM_EDGE, 2 * MIN_ZOOM_EDGE));
  return dataBounds ? Math.max(fit, map.getBoundsZoom(dataBounds, true)) : Math.max(12, fit);
}
/** 최소 배율을 바꾼다. setMinZoom 은 지금 배율이 더 낮으면 애니메이션으로 확대하는데, 그사이 setView 로 옮겨도
 *  애니메이션이 끝나는 순간 그 자리로 되돌아간다(전체 화면 지도가 경로 대신 최소 배율로 열렸다). 그래서 애니메이션 없이 */
function applyMinZoom(map) {
  // getBoundsZoom 은 지금 최소 배율보다 낮게 답하지 않는다. 지도 칸이 낮아진 날(번호표가 길거나 시간표가 짧은 날)에 앞 요일의 값에 묶이지 않게 먼저 푼다
  map.options.minZoom = 0;
  const mz = mapMinZoom(map);
  map.options.minZoom = mz;
  if (map.getZoom() < mz) map.setZoom(mz, { animate: false });
  map.fire("zoomlevelschange");
}

// 지도 색은 디자인 토큰 map-*(style.css)에서 읽는다. 기기 테마가 바뀌면 다시 읽고 다시 그린다.
// 10/2 토큰을 정하며 찻길·보행자 길 양옆 테두리(예전 road-case·ped-case)는 road-line·ped-line 으로 합쳤다
const MAP_COLORS = ["land", "green", "park", "grass", "pitch", "campus", "campus-line", "contour", "contour-index", "contour-label", "water", "walk-area",
  "road", "road-line", "road-secondary", "road-secondary-line", "road-primary", "road-primary-line", "road-trunk", "road-trunk-line",
  "ped", "ped-line", "foot", "steps", "building", "building-line", "halo"];
let mapColorCache = null;
function mapColors() {
  if (!mapColorCache) {
    const cs = getComputedStyle(document.documentElement);
    mapColorCache = Object.fromEntries(MAP_COLORS.map((k) => [k, cs.getPropertyValue(`--map-${k}`).trim()]));
    mapColorCache.font = getComputedStyle(document.body).fontFamily;
  }
  return mapColorCache;
}
matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => {
  mapColorCache = null;
  for (const mp of [maps.small, maps.full]) if (mp) mp.base.redraw();
});

// 선 폭은 미터로 정하고 배율마다 화소로 바꾼다(최소 화소 아래로는 가늘어지지 않는다). 캠퍼스 안 찻길 폭(m)은 OSM highway 값으로
const ROAD_M = { service: 4.5, residential: 6, living_street: 5, unclassified: 6, tertiary: 7, tertiary_link: 6 };

/** 바탕을 그린다. b = 캔버스가 덮는 범위(layer 좌표), m = 화소 배수. 순서: 땅 → 등고선 → 물 → 도로면 → 길(선) → 건물 → 등고선 높이.
 *  보행로·계단은 처음 시안의 주황 점선 대신 옅은 회색 점·사다리로, 확대했을 때만(10/1 사용자: 주황 점선이 너무 많아 시선을 빼앗는다).
 *  산길은 15부터, 캠퍼스 안 보행로는 15.5부터, 계단은 16.25부터. 경로선(파랑)이 지도에서 가장 눈에 띄게 */
function drawBasemap(ctx, map, b, m) {
  const size = b.getSize(), C = mapColors();
  ctx.setTransform(m, 0, 0, m, 0, 0);
  ctx.globalAlpha = 1;
  ctx.setLineDash([]);
  ctx.fillStyle = C.land;
  ctx.fillRect(0, 0, size.x, size.y);
  if (!basemap) return;
  const z = map.getZoom(), S = 256 * 2 ** z, o = map.getPixelOrigin();
  const ox = o.x + b.min.x, oy = o.y + b.min.y;
  const k = (156543.034 * Math.cos((map.getCenter().lat * Math.PI) / 180)) / 2 ** z; // 화소 하나가 몇 m
  const pad = 12 / S;
  const x0 = ox / S - pad, y0 = oy / S - pad, x1 = (ox + size.x) / S + pad, y1 = (oy + size.y) / S + pad;
  const seen = (f) => f.bb[2] >= x0 && f.bb[0] <= x1 && f.bb[3] >= y0 && f.bb[1] <= y1;
  const trace = (p, close) => {
    ctx.moveTo(p[0] * S - ox, p[1] * S - oy);
    for (let i = 2; i < p.length; i += 2) ctx.lineTo(p[i] * S - ox, p[i + 1] * S - oy);
    if (close) ctx.closePath();
  };
  const fill = (list, color, line, width) => {
    if (!list) return;
    ctx.fillStyle = color;
    if (line) { ctx.strokeStyle = line; ctx.lineWidth = width; ctx.lineJoin = "round"; }
    for (const f of list) {
      if (!seen(f)) continue;
      ctx.beginPath();
      for (const r of f.rings) trace(r, true);
      ctx.fill("evenodd");
      if (line) ctx.stroke();
    }
  };
  // 폭이 같은 선끼리 한 번에 긋는다(점선은 선마다 처음부터)
  const stroke = (list, color, width, { dash = null, cap = "round", alpha = 1 } = {}) => {
    if (!list || !(alpha > 0)) return;
    ctx.strokeStyle = color;
    ctx.globalAlpha = alpha;
    ctx.lineCap = cap;
    ctx.lineJoin = "round";
    ctx.setLineDash(dash || []);
    let cur = -1;
    for (const f of list) {
      if (!seen(f)) continue;
      const w = typeof width === "function" ? width(f) : width;
      if (w !== cur) {
        if (cur >= 0) ctx.stroke();
        ctx.beginPath();
        ctx.lineWidth = cur = w;
      }
      trace(f.pts, false);
    }
    if (cur >= 0) ctx.stroke();
    ctx.globalAlpha = 1;
    ctx.setLineDash([]);
  };
  const px = (meters, min, extra = 0) => Math.max(min, meters / k) + extra;
  const { areas: A, lines: Ln, contours: Z } = basemap;
  fill(A.green, C.green);
  fill(A.park, C.park);
  fill(A.grass, C.grass);
  fill(A.campus, C.campus, C["campus-line"], 1.2);
  fill(A.pitch, C.pitch);
  if (z >= 15.75) stroke(Z.minor, C.contour, 0.7);
  stroke(Z.index, C["contour-index"], 1.1);
  fill(A.water, C.water);
  fill(A.walk, C["walk-area"]);
  fill(A.road, C.road, C["road-line"], 0.9);
  for (const t of ["secondary", "primary", "trunk"]) fill(A[`road_${t}`], C[`road-${t}`], C[`road-${t}-line`], 0.9);
  const roadW = (f) => ROAD_M[f.kind] || 5;
  stroke(Ln.road, C["road-line"], (f) => px(roadW(f), 2.6, 2));
  stroke(Ln.pedestrian, C["ped-line"], px(5, 2.6, 2));
  stroke(Ln.road, C.road, (f) => px(roadW(f), 1.6));
  stroke(Ln.pedestrian, C.ped, px(5, 1.6));
  const dots = [0.1, Math.max(3.5, 1.9 / k)]; // 둥근 끝 + 아주 짧은 선 = 점
  if (z >= 15) stroke(Ln.trail, C.foot, px(0.8, 1.4), { dash: dots });
  if (z >= 15.5) stroke(Ln.foot, C.foot, px(0.8, 1.6), { dash: dots });
  if (z >= 16.25) stroke(Ln.steps, C.steps, px(2.2, 3), { dash: [Math.max(1.2, 0.35 / k), Math.max(1.2, 0.35 / k)], cap: "butt" });
  fill(A.building, C.building, C["building-line"], 0.8);
  // 많이 확대하면 계곡선(25 m) 가운데에 높이: t-label(12px 500), map-halo 2px 테두리(10/2 디자인: 지도 안 글자도 12px 이상)
  if (z >= 17 && Z.index) {
    ctx.font = `500 12px ${C.font}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.lineWidth = 4;
    ctx.lineJoin = "round";
    ctx.strokeStyle = C.halo;
    ctx.fillStyle = C["contour-label"];
    for (const f of Z.index) {
      if (!seen(f)) continue;
      const i = Math.floor(f.pts.length / 4) * 2;
      const x = f.pts[i] * S - ox, y = f.pts[i + 1] * S - oy;
      if (x < 0 || y < 0 || x > size.x || y > size.y) continue;
      ctx.strokeText(String(f.z), x, y);
      ctx.fillText(String(f.z), x, y);
    }
  }
}

/** 바탕 지도 층: Leaflet 의 캔버스 그리기 틀(L.Renderer: 화면보다 조금 넓은 캔버스, 확대·축소 애니메이션 동안 늘였다 줄임)에 그림만 우리 것. */
const BaseMap = typeof L === "undefined" ? null : L.Renderer.extend({
  options: { padding: 0.1, pane: "ttw-base" },
  _initContainer() {
    const c = (this._container = document.createElement("canvas"));
    c.setAttribute("aria-hidden", "true");
    this._ctx = c.getContext("2d");
  },
  _destroyContainer() {
    L.DomUtil.remove(this._container);
    this._ctx = null;
  },
  _update() {
    if (this._map._animatingZoom && this._bounds) return;
    L.Renderer.prototype._update.call(this);
    const b = this._bounds, c = this._container, size = b.getSize();
    this._m = Math.min(2, window.devicePixelRatio || 1); // 3배 화면도 2배로(캔버스 메모리)
    L.DomUtil.setPosition(c, b.min);
    c.width = Math.round(this._m * size.x);
    c.height = Math.round(this._m * size.y);
    c.style.width = `${size.x}px`;
    c.style.height = `${size.y}px`;
    this.redraw();
  },
  redraw() {
    if (this._ctx && this._bounds && this._map) drawBasemap(this._ctx, this._map, this._bounds, this._m || 1);
  },
  // 끌거나 미끄러지는 동안에도 그려 둔 범위(화면 + 여유 10%)를 벗어나면 다시 그린다. Leaflet 그리기 틀은 다 멈춘 뒤에만 다시 그려서
  // 세게 밀면 멈출 때까지 바탕이 비었다(타일은 옮기는 동안에도 받는다)
  getEvents() {
    return { ...L.Renderer.prototype.getEvents.call(this), move: this._onMove };
  },
  _onMove() {
    if (this._frame || !this._bounds || this._map._animatingZoom) return;
    this._frame = requestAnimationFrame(() => {
      this._frame = 0;
      const map = this._map;
      if (!map || map._animatingZoom) return;
      const a = map.containerPointToLayerPoint([0, 0]), b = map.containerPointToLayerPoint(map.getSize());
      if (!this._bounds.contains(a) || !this._bounds.contains(b)) this._update();
    });
  },
  onRemove() {
    cancelAnimationFrame(this._frame);
    this._frame = 0;
    L.Renderer.prototype.onRemove.call(this);
  },
});

/** 건물 번호 목록(번호만인 건물 먼저, 짧은 번호 먼저): 수업이 없는 날 모든 건물 번호를 겹치지 않게 놓을 때 이 순서로.
 *  기숙사(10/3 디자인·자료): 919동은 네 동을 따로 쓴다(919A·919B·919C·919D, 이동시간 지점). 이동시간 지점이 아닌 기숙사 동(919 한 점)은
 *  번호로 쓰지 않는다. 붙어 있는 동이라 낮은 배율에서는 겹치는 번호가 숨고 확대하면 다 보인다.
 *  기숙사 동의 이름은 자료의 건물 이름('(관악사)학부 생활관') 대신 종류로 쓴다(학부생활관). */
let buildingMarks = null;
function allBuildingMarks() {
  if (!buildingMarks) {
    const ids = new Set(state.campus.ids);
    buildingMarks = Object.entries(state.campus.buildings || {})
      .filter(([id, v]) => v && v[1] !== null && v[1] !== undefined && !(isDorm(id) && !ids.has(id)))
      .map(([id, v]) => ({ id, text: id === "GATE" ? "정문" : id, name: buildingName(id), at: L.latLng(v[1], v[2]), pri: /^\d+$/.test(id) ? 0 : 1 }))
      .sort((a, b) => a.pri - b.pri || a.id.length - b.id.length);
  }
  return buildingMarks;
}

/** 지도 둘 다 확대·축소된다. 마우스: 확대·축소 버튼, 휠, 끌기. 터치: 두 손가락으로 확대·이동, 두 번 눌러 확대.
 *  시간표 옆 작은 지도는 터치에서 한 손가락 끌기를 끈다(페이지 스크롤이 지도에 걸리지 않게). 전체 화면 지도는 한 손가락으로 끈다. */
function makeMap(el, full) {
  if (typeof L === "undefined" || !state.campus) return null;
  if (!campusBounds) campusBounds = L.latLngBounds(state.campus.ids.map(coordOf).filter(Boolean)).pad(0.1);
  const still = reduceMotion.matches;
  const mouse = finePointer.matches;
  const map = L.map(el, {
    zoomControl: false, attributionControl: false, // 저작권 표기는 지도 밖 .map-attr(늘 보이고, 스크린리더가 읽는다)
    dragging: full || mouse, touchZoom: true, doubleClickZoom: true, scrollWheelZoom: full || mouse, boxZoom: mouse,
    keyboard: true, inertia: !still, zoomAnimation: !still, fadeAnimation: !still, markerZoomAnimation: !still,
    // 끌 수 있는 범위는 바탕 지도 자료 범위(loadBasemap 이 받으면 건다). 받기 전에 캠퍼스 범위로 묶으면 첫 요일을 맞출 때 가운데가 캠퍼스에 묶여 핀이 잘린다
    zoomSnap: 0.25, zoomDelta: 0.5, maxZoom: 19.5, maxBounds: dataBounds || undefined, maxBoundsViscosity: 1.0,
  });
  const buttons = full || mouse;
  if (buttons) L.control.zoom({ position: "topright", zoomInTitle: "확대", zoomOutTitle: "축소" }).addTo(map);
  el.setAttribute("role", "region");
  el.setAttribute("aria-label", "지도");
  // 바탕 지도(타일 자리 200), 수업 뒤 출발·도착 자리로 가는 길은 경로선(overlayPane, 400) 아래 칸: 겹치는 길에서 경로를 덮지 않게.
  // 선 끝과 핀을 잇는 점선의 테두리는 그보다도 아래 칸(어느 선도 덮지 않게)
  const basePane = map.createPane("ttw-base");
  basePane.style.zIndex = "200";
  basePane.style.pointerEvents = "none";
  map.createPane("ttw-stub").style.zIndex = "385";
  map.createPane("ttw-back").style.zIndex = "390";
  const base = new BaseMap().addTo(map);
  map.setView(campusBounds.getCenter(), 15, { animate: false });
  const legend = el.closest(".mapcard").querySelector(".legend");
  const mp = { map, el, base, full, buttons, legend, back: L.layerGroup().addTo(map), lines: L.layerGroup().addTo(map), stubs: L.layerGroup().addTo(map),
    marks: L.layerGroup().addTo(map), legLabels: L.layerGroup().addTo(map), names: L.layerGroup().addTo(map), data: null };
  // 배율이 바뀌면 붙어 보이는 번호를 다시 묶고, 옆으로 비킨 선을 그 배율의 화소 간격으로 다시 그린다(선 끝과 핀을 잇는 점선도 그 자리로).
  // 구간 라벨과 건물 번호는 옮길 때마다(화면 가장자리·버튼에 걸리지 않게). 배율이 바뀌면 zoomend 다음에 moveend 가 온다
  map.on("zoomend", () => { if (mp.data) { placeMarks(mp); drawReturn(mp); drawStubs(mp); } });
  map.on("moveend", () => { if (mp.data) { placeLegLabels(mp); placeLabels(mp); } });
  loadBasemap();
  return mp;
}

// 수업 뒤 출발·도착 자리로 가는 길: ⌂ 핀과 같은 색(home) 파선 + 흰 테두리, 경로선 옆으로 7px 비켜서(같은 길을 되짚어도 경로선이 가려지지 않게)
const RETURN_OFFSET = 7, RETURN_DASH = "8 6";
const RETURN_KEY = '<svg class="line-key" width="20" height="8" viewBox="0 0 20 8" aria-hidden="true"><path d="M1 4H19" fill="none" stroke="currentColor" stroke-width="3" stroke-dasharray="4 3"/></svg>';

/** 선을 진행 방향 오른쪽으로 px 만큼 평행하게 옮긴 점들(지금 배율의 layer 좌표). 모서리는 두 변 법선의 이등분선, 뾰족하면 2px 배까지만. */
function offsetPoints(map, line, px) {
  const pts = [];
  for (const ll of line) {
    const p = map.latLngToLayerPoint(ll);
    const q = pts[pts.length - 1];
    if (!q || Math.hypot(p.x - q.x, p.y - q.y) > 0.5) pts.push(p);
  }
  if (pts.length < 2) return pts;
  const normal = (a, b) => { const dx = b.x - a.x, dy = b.y - a.y, d = Math.hypot(dx, dy); return [-dy / d, dx / d]; };
  return pts.map((p, i) => {
    const n1 = i > 0 ? normal(pts[i - 1], p) : null;
    const n2 = i < pts.length - 1 ? normal(p, pts[i + 1]) : null;
    let ox, oy;
    if (n1 && n2) {
      const sx = n1[0] + n2[0], sy = n1[1] + n2[1], s = Math.hypot(sx, sy);
      if (s < 1) { ox = n2[0] * px; oy = n2[1] * px; } // 거의 되돌아가는 꺾임: 이음매 없이 다음 변 쪽으로
      else { const m = (2 * px) / s; ox = (sx / s) * m; oy = (sy / s) * m; }
    } else { const n = n1 || n2; ox = n[0] * px; oy = n[1] * px; }
    return L.point(p.x + ox, p.y + oy);
  });
}

function offsetLine(map, line, px) {
  const pts = offsetPoints(map, line, px);
  return pts.length < 2 ? line : pts.map((p) => map.layerPointToLatLng(p));
}

function drawReturn(mp) {
  mp.back.clearLayers();
  for (const lg of mp.data.legs) {
    if (!lg.home) continue;
    const off = offsetLine(mp.map, lg.line, RETURN_OFFSET);
    L.polyline(off, { pane: "ttw-back", className: "map-route-home-case", weight: 7, dashArray: RETURN_DASH, lineCap: "butt", lineJoin: "round", interactive: false }).addTo(mp.back);
    L.polyline(off, { pane: "ttw-back", className: "map-route-home", weight: 3, dashArray: RETURN_DASH, lineCap: "butt", lineJoin: "round", interactive: false }).addTo(mp.back);
  }
}

// 선 끝과 핀을 잇는 점선(10/3 사용자: 경로와 번호가 떨어져 있어 이상하다). 경로 자료는 건물 문 앞에서 끝나고 핀은 건물 자리(번호를 쓰는 자리)에
// 서서, 둘 사이가 보통 20~50m(가장 먼 301동은 100m) 벌어진다. 그 사이를 구간 선과 같은 색 점선으로 잇는다(지도 앱의 '길 끝에서 목적지까지').
// 실선을 핀까지 늘이지 않는 것은 건물을 가로지르는 길처럼 읽혀서고(일곱에 하나는 핀이 선 건물 면 밖을 많이 지난다), 핀을 문 앞으로 옮기지 않는 것은
// 들어간 문과 나오는 문이 다른 건물(16동은 문 사이 155m)에서 다음 구간이 다시 핀과 떨어지고 번호가 건물 밖 길 위에 서서다
// 점은 그 선의 굵기 그대로(수업 가는 길 4px, 출발·도착 자리로 가는 길 3px), 점 사이 3px. 테두리는 card 1px: 건물 위에서 route 점이
// 2.5:1(라이트)이라 3:1 에 못 미치는데, 선처럼 2px 를 두르면 흰 띠가 이어져 구슬 꿴 줄처럼 무거워진다. 테두리는 맨 아래 칸에 그려 어느 선도 덮지 않는다
// 한 핀에 닿는 점선은 선 끝이 서로 10px 안이면 하나만 긋는다(수업 가는 길 먼저. 10/3 디자인): 같은 문으로 들어가고 나오는 건물에서는 실선의 끝과
// 7px 비킨 파선의 시작이 나란해서, 둘 다 그으면 두 색 점이 겹친 채 핀까지 간다. 문이 다르면 둘 다 긋는다
const STUB = { route: { weight: 4, dashArray: "0.1 7" }, home: { weight: 3, dashArray: "0.1 6" } }, STUB_CASE = 1, STUB_NEAR = 10;

/** 건물 b 의 핀이 지금 서 있는 자리: 다른 수업 핀과 묶였으면 그 묶음 자리(placeMarks), 출발·도착 건물이면 ⌂. 핀이 없으면 null */
function pinSpot(mp, b) {
  const pin = (mp.pins || []).find((q) => q.bs.includes(b));
  return pin ? pin.at : b === mp.data.home ? mp.data.homeAt : null;
}

/** 구간 lg 의 그려진 선 양 끝에서 핀까지: [[선 끝, 핀 자리], …]. 출발·도착 자리로 가는 길은 옆으로 비킨 선의 끝에서. 2px 안쪽이면 없다 */
function legStubs(mp, lg) {
  const { map } = mp;
  const line = lg.home ? offsetLine(map, lg.line, RETURN_OFFSET) : lg.line, out = [];
  for (const [end, b] of [[line[0], lg.ends[0]], [line[line.length - 1], lg.ends[1]]]) {
    const pin = pinSpot(mp, b);
    if (!pin) continue;
    const p = map.latLngToLayerPoint(end), q = map.latLngToLayerPoint(pin);
    if (Math.hypot(p.x - q.x, p.y - q.y) >= 2) out.push([end, pin]); // 선 끝에서 시작해야 점 간격이 선 끝에 맞는다
  }
  return out;
}

/** 그릴 점선을 구간 순서대로: [구간 0 의 [[선 끝, 핀 자리], …], 구간 1 의 …]. 같은 핀에 닿고 선 끝이 STUB_NEAR 안인 것은 하나만 남긴다
 *  (수업 가는 길이 먼저, 그다음은 앞 구간) */
function dayStubs(mp) {
  const { map } = mp, legs = mp.data.legs, out = legs.map(() => []), kept = [];
  const order = legs.map((_, i) => i).sort((a, b) => Number(legs[a].home) - Number(legs[b].home)); // 안정 정렬: 같은 갈래는 구간 순서 그대로
  for (const i of order) {
    for (const s of legStubs(mp, legs[i])) {
      const p = map.latLngToLayerPoint(s[0]), pin = s[1];
      if (kept.some((k) => (k.pin === pin || (k.pin[0] === pin[0] && k.pin[1] === pin[1])) && Math.hypot(k.p.x - p.x, k.p.y - p.y) <= STUB_NEAR)) continue;
      kept.push({ pin, p });
      out[i].push(s);
    }
  }
  return out;
}

function drawStubs(mp) {
  mp.stubs.clearLayers();
  dayStubs(mp).forEach((stubs, i) => {
    const home = mp.data.legs[i].home, dots = home ? STUB.home : STUB.route;
    for (const seg of stubs) {
      const opt = { ...dots, lineCap: "round", interactive: false, ofHome: home };
      L.polyline(seg, { ...opt, weight: dots.weight + 2 * STUB_CASE, pane: "ttw-stub", className: "map-stub-case" }).addTo(mp.stubs);
      L.polyline(seg, { ...opt, pane: home ? "ttw-back" : "overlayPane", className: home ? "map-stub-home" : "map-stub" }).addTo(mp.stubs);
    }
  });
}

/** 지도 아래 번호표: 수업 순서 번호와 건물, 출발·도착, 점선(마지막 수업 뒤 출발·도착 자리로 가는 길)이 있으면 그 견본.
 *  '기숙사 가는 길'. '돌아가는 길'은 '빙 돌아가는 길(우회로)'로도 읽혀서, '수업 뒤 기숙사로'는 말이 어색해서 쓰지 않는다 */
function renderLegend(mp, legs, hasReturn) {
  const items = [];
  let n = 0;
  for (const l of legs) {
    if (!l.meeting) continue;
    n += 1;
    items.push(h("li", {}, h("span", { class: "num" }, String(n)), h("span", {}, l.meeting.building ? buildingLabel(l.meeting.building) : "강의실 미정")));
  }
  if (items.length) items.push(h("li", {}, h("span", { class: "num home", "aria-hidden": "true" }, svg(HOME_PIN.replace('width="12" height="12"', 'width="10" height="10"'))), h("span", {}, placeLabel(state.result.home))));
  if (items.length && hasReturn) items.push(h("li", { class: "line" }, svg(RETURN_KEY), h("span", {}, `${placeLabel(state.result.home)} 가는 길`)));
  mp.legend.replaceChildren(...items);
}

function renderMap(mp, ev, day, { reveal = false } = {}) {
  const { map } = mp;
  const R = state.result;
  mp.data = null; // 아래에서 배율을 맞추는 동안(zoomend·moveend) 앞 요일의 핀·라벨을 다시 놓지 않게
  const legs = ev.days[day] ? ev.legs.filter((l) => l.day === day) : [];
  // 선: 수업 가는 길(번호가 붙은 수업으로)은 실선, 마지막 수업 뒤 출발·도착 자리로 가는 길은 점선
  const homeLines = [], classLines = [], legLines = [];
  let num = 0; // 도착하는 수업의 번호(핀 번호와 같다)
  for (const l of legs) {
    if (l.meeting) num += 1;
    if (l.from === l.to) continue;
    let line = routeLine(state.routes, l.from, l.to);
    if (!line) {
      const a = coordOf(l.from), b = coordOf(l.to);
      if (!a || !b) continue;
      line = [a, b];
    }
    (l.meeting ? classLines : homeLines).push(line);
    const mins = Math.round(l.minutes);
    // 걷는 시간 라벨(출발·도착 자리로 가는 구간은 ⌂ 를 붙인다). 라벨 자리는 placeLegLabels 가 배율마다 고른다
    legLines.push({ line, home: !l.meeting, text: mins > 0 ? `${mins}분` : "", num: l.meeting ? num : 0, ends: [l.from, l.to] });
  }
  // 같은 길을 오가는 두 구간(301동 → 83동 → 301동)은 두 라벨이 한 길에 나란히 서서 어느 쪽이 어느 쪽인지 모른다. 이 라벨들에만 앞에
  // 도착하는 수업 번호를 붙인다(10/2 디자인: '2 26분', '3 32분'. ⌂ 19분의 ⌂ 처럼 '그 수업으로 가는 길'). ⌂ 구간은 ⌂ 가 이미 말한다
  const sameRoad = (a, b) => (a.ends[0] === b.ends[0] && a.ends[1] === b.ends[1]) || (a.ends[0] === b.ends[1] && a.ends[1] === b.ends[0]);
  for (const lg of legLines) lg.tag = !lg.home && lg.text && legLines.some((o) => o !== lg && !o.home && o.text && sameRoad(lg, o)) ? lg.num : 0;
  renderLegend(mp, legs, homeLines.length > 0); // 번호표를 먼저 채워야 지도 칸 높이가 정해진다
  mp.el.setAttribute("aria-label", `${DAY_KO[day]}요일 지도`);
  // 맞추는 동안 끌 수 있는 범위(maxBounds)를 풀었다가 맞춘 뒤 다시 건다(10/3 디자인 세션이 찾은 것). 걸어 둔 채 칸 크기나 최소 배율이 바뀌면
  // Leaflet 이 moveend 마다 0.25초 애니메이션으로 범위 안에 옮기는데(_panInsideMaxBounds), 그 애니메이션이 뒤이은 setView·fitBounds 와 엉킨다:
  // 남은 만큼 밀리거나(수업 없는 날 ⌂ 가 가운데에서 11~39px 벗어났다), 최소 배율이 올라간 날은 맞춘 뒤에 최소 배율로 되돌아간다
  // (폰 320·태블릿 768 에서 수업 없는 날이 캠퍼스 전체로 열려 ⌂ 가 위에서 잘렸다). 그래서 같은 요일은 어디서 넘어와도 같은 자리·같은 배율이다
  const limit = map.options.maxBounds;
  if (limit) map.setMaxBounds(null);
  map.invalidateSize();
  applyMinZoom(map);
  mp.lines.clearLayers();
  const homeAt = coordOf(R.home);
  const stops = [], pts = homeAt ? [homeAt] : [];
  let n = 0;
  for (const l of legs) {
    if (!l.meeting) continue;
    n += 1;
    const at = l.meeting.building ? coordOf(l.meeting.building) : null;
    if (at && l.meeting.building !== R.home) stops.push({ at, nums: [n], names: [l.meeting.section.name], b: l.meeting.building });
  }
  for (const line of [...classLines, ...homeLines]) pts.push(...line);
  // 선 모양: 수업 가는 길은 route 4px 실선 + card 2px 테두리. 출발·도착 자리로 가는 길은 경로선 아래 칸에 ⌂ 색 파선(drawReturn, 배율이 정해진 뒤)
  const drawn = [];
  for (const line of classLines) drawn.push(L.polyline(line, { className: "map-route-case", weight: 8, lineCap: "round", lineJoin: "round", interactive: false }).addTo(mp.lines));
  for (const line of classLines) drawn.push(L.polyline(line, { className: "map-route", weight: 4, lineCap: "round", lineJoin: "round", interactive: false }).addTo(mp.lines));
  for (const st of stops) pts.push(st.at);
  // 요일·순위를 바꾸면 그날 경로 전체가 들어오게(애니메이션 없이). 핀이 오른쪽 위 버튼(크게 보기, 확대·축소), 오른쪽 아래 저작권 표기와
  // 핀 오른쪽 건물 번호에 가리지 않게 가장자리를 비운다. 폰의 작은 지도는 폭이 좁아 위쪽을 비운다
  const k = remPx() / 16; // 글자를 키우면 저작권 표기도 커진다
  const attr = mp.el.parentElement.querySelector(".map-attr"); // 좁은 지도에서는 저작권 표기가 두 줄이 된다
  const top = Math.max(mp.full || mp.buttons ? 40 : 56, Math.round(24 + 16 * k)), bottom = Math.max(32, Math.round(16 + 16 * k), (attr ? attr.offsetHeight : 0) + 8);
  const pad = mp.full ? { paddingTopLeft: [24, top], paddingBottomRight: [68, bottom] }
    : mp.buttons ? { paddingTopLeft: [20, top], paddingBottomRight: [56, bottom] } : { paddingTopLeft: [20, top], paddingBottomRight: [20, bottom] };
  if (pts.length > 1) {
    const bounds = L.latLngBounds(pts), fit = { ...pad, maxZoom: 17, animate: false };
    map.fitBounds(bounds, fit);
    // 묶인 핀(2·3·4·5·6)은 한 핀보다 넓다. 가장자리 밖으로 잘리면 그만큼 더 비우고 다시 맞춘다(묶음은 배율마다 달라서 몇 번 본다).
    // 맨 아래 핀이 오른쪽 아래 저작권 표기 밑에 걸려도 그만큼 아래를 더 비운다(아래 여백은 선 끝 기준이라 핀 반지름만큼 모자랄 수 있다).
    // 배율이 그대로면 더 비운 폭의 반만큼만 옮겨지므로 둘째부터는 두 배로 비운다
    for (let i = 0; i < 4; i++) {
      const w = map.getSize().x;
      const host = mp.el.getBoundingClientRect(), ar = attr ? attr.getBoundingClientRect() : null;
      const attrLeft = ar && ar.width ? ar.left - host.left : Infinity, attrTop = ar && ar.width ? ar.top - host.top : Infinity;
      let l = 0, r = 0, under = 0;
      const pins = groupStops(map, stops).map((pin) => [map.latLngToContainerPoint(pin.at), pin.w]);
      if (homeAt) pins.push([map.latLngToContainerPoint(homeAt), 24]);
      for (const [pt, pw] of pins) {
        l = Math.max(l, 4 + pw / 2 - pt.x);
        r = Math.max(r, pt.x + pw / 2 + 4 - w);
        if (pt.x + pw / 2 > attrLeft && pt.y + 12 - attrTop > 0.5) under = Math.max(under, pt.y + 12 + 2 - attrTop); // 걸렸을 때만, 2px 띄운다
      }
      if (l < 1 && r < 1 && under < 1) break;
      const more = (v) => (v < 1 ? 0 : Math.ceil(v) * (i ? 2 : 1));
      fit.paddingTopLeft = [fit.paddingTopLeft[0] + more(l), fit.paddingTopLeft[1]];
      fit.paddingBottomRight = [fit.paddingBottomRight[0] + more(r), fit.paddingBottomRight[1] + more(under)];
      map.fitBounds(bounds, fit);
    }
  } else if (pts.length) map.setView(pts[0], 16, { animate: false }); // 수업 없는 날: 출발·도착 자리를 가운데에, 배율 16
  if (limit) { map.panInsideBounds(limit, { animate: false }); map.setMaxBounds(limit); } // 범위 밖이면 애니메이션 없이 안으로 옮긴 뒤 다시 건다
  mp.data = { stops, legs: legLines, homeAt, home: R.home }; // home: 결과가 지워진 뒤(입력 화면에서 과목을 바꾼 뒤)에도 지도가 옮겨지면 다시 그린다
  drawReturn(mp);
  placeMarks(mp);
  drawStubs(mp); // 핀 자리(묶음)가 정해진 뒤에
  placeLegLabels(mp);
  placeLabels(mp);
  if (reveal && !reduceMotion.matches) revealRoute(mp, drawn);
}

/** 지금 배율에서 겹치는 수업 핀을 묶는다: [{at, nums, names, bs, label '2·3', w 핀 폭}] */
function groupStops(map, stops) {
  const merged = [];
  for (const st of stops) {
    const pt = map.latLngToContainerPoint(st.at);
    const near = merged.find((m) => Math.abs(m.pt.x - pt.x) < 24 && Math.abs(m.pt.y - pt.y) < 24);
    if (near) {
      near.nums.push(...st.nums);
      near.names.push(...st.names);
      if (!near.bs.includes(st.b)) near.bs.push(st.b);
    } else merged.push({ at: st.at, pt, nums: [...st.nums], names: [...st.names], bs: [st.b] });
  }
  for (const st of merged) {
    st.label = st.nums.join("·");
    st.w = st.label.length > 1 ? 12 + 7 * st.label.length : 24;
  }
  return merged;
}

/** 핀. 화면에서 겹치는 수업 핀은 1·2 로 묶는다(배율이 바뀔 때마다 다시). 구간 라벨은 placeLegLabels. */
function placeMarks(mp) {
  const { map, marks, data } = mp;
  marks.clearLayers();
  const merged = groupStops(map, data.stops);
  if (data.homeAt) {
    L.marker(data.homeAt, { keyboard: false, interactive: false,
      icon: L.divIcon({ className: "", html: `<div class="pin home" role="img" aria-label="${esc(placeLabel(data.home))}">${HOME_PIN}</div>`, iconSize: [24, 24], iconAnchor: [12, 12] }) }).addTo(marks);
  }
  for (const st of merged) {
    const name = [st.label, ...new Set(st.names), st.bs.map(buildingLabel).join("·")].join(", "); // 1, 동물생화학 2, 26동
    L.marker(st.at, { keyboard: false, interactive: false, zIndexOffset: 100,
      icon: L.divIcon({ className: "", html: `<div class="pin" role="img" aria-label="${esc(name)}">${st.label}</div>`, iconSize: [st.w, 24], iconAnchor: [st.w / 2, 12] }) }).addTo(marks);
  }
  mp.pins = merged;
}

/** 지도 글자 폭(px). 굵기 w 의 12px(지도 그림 글자는 px 고정). 글꼴을 받으면 다시 잰다. */
const mapTextW = (() => {
  let cache = new Map();
  if (document.fonts) document.fonts.addEventListener("loadingdone", () => { cache = new Map(); });
  return (w, text) => {
    const k = `${w} ${text}`;
    let v = cache.get(k);
    if (v === undefined) {
      canvas.font = `${w} 12px ${mapColors().font}`;
      v = canvas.measureText(text).width;
      cache.set(k, v);
    }
    return v;
  };
})();
/** 건물 번호(.blabel b, 12px 700)와 이름(span, 12px 500) 가운데 넓은 쪽 + 테두리 여유. */
const blabelW = (text, name) => Math.max(mapTextW(700, text), name ? mapTextW(500, name) : 0) + 4;

/** 지도 오른쪽 위 버튼(크게 보기, 마우스·전체 화면 지도의 확대·축소)의 상자, 지도 칸 좌표 [x0, y0, x1, y1]. */
function mapButtonBoxes(mp) {
  const host = mp.el.getBoundingClientRect(), out = [];
  for (const el of mp.el.parentElement.querySelectorAll(".map-expand > span, .leaflet-control-zoom")) {
    const r = el.getBoundingClientRect();
    if (r.width) out.push([r.left - host.left - 2, r.top - host.top - 2, r.right - host.left + 2, r.bottom - host.top + 2]);
  }
  return out;
}

/** 수업이 있는 날 핀 옆 건물 번호: 글, (많이 확대하면) 이름, 폭, 자리. 핀 오른쪽이 기본이고 오른쪽 가장자리나 오른쪽 위 버튼에 걸리면 왼쪽,
 *  왼쪽도 가장자리에 걸리거나(폰의 좁은 지도에서 넓게 묶인 핀 2·3·4·5·6) 다른 핀을 덮으면 핀 아래에 둔다(dx: 가장자리에 걸리지 않게 옆으로 민 만큼). */
function pinTag(mp, pin, withName) {
  const { map } = mp;
  const text = pin.bs.map((b) => (b === "GATE" ? "정문" : b)).join("·");
  const name = withName ? pin.bs.map(buildingName).filter(Boolean).join("·") : "";
  const pt = map.latLngToContainerPoint(pin.at), x = pt.x, lw = blabelW(text, name), W = map.getSize().x, hw = pin.w / 2, hh = name ? 15 : 9;
  const right = [x + hw + 3, pt.y - hh, x + hw + 3 + lw, pt.y + hh], left = [x - hw - 3 - lw, pt.y - hh, x - hw - 3, pt.y + hh];
  let side = right[2] > W - 4 || mapButtonBoxes(mp).some((b) => boxHit(right, b)) ? "left" : "right", dx = 0;
  if (side === "left" && x - hw >= 0 && x + hw <= W) { // 핀이 화면 안에 있을 때만(지도를 끌어 핀이 나가면 번호도 따라 나간다)
    const others = (mp.pins || []).filter((q) => q !== pin).map((q) => [map.latLngToContainerPoint(q.at), q.w / 2]);
    if (mp.data && mp.data.homeAt) others.push([map.latLngToContainerPoint(mp.data.homeAt), 12]);
    if (left[0] < 4 || others.some(([q, w]) => boxHit(left, [q.x - w - 1, q.y - 13, q.x + w + 1, q.y + 13]))) {
      side = "below";
      dx = Math.max(4 + lw / 2 - x, Math.min(0, W - 4 - lw / 2 - x));
    }
  }
  return { text, name, lw, side, dx };
}

// ---- 구간 라벨 자리
// 10/1 밤 사용자 제보: 두 구간이 함께 지나는 길에 놓인 '12분'이 어느 구간 것인지 한눈에 안 들어왔다(구간 길이의 가운데에 두던 때).
// 이제 라벨은 그 구간만 지나는 자리(다른 구간 선에서 LABEL_SEP 넘게 떨어진 자리) 가운데 가장 긴 토막의 가운데에 둔다. 그런 자리가
// 없으면(다른 구간과 같은 길만 지나면) 다른 선에서 가장 먼 자리. 목표는 선 모양으로만 정해서 지도를 옮겨도 그대로이고, 목표가 핀·핀 옆
// 건물 번호·다른 라벨·지도 버튼·저작권 표기에 걸리거나 화면 밖이면 목표에서 가까운 자리를 고른다(그 구간만 지나는 자리부터).
// 둘 데가 없으면 숨긴다(가이드: 다른 라벨·핀과 겹치면 숨긴다). 그 구간만 지나는 자리가 짧은 라벨부터 자리를 잡는다
const LABEL_SEP = 8; // 다른 구간 선의 가운데에서 라벨 상자까지: 경로선 테두리 반폭 4px + 틈 4px
const LABEL_H = 18; // .leg-label: 줄 16px + 위아래 1px

const boxHit = (a, b) => !(a[2] <= b[0] || a[0] >= b[2] || a[3] <= b[1] || a[1] >= b[3]);

/** 축에 맞춘 상자 r = [x0, y0, x1, y1] 과 선분 ab 사이 거리(겹치면 0). */
function boxSegDist(r, a, b) {
  const dx = b.x - a.x, dy = b.y - a.y;
  let t0 = 0, t1 = 1; // Liang–Barsky: 선분이 상자를 지나는지
  const clip = (p, q) => {
    if (p === 0) return q >= 0;
    const t = q / p;
    if (p < 0) { if (t > t1) return false; if (t > t0) t0 = t; } else { if (t < t0) return false; if (t < t1) t1 = t; }
    return true;
  };
  if (clip(-dx, a.x - r[0]) && clip(dx, r[2] - a.x) && clip(-dy, a.y - r[1]) && clip(dy, r[3] - a.y)) return 0;
  const toBox = (p) => Math.hypot(Math.max(r[0] - p.x, 0, p.x - r[2]), Math.max(r[1] - p.y, 0, p.y - r[3]));
  const l2 = dx * dx + dy * dy;
  const toSeg = (x, y) => { const t = l2 ? Math.max(0, Math.min(1, ((x - a.x) * dx + (y - a.y) * dy) / l2)) : 0; return Math.hypot(x - a.x - t * dx, y - a.y - t * dy); };
  return Math.min(toBox(a), toBox(b), toSeg(r[0], r[1]), toSeg(r[2], r[1]), toSeg(r[0], r[3]), toSeg(r[2], r[3]));
}

function placeLegLabels(mp) {
  const { map, data } = mp;
  mp.legLabels.clearLayers();
  mp.boxes = [];
  if (!data) return;
  const size = map.getSize(), o = map.containerPointToLayerPoint([0, 0]);
  const withName = map.getZoom() >= 17.25;
  // 피할 상자(layer 좌표): 핀과 핀 옆 건물 번호, 지도 위 버튼(크게 보기, 확대·축소)과 저작권 표기
  const pins = [], avoid = [];
  if (data.homeAt) { const p = map.latLngToLayerPoint(data.homeAt); pins.push([p.x - 14, p.y - 14, p.x + 14, p.y + 14]); }
  for (const pin of mp.pins || []) {
    const p = map.latLngToLayerPoint(pin.at), hw = pin.w / 2, t = pinTag(mp, pin, withName), hh = t.name ? 15 : 9;
    pins.push([p.x - hw - 2, p.y - 14, p.x + hw + 2, p.y + 14]);
    avoid.push(t.side === "below" ? [p.x + t.dx - t.lw / 2 - 2, p.y + 12, p.x + t.dx + t.lw / 2 + 2, p.y + 16 + 2 * hh]
      : t.side === "left" ? [p.x - hw - 5 - t.lw, p.y - hh, p.x - hw, p.y + hh] : [p.x + hw, p.y - hh, p.x + hw + 5 + t.lw, p.y + hh]);
  }
  const ui = [];
  const host = mp.el.getBoundingClientRect();
  for (const el of mp.el.parentElement.querySelectorAll(".map-expand, .leaflet-control-zoom, .map-attr")) {
    const r = el.getBoundingClientRect();
    if (r.width) ui.push([o.x + r.left - host.left - 4, o.y + r.top - host.top - 4, o.x + r.right - host.left + 4, o.y + r.bottom - host.top + 4]);
  }
  avoid.push(...pins, ...ui);
  const view = [o.x + 4, o.y + 4, o.x + size.x - 4, o.y + size.y - 4];
  // 구간 선(layer 좌표). 출발·도착 자리로 가는 길은 그려진 대로 오른쪽으로 비킨 선
  const lines = data.legs.map((lg) => (lg.home ? offsetPoints(map, lg.line, RETURN_OFFSET) : lg.line.map((ll) => map.latLngToLayerPoint(ll))));
  const seg = (a, b) => [a, b, Math.min(a.x, b.x), Math.min(a.y, b.y), Math.max(a.x, b.x), Math.max(a.y, b.y)];
  // 선 끝과 핀을 잇는 점선(그려진 것만)도 그 구간의 선으로 친다(다른 구간 라벨이 그 위에 서지 않게). 라벨 후보 자리는 길 위(lines)에서만 고른다
  const stubs = dayStubs(mp);
  const segs = lines.map((pts, i) => pts.slice(1).map((b, k) => seg(pts[k], b))
    .concat(stubs[i].map(([a, b]) => seg(map.latLngToLayerPoint(a), map.latLngToLayerPoint(b)))));
  const isHome = data.legs.map((lg) => lg.home);
  const CAP = 32; // 이보다 먼 선은 볼 필요가 없다
  /** 상자 r 에서 i 아닌 구간 선까지 가장 가까운 거리: [모든 선, 수업 가는 길(실선)만]. */
  const sepOf = (i, r) => {
    let all = CAP, cls = CAP;
    for (let j = 0; j < segs.length; j++) {
      if (j === i) continue;
      for (const [a, b, x0, y0, x1, y1] of segs[j]) {
        const d0 = isHome[j] ? all : cls; // 이 선이 줄일 수 있는 값
        if (x0 > r[2] + d0 || x1 < r[0] - d0 || y0 > r[3] + d0 || y1 < r[1] - d0) continue;
        const d = boxSegDist(r, a, b);
        all = Math.min(all, d);
        if (!isHome[j]) cls = Math.min(cls, d);
        if (!cls) return [0, 0];
      }
    }
    return [all, cls];
  };
  /** 구간 i 의 선이 다른 수업 구간 선과 3px 안에 겹치는 길이 비율. 거의 1 이면 같은 길을 되짚는 구간(301 → 83 → 301). */
  const overlap = (i) => {
    const pts = lines[i];
    let tot = 0, hit = 0;
    for (let k = 1; k < pts.length; k++) {
      const a = pts[k - 1], b = pts[k], len = Math.hypot(b.x - a.x, b.y - a.y), n = Math.max(1, Math.ceil(len / 4));
      for (let m = 0; m < n; m++) {
        const t = (m + 0.5) / n, p = L.point(a.x + (b.x - a.x) * t, a.y + (b.y - a.y) * t);
        tot += len / n;
        if (segs.some((sg, j) => j !== i && !isHome[j] && sg.some(([c, d, x0, y0, x1, y1]) => p.x >= x0 - 3 && p.x <= x1 + 3 && p.y >= y0 - 3 && p.y <= y1 + 3
          && L.LineUtil.pointToSegmentDistance(p, c, d) <= 3))) hit += len / n;
      }
    }
    return tot ? hit / tot : 1;
  };
  const items = [];
  data.legs.forEach((lg, i) => {
    const pts = lines[i];
    if (!lg.text || pts.length < 2) return;
    const cum = [0];
    for (let k = 1; k < pts.length; k++) cum.push(cum[k - 1] + Math.hypot(pts[k].x - pts[k - 1].x, pts[k].y - pts[k - 1].y));
    const len = cum[cum.length - 1];
    // 상자: 좌우 6px, ⌂ 10px + 2px, 수업 번호(.num 16px 원, 왼쪽 -4px·오른쪽 4px 여백)
    const numW = lg.tag ? Math.max(16, Math.ceil(mapTextW(700, String(lg.tag))) + 8) : 0;
    const hw = (Math.ceil(mapTextW(500, lg.text)) + 12 + (lg.home ? 12 : 0) + numW) / 2 + 1, hh = LABEL_H / 2 + 1;
    const step = Math.max(3, len / 160), end = Math.min(12, len / 2);
    const cands = [];
    for (let s = end, k = 1; s <= len - end + 1e-6; s += step) {
      while (k < cum.length - 1 && cum[k] < s) k++;
      const seg = cum[k] - cum[k - 1], t = seg ? (s - cum[k - 1]) / seg : 0;
      const x = pts[k - 1].x + (pts[k].x - pts[k - 1].x) * t, y = pts[k - 1].y + (pts[k].y - pts[k - 1].y) * t;
      const box = [x - hw, y - hh, x + hw, y + hh];
      const [sep, cls] = sepOf(i, box);
      cands.push({ s, x, y, box, sep, cls });
    }
    // 목표: 그 구간만 지나는 토막(이어진 후보) 가운데 가장 긴 것의 가운데. 없으면 다른 선에서 가장 먼 자리(같으면 구간 가운데에 가까운 쪽)
    const runs = [];
    let first = -1;
    cands.forEach((c, n) => {
      const own = c.sep >= LABEL_SEP;
      if (own && first < 0) first = n;
      if (first >= 0 && (!own || n === cands.length - 1)) { runs.push([cands[first].s, cands[own ? n : n - 1].s]); first = -1; }
    });
    const longest = runs.reduce((a, r) => (!a || r[1] - r[0] > a[1] - a[0] ? r : a), null);
    const mid = (c) => Math.abs(c.s - len / 2);
    const target = longest ? (longest[0] + longest[1]) / 2 : cands.reduce((a, c) => (c.sep > a.sep || (c.sep === a.sep && mid(c) < mid(a)) ? c : a)).s;
    // 다른 수업 실선이 지나가는 자리에도 둘 수 있는 라벨: ⌂ 라벨(⌂ 가 어느 선인지 말한다), 같은 길을 되짚는 구간(어디 두어도 그 길뿐)
    const anywhere = lg.home || (!longest && overlap(i) >= 0.9);
    items.push({ i, lg, cands, target, anywhere, own: runs.reduce((t, r) => t + r[1] - r[0] + step, 0) });
  });
  const placed = [];
  const free = (bx) => bx[0] >= view[0] && bx[1] >= view[1] && bx[2] <= view[2] && bx[3] <= view[3]
    && !avoid.some((q) => boxHit(bx, q)) && !placed.some((q) => boxHit(bx, q));
  items.sort((a, b) => a.own - b.own || a.i - b.i);
  for (const it of items) {
    const near = (a, b) => Math.abs(a.s - it.target) - Math.abs(b.s - it.target);
    const loose = (a, b) => b.sep - a.sep || near(a, b);
    // 1) 그 구간만 지나는 자리, 2) 다른 수업 실선이 라벨 밑으로 지나가지는 않는 자리, 3) (anywhere 일 때만) 아무 자리
    const c = it.cands.filter((x) => x.sep >= LABEL_SEP).sort(near).find((x) => free(x.box))
      || it.cands.filter((x) => x.sep < LABEL_SEP && x.cls > 0).sort(loose).find((x) => free(x.box))
      || (it.anywhere ? it.cands.filter((x) => x.sep < LABEL_SEP && !x.cls).sort(loose).find((x) => free(x.box)) : null);
    if (!c) continue; // 둘 데가 없거나 어느 구간 것인지 헷갈리는 자리뿐이면 숨긴다(크게 보기에서 확대하면 보인다)
    placed.push([c.box[0] - 2, c.box[1] - 2, c.box[2] + 2, c.box[3] + 2]);
    L.marker(map.layerPointToLatLng([c.x, c.y]), { interactive: false, keyboard: false,
      icon: L.divIcon({ className: "", html: `<span class="leg-label${it.lg.home ? " to-home" : ""}" aria-hidden="true">${it.lg.home ? HOME_PIN.replace('width="12" height="12"', 'width="10" height="10"') : ""}${it.lg.tag ? `<span class="num">${it.lg.tag}</span>` : ""}${it.lg.text}</span>`, iconSize: [0, 0] }) }).addTo(mp.legLabels);
  }
  mp.boxes = pins.concat(ui, placed); // 수업이 없는 날 건물 번호가 피할 자리(placeLabels): 핀, 지도 버튼·저작권 표기, 구간 라벨
}

/**
 * 건물 번호(사용자 결정 10/1). 수업이 있는 날: 그날 수업 건물 번호만 핀 오른쪽에(겹쳐도 숨기지 않는다).
 * 수업이 없는 날: 배율 15.5 이상에서 모든 건물 번호, 화면에서 겹치거나(핀·구간 라벨 자리도) 가장자리에 걸리면 숨긴다. 배율 17.25 이상이면 이름도.
 * 꾸밈이라 스크린리더는 읽지 않는다(핀 이름과 아래 번호표가 같은 것을 말한다).
 */
function placeLabels(mp) {
  const { map, names, data } = mp;
  names.clearLayers();
  if (!data || !state.campus) return;
  const z = map.getZoom(), withName = z >= 17.25;
  const icon = (html) => L.divIcon({ className: "", html, iconSize: [0, 0] });
  const size = map.getSize();
  if (data.stops.length) {
    for (const pin of mp.pins || []) {
      const { text, name, side, dx } = pinTag(mp, pin, withName); // 오른쪽 가장자리·버튼에 걸리면 핀 왼쪽, 왼쪽도 걸리면 핀 아래
      L.marker(pin.at, { interactive: false, keyboard: false, zIndexOffset: 50,
        icon: icon(`<div class="blabel day${side === "right" ? "" : " " + side}" style="--pin-half:${pin.w / 2}px;--dx:${dx}px" aria-hidden="true"><b>${esc(text)}</b>${name ? `<span>${esc(name)}</span>` : ""}</div>`) }).addTo(names);
    }
    return;
  }
  if (z < 15.5) return;
  const o = map.containerPointToLayerPoint([0, 0]);
  const placed = (mp.boxes || []).slice();
  for (const lb of allBuildingMarks()) {
    const p = map.latLngToLayerPoint(lb.at);
    const w = blabelW(lb.text, withName ? lb.name : ""), hh = withName ? 28 : 15;
    const box = [p.x - w / 2 - 2, p.y - hh / 2 - 1, p.x + w / 2 + 2, p.y + hh / 2 + 1];
    if (box[0] < o.x + 2 || box[1] < o.y + 2 || box[2] > o.x + size.x - 2 || box[3] > o.y + size.y - 2) continue;
    if (placed.some((q) => !(box[2] < q[0] || box[0] > q[2] || box[3] < q[1] || box[1] > q[3]))) continue;
    placed.push(box);
    L.marker(lb.at, { interactive: false, keyboard: false,
      icon: icon(`<div class="blabel" aria-hidden="true"><b>${esc(lb.text)}</b>${withName && lb.name ? `<span>${esc(lb.name)}</span>` : ""}</div>`) }).addTo(names);
  }
}

/** 첫 결과에서 한 번: 1위 경로 실선을 400ms 동안 그리고, 핀은 번호 순서로 나타난다. */
function revealRoute(mp, drawn) {
  const easing = "cubic-bezier(0.2, 0, 0, 1)";
  for (const pl of drawn) {
    const path = pl.getElement && pl.getElement();
    if (!path || !path.animate || !path.getTotalLength) continue;
    const len = path.getTotalLength();
    if (!len) continue;
    path.style.strokeDasharray = String(len);
    path.animate([{ strokeDashoffset: len }, { strokeDashoffset: 0 }], { duration: 400, easing })
      .finished.then(() => { path.style.strokeDasharray = ""; }, () => null);
  }
  const pins = [...mp.el.querySelectorAll(".pin:not(.home)")];
  pins.forEach((p, i) => p.animate([{ opacity: 0, transform: "scale(.6)" }, { opacity: 1, transform: "none" }],
    { duration: 200, delay: (i * 400) / Math.max(1, pins.length), easing, fill: "backwards" }));
  // 실선 끝과 핀을 잇는 점선은 실선이 다 그려진 뒤에 나타난다(파선 쪽 점선은 파선처럼 처음부터 있다)
  mp.stubs.eachLayer((pl) => {
    const path = !pl.options.ofHome && pl.getElement && pl.getElement();
    if (path && path.animate) path.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 150, delay: 400, easing, fill: "backwards" });
  });
}

function renderFullMap() {
  if (!state.result) return;
  $("map-title").textContent = `${DAY_KO[state.day]}요일 지도`;
  if (!maps.full) maps.full = makeMap($("map-full"), true);
  if (maps.full) renderMap(maps.full, currentEv(), state.day);
  remember($("map-full")); // 번호표가 들어간 뒤의 크기(크기가 같으면 다시 그리지 않는다)
}

// ---------------------------------------------------------------- 순위

function twinText(twins) {
  const shown = twins.slice(0, 3).map(sectionLabel).join(", ");
  return twins.length > 3 ? `${shown} 외 ${twins.length - 3}개` : shown;
}

/** 후보 카드: 순위, 한 주 걷는 시간·등교 요일(늦는 수업이 있으면 빨간 ' · 월수 2분 늦음'), 요일별 미리보기. 고른 카드는 테두리와 담은 분반 목록.
 *  늦는 분을 한 주치 더한 값(예전 ' · 10분 늦음')은 뜻이 없어서 쓰지 않는다(10/1 사용자). 그 뒤 '늦을 수 있음'(앱 말투에 안 맞음),
 *  '늦음'(가이드 형식 '분 + 늦음'·원칙 '늦음은 분으로'에 안 맞음)을 거쳐 늦는 요일과 그 분으로(10/1 밤 사용자 결정, lateText) */
function rankItem(ev, i) {
  const R = state.result;
  const [h0, h1] = R.axis;
  const span = (h1 - h0) * 60;
  const pct = (x) => `${(x / span) * 100}%`;
  const cur = i === state.rank;
  const walk = Math.round(ev.travel);
  const late = lateText(ev.legs, true);
  const days = R.days.filter((d) => (ev.days[d] || []).length).map((d) => DAY_KO[d]).join("");
  // 요약은 덩이 사이(' · ' 의 가운뎃점 앞)에서만 줄을 바꾼다('늦음'만 다음 줄로 떨어지지 않게, 줄 끝에 점이 남지 않게).
  // 시간이 모두 미정이면 등교 요일이 없다
  const nw = (t) => h("span", { class: "nw" }, t);
  const sum = [nw(`걷기 주 ${walk}분`), days ? [" ·\u00a0", nw(`${days} 등교`)] : null];
  const clsOf = (courseId) => state.byId.get(courseId)?.cls || "";
  const week = h("span", { class: "week", "aria-hidden": "true", style: { "--days": String(R.days.length) } },
    R.days.map((d) => h("span", { class: "wd" }, DAY_KO[d])),
    R.days.map((d) => h("span", { class: "wc" }, (ev.days[d] || []).map((m) => h("span", {
      class: "wb", style: { top: pct(m.start - h0 * 60), height: pct(m.end - m.start), background: clsColor(clsOf(m.section.courseId)) },
    })))));
  const btn = h("button", {
    type: "button", class: "rank-hit", "data-rank": String(i), "aria-current": cur ? "true" : null,
    "aria-label": [`${i + 1}위`, `걷기 주 ${walk}분`, days ? `${days} 등교` : "", late].filter(Boolean).join(", "),
  },
  h("span", { class: "rank-head" }, h("span", { class: "rank-no" }, `${i + 1}위`),
    h("span", { class: "rank-sum" }, sum, late ? h("span", { class: "late" }, " ·\u00a0", nw(late)) : null)),
  week);
  return h("li", { class: cur ? "rank selected" : "rank" }, btn, cur ? rankPicks(ev) : null);
}

/**
 * 고른 카드의 분반 목록: 과목명 | 분반 두 열(수강신청 때 분반 열만 내려 읽게). 분반은 번호만 진하게, 교수는 흐리게.
 * 같은 시간·건물의 다른 분반은 아래 줄에 '같은 시간·건물'(과목명 열)과 그 분반(분반 열). 좁은 카드·큰 글자면 분반이 과목명 아래로 간다(CSS).
 */
function rankPicks(ev) {
  return h("ul", { class: "rank-picks" }, ev.sections.map((s) => {
    const c = state.byId.get(s.courseId);
    const [no, prof] = sectionParts(s);
    const twins = s.twins && s.twins.length ? s.twins : null;
    return h("li", {},
      h("span", { class: "swatch", "aria-hidden": "true", style: { background: clsColor(c ? c.cls : "") } }),
      h("span", { class: "p-name" }, s.name), " ",
      h("span", { class: "p-sec" }, h("span", { class: "no" }, no), h("wbr"), h("span", { class: "pf" }, prof)),
      twins ? [" ", h("span", { class: "p-twins" }, h("span", { class: "p-tl" }, "같은 시간·건물"), " ", h("span", { class: "p-tw" }, twinText(twins)))] : null);
  }));
}

function renderRanks({ focus = null } = {}) {
  const R = state.result;
  const shown = Math.min(state.ranksShown, R.ranked.length);
  $("ranks").replaceChildren(...R.ranked.slice(0, shown).map((ev, i) => rankItem(ev, i)));
  renderMore();
  if (focus !== null) $("ranks").querySelector(`[data-rank="${focus}"]`)?.focus({ preventScroll: true });
}

// ---- 더 보기와 더 찾기(디자인 규칙 '후보 카드'. 10/3 밤 사용자: "개수 상관없이 더 찾기 누르면 다음 순위 이어서 찾아줘")
// 목록 아래 버튼 한 자리. 찾은 것 가운데 안 보인 것이 있으면 '더 보기'(RANKS_STEP 개씩 편다), 다 보였고 조합이 더 있으면 '더 찾기'(다음 순위
// TOP_K 개를 목록에 붙인다. 한도 없음), 다 찾았으면 자리를 숨기고 제목이 '전체 조합 N개를 찾았어요'가 된다.
// 엔진은 이어서 찾지 못하고 topK 를 키워 처음부터 다시 찾는다(순위는 topK 와 상관없이 정해져 있어 앞쪽은 그대로이고 그 뒤 순위가 이어 붙는다).
// 걸리는 시간은 topK 가 커져도 거의 같아서(10/3 잼, 분반이 많은 과목 일곱: 20개 2.0초, 60개 2.2초, 1,000개 2.8초) 찾을 때는 넉넉히 찾아 두고
// (찾아 둔 수 20 → 60 → 140 → 300 …) TOP_K 개씩 목록에 올린다. 또 버튼이 '더 찾기'가 될 때 찾아 둔 것이 없으면 다음 몫을 미리 찾는다:
// 그러면 대개 누르자마자 붙는다. 찾아 둔 것(R.ahead)은 누르기 전까지 목록에도 제목의 수에도 넣지 않는다.
const rankMore = {
  job: null, // 돌고 있는 탐색 {opts, onProgress, done: Promise<"ok" | "cancelled" | "failed">}
  waiting: false, // 눌러 놓고 탐색을 기다리는 중(버튼은 aria-disabled, 500ms 뒤 '찾는 중')
  failed: false, // 눌렀는데 찾지 못했다(오류 줄 + '다시 시도')
  held: false, // 취소했거나 찾지 못했거나 다른 화면으로 가서 멈춘 뒤에는 다시 누를 때까지 미리 찾지 않는다
};

function renderMore() {
  const R = state.result;
  const rest = state.ranksShown < R.ranked.length; // 찾은 것 가운데 안 보인 것이 있다
  const more = hasMore(R);
  $("ranks-more").hidden = !rest && !more;
  if (rankMore.waiting) return; // 기다리는 동안의 라벨은 waitMore 가 그린다
  const failed = !rest && more && rankMore.failed;
  $("ranks-error").hidden = !failed;
  const btn = $("ranks-more-btn");
  btn.classList.toggle("small", failed); // 오류 줄 옆의 '다시 시도'는 다른 곳처럼 작은 텍스트 버튼
  btn.replaceChildren(rest ? "더 보기" : failed ? "다시 시도" : "더 찾기");
  if (failed) btn.setAttribute("aria-describedby", "ranks-error"); else btn.removeAttribute("aria-describedby");
  // 버튼이 '더 찾기'가 됐다: 찾아 둔 것이 없으면 다음 몫을 미리 찾는다. 워커에서만(화면 스레드에서 돌리면 누르지도 않았는데 화면이 멈춘다)
  if (!rest && !R.ahead.length && moreBeyond(R) && !rankMore.job && !rankMore.held && !rankMore.failed && startWorker()) seekMore(R, true);
}

/** 찾아 둔 것 뒤의 순위를 찾기 시작한다(결과를 만든 과목·조건 그대로 topK 만 키워서). 찾은 것은 R.ahead 에 둔다. spare = 누르기 전에 미리 찾는 것. */
function seekMore(R, spare) {
  const have = R.ranked.length + R.ahead.length;
  let want = have * 2 + TOP_K; // 찾아 둔 수가 20 → 60 → 140 → 300 …
  if (R.total && R.total.exact) want = Math.min(want, R.total.count);
  const courses = R.courses.map((c) => ({ id: c.id, name: c.name, cls: c.cls, sections: c.sections }));
  const job = { opts: { topK: want, home: R.home, mode: R.mode, count: false, spare }, onProgress: null, done: null };
  job.done = compute(courses, (done, ms) => { if (job.onProgress) job.onProgress(done, ms); }, job.opts).then((res) => {
    if (state.result !== R || res.ranked.length < have) return "failed"; // 앞쪽은 지난번과 같다는 약속이 깨졌다(올 수 없는 일)
    const tail = res.ranked.slice(have);
    sortSections(tail, R.courses);
    R.ahead = R.ahead.concat(tail);
    R.full = res.ranked.length >= want;
    if (res.total) R.total = res.total; // 달라는 것보다 적게 왔다: 그게 전부다
    return "ok";
  }, (e) => {
    if (e instanceof Cancelled) return "cancelled";
    console.error(e);
    return "failed";
  }).then((how) => {
    if (rankMore.job === job) rankMore.job = null;
    if (how !== "ok" && state.result === R) rankMore.held = true;
    return how;
  });
  rankMore.job = job;
  return job;
}

/**
 * 탐색을 기다리는 동안의 버튼. '시간표 만들기'와 같다: 500ms 가 지나도 안 끝나면 작은 스피너 + '찾는 중'(한번 뜨면 200ms 이상),
 * 10초를 넘을 수 있으면 '찾는 중 42%'와 오른쪽 '취소'. 미리 찾던 탐색이 돌고 있으면 그것을 기다린다. 그동안에도 카드를 고르고 요일을 바꿀 수 있다.
 */
async function waitMore(R) {
  const btn = $("ranks-more-btn"), cancel = $("ranks-cancel");
  rankMore.waiting = true;
  $("ranks-error").hidden = true;
  btn.classList.remove("small");
  btn.removeAttribute("aria-describedby");
  btn.replaceChildren("더 찾기");
  btn.setAttribute("aria-disabled", "true"); // disabled 는 초점을 잃게 해서 쓰지 않는다. 두 번째 누름은 rankMore.waiting 으로 무시한다
  const t0 = performance.now();
  let shownAt = 0, long = false;
  const label = (text) => btn.replaceChildren(h("span", { class: "spinner small", "aria-hidden": "true" }), text);
  const showSpinner = () => {
    if (shownAt) return;
    shownAt = performance.now();
    label("찾는 중");
    announce("시간표 찾는 중");
  };
  // 10초를 넘을 것 같으면 진행 정도와 '취소'. 누른 뒤로 기다린 시간에 남은 시간을 더해 본다(미리 찾던 탐색은 누르기 전부터 돌고 있었다)
  const onProgress = (done, ms) => {
    if (!shownAt) return;
    const waited = performance.now() - t0, left = done > 0 ? ms / done - ms : Infinity;
    if (!long && (waited > 5000 || (ms > 1000 && waited + left > LONG_MS))) {
      long = true;
      cancel.hidden = false;
    }
    const pct = Math.min(99, Math.floor(done * 100));
    if (long && pct >= 1) label(`찾는 중 ${pct}%`);
  };
  let timer = null, how = "ok";
  if (!rankMore.job && !startWorker() && estimate(R.courses) > HEAVY) { showSpinner(); await nextPaint(); } else timer = setTimeout(showSpinner, 500);
  if (state.result !== R || screen !== "result") how = "cancelled"; // 스피너를 그리는 사이 다른 화면으로 갔다
  else {
    const job = rankMore.job || seekMore(R, false);
    job.opts.spare = false; // 이제 누른 것이다(워커가 죽으면 화면 스레드에서라도 찾는다)
    job.onProgress = onProgress;
    how = await job.done;
  }
  clearTimeout(timer);
  if (shownAt && how !== "cancelled") { const rest = 200 - (performance.now() - shownAt); if (rest > 0) await sleep(rest); } // 한번 뜬 스피너는 200ms 이상
  rankMore.waiting = false;
  if (cancel.contains(document.activeElement)) btn.focus({ preventScroll: true }); // 숨기면 초점을 잃는다
  cancel.hidden = true;
  btn.removeAttribute("aria-disabled");
  return how;
}

/**
 * '더 찾기'(찾지 못한 뒤에는 '다시 시도')를 눌렀다. 찾아 둔 것이 있으면 바로, 없으면 찾는 동안 기다렸다가 다음 순위 TOP_K 개를 목록에 붙인다.
 * 이미 보이던 카드의 차례와 고른 카드는 그대로이고, 새 카드는 애니메이션 없이 붙고, 화면은 스크롤하지 않는다(버튼이 있던 자리에 새 카드의 첫 장).
 * 달라는 것보다 적게 왔으면 그게 전부라 버튼 자리가 없어지고 제목이 '전체 조합 N개를 찾았어요'가 된다.
 */
async function findMore() {
  const R = state.result;
  if (rankMore.waiting || !R) return;
  rankMore.failed = rankMore.held = false;
  const box = $("ranks-more"), btn = $("ranks-more-btn");
  const at = document.activeElement; // 누를 때의 초점
  let how = !R.ahead.length && moreBeyond(R) ? await waitMore(R) : "ok";
  if (state.result !== R) return; // 그사이 새 결과가 왔다
  if (how === "ok" && screen !== "result") how = "cancelled"; // 탐색이 막 끝났을 때 다른 화면으로 갔다: 찾은 것은 찾아 둔 채로 두고 목록은 그대로
  // 기다리는 동안 초점이 다른 데로 갔으면(카드를 골랐거나 Tab 으로 떠났다) 옮기지 않는다
  const stay = document.activeElement !== at && !box.contains(document.activeElement);
  if (how !== "ok") { // 취소했거나(다른 화면으로 간 것 포함) 찾지 못했다: 목록은 그대로
    rankMore.failed = how === "failed";
    renderMore();
    if (!stay && screen === "result") btn.focus({ preventScroll: true });
    if (rankMore.failed) announce("더 찾지 못했어요", "alert");
    return;
  }
  const from = R.ranked.length;
  R.ranked.push(...R.ahead.splice(0, TOP_K));
  state.ranksShown = R.ranked.length;
  // 새로 올린 조합에 더 이르거나 늦은 수업, 주말 수업이 있으면 시간 축과 요일 탭이 넓어진다(줄지는 않는다)
  const days = weekDays(R.ranked), axis = hourRange(R.ranked);
  axis[0] = Math.min(axis[0], R.axis[0]);
  axis[1] = Math.max(axis[1], R.axis[1]);
  const grew = days.length !== R.days.length || axis[0] !== R.axis[0] || axis[1] !== R.axis[1];
  R.days = days;
  R.axis = axis;
  // 목록 위쪽의 높이가 달라져도(시간 축이 넓어져 칸이 길어진다, 다 찾아서 제목의 희미한 줄이 없어진다) 보던 목록 자리가 밀리지 않게 달라진 만큼 스크롤을 맞춘다.
  // 목록을 보고 있을 때만이다(목록 머리가 상단 바 위로 지나갔을 때). 기다리는 동안 위로 올라가 시간표를 보고 있으면 그 자리가 그대로여야 한다.
  // 재는 동안 전환을 끈다(style.css 의 is-still): 동작 줄이기에서는 모든 속성이 1ms 전환이라 바뀐 높이가 한 틀 뒤에야 잡힌다
  // (스크롤 붙잡기가 없는 Safari 에서 목록이 그만큼 밀렸다. 크롬은 붙잡기가 대신 맞춰 준다)
  const top = $("ranks").getBoundingClientRect().top;
  const inList = top < document.querySelector("#view-result .topbar").getBoundingClientRect().bottom;
  let back = "";
  document.documentElement.classList.add("is-still");
  try {
    if (grew) { // 시간표와 미리보기 막대를 새 축으로 다시 그린다
      // 기다리는 동안 요일 탭이나 카드로 간 초점은 다시 그린 뒤 같은 탭·카드로 돌려준다
      const d = (stay && document.activeElement && document.activeElement.dataset) || {};
      back = d.rank ? `#ranks [data-rank="${d.rank}"]` : d.day ? `#daytabs [data-day="${d.day}"]` : "";
      renderResult();
    } else {
      $("rank-count").replaceChildren(...rankTitle(R));
      $("ranks").append(...R.ranked.slice(from).map((ev, i) => rankItem(ev, from + i)));
      renderMore();
    }
    if (inList) window.scrollBy(0, $("ranks").getBoundingClientRect().top - top);
  } finally {
    document.documentElement.classList.remove("is-still");
  }
  if (back) document.querySelector(back)?.focus({ preventScroll: true });
  // 초점은 새 카드의 첫 장으로(버튼은 새 카드 뒤에 있어서, 버튼에 두면 스무 장을 거슬러 올라가야 한다). 새 카드가 없으면(다 찾았다) 마지막 카드로
  if (!stay) $("ranks").querySelector(`[data-rank="${Math.min(from, R.ranked.length - 1)}"]`)?.focus({ preventScroll: true });
  announce(foundText(R)); // 초점이 카드로 가도 목록 제목의 수가 바뀐 것은 읽히지 않는다
}

function selectRank(i) {
  if (i !== state.rank) {
    const was = state.rank, list = $("ranks");
    state.rank = i;
    updateTabs();
    renderDay({ fade: true });
    // 바뀌는 두 장만 다시 그린다(더 찾기로 목록이 수백 장이 되면 다 다시 그리는 데만 0.1~0.4초가 걸린다. 폰은 그 서너 배)
    for (const k of [was, i]) list.children[k]?.replaceWith(rankItem(state.result.ranked[k], k));
    list.children[i]?.querySelector(".rank-hit").focus({ preventScroll: true });
    announce(`${i + 1}위 시간표`);
  }
  // 두 칸이 화면 밖이면 칸이 보이게 스크롤한다
  const bar = document.querySelector("#view-result .topbar").getBoundingClientRect().bottom;
  const panes = $("panes").getBoundingClientRect();
  if (panes.top < bar || panes.bottom > window.innerHeight) $("daytabs").scrollIntoView({ block: "start", behavior: reduceMotion.matches ? "auto" : "smooth" });
}

$("ranks").addEventListener("click", (e) => {
  const b = e.target.closest("[data-rank]");
  if (b) selectRank(Number(b.dataset.rank));
});
$("ranks-more-btn").addEventListener("click", () => {
  if (rankMore.waiting) return;
  const from = state.ranksShown;
  if (from >= state.result.ranked.length) { findMore(); return; }
  state.ranksShown += RANKS_STEP;
  renderRanks({ focus: from });
});
$("ranks-cancel").addEventListener("click", () => cancelCompute());

// ---------------------------------------------------------------- 정보 화면, 자료 출처, 오픈소스 라이선스

/** 웹 Safari(iPhone·iPad 의 Safari 탭)에서만 '홈 화면에 추가' 안내. navigator.standalone 은 Safari 탭에서만 false 다. */
function isSafariTab() {
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  return SHELL === "web" && ios && navigator.standalone === false;
}

// ---- 이벤트 테마(디자인 규칙 '이벤트 테마'): 정해 둔 기간에 저절로 켜진다. 한 벌뿐이라 기기가 다크여도 같은 모습이다.
// [값, 이름, 시작 MM-DD, 끝 MM-DD(그날까지, 기기 날짜), 상태 바 색 = style.css 의 그 테마 --bg, 스토어 앱의 시스템 바 글자("DARK" = 짙은 바탕 위 밝은 글자, "LIGHT" = 그 반대)].
// 기간은 한 해 안에 두고(해를 넘기지 않는다) 서로 겹치지 않게 한다. index.html 머리의 스크립트가 같은 판단으로 그리기 전에 먼저 건다(테마를 더하면 거기도 고친다)
const THEMES = [["xmas", "크리스마스", "12-01", "12-25", "#103924", "DARK"]];
const BASE_BAR = ["#eef0ff", "#16171b"]; // 기본 테마의 상태 바 색(라이트, 다크)
/** 지금 켤 이벤트 테마(없으면 null). event 는 돌아가기와 물어본 것을 기억하는 이름이다: 해마다 달라서('xmas-2026') 그 해 그 테마에만 남는다.
 *  시험용 주소(?theme=xmas)는 기간 밖에서도 켜고, 그때 고른 것이 실제 기간에 남지 않게 따로 기억한다('xmas-test'). */
function seasonTheme(now = new Date()) {
  const test = new URLSearchParams(location.search).get("theme");
  const md = `${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`;
  const forced = THEMES.find(([id]) => id === test);
  const t = forced || THEMES.find(([, , from, to]) => md >= from && md <= to);
  return t ? { id: t[0], name: t[1], event: `${t[0]}-${forced ? "test" : now.getFullYear()}`, bar: t[4], bars: t[5] } : null;
}
let season = seasonTheme();
const themeOn = () => !!season && store.get("themeOff", "") !== season.event;
let themedBars = false; // 스토어 앱의 시스템 바 글자색을 테마에 맞춰 바꿔 두었는지
function applyTheme(on) {
  const t = on ? season : null;
  if (t) document.documentElement.dataset.theme = t.id; else delete document.documentElement.dataset.theme;
  const metas = document.querySelectorAll('meta[name="theme-color"]');
  if (metas[0]) metas[0].content = t ? t.bar : BASE_BAR[0];
  if (metas[1]) metas[1].content = t ? t.bar : BASE_BAR[1];
  // 스토어 앱은 화면을 상태 바 밑까지 그린다. 상태 바의 시계·아이콘이 테마 바탕 위에서 보이게 글자색을 맞추고, 테마를 끄면 기기 설정대로 돌린다
  if (IN_APP && (t || themedBars)) {
    themedBars = !!t;
    try { capacitor.Plugins.SystemBars.setStyle({ style: t ? t.bars : "DEFAULT" }).catch(() => null); } catch { /* 없으면 그대로 둔다 */ }
  }
  mapColorCache = null; // 다크 기기에서는 테마를 켜고 끌 때 지도 색도 바뀐다
  for (const mp of [maps.small, maps.full]) if (mp) mp.base.redraw();
}
applyTheme(themeOn());
// 앱을 켜 둔 채 기간이 시작되거나 끝나도 보고 있는 동안에는 바꾸지 않는다. 다른 데 갔다가 돌아올 때(앱을 다시 열 때) 날짜를 다시 본다:
// 폰은 앱을 며칠씩 내려만 두기도 해서, 새로 켤 때만 보면 기간이 끝난 테마가 남는다
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "visible") return;
  const now = seasonTheme();
  if ((now ? now.event : "") === (season ? season.event : "")) return;
  season = now;
  if ($("theme-ask").open) $("theme-ask").close(); // 지난 테마를 묻던 시트는 거둔다
  applyTheme(themeOn());
  renderInfo();
  setTimeout(askTheme, 400);
});
/** 켜거나 끈다(정보 화면의 테마 행, 묻는 시트). 고른 것은 그 해 그 테마에만 남는다. */
function setTheme(on) {
  if (!season) return;
  if (on) store.del("themeOff"); else store.set("themeOff", season.event);
  store.set("themeAsked", season.event); // 스스로 골랐으면 다시 묻지 않는다
  applyTheme(on);
}
/** 이벤트 테마가 켜진 뒤 처음 들어왔을 때 한 번 묻는다: '기본 테마로 돌아갈까요?' [닫기] [돌아가기].
 *  시간표를 만들어 본 적이 없는 사람에게는 묻지 않는다(돌아갈 '원래'를 본 적이 없다). 닫기·바깥 누르기·뒤로 가기는 그대로 둔다는 뜻이다. */
function askTheme() {
  if (!themeOn() || store.get("themeAsked", "") === season.event || !store.get("made", false)) return;
  if (screen !== "input" || document.querySelector("dialog[open]")) return; // 그새 다른 화면이나 시트를 열었으면 끼어들지 않고 다음에 켤 때 묻는다
  store.set("themeAsked", season.event);
  openSheet($("theme-ask"));
}
$("theme-ask-yes").addEventListener("click", () => { setTheme(false); renderInfo(); closeSheet($("theme-ask")); });

function renderInfo() {
  const next = (key, text) => h("button", { type: "button", class: "info-row", "data-info": key }, h("span", {}, text), icon(I.right, 20));
  const out = (href, text) => h("a", { class: "info-row", href, target: "_blank", rel: "noopener" }, h("span", {}, text), icon(I.out, 20));
  // 테마 행은 이벤트 테마의 기간에만 있다: 기본 | 그 테마. 보이는 값 위에 투명한 select 를 덮는다(과목 시트의 강의실 값과 같은 방식, style.css .info-pick)
  let themeRow = null;
  if (season) {
    const names = { "": "기본", [season.id]: season.name };
    const theme = h("select", { id: "theme", "aria-label": "테마" }, h("option", { value: "" }, names[""]), h("option", { value: season.id }, season.name));
    theme.value = themeOn() ? season.id : "";
    const value = document.createTextNode(names[theme.value]);
    theme.addEventListener("change", () => { setTheme(!!theme.value); value.data = names[theme.value]; });
    themeRow = h("label", { class: "info-row" }, h("span", {}, "테마"), h("span", { class: "info-pick" }, value, icon(I.down, 20), theme));
  }
  const rows = [
    themeRow,
    next("calc", "이동시간 계산 방법"),
    next("sources", "자료 출처"),
    PRIVACY_URL ? out(PRIVACY_URL, "개인정보 처리방침") : null,
    next("licenses", "오픈소스 라이선스"),
    CONTACT_URL ? out(CONTACT_URL, "문의하기") : null,
    isSafariTab() ? next("a2hs", "홈 화면에 추가") : null,
    REVIEW_URL[SHELL] ? out(REVIEW_URL[SHELL], "리뷰 남기기") : null,
    h("div", { class: "info-row" }, h("span", {}, "버전"), h("span", { class: "v" }, APP_VERSION)),
  ];
  $("info-list").replaceChildren(...rows.filter(Boolean).map((r) => h("li", {}, r)));
}

$("info-list").addEventListener("click", (e) => {
  const b = e.target.closest("[data-info]");
  if (!b) return;
  const k = b.dataset.info;
  if (k === "calc") openSheet($("calc-sheet"), b);
  else if (k === "a2hs") openSheet($("a2hs-sheet"), b);
  else go("page", { page: k });
});

let pageName = "sources";
function renderPage() {
  const sources = pageName !== "licenses";
  $("page-title").textContent = sources ? "자료 출처" : "오픈소스 라이선스";
  const link = (href, text) => h("a", { href, target: "_blank", rel: "noopener" }, text);
  const rows = sources ? [
    ["과목", ["서울대학교 수강편람", state.semesterMeta.updated ? ` · ${asofLong(state.semesterMeta.updated)}` : ""]],
    ["건물", "서울대학교 캠퍼스맵"],
    ["길", link("https://moreadorecampus.com/", "캠퍼스 마법 지도")],
    ["경사", "국토지리정보원 수치지형도 · 공공누리 제1유형"],
    ["지도", ["국토지리정보원 수치지형도 · 공공누리 제1유형, ", link("https://www.openstreetmap.org/copyright", "© OpenStreetMap contributors"), " · ODbL"]],
  ] : [
    ["지도 표시", [link("https://github.com/Leaflet/Leaflet/blob/main/LICENSE", "Leaflet"), " · BSD-2-Clause"]],
    ["글꼴", [link("https://github.com/orioncactus/pretendard/blob/main/LICENSE", "Pretendard"), " · SIL OFL 1.1"]],
    ["로고 글꼴", [link("https://github.com/google/fonts/blob/main/ofl/fredoka/OFL.txt", "Fredoka"), " · SIL OFL 1.1"]],
    ["지도 자료", [link("https://www.openstreetmap.org/copyright", "OpenStreetMap"), " · ODbL"]],
    ["지도·경사 자료", [link("https://www.kogl.or.kr/info/licenseType1.do", "국토지리정보원 수치지형도"), " · 공공누리 제1유형"]],
  ];
  $("page-list").replaceChildren(...rows.map(([k, v]) => h("li", {}, h("span", { class: "k" }, k), h("span", { class: "v" }, v))));
}

// ---------------------------------------------------------------- 화면 이동과 뒤로 가기
// 화면(결과, 정보, 자료 출처·라이선스, 전체 화면 지도)만 기록을 남긴다. 요일 탭, 순위 선택, 시트는 남기지 않는다.
// 새로 켜면 늘 입력 화면에서 시작한다.

const VIEWS = ["input", "result", "map", "info", "page"];
const H1 = { result: "result-title", map: "map-title", info: "info-title", page: "page-title" };
let screen = "input", depth = 0;
const scrollOf = {}, openers = {};

function go(name, extra = {}) {
  openers[name] = document.activeElement;
  depth += 1;
  history.pushState({ view: name, depth, ...extra }, "", `#${extra.page || name}`);
  show(name, "forward", extra);
}

function back() {
  if (depth > 0) history.back();
  else show("input", "back");
}

function titleOf(name) {
  const t = name === "input" ? "" : $(H1[name]).textContent;
  return t ? `${t} · TT Wizard` : "TT Wizard";
}

/** View Transitions 가 되면 결과·정보 화면이 24px 옆에서 밀려 들어오고(300ms), 뒤로 갈 때는 반대로(200ms). 안 되면 바로 바뀐다. */
function transition(apply, dir) {
  if (!document.startViewTransition || reduceMotion.matches || document.visibilityState !== "visible") { apply(); return; }
  const root = document.documentElement;
  root.dataset.nav = dir;
  const t = document.startViewTransition(apply);
  const done = () => { if (root.dataset.nav === dir) delete root.dataset.nav; };
  t.finished.then(done, done);
}

function show(name, dir, extra = {}) {
  if ((name === "result" || name === "map") && !state.result) name = "input";
  if (name !== "input" || screen === "result") cancelCompute(); // 결과 화면을 떠나면 더 찾기도 멈춘다
  const from = screen;
  scrollOf[from] = window.scrollY;
  if (from === "input") store.set("scroll", window.scrollY);
  if (name === "page") pageName = extra.page || pageName;
  const apply = () => {
    for (const v of VIEWS) {
      const el = $(`view-${v}`);
      el.hidden = v !== name;
      el.querySelector("main").hidden = v !== name;
    }
    screen = name;
    if (name === "result") renderResult();
    if (name === "map") renderFullMap();
    if (name === "page") renderPage();
    document.title = titleOf(name);
    if (name !== "input") hideSnackbar();
    window.scrollTo(0, dir === "back" ? scrollOf[name] || 0 : 0);
    if (dir === "forward" && H1[name]) $(H1[name]).focus({ preventScroll: true });
    else if (dir === "back") {
      const el = openers[from];
      if (el && el.isConnected && !el.closest("[hidden]")) el.focus({ preventScroll: true });
      else if (name === "input") $("run").focus({ preventScroll: true });
    }
    if (name === "input") showUpdateIfReady();
  };
  transition(apply, dir);
}

window.addEventListener("popstate", (e) => {
  for (const d of document.querySelectorAll("dialog[open]")) d.close(); // 화면이 바뀌면 열린 시트도 함께 닫는다
  const st = e.state && e.state.view ? e.state : { view: "input", depth: 0 };
  const dir = (st.depth || 0) < depth ? "back" : "forward";
  depth = st.depth || 0;
  show(st.view, dir, st);
});

// ---------------------------------------------------------------- 스낵바 (되돌리기, 새 버전)
// 한 번에 하나, 5초. 초점이 들어가 있거나 누르고 있는 동안에는 사라지지 않는다

let snackTimer = null, snackFn = null;
function showSnackbar(text, action, fn) {
  const bar = $("snackbar");
  $("snackbar-text").textContent = text;
  $("snackbar-action").textContent = action;
  snackFn = fn;
  bar.hidden = true;
  void bar.offsetWidth; // 다시 올라오게
  bar.hidden = false;
  placeSnackbar();
  armSnackbar();
}
/** 넓은 화면 입력 화면: 시간표 만들기가 오른쪽 칸 안(sticky)이라 자리가 그때그때 달라서, 스낵바를 그 버튼 바로 위에 같은 폭으로 띄운다. */
function placeSnackbar() {
  const bar = $("snackbar");
  bar.style.bottom = bar.style.left = bar.style.right = bar.style.maxWidth = "";
  if (bar.hidden || screen !== "input" || !twoPane.matches) return;
  const r = $("run").getBoundingClientRect();
  if (!r.width || r.bottom <= 0 || r.top >= innerHeight) return;
  bar.style.bottom = `${Math.round(innerHeight - r.top + 8)}px`;
  bar.style.left = `${Math.round(r.left)}px`;
  bar.style.right = `${Math.round(document.documentElement.clientWidth - r.right)}px`;
  bar.style.maxWidth = "none";
}
window.addEventListener("scroll", placeSnackbar, { passive: true });
window.addEventListener("resize", placeSnackbar);
function armSnackbar() {
  clearTimeout(snackTimer);
  snackTimer = setTimeout(hideSnackbar, 5000);
}
function hideSnackbar() {
  clearTimeout(snackTimer);
  $("snackbar").hidden = true;
  snackFn = null;
}
{
  const bar = $("snackbar");
  bar.addEventListener("focusin", () => clearTimeout(snackTimer));
  bar.addEventListener("focusout", () => { if (!bar.hidden) armSnackbar(); });
  bar.addEventListener("pointerdown", () => clearTimeout(snackTimer));
  for (const t of ["pointerup", "pointercancel"]) bar.addEventListener(t, () => { if (!bar.hidden && !bar.contains(document.activeElement)) armSnackbar(); });
  $("snackbar-action").addEventListener("click", () => { const f = snackFn; hideSnackbar(); if (f) f(); });
}

// ---------------------------------------------------------------- 설치(웹), 새 버전, 연결 상태

// 서비스 워커: 설치한 앱이 네트워크 없이도 열리게(web/sw.js). https 나 localhost 에서만 된다. 스토어 앱(안드로이드·iOS)은 화면 파일이
// 앱에 들어 있어 쓰지 않는다(새 버전도 스토어 업데이트라 스낵바가 없다)
let updateReady = false, updateShown = false;
if (!IN_APP && "serviceWorker" in navigator && (location.protocol === "https:" || ["localhost", "127.0.0.1"].includes(location.hostname))) {
  const hadController = Boolean(navigator.serviceWorker.controller);
  navigator.serviceWorker.register("sw.js").catch(() => null);
  // 새 워커가 이 화면을 맡으면 새 버전이 올라온 것(처음 설치될 때는 빼고)
  navigator.serviceWorker.addEventListener("controllerchange", () => {
    if (!hadController) return;
    updateReady = true;
    showUpdateIfReady();
  });
}
/** 새 버전 스낵바는 입력 화면에서만. 결과를 보는 중이면 돌아올 때까지 미룬다. */
function showUpdateIfReady() {
  if (!updateReady || updateShown || screen !== "input") return;
  updateShown = true;
  showSnackbar("새 버전이 있어요", "새로고침", () => location.reload());
  announce("새 버전이 있어요");
}

// 설치 권유(웹 브라우저만): 첫 시간표를 만든 뒤 상단 바의 작은 '설치'. 시스템 창을 닫으면 버튼을 없애고 다시 두지 않는다
let installPrompt = null;
window.addEventListener("beforeinstallprompt", (e) => {
  e.preventDefault();
  installPrompt = e;
  updateInstall();
});
function updateInstall() {
  $("install").hidden = !(SHELL === "web" && installPrompt && store.get("made", false) && !store.get("installDismissed", false));
}
$("install").addEventListener("click", async () => {
  if (!installPrompt) return;
  const p = installPrompt;
  installPrompt = null;
  p.prompt();
  const choice = await p.userChoice.catch(() => null);
  if (!choice || choice.outcome !== "accepted") store.set("installDismissed", true);
  updateInstall();
  $("open-info").focus({ preventScroll: true });
});
window.addEventListener("appinstalled", () => { installPrompt = null; updateInstall(); });

function renderOnline() {
  $("offline-tag").hidden = navigator.onLine !== false;
}
window.addEventListener("offline", renderOnline);
window.addEventListener("online", () => {
  renderOnline();
  if (!basemap && (maps.small || maps.full)) loadBasemap(); // 처음 받다 끊겼으면 다시
});

// 외부 링크(처리방침·문의·출처)는 앱 밖으로. 스토어 앱은 Capacitor Browser(iOS 인앱 Safari, 안드로이드 Custom Tab), 웹은 새 탭
document.addEventListener("click", (e) => {
  const a = e.target.closest('a[target="_blank"]');
  const browser = IN_APP && capacitor?.Plugins?.Browser;
  if (!a || !browser) return;
  e.preventDefault();
  browser.open({ url: a.href });
});

// ---------------------------------------------------------------- 시작

$("year").addEventListener("change", onYearChange);
$("term").addEventListener("change", () => switchSemester(`${$("year").value}-${$("term").value}`));
$("banner-retry").addEventListener("click", () => {
  const f = bannerRetry;
  hideBanner();
  if (!$("year").hidden) $("year").focus({ preventScroll: true });
  if (f) f();
});

const q = $("q");
q.addEventListener("input", () => renderResults());
q.addEventListener("keydown", (e) => {
  if (e.key !== "Enter") return;
  if (e.isComposing || e.keyCode === 229) return; // 한글 조합 중의 Enter 는 무시한다
  e.preventDefault();
  if (state.loaded && findCourses(q.value).hits.length) saveRecent(q.value);
  q.blur(); // 키보드만 닫는다
});
// 폰(한 칸): 빈 검색창에 초점이 오면 최근 검색어를 띄우고, 초점이 검색창과 그 카드 밖으로 나가면 내린다. 다른 곳을 누른 순간
// 카드가 사라져 누른 자리가 밀리지 않게(눌림이 엉뚱한 곳에 가지 않게) 조금 뒤에 내린다. 넓은 화면은 초점과 상관없이 늘 둔다
q.addEventListener("focus", () => { if (!q.value.trim()) renderResults(); });
for (const el of [q, $("results")]) {
  el.addEventListener("focusout", () => setTimeout(() => {
    if (!twoPane.matches && !q.value.trim() && !searchFocused()) renderResults();
  }, 250));
}
twoPane.addEventListener("change", () => { renderResults(); placeSnackbar(); });
// 지운 칩·고른 칩은 다시 그리면 사라지므로 초점을 옮긴다. 키보드(detail 0)와 마우스로 눌렀을 때만:
// 터치로 누를 때 검색창에 초점을 주면 화상 키보드가 올라온다(크롬은 누른 버튼에 초점이 간다)
const keptFocus = (e, el) => document.activeElement === el && (e.detail === 0 || !coarsePointer.matches);
$("recent-list").addEventListener("click", (e) => {
  const del = e.target.closest("[data-del]");
  if (del) {
    const had = keptFocus(e, del);
    const i = recent.indexOf(del.dataset.del);
    setRecent(recent.filter((x) => x !== del.dataset.del));
    renderResults();
    // 키보드로 지웠으면 초점을 다음(없으면 앞) 검색어로, 다 지웠으면 검색창으로
    if (had) ($("recent-list").querySelectorAll(".chip-q")[Math.min(i, recent.length - 1)] || q).focus({ preventScroll: true });
    return;
  }
  const b = e.target.closest("[data-q]");
  if (!b) return;
  const had = keptFocus(e, b);
  q.value = b.dataset.q;
  saveRecent(b.dataset.q); // 다시 쓴 검색어는 맨 앞으로
  renderResults();
  if (had) q.focus({ preventScroll: true });
});
$("recent-clear").addEventListener("click", (e) => {
  const had = keptFocus(e, e.currentTarget);
  setRecent([]);
  renderResults();
  if (had) q.focus({ preventScroll: true });
});
// 가상 키보드가 떠 있는 동안에만 하단 주요 버튼을 숨긴다. 초점만 보면 키보드를 내려도(안드로이드 뒤로, 키보드 내림 버튼)
// 검색창에 초점이 남아 버튼이 계속 안 보였다(10/1 사용자 제보). 키보드는 보이는 높이가 키보드 없을 때보다 크게 줄어든 것으로 안다:
// 브라우저(iOS Safari·Chrome)는 visual viewport 만, 앱 껍데기(WebView)는 창 높이가 줄어든다. 주소창이 접히고 펴지는 차이(~80px)는 넘지 않는다
const vv = window.visualViewport;
const viewH = () => (vv ? vv.height * vv.scale : window.innerHeight);
let fullH = 0; // 키보드 없을 때의 높이. 화면을 돌리면 다시 잰다
let typingGrace = 0; // 초점을 받은 뒤 키보드가 올라오는 동안(버튼이 키보드를 따라 올라왔다 사라지지 않게 먼저 숨긴다)
function updateTyping() {
  const cur = viewH();
  if (cur > fullH) fullH = cur;
  const typing = document.activeElement === q && coarsePointer.matches && (fullH - cur > 120 || performance.now() < typingGrace);
  document.body.classList.toggle("is-typing", typing);
}
q.addEventListener("focus", () => { typingGrace = performance.now() + 800; updateTyping(); setTimeout(updateTyping, 850); });
q.addEventListener("blur", () => { typingGrace = 0; updateTyping(); });
(vv || window).addEventListener("resize", updateTyping);
const onRotate = () => { fullH = 0; updateTyping(); };
if (window.screen.orientation) window.screen.orientation.addEventListener("change", onRotate); // screen 은 이 파일에서 지금 화면 이름이라 window.screen
else window.addEventListener("orientationchange", onRotate);
updateTyping();
$("q-clear").addEventListener("click", () => {
  q.value = "";
  renderResults();
  q.focus();
});
// 검색창에 초점이 있을 때 담기·지우기·최근 검색어를 눌러도 키보드가 닫히지 않게 초점을 옮기지 않는다
for (const el of [$("results-list"), $("q-clear"), $("recent")]) {
  el.addEventListener("mousedown", (e) => { if (document.activeElement === q && e.target.closest("button")) e.preventDefault(); });
}
$("results-list").addEventListener("click", (e) => {
  const b = e.target.closest(".btn-add");
  const c = b && state.byId.get(b.dataset.id);
  if (!c) return;
  if (isPicked(c.id)) removeCourse(c.id);
  else { addCourse(c.id); saveRecent(q.value); }
  setAddButton(b, c.name, isPicked(c.id));
});
// 과목 둘러보기: 목록을 바꾸면 새 목록을 맨 위부터(선택칸이 위로 지나갔으면 선택칸 바로 아래부터) 보이고 과목 수를 읽는다
$("browse-select").addEventListener("change", (e) => {
  browseKey = e.target.value;
  store.set("browse", browseKey);
  renderBrowse(true);
  const box = $("results"), top = $("browse").getBoundingClientRect().top - box.getBoundingClientRect().top + box.scrollTop;
  if (box.scrollTop > top) box.scrollTop = top;
  announce(`과목 ${browseCourses().length}개`);
});
$("browse-list").addEventListener("click", (e) => {
  const b = e.target.closest(".btn-add");
  const c = b && state.byId.get(b.dataset.id);
  if (!c) return;
  if (isPicked(c.id)) removeCourse(c.id);
  else addCourse(c.id);
  setAddButton(b, c.name, isPicked(c.id));
});
$("results-more").addEventListener("click", () => {
  resultsShown += RESULTS_STEP;
  renderResults({ more: true });
});

$("picked-list").addEventListener("click", (e) => {
  const rm = e.target.closest("[data-remove]");
  if (rm) { removeCourse(rm.dataset.remove, { fromList: true }); return; }
  const hit = e.target.closest("[data-open]");
  if (hit && state.loaded) openCourseSheet(hit.dataset.open, hit);
});
$("picked-retry").addEventListener("click", run);
$("run").addEventListener("click", run);
$("cancel").addEventListener("click", cancelCompute);
$("open-info").addEventListener("click", () => go("info"));
$("open-calc").addEventListener("click", (e) => openSheet($("calc-sheet"), e.currentTarget));
$("open-sources").addEventListener("click", () => go("page", { page: "sources" }));
$("map-expand").addEventListener("click", () => go("map"));
for (const b of document.querySelectorAll("[data-back]")) b.addEventListener("click", back);

// 칸 크기가 바뀌면(화면 회전, 폭 구간) 시간표 높이와 지도를 다시 맞춘다. 그린 때와 크기가 같으면 두지 않는다
// (결과 화면이 처음 뜰 때도 불리므로, 첫 결과의 경로 그리기를 끊지 않게)
let resizeTimer = null;
const resizeObserver = new ResizeObserver((entries) => {
  for (const en of entries) {
    const { width, height } = en.contentRect;
    const prev = drawnSize.get(en.target);
    if (!width || !height || (prev && Math.abs(prev[0] - width) < 1 && Math.abs(prev[1] - height) < 1)) continue;
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(() => {
      if (!state.result) return;
      if (screen === "result") renderDay();
      if (screen === "map") renderFullMap();
    }, 150);
  }
});
resizeObserver.observe($("panes"));
resizeObserver.observe($("map-full"));

// 화면이 숨겨질 때 한 번 더 저장한다(앱이 꺼졌다 켜져도 그대로)
document.addEventListener("visibilitychange", () => {
  if (document.visibilityState !== "hidden") return;
  if (state.semester) { savePicks(); saveOverrides(); }
  if (screen === "input") store.set("scroll", window.scrollY);
});

history.scrollRestoration = "manual";
history.replaceState({ view: "input", depth: 0 }, "", location.pathname + location.search);
// 교과구분 색 풀이: 결과 화면 시간표 아래, 입력 화면 담은 과목 아래
for (const id of ["cls-legend", "picked-legend"]) {
  $(id).replaceChildren(...CLS_GROUPS.map(([name, key]) => h("span", {}, h("span", { class: "dot", "aria-hidden": "true", style: { background: `var(--cls-${key})` } }), name)));
}
renderInfo();
renderOnline();
renderResults(); // 검색창 지우기 단추와 결과 카드(자료를 받기 전에는 두지 않는다)
start();
setTimeout(askTheme, 400); // 첫 화면이 그 테마로 보인 뒤에 묻는다
