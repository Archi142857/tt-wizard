// TT Wizard 화면(디자인 규칙 v3). 자료(data/*.json)는 scripts/export_web.py 가 만들고, 탐색은 engine.js 가 브라우저에서 한다.
// 화면은 입력 · 결과 · 정보 셋이고 전체 화면 지도, 자료 출처·오픈소스 라이선스가 그 위에 뜬다. 화면만 방문 기록(pushState)을
// 남기고 시트(<dialog>)는 남기지 않는다. 화면 문구는 디자인 규칙 '문구'를 따른다(문장은 해요체 한 줄, 그 밖에는 명사구).
import { DAY_KO, parseCourses, TravelMatrix, search, findConflicts, countFeasible, routeLine } from "./engine.js";

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------- 어디서 도는지: 웹, 설치한 PWA, Android 앱(TWA), iOS 앱(Capacitor)
// 앱마다 다른 것(설치 안내, 새 버전 알림, 외부 링크, 햅틱)은 이 값으로만 가른다. CSS 는 html[data-shell] 을 본다
const session = {
  get(k) { try { return sessionStorage.getItem(k); } catch { return null; } },
  set(k, v) { try { sessionStorage.setItem(k, v); } catch { /* 없어도 된다 */ } },
};
const query = new URLSearchParams(location.search);
if (document.referrer.startsWith("android-app://") || query.get("src") === "twa") session.set("twa", "1");
const SHELL = window.Capacitor?.isNativePlatform?.() ? "ios"
  : session.get("twa") ? "twa"
  : (matchMedia("(display-mode: standalone)").matches || navigator.standalone) ? "pwa" : "web";
document.documentElement.dataset.shell = SHELL;
if (query.has("src")) { // TWA 시작 주소의 ?src=twa 는 판별에만 쓰고 지운다
  query.delete("src");
  const rest = query.toString();
  history.replaceState(null, "", location.pathname + (rest ? `?${rest}` : ""));
}

// ---------------------------------------------------------------- 설정

const APP_VERSION = "0.6.0";
// 정보 화면 링크. 주소가 정해지면 넣는다(비어 있으면 그 행을 보이지 않는다)
const PRIVACY_URL = ""; // 개인정보 처리방침 공개 페이지(스토어에 적는 주소와 같게)
const CONTACT_URL = ""; // 문의 페이지(App Store 지원 URL과 같은 곳)
const REVIEW_URL = { twa: "", ios: "" }; // 스토어 앱 페이지(스토어 앱에서만 '리뷰 남기기')
const TOP_K = 20; // 한 번에 찾는 조합 수. 후보 카드는 6개씩 보인다(넓은 화면의 2·3열이 꽉 차게)
const RESULTS_STEP = 8;
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
const collator = new Intl.Collator("ko");

const state = {
  campus: null, routes: null, routesLoading: null, travel: {},
  current: "", semesters: [], semester: "", semesterMeta: {}, cache: new Map(), loading: false, loaded: false,
  courses: [], byId: new Map(),
  // 담은 과목 [{id, excluded: Set<분반 키>, name, cls, credit, dept}]. 이름 등은 자료에서 사라진 과목을 보이려고 함께 저장한다
  picks: [],
  overrides: {}, // 분반 키 → {rooms: {수업 번호: 건물}, times: [[요일, 시작, 끝, 건물]]} 강의실·시간 미정을 직접 넣은 것
  home: "919", homeOther: "", mode: "slope",
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
function placeLabel(b) {
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

/** 분반 표기는 어디서나 061(나민애). 교수가 없으면 061(교수 미정). */
function instructorOf(s) {
  return String(s.instructor || "").trim() || "교수 미정";
}
function sectionLabel(s) {
  return `${s.no}(${instructorOf(s)})`;
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

let buildingOpts = null;
/** 고를 수 있는 건물: 이동시간 자료(경로·경사)가 있는 강의 건물. 출발 후보(기숙사·정문)는 뺀다. [[건물, '301동 제1공학관']] */
function buildingOptions() {
  if (!buildingOpts) {
    const nat = (b) => b.split(/(\d+)/).map((x) => (/^\d+$/.test(x) ? x.padStart(5, "0") : x)).join("");
    const homes = new Set((state.campus.homes || []).map(([id]) => id));
    buildingOpts = state.campus.ids
      .filter((b) => !homes.has(b) && b !== "GATE")
      .sort((a, b) => nat(a).localeCompare(nat(b)))
      .map((b) => { const name = (state.campus.buildings[b] || [""])[0]; return [b, `${b}동${name ? " " + name : ""}`]; });
  }
  return buildingOpts;
}

function buildingSelect(value, attrs) {
  const el = h("select", attrs, h("option", { value: "" }, "미정"), buildingOptions().map(([b, text]) => h("option", { value: b }, text)));
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
    buildingOpts = null;
    state.current = (index && index.current) || (campus.meta || {}).semester || "";
    state.semesters = index && index.list && index.list.length ? index.list : [[state.current, "courses.json"]];
    migrateStore(state.current);
    const homes = (campus.homes || []).map(([b]) => b);
    const saved = store.get("home", homes[0] || "919");
    state.home = homes.includes(saved) || campus.ids.includes(saved) ? saved : homes[0] || campus.ids[0];
    state.homeOther = store.get("homeOther", "");
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
const fitTerm = () => { fitSelect($("year")); fitSelect($("term")); };
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

const CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";
function choOf(ch) {
  const code = ch.charCodeAt(0) - 0xac00;
  return code >= 0 && code < 11172 ? CHO[Math.floor(code / 588)] : ch;
}

/** 검색용 글자 열과 각 글자의 원래 위치. skip 에 맞는 글자는 빼고 소문자로(cho 면 음절을 초성으로) 바꾼다. */
function keyChars(text, skip = /\s/, cho = false) {
  const s = String(text || "");
  const keys = [], pos = [];
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (skip.test(ch)) continue;
    const low = ch.toLowerCase();
    keys.push(cho ? choOf(ch) : low.length === 1 ? low : ch);
    pos.push(i);
  }
  return { key: keys.join(""), pos };
}

function indexCourses() {
  state.byId = new Map(state.courses.map((c) => [c.id, c]));
  for (const c of state.courses) {
    c.nameKey = keyChars(c.name).key;
    c.choKey = keyChars(c.name, /\s/, true).key;
    c.idKey = keyChars(c.id, /[\s.]/).key; // 교과목번호는 공백·마침표·대소문자를 무시한다
    c.deptKey = keyChars(c.dept).key;
    c.profs = [...new Set(c.sections.map((s) => String(s.instructor || "").trim()).filter(Boolean))];
    c.profKeys = c.profs.map((p) => keyChars(p).key);
  }
}

/** 과목명(앞부분이 맞는 것 먼저) → 교과목번호 → 학과 → 교수 순. 초성만 넣으면 과목명 초성으로 찾는다. */
function findCourses(raw) {
  const q = keyChars(raw).key;
  const qId = keyChars(raw, /[\s.]/).key;
  const onlyCho = /^[ㄱ-ㅎ]+$/.test(q);
  const hits = [];
  if (!q) return { q, qId, hits };
  for (const c of state.courses) {
    let rank = -1, kind = "", prof = "";
    if (onlyCho) {
      if (c.choKey.includes(q)) { rank = c.choKey.startsWith(q) ? 0 : 1; kind = "cho"; }
    } else if (c.nameKey.startsWith(q)) { rank = 0; kind = "name"; }
    else if (c.nameKey.includes(q)) { rank = 1; kind = "name"; }
    else if (qId && c.idKey.includes(qId)) { rank = 2; kind = "id"; }
    else if (c.deptKey.includes(q)) { rank = 3; kind = "dept"; }
    else {
      const k = c.profKeys.findIndex((p) => p.includes(q));
      if (k >= 0) { rank = 4; kind = "prof"; prof = c.profs[k]; }
    }
    if (rank >= 0) hits.push({ c, rank, kind, prof });
  }
  hits.sort((a, b) => a.rank - b.rank || collator.compare(a.c.name, b.c.name) || collator.compare(a.c.id, b.c.id));
  return { q, qId, hits };
}

/** text 에서 q 와 맞는 부분을 굵게. */
function marked(text, q, skip = /\s/, cho = false) {
  const s = String(text || "");
  const { key, pos } = keyChars(s, skip, cho);
  const at = q ? key.indexOf(q) : -1;
  if (at < 0) return [s];
  const a = pos[at], b = pos[at + q.length - 1] + 1;
  return [s.slice(0, a), h("b", {}, s.slice(a, b)), s.slice(b)];
}

const isPicked = (id) => state.picks.some((p) => p.id === id);

/** 담기 버튼과 그 행. 누르는 영역은 행 전체(style.css), 담은 과목의 행은 어두운 바탕. */
function setAddButton(b, name, picked) {
  b.classList.toggle("is-on", picked);
  b.closest(".result")?.classList.toggle("is-picked", picked);
  b.setAttribute("aria-label", `${name} ${picked ? "담음" : "담기"}`);
  b.replaceChildren(...(picked ? [icon(I.check, 16), "담음"] : ["담기"]));
}

function resultRow({ c, kind, prof }, { q, qId }) {
  const title = kind === "name" ? marked(c.name, q) : kind === "cho" ? marked(c.name, q, /\s/, true) : [c.name];
  // 메타: 학과 · 교과구분 · 학점. 교과목번호·교수로 찾았으면 학과 자리에 그것을 보인다
  const first = kind === "id" ? marked(c.id, qId, /[\s.]/) : kind === "dept" ? marked(c.dept, q) : kind === "prof" ? marked(prof, q) : c.dept ? [c.dept] : null;
  const rest = [c.cls, fmtCredit(c.credit)].filter(Boolean).join(" · ");
  const btn = h("button", { type: "button", class: "btn-add", "data-id": c.id });
  const row = h("li", { class: "result" },
    h("div", { class: "r-body" }, h("span", { class: "r-title" }, title), h("span", { class: "r-meta" }, first ? [first, rest ? ` · ${rest}` : ""] : rest)),
    btn);
  setAddButton(btn, c.name, isPicked(c.id));
  return row;
}

let resultsShown = RESULTS_STEP, lastQuery = "", countTimer = null;
function renderResults({ more = false } = {}) {
  const raw = $("q").value;
  $("q-clear").hidden = !raw;
  const box = $("results");
  if (!raw.trim() || !state.loaded) {
    box.hidden = true;
    lastQuery = "";
    clearTimeout(countTimer);
    return;
  }
  if (raw !== lastQuery) { resultsShown = RESULTS_STEP; lastQuery = raw; }
  const found = findCourses(raw);
  const list = $("results-list");
  const before = more ? list.children.length : 0;
  list.replaceChildren(...found.hits.slice(0, resultsShown).map((hit) => resultRow(hit, found)));
  box.hidden = false;
  $("results-empty").hidden = found.hits.length > 0;
  $("results-more").hidden = found.hits.length <= resultsShown;
  if (more) { list.children[before]?.querySelector("button")?.focus(); return; }
  clearTimeout(countTimer);
  countTimer = setTimeout(() => announce(found.hits.length ? `결과 ${found.hits.length}개` : "검색 결과 없음"), 500);
}

function syncAddButtons() {
  for (const b of $("results-list").querySelectorAll(".btn-add")) {
    const c = state.byId.get(b.dataset.id);
    if (c) setAddButton(b, c.name, isPicked(c.id));
  }
}

// ---------------------------------------------------------------- 담은 과목

/** 담은 과목·분반·직접 입력이 바뀐 뒤: 저장하고, 그 조합에 대한 오류와 결과를 비운다. */
function changed() {
  cancelCompute();
  savePicks();
  saveOverrides();
  clearErrors();
  state.result = null;
}

function clearErrors() {
  state.errors.overlap = new Set();
  state.errors.general = null;
}

function addCourse(id) {
  const c = state.byId.get(id);
  if (!c || isPicked(id)) return;
  state.picks.push({ id, excluded: new Set(), ...snapshot(c) });
  changed();
  renderPicked({ added: id });
  announce(`${c.name} 담았어요`);
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
  $("picked-count").textContent = state.picks.length ? String(state.picks.length) : "";
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

function renderPicked({ added = "" } = {}) {
  const n = state.picks.length;
  $("picked-count").textContent = n ? String(n) : "";
  $("picked-empty").hidden = n > 0;
  $("picked-legend").hidden = n === 0; // 점 색 풀이는 담은 과목이 있을 때만
  $("picked-list").replaceChildren(...state.picks.map((p) => courseRow(p, p.id === added)));
  renderPickedError();
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

function renderSettings() {
  const homes = state.campus.homes || [];
  const preset = homes.some(([b]) => b === state.home);
  $("home-seg").replaceChildren(...homes.map(([b, label]) => segItem("home", b, label, b === state.home)), segItem("home", "other", "다른 건물", !preset));
  $("home-seg").hidden = false;
  const sel = $("home-select");
  sel.replaceChildren(...buildingOptions().map(([b, text]) => h("option", { value: b }, text)));
  sel.hidden = preset;
  if (!preset) sel.value = state.home;
  for (const r of document.querySelectorAll('input[name="mode"]')) {
    r.checked = r.value === state.mode;
    r.disabled = r.value === "slope" && !state.campus.slope;
  }
}

function setHome(b, other = false) {
  cancelCompute();
  state.home = b;
  store.set("home", b);
  if (other) { state.homeOther = b; store.set("homeOther", b); }
  state.result = null;
  const preset = (state.campus.homes || []).some(([x]) => x === b);
  $("home-select").hidden = preset;
  if (!preset) $("home-select").value = b;
}

$("home-seg").addEventListener("change", (e) => {
  if (e.target.value !== "other") { setHome(e.target.value); return; }
  const opts = [...$("home-select").options].map((o) => o.value);
  setHome(opts.includes(state.homeOther) ? state.homeOther : opts[0], true);
});
$("home-select").addEventListener("change", (e) => setHome(e.target.value, true));
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
    if (p) runHere(p.courses).then(p.resolve, p.reject);
  };
  return worker;
}

function settle(value, error) {
  const p = pending;
  pending = null;
  if (!p) return;
  if (error) p.reject(error); else p.resolve(value);
}

/** 화면 스레드에서 탐색(워커를 못 쓸 때). 전체 조합 수도 워커와 같게: 찾은 게 TOP_K 보다 적으면 그게 전부다. */
function runHere(courses) {
  return new Promise((resolve) => {
    const res = search(courses, travelFor(state.mode), state.home, { topK: TOP_K });
    if (!res.ranked.length) { resolve({ ranked: [], conflict: findConflicts(courses) }); return; }
    res.total = res.ranked.length < TOP_K ? { count: res.ranked.length, exact: true } : countFeasible(courses);
    resolve(res);
  });
}

/** 탐색: {ranked, stats, total} 또는 조합이 없으면 {ranked: [], conflict: [과목 id]}. total = {count, exact}(전체 조합 수). */
function compute(courses, onProgress) {
  const w = startWorker();
  if (!w) return runHere(courses);
  return new Promise((resolve, reject) => {
    const id = ++searchId;
    pending = { id, courses, resolve, reject, onProgress };
    const msg = { type: "search", id, courses, home: state.home, mode: state.mode, topK: TOP_K };
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

function showResult(res, courses) {
  const order = new Map(courses.map((c, i) => [c.id, i]));
  for (const ev of res.ranked) ev.sections.sort((a, b) => order.get(a.courseId) - order.get(b.courseId));
  state.result = { ranked: res.ranked, total: res.total || null, courses, home: state.home, mode: state.mode, days: weekDays(res.ranked), axis: hourRange(res.ranked) };
  state.rank = 0;
  state.day = firstDay(res.ranked[0]);
  state.ranksShown = RANKS_STEP;
  state.reveal = true;
  store.set("made", true);
  updateInstall();
  go("result");
  if (SHELL === "ios") window.Capacitor?.Plugins?.Haptics?.notification?.({ type: "SUCCESS" })?.catch?.(() => null);
}

// ---------------------------------------------------------------- 결과 화면

const currentEv = () => state.result.ranked[state.rank];

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
const weekLate = (ev) => ev.legs.reduce((s, l) => s + lateOf(l), 0);

/** 다 못 센 조합 수(실제는 그보다 많다)의 어림수: 10000 → '1만 개', 3456 → '3천 개', 456 → '400개'. */
const roughCount = (n) => (n >= 10000 ? `${Math.floor(n / 10000)}만 개` : n >= 1000 ? `${Math.floor(n / 1000)}천 개` : `${n >= 100 ? Math.floor(n / 100) * 100 : n}개`);

/**
 * 목록 제목: 희미한 '(전체 조합 1,234개 중)' + '걷는 시간이 짧은 20개를 찾았어요'. 찾은 것이 전부면 '전체 조합 4개를 찾았어요' 하나.
 * total 은 워커가 센 겹치지 않는 조합 수(같은 시간·건물 분반은 하나라 찾은 수와 단위가 같다). exact=false 면 그보다 많다는 뜻이라
 * 어림수로 '(1만 개가 넘는 조합 중)'. total 이 없으면(예전 워커) 희미한 부분 없이.
 */
function rankTitle(R) {
  const m = R.ranked.length, t = R.total;
  if (t ? t.exact && t.count <= m : m < TOP_K) return [`전체 조합 ${m}개를 찾았어요`];
  const found = h("span", { class: "rank-found" }, `걷는 시간이 짧은 ${m}개를 찾았어요`);
  if (!t) return [found];
  const n = Math.max(t.count, m);
  const all = t.exact ? `전체 조합 ${n.toLocaleString("ko-KR")}개` : `${roughCount(n)}가 넘는 조합`;
  return [h("span", { class: "rank-total" }, `(${all} 중)`), " ", found];
}

function renderResult() {
  const R = state.result;
  if (!R) return;
  $("rank-count").replaceChildren(...rankTitle(R));
  $("rank-cond").textContent = `출발·도착 ${placeLabel(R.home)} · ${R.mode === "slope" ? "경사 반영" : "평지"}`;
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
  remember($("panes"));
  const ev = currentEv();
  renderTimetable(ev, state.day);
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

const ttHeight = () => parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--tt-h")) || 316;
const remPx = () => parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;

/** 늦는 까닭: 걷는 시간과 쉬는 시간(강의실 미정 수업 앞뒤 쉬는 시간 포함). */
function lateWhy(l) {
  return `${placeLabel(l.from)}에서 ${buildingLabel(l.to)}까지 걷기 ${Math.round(l.minutes)}분, 쉬는 시간 ${Math.round(l.slack + l.minutes)}분`;
}

/** 칸 하나: 교과구분 연한 색 바탕에 과목명(부제 괄호 뺀 것)과 강의실, 늦으면 빨간 'N분 늦음'. */
function renderTimetable(ev, day) {
  const box = $("tt");
  if (!(ev.days[day] || []).length) { box.replaceChildren(h("p", { class: "tt-empty" }, "수업 없음")); return; }
  const [h0, h1] = state.result.axis;
  const span = (h1 - h0) * 60;
  const gridPx = ttHeight();
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
  const titleFont = `500 ${14 * k}px ${getComputedStyle(grid).fontFamily}`;
  const legs = ev.legs.filter((l) => l.day === day);
  let n = 0;
  legs.forEach((l, i) => {
    const m = l.meeting;
    if (!m) return;
    n += 1; // 지도 번호와 같은 순서
    const late = lateOf(l);
    const heightPct = ((m.end - m.start) / span) * 100;
    const px = (heightPct / 100) * gridPx;
    // 칸 높이에 맞춰 과목명을 몇 줄까지 보일지 정한다(줄 18, 강의실 줄 16, 늦음 줄 18, 위아래 여백 6). 넘치면 마지막 줄에 말줄임.
    // 과목명이 먼저다: 과목명을 다 보이고도 남으면 강의실(폰에서 75분 수업은 과목명이 한 줄이면 강의실까지).
    // 낮은 칸은 늦음 표시가 과목명 위 오른쪽에 겹친다
    const short = px < 38 * k;
    const lateRow = late && !short ? 18 * k : 0;
    const avail = px - 6 - lateRow;
    const need = Math.min(3, textLines(shortName(m.section.name), titleFont, textW));
    const showRoom = !short && (avail >= 50 * k || avail - 16 * k >= need * 18 * k);
    const lines = Math.max(1, Math.min(3, Math.floor((avail - (showRoom ? 16 * k : 0)) / (18 * k))));
    const cls = state.byId.get(m.section.courseId)?.cls || "";
    const nx = legs[i + 1];
    let next = "";
    if (m.building && nx) {
      if (nx.meeting && nx.meeting.building) next = `다음 수업까지 걷기 ${Math.round(nx.minutes)}분`;
      else if (!nx.meeting) next = `${placeLabel(state.result.home)}까지 걷기 ${Math.round(nx.minutes)}분`;
    }
    const said = [`${n}. ${hm(m.start)}~${hm(m.end)} ${m.section.name}`, roomLabel(m), late ? `${late}분 늦음(${lateWhy(l)})` : "", next].filter(Boolean).join(", ");
    grid.append(h("li", {
      class: `tt-block${short ? " short" : ""}${lateRow ? " is-late" : ""}`,
      style: { top: top(m.start), height: `calc(${heightPct}% - 2px)`, background: clsFill(cls), "--lines": String(lines) },
      title: `${m.section.name} ${hm(m.start)}~${hm(m.end)} ${roomLabel(m)}`,
    },
    h("span", { class: "sr-only" }, said),
    late ? h("span", { class: "tt-late", "aria-hidden": "true", title: lateWhy(l) }, `${late}분 늦음`) : null,
    h("span", { class: "b-title", "aria-hidden": "true" }, shortName(m.section.name)),
    showRoom ? h("span", { class: "b-room", "aria-hidden": "true" }, roomLabel(m)) : null));
  });
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
  const late = legs.reduce((s, l) => s + lateOf(l), 0);
  box.replaceChildren(...[h("span", {}, "걷기 ", h("b", {}, `${walk}분`)),
    late ? h("span", { class: "tag danger" }, h("span", { class: "sr-only" }, ", "), `${late}분 늦음`) : null].filter(Boolean));
}

// ---------------------------------------------------------------- 지도

const maps = { small: null, full: null };
let campusBounds = null;

function coordOf(b) {
  const v = state.campus.buildings[b];
  return v && v[1] !== null && v[1] !== undefined ? [v[1], v[2]] : null;
}

function midpoint(line) {
  let total = 0;
  const seg = [];
  for (let i = 1; i < line.length; i++) {
    const dy = line[i][0] - line[i - 1][0], dx = (line[i][1] - line[i - 1][1]) * Math.cos((line[i][0] * Math.PI) / 180);
    const d = Math.hypot(dx, dy);
    seg.push(d);
    total += d;
  }
  let acc = 0;
  for (let i = 0; i < seg.length; i++) {
    if (acc + seg[i] >= total / 2) {
      const t = seg[i] ? (total / 2 - acc) / seg[i] : 0;
      return [line[i][0] + (line[i + 1][0] - line[i][0]) * t, line[i][1] + (line[i + 1][1] - line[i][1]) * t];
    }
    acc += seg[i];
  }
  return line[0];
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
    zoomSnap: 0.25, zoomDelta: 0.5, maxBounds: campusBounds, maxBoundsViscosity: 1.0,
  });
  const buttons = full || mouse;
  if (buttons) L.control.zoom({ position: "topright", zoomInTitle: "확대", zoomOutTitle: "축소" }).addTo(map);
  el.setAttribute("role", "region");
  el.setAttribute("aria-label", "지도");
  // 타일을 못 불러오면(오프라인) 선과 핀만 그리고 '지도 배경 없음'
  const note = el.parentElement.querySelector(".map-note");
  const tiles = L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", { maxZoom: 19, className: "map-tiles" });
  let ok = 0;
  tiles.on("loading", () => { ok = 0; });
  tiles.on("tileload", () => { ok += 1; note.hidden = true; });
  tiles.on("tileerror", () => { if (!ok) note.hidden = false; });
  tiles.addTo(map);
  map.setView(campusBounds.getCenter(), 15, { animate: false });
  // 수업 뒤 출발·도착 자리로 가는 길은 경로선(overlayPane, 400) 아래 칸에 그린다: 겹치는 길에서 경로를 덮지 않게
  map.createPane("ttw-back").style.zIndex = "390";
  const legend = el.closest(".mapcard").querySelector(".legend");
  const mp = { map, el, tiles, full, buttons, legend, back: L.layerGroup().addTo(map), lines: L.layerGroup().addTo(map), marks: L.layerGroup().addTo(map), data: null };
  // 배율이 바뀌면 붙어 보이는 번호를 다시 묶고, 옆으로 비킨 선을 그 배율의 화소 간격으로 다시 그린다
  map.on("zoomend", () => { if (mp.data) { placeMarks(mp); drawReturn(mp); } });
  return mp;
}

// 수업 뒤 출발·도착 자리로 가는 길: ⌂ 핀과 같은 색(home) 파선 + 흰 테두리, 경로선 옆으로 7px 비켜서(같은 길을 되짚어도 경로선이 가려지지 않게)
const RETURN_OFFSET = 7, RETURN_DASH = "8 6";
const RETURN_KEY = '<svg class="line-key" width="20" height="8" viewBox="0 0 20 8" aria-hidden="true"><path d="M1 4H19" fill="none" stroke="currentColor" stroke-width="3" stroke-dasharray="4 3"/></svg>';

/** 선을 진행 방향 오른쪽으로 px 만큼 평행하게 옮긴다(지금 배율의 화면 좌표에서). 모서리는 두 변 법선의 이등분선, 뾰족하면 2px 배까지만. */
function offsetLine(map, line, px) {
  const pts = [];
  for (const ll of line) {
    const p = map.latLngToLayerPoint(ll);
    const q = pts[pts.length - 1];
    if (!q || Math.hypot(p.x - q.x, p.y - q.y) > 0.5) pts.push(p);
  }
  if (pts.length < 2) return line;
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
    return map.layerPointToLatLng(L.point(p.x + ox, p.y + oy));
  });
}

function drawReturn(mp) {
  mp.back.clearLayers();
  for (const line of mp.data.homeLines || []) {
    const off = offsetLine(mp.map, line, RETURN_OFFSET);
    L.polyline(off, { pane: "ttw-back", className: "map-route-home-case", weight: 7, dashArray: RETURN_DASH, lineCap: "butt", lineJoin: "round", interactive: false }).addTo(mp.back);
    L.polyline(off, { pane: "ttw-back", className: "map-route-home", weight: 3, dashArray: RETURN_DASH, lineCap: "butt", lineJoin: "round", interactive: false }).addTo(mp.back);
  }
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
  const legs = ev.days[day] ? ev.legs.filter((l) => l.day === day) : [];
  // 선: 수업 가는 길(번호가 붙은 수업으로)은 실선, 마지막 수업 뒤 출발·도착 자리로 가는 길은 점선
  const homeLines = [], classLines = [], labels = [];
  for (const l of legs) {
    if (l.from === l.to) continue;
    let line = routeLine(state.routes, l.from, l.to);
    if (!line) {
      const a = coordOf(l.from), b = coordOf(l.to);
      if (!a || !b) continue;
      line = [a, b];
    }
    (l.meeting ? classLines : homeLines).push(line);
    const mins = Math.round(l.minutes);
    if (mins > 0) labels.push({ at: midpoint(line), text: `${mins}분`, home: !l.meeting }); // 출발·도착 자리로 가는 구간은 ⌂ 를 붙인다
  }
  renderLegend(mp, legs, homeLines.length > 0); // 번호표를 먼저 채워야 지도 칸 높이가 정해진다
  mp.el.setAttribute("aria-label", `${DAY_KO[day]}요일 지도`);
  map.invalidateSize();
  map.setMinZoom(Math.max(12, map.getBoundsZoom(campusBounds, false)));
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
  // 요일·순위를 바꾸면 그날 경로 전체가 들어오게(애니메이션 없이). 핀이 오른쪽 위 버튼(크게 보기, 확대·축소), 왼쪽 위 '지도 배경 없음',
  // 오른쪽 아래 저작권 표기에 가리지 않게 가장자리를 비운다. 폰의 작은 지도는 폭이 좁아 위쪽을 비운다
  const k = remPx() / 16; // 글자를 키우면 저작권 표기와 '지도 배경 없음'도 커진다
  const top = Math.max(mp.full || mp.buttons ? 40 : 56, Math.round(24 + 16 * k)), bottom = Math.max(32, Math.round(16 + 16 * k));
  const pad = mp.full ? { paddingTopLeft: [24, top], paddingBottomRight: [68, bottom] }
    : mp.buttons ? { paddingTopLeft: [20, top], paddingBottomRight: [56, bottom] } : { paddingTopLeft: [20, top], paddingBottomRight: [20, bottom] };
  if (pts.length > 1) map.fitBounds(L.latLngBounds(pts), { ...pad, maxZoom: 17, animate: false });
  else if (pts.length) map.setView(pts[0], 16, { animate: false });
  mp.data = { stops, labels, homeAt, homeLines };
  drawReturn(mp);
  placeMarks(mp);
  if (reveal && !reduceMotion.matches) revealRoute(mp, drawn);
}

/** 핀과 구간 라벨. 화면에서 겹치는 수업 핀은 1·2 로 묶고, 걷는 시간 라벨은 핀·다른 라벨과 겹치면 숨긴다. */
function placeMarks(mp) {
  const { map, marks, data } = mp;
  marks.clearLayers();
  const merged = [];
  for (const st of data.stops) {
    const pt = map.latLngToContainerPoint(st.at);
    const near = merged.find((m) => Math.abs(m.pt.x - pt.x) < 24 && Math.abs(m.pt.y - pt.y) < 24);
    if (near) {
      near.nums.push(...st.nums);
      near.names.push(...st.names);
      if (!near.bs.includes(st.b)) near.bs.push(st.b);
    } else merged.push({ at: st.at, pt, nums: [...st.nums], names: [...st.names], bs: [st.b] });
  }
  if (data.homeAt) {
    L.marker(data.homeAt, { keyboard: false, interactive: false,
      icon: L.divIcon({ className: "", html: `<div class="pin home" role="img" aria-label="${esc(placeLabel(state.result.home))}">${HOME_PIN}</div>`, iconSize: [24, 24], iconAnchor: [12, 12] }) }).addTo(marks);
  }
  for (const st of merged) {
    const label = st.nums.join("·");
    const w = label.length > 1 ? 12 + 7 * label.length : 24;
    const name = [label, ...new Set(st.names), st.bs.map(buildingLabel).join("·")].join(", "); // 1, 동물생화학 2, 26동
    L.marker(st.at, { keyboard: false, interactive: false, zIndexOffset: 100,
      icon: L.divIcon({ className: "", html: `<div class="pin" role="img" aria-label="${esc(name)}">${label}</div>`, iconSize: [w, 24], iconAnchor: [w / 2, 12] }) }).addTo(marks);
  }
  const taken = [data.homeAt, ...merged.map((m) => m.at)].filter(Boolean).map((a) => map.latLngToContainerPoint(a));
  for (const lb of data.labels) {
    const pt = map.latLngToContainerPoint(lb.at);
    if (taken.some((q) => Math.abs(q.x - pt.x) < 30 && Math.abs(q.y - pt.y) < 22)) continue;
    taken.push(pt);
    L.marker(lb.at, { interactive: false, keyboard: false,
      icon: L.divIcon({ className: "", html: `<span class="leg-label${lb.home ? " to-home" : ""}" aria-hidden="true">${lb.home ? HOME_PIN.replace('width="12" height="12"', 'width="10" height="10"') : ""}${lb.text}</span>`, iconSize: [0, 0] }) }).addTo(marks);
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

/** 후보 카드: 순위, 한 주 걷는 시간·등교 요일(늦으면 빨간 'N분 늦음'), 요일별 미리보기. 고른 카드는 테두리와 담은 분반 목록. */
function rankItem(ev, i) {
  const R = state.result;
  const [h0, h1] = R.axis;
  const span = (h1 - h0) * 60;
  const pct = (x) => `${(x / span) * 100}%`;
  const cur = i === state.rank;
  const walk = Math.round(ev.travel);
  const late = weekLate(ev);
  const days = R.days.filter((d) => (ev.days[d] || []).length).map((d) => DAY_KO[d]).join("");
  const sum = days ? `걷기 주 ${walk}분 · ${days} 등교` : `걷기 주 ${walk}분`; // 시간이 모두 미정이면 등교 요일이 없다
  const clsOf = (courseId) => state.byId.get(courseId)?.cls || "";
  const week = h("span", { class: "week", "aria-hidden": "true", style: { "--days": String(R.days.length) } },
    R.days.map((d) => h("span", { class: "wd" }, DAY_KO[d])),
    R.days.map((d) => h("span", { class: "wc" }, (ev.days[d] || []).map((m) => h("span", {
      class: "wb", style: { top: pct(m.start - h0 * 60), height: pct(m.end - m.start), background: clsColor(clsOf(m.section.courseId)) },
    })))));
  const btn = h("button", {
    type: "button", class: "rank-hit", "data-rank": String(i), "aria-current": cur ? "true" : null,
    "aria-label": [`${i + 1}위`, `걷기 주 ${walk}분`, days ? `${days} 등교` : "", late ? `${late}분 늦음` : ""].filter(Boolean).join(", "),
  },
  h("span", { class: "rank-head" }, h("span", { class: "rank-no" }, `${i + 1}위`),
    h("span", { class: "rank-sum" }, sum, late ? h("span", { class: "late" }, ` · ${late}분 늦음`) : null)),
  week);
  return h("li", { class: cur ? "rank selected" : "rank" }, btn, cur ? rankPicks(ev) : null);
}

function rankPicks(ev) {
  return h("ul", { class: "rank-picks" }, ev.sections.map((s) => {
    const c = state.byId.get(s.courseId);
    return h("li", {},
      h("span", { class: "swatch", "aria-hidden": "true", style: { background: clsColor(c ? c.cls : "") } }),
      h("span", {}, `${s.name} `, h("span", { class: "p-sec" }, sectionLabel(s)),
        s.twins && s.twins.length ? h("span", { class: "p-twins" }, `같은 시간·건물: ${twinText(s.twins)}`) : null));
  }));
}

function renderRanks({ focus = null } = {}) {
  const R = state.result;
  const shown = Math.min(state.ranksShown, R.ranked.length);
  $("ranks").replaceChildren(...R.ranked.slice(0, shown).map((ev, i) => rankItem(ev, i)));
  $("ranks-more").hidden = shown >= R.ranked.length;
  if (focus !== null) $("ranks").querySelector(`[data-rank="${focus}"]`)?.focus({ preventScroll: true });
}

function selectRank(i) {
  if (i !== state.rank) {
    state.rank = i;
    updateTabs();
    renderDay({ fade: true });
    renderRanks({ focus: i });
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
$("ranks-more").addEventListener("click", () => {
  const from = state.ranksShown;
  state.ranksShown += RANKS_STEP;
  renderRanks({ focus: from });
});

// ---------------------------------------------------------------- 정보 화면, 자료 출처, 오픈소스 라이선스

/** 웹 Safari(iPhone·iPad 의 Safari 탭)에서만 '홈 화면에 추가' 안내. navigator.standalone 은 Safari 탭에서만 false 다. */
function isSafariTab() {
  const ios = /iphone|ipad|ipod/i.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  return SHELL === "web" && ios && navigator.standalone === false;
}

function renderInfo() {
  const next = (key, text) => h("button", { type: "button", class: "info-row", "data-info": key }, h("span", {}, text), icon(I.right, 20));
  const out = (href, text) => h("a", { class: "info-row", href, target: "_blank", rel: "noopener" }, h("span", {}, text), icon(I.out, 20));
  const rows = [
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
    ["지도", [link("https://www.openstreetmap.org/copyright", "© OpenStreetMap contributors"), " · ODbL"]],
  ] : [
    ["지도 표시", [link("https://github.com/Leaflet/Leaflet/blob/main/LICENSE", "Leaflet"), " · BSD-2-Clause"]],
    ["글꼴", [link("https://github.com/orioncactus/pretendard/blob/main/LICENSE", "Pretendard"), " · SIL OFL 1.1"]],
    ["로고 글꼴", [link("https://github.com/google/fonts/blob/main/ofl/fredoka/OFL.txt", "Fredoka"), " · SIL OFL 1.1"]],
    ["지도 자료", [link("https://www.openstreetmap.org/copyright", "OpenStreetMap"), " · ODbL"]],
    ["경사 자료", [link("https://www.kogl.or.kr/info/licenseType1.do", "국토지리정보원 수치지형도"), " · 공공누리 제1유형"]],
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
  if (name !== "input") cancelCompute();
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
  armSnackbar();
}
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

// 서비스 워커: 설치한 앱이 네트워크 없이도 열리게(web/sw.js). https 나 localhost 에서만 된다. iOS 앱은 파일을 앱에 넣는다
let updateReady = false, updateShown = false;
if (SHELL !== "ios" && "serviceWorker" in navigator && (location.protocol === "https:" || ["localhost", "127.0.0.1"].includes(location.hostname))) {
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
  for (const mp of [maps.small, maps.full]) if (mp) mp.tiles.redraw();
});

// 외부 링크(처리방침·문의·출처)는 앱 밖으로. iOS 앱은 인앱 Safari(Capacitor Browser), 웹·TWA 는 새 탭·Custom Tab
document.addEventListener("click", (e) => {
  const a = e.target.closest('a[target="_blank"]');
  const browser = SHELL === "ios" && window.Capacitor?.Plugins?.Browser;
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
  q.blur(); // 키보드만 닫는다
});
// 가상 키보드가 뜬 동안에는 하단 주요 버튼을 숨긴다
q.addEventListener("focus", () => { if (coarsePointer.matches) document.body.classList.add("is-typing"); });
q.addEventListener("blur", () => document.body.classList.remove("is-typing"));
$("q-clear").addEventListener("click", () => {
  q.value = "";
  renderResults();
  q.focus();
});
// 검색창에 초점이 있을 때 담기·지우기를 눌러도 키보드가 닫히지 않게 초점을 옮기지 않는다
for (const el of [$("results-list"), $("q-clear")]) {
  el.addEventListener("mousedown", (e) => { if (document.activeElement === q && e.target.closest("button")) e.preventDefault(); });
}
$("results-list").addEventListener("click", (e) => {
  const b = e.target.closest(".btn-add");
  const c = b && state.byId.get(b.dataset.id);
  if (!c) return;
  if (isPicked(c.id)) removeCourse(c.id); else addCourse(c.id);
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
start();
