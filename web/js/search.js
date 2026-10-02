// TT Wizard 과목 검색 — 백엔드 세션. 화면(app.js)은 searchCourses 결과를 그리고 강조만 한다.
//
// SNUTT(wafflestudio/snutt-timetable·snutt-v2 의 강의 검색)를 따른 것:
//   - 띄어쓰기로 나눈 낱말을 모두 만족하는 과목만(그리고). '글쓰기 나민애', '컴공과 자료구조'
//   - 한글 낱말은 글자 사이를 건너뛰어도 맞는다(줄임말). '대글' → 대학 글쓰기, '컴개실' → 컴퓨터의 개념 및 실습, '선대' → 선형대수학
//   - 학과 줄임: 학과 이름 처음(낱말 머리)부터 건너뛰며 맞추고, '과'·'부' 로 끝나면 그 글자는 뺀다. '컴공과' → 컴퓨터공학부, '국문과' → 국어국문학과.
//     '학' 으로 끝나는 낱말(수학·경제학)은 학과로 찾지 않는다(그 학과 과목이 다 딸려 나와서)
//   - 특별 낱말: 전공(전선·전필) 교양·전선·전필·교직·일선·공통 학부·학사 대학원·석박 석사·박사 3학점 301동·43-1동 301-118(강의실)
//     SNUTT 는 전공·학부·학사·대학원·석박·건물·강의실은 거르기만 하고, 교양·전선·전필·석사·박사 … 는 '구분이 그 말이거나 과목명에
//     그 글자가 차례로 있거나'로 찾는다(줄 세우기는 없다). 여기서는 낱말이 여럿이면 거르기를 먼저 본다(matchPlan)
// 여기에 더한 것(SNUTT 에는 없다):
//   - 초성과 글자를 섞어도 된다: 'ㄷㅎ글쓰기', '대ㄱ쓰기', 'ㅋㄱㅅ'. 교수 이름도 초성으로('ㄴㅁㅇ' → 나민애)
//   - 치는 중인 마지막 글자도 맞는다: '그' → 글, '글쓱' → 글쓰기(받침 ㄱ 이 다음 글자 첫소리). 덜 확실해서 조금 뒤로
//   - 한/영 전환을 잊고 친 영문 자판 글자: 'eogkr rmfTmrl' → 대학 글쓰기
//   - 띄어쓰기·대소문자·가운뎃점·괄호·로마 숫자(Ⅱ = 2)는 무시한다. 교과목번호는 마침표 없이 쳐도 된다(여섯 글자 이상)
//   - 맞는 정도로 줄 세운다(점수가 작을수록 앞):
//       과목명 처음 0 · 과목명 낱말 머리 1 · 교수 이름 전체(초성도) 1.5 · 과목명 안 2 · 낱말 머리글자 줄임 3 · 과목명 처음부터 건너뛴 줄임 3.2
//       · 학과 3.4 · 건너뛴 글자 4 · 분반 번호 4.5 · 교과목번호 5 · 교수 이름 일부 7 · 특별 낱말 8
//     특별 낱말이 과목명 낱말 머리에도 있으면('교양' → 교양연주): 그 낱말만 쳤을 때는 과목명 점수(0·1)로 앞에,
//     다른 낱말과 함께 쳤을 때는 거르기가 먼저(8)이고 과목명에만 있는 과목은 맨 뒤(8.2)
//     치는 중인 글자로 맞으면 +1.5(과목명 안이면 +2.5). 줄임은 건너뛴 횟수·글자 수만큼 뒤로.
//     '과목명 안' 은 그 낱말이 어느 과목명에서도 낱말 머리로 맞지 않으면 줄임말로 보고 3.8 로(LATE)
//     같으면 앞에서 맞은 것, 짧은 과목명, 가나다순. 낱말이 여럿이면 낱말 점수의 평균(띄어 쓴 검색어 전체가 과목명에 이어져 있으면 그 점수)
//
// 쓰는 법(app.js):
//   import { indexCourses, searchCourses, splitMarks, normKey } from "./search.js";
//   const index = indexCourses(state.courses);          // 과목 자료를 읽은 뒤(학기를 바꾼 뒤) 한 번
//   const { hits } = searchCourses(index, q.value);     // 검색창 값을 그대로(끝의 띄어쓰기로 '다 친 낱말'을 안다)
//   hits: [{ c, score, kind, marks }] 좋은 순. kind: 가장 잘 맞은 칸 'name' 'initials' 'fuzzy' 'id' 'dept' 'prof' 'special'
//   marks: { name?, id?, dept?: [[시작, 끝), ...] 원래 글자 위치, prof?: { name, ranges } }
//   splitMarks(text, ranges) → [{ text, mark }]  (mark 인 조각을 굵게)
//   normKey(text) → 비교용 글자 열(최근 검색어에서 같은 말을 하나로 칠 때)
// 테스트: tests/test_search.py (tests/search_runner.mjs 를 node 로 부른다)

const CHO = "ㄱㄲㄴㄷㄸㄹㅁㅂㅃㅅㅆㅇㅈㅉㅊㅋㅌㅍㅎ";
const JUNG = "ㅏㅐㅑㅒㅓㅔㅕㅖㅗㅘㅙㅚㅛㅜㅝㅞㅟㅠㅡㅢㅣ";
const JONG = ["", "ㄱ", "ㄲ", "ㄳ", "ㄴ", "ㄵ", "ㄶ", "ㄷ", "ㄹ", "ㄺ", "ㄻ", "ㄼ", "ㄽ", "ㄾ", "ㄿ", "ㅀ", "ㅁ", "ㅂ", "ㅄ", "ㅅ", "ㅆ", "ㅇ", "ㅈ", "ㅊ", "ㅋ", "ㅌ", "ㅍ", "ㅎ"];
// 겹받침·겹모음을 자판에서 치는 순서로 푼다(치는 중인 글자를 낱자 단위로 견주려고)
const SPLIT = { "ㄳ": "ㄱㅅ", "ㄵ": "ㄴㅈ", "ㄶ": "ㄴㅎ", "ㄺ": "ㄹㄱ", "ㄻ": "ㄹㅁ", "ㄼ": "ㄹㅂ", "ㄽ": "ㄹㅅ", "ㄾ": "ㄹㅌ", "ㄿ": "ㄹㅍ", "ㅀ": "ㄹㅎ", "ㅄ": "ㅂㅅ",
  "ㅘ": "ㅗㅏ", "ㅙ": "ㅗㅐ", "ㅚ": "ㅗㅣ", "ㅝ": "ㅜㅓ", "ㅞ": "ㅜㅔ", "ㅟ": "ㅜㅣ", "ㅢ": "ㅡㅣ" };
const SEP = new Set(" \t\n\r\f\v\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u200b\u2028\u2029\u202f\u205f\u3000\ufeff" +
  "()[]{}<>《》『』「」〈〉【】\"'‘’“”,.:;/\\·ㆍ・‧-–—―_!?&~|*+#@^`=");
const ROMAN = { "Ⅰ": "1", "Ⅱ": "2", "Ⅲ": "3", "Ⅳ": "4", "Ⅴ": "5", "Ⅵ": "6", "Ⅶ": "7", "Ⅷ": "8", "Ⅸ": "9", "Ⅹ": "10",
  "ⅰ": "1", "ⅱ": "2", "ⅲ": "3", "ⅳ": "4", "ⅴ": "5" };
const TAG = /^\s*[([][^)\]]{1,8}[)\]]\s*/; // 과목명 맨 앞 꼬리표 '(공유)'

const isSyllable = (c) => c >= "가" && c <= "힣";
const isCons = (c) => c.length === 1 && CHO.includes(c); // 초성으로 쓰는 홑·쌍자음
const hasHangul = (s) => /[가-힣ㄱ-ㅣ]/.test(s);

function parts(ch) {
  const code = ch.charCodeAt(0) - 0xac00;
  return { cho: CHO[Math.floor(code / 588)], jung: JUNG[Math.floor((code % 588) / 28)], jong: JONG[code % 28] };
}
function compose(cho, jung, jong = "") {
  return String.fromCharCode(0xac00 + CHO.indexOf(cho) * 588 + JUNG.indexOf(jung) * 28 + JONG.indexOf(jong));
}
const JAMO = new Map();
/** 음절 → 자판 순서 낱자 열('왕' → 'ㅇㅗㅏㅇ'). 음절이 아니면 그대로 */
function jamoOf(ch) {
  let v = JAMO.get(ch);
  if (v === undefined) {
    if (isSyllable(ch)) {
      const { cho, jung, jong } = parts(ch);
      v = cho + (SPLIT[jung] || jung) + (SPLIT[jong] || jong);
    } else v = ch;
    JAMO.set(ch, v);
  }
  return v;
}

// 빠른 거르기: 칸마다 든 초성·숫자(mask)와 영문(lat)을 비트로. 검색어 글자의 비트가 다 있어야 맞을 수 있다
const BIT = new Map([...CHO].map((c, k) => [c, 1 << k]).concat([..."0123456789"].map((d, k) => [d, 1 << (19 + k)])));
const LBIT = new Map([..."abcdefghijklmnopqrstuvwxyz"].map((c, k) => [c, 1 << k]));
const WORD = 1, HEAD = 2;

/**
 * 비교용 칸 { key, cho, pos, flag, n, mask, lat }. 띄어쓰기·문장부호는 빼고 소문자로, 로마 숫자는 숫자로, 전각은 반각으로.
 * key 글자 열, cho 글자마다 초성(음절이 아니면 그 글자), pos 원래 글자 위치,
 * flag WORD(낱말 머리: 띄어쓰기·문장부호 뒤, 한글·숫자·영문이 바뀌는 곳) HEAD(칸의 처음, 과목명이면 꼬리표 '(공유)' 다음)
 */
function field(text, tag = false) {
  const s = String(text ?? "").normalize("NFC");
  const skip = tag ? (TAG.exec(s)?.[0].length ?? 0) : 0;
  let key = "", cho = "", mask = 0, lat = 0, prev = 0, sep = true, headDone = false;
  const pos = [], flag = [];
  for (let i = 0; i < s.length; i++) {
    let raw = s[i], rc = raw.charCodeAt(0);
    if (rc >= 0xff01 && rc <= 0xff5e) raw = String.fromCharCode((rc -= 0xfee0)); // 전각 영문·숫자·괄호 → 반각
    if (SEP.has(raw)) { sep = true; continue; }
    const conv = rc >= 0xac00 && rc <= 0xd7a3 || rc >= 97 && rc <= 122 || rc >= 48 && rc <= 57 ? raw
      : rc >= 65 && rc <= 90 ? String.fromCharCode(rc + 32) : ROMAN[raw] || raw.toLowerCase();
    for (let k = 0; k < conv.length; k++) {
      const c = conv[k];
      const code = c.charCodeAt(0);
      const syl = code >= 0xac00 && code <= 0xd7a3;
      const kind = syl || (code >= 0x3131 && code <= 0x318e) ? 1 : code >= 48 && code <= 57 ? 2 : code >= 97 && code <= 122 ? 3 : 4;
      let f = i < skip ? 0 : sep || (prev && kind !== prev) ? WORD : 0; // 꼬리표 '(공유)' 안은 낱말 머리로 치지 않는다
      if (!headDone && i >= skip) { f |= HEAD; headDone = true; }
      const c0 = syl ? CHO[Math.floor((code - 0xac00) / 588)] : c;
      key += c;
      cho += c0;
      pos.push(i);
      flag.push(f);
      mask |= BIT.get(c0) || 0;
      lat |= LBIT.get(c0) || 0;
      sep = false;
      prev = kind;
    }
  }
  return { key, cho, pos, flag: Uint8Array.from(flag), n: key.length, mask, lat };
}

/** 검색어 낱말 → 칸 + 맞추기 정보. typing 이면 마지막 음절을 치는 중일 수 있다(낱자 앞부분, 받침을 다음 첫소리로). */
function queryField(word, typing) {
  const q = field(word);
  q.cons = Array.from(q.key, isCons);
  q.need = 0;
  q.needLat = 0;
  for (const c of q.cho) { q.need |= BIT.get(c) || 0; q.needLat |= LBIT.get(c) || 0; }
  q.last = -1;
  q.jamo = q.splitA = q.splitB = null;
  const c = q.key[q.n - 1];
  if (typing && q.n && isSyllable(c)) {
    q.last = q.n - 1;
    q.jamo = jamoOf(c);
    const { cho, jung, jong } = parts(c);
    if (jong && CHO.includes(jong)) { q.splitA = compose(cho, jung); q.splitB = jong; } // '쓱' → 쓰 + ㄱ
    else if (SPLIT[jong]) { q.splitA = compose(cho, jung, SPLIT[jong][0]); q.splitB = SPLIT[jong][1]; } // '닭' → 달 + ㄱ
  }
  return q;
}

const fits = (t, q) => (t.mask & q.need) === q.need && (t.lat & q.needLat) === q.needLat;

/** 검색어 i 번째 글자와 칸 j 번째 글자: 0 안 맞음, 1 맞음, 2 치는 중인 글자로 맞음(낱자 앞부분: '그' → 글, '고' → 과) */
function um(q, i, t, j) {
  const c = t.key.charCodeAt(j), qc = q.key.charCodeAt(i);
  if (c === qc) return 1;
  if (q.cons[i]) return t.cho.charCodeAt(j) === qc ? 1 : 0;
  if (i === q.last && t.cho.charCodeAt(j) === q.cho.charCodeAt(i) && jamoOf(t.key[j]).startsWith(q.jamo)) return 2;
  return 0;
}

/**
 * 이어진 그대로 맞는 가장 좋은 자리 { at, len, score, partial } 또는 null.
 * score: 칸 처음 0 · 낱말 머리 1 · 안 2. 치는 중인 글자로 맞으면 1.5 · 2.5 · 4.5.
 * 마지막 음절의 받침이 다음 글자 첫소리면('글쓱' → 글쓰 + 기) 칸 글자 하나를 더 덮는다(len = 검색어 길이 + 1)
 */
function contiguous(q, t) {
  const m = q.n, n = t.n;
  let best = null;
  for (let s = 0; s + m <= n; s++) {
    let k = 0;
    while (k < m - 1 && um(q, k, t, s + k) === 1) k++;
    if (k < m - 1) continue;
    let len = m, partial = false;
    const r = um(q, m - 1, t, s + m - 1);
    if (r === 2) partial = true;
    else if (r === 0) {
      if (q.splitA === null || s + m >= n || t.key[s + m - 1] !== q.splitA || t.cho[s + m] !== q.splitB) continue;
      partial = true;
      len = m + 1;
    }
    const f = t.flag[s];
    const score = f & HEAD ? (partial ? 1.5 : 0) : f & WORD ? (partial ? 2.5 : 1) : (partial ? 4.5 : 2);
    if (!best || score < best.score) {
      best = { at: s, len, score, partial };
      if (score === 0) break;
    }
  }
  return best;
}

let bufBest = new Float64Array(256), bufFrom = new Int32Array(256);
/**
 * 건너뛰며 맞추기(줄임말). 낱말 머리에서 시작하는 덩어리와 이어짐을 높이 치는 정렬 하나를 고른다(동적 계획법).
 * anchored 면 낱말 머리에서 시작해야 한다(학과: '국문' → 국어국문학과, '인지' → 협동과정 인지과학전공).
 * → { idx: 칸 글자 위치들, gaps: 건너뛴 횟수, initials: 덩어리마다 낱말 머리에서 시작, head: 칸 처음에서 시작, spread: 건너뛴 글자 수, partial } 또는 null
 */
function fuzzy(q, t, anchored = false) {
  const m = q.n, n = t.n;
  if (m < 2 || m > n) return null;
  for (let i = 0, j = 0; i < m; j++) { // 차례대로 다 들어 있나(없으면 정렬할 것도 없다)
    if (j === n) return null;
    if ((i || !anchored || t.flag[j] & WORD) && um(q, i, t, j)) i++;
  }
  const size = m * n;
  if (bufBest.length < size) { bufBest = new Float64Array(size * 2); bufFrom = new Int32Array(size * 2); }
  const best = bufBest, from = bufFrom, NEG = -1e9;
  for (let j = 0; j < n; j++) {
    best[j] = (!anchored || t.flag[j] & WORD) && um(q, 0, t, j) ? (t.flag[j] & WORD ? 3 : 0) + (t.flag[j] & HEAD ? 2 : 0) - j * 0.05 : NEG;
    from[j] = -1;
  }
  for (let i = 1; i < m; i++) {
    const row = i * n, prev = row - n;
    let runMax = NEG, runArg = -1; // j-2 까지의 최댓값(사이를 건너뛰는 경우)
    best[row] = NEG;
    from[row] = -1;
    for (let j = 1; j < n; j++) {
      if (j >= 2 && best[prev + j - 2] > runMax) { runMax = best[prev + j - 2]; runArg = j - 2; }
      best[row + j] = NEG;
      from[row + j] = -1;
      if (!um(q, i, t, j)) continue;
      const adj = best[prev + j - 1] > NEG ? best[prev + j - 1] + 4 : NEG; // 바로 이어짐
      const skip = runMax > NEG ? runMax - 1 + (t.flag[j] & WORD ? 3 : 0) : NEG; // 건너뜀: 낱말 머리면 덜 깎는다
      if (adj > NEG && adj >= skip) { best[row + j] = adj; from[row + j] = j - 1; }
      else if (skip > NEG) { best[row + j] = skip; from[row + j] = runArg; }
    }
  }
  let end = -1, top = NEG;
  for (let j = 0, last = (m - 1) * n; j < n; j++) if (best[last + j] > top) { top = best[last + j]; end = j; }
  if (end < 0) return null;
  const idx = new Array(m);
  for (let i = m - 1, j = end; i >= 0; i--) { idx[i] = j; j = from[i * n + j]; }
  let gaps = 0, initials = true;
  for (let i = 0; i < m; i++) {
    if (i > 0 && idx[i] === idx[i - 1] + 1) continue;
    if (i > 0) gaps++;
    if (!(t.flag[idx[i]] & WORD)) initials = false;
  }
  return { idx, gaps, initials, head: !!(t.flag[idx[0]] & HEAD), spread: idx[m - 1] - idx[0] - (m - 1), partial: um(q, m - 1, t, idx[m - 1]) === 2 };
}

// ---------------------------------------------------------------- 한/영 전환을 잊고 친 글자

const KEYS = { q: "ㅂ", w: "ㅈ", e: "ㄷ", r: "ㄱ", t: "ㅅ", y: "ㅛ", u: "ㅕ", i: "ㅑ", o: "ㅐ", p: "ㅔ", a: "ㅁ", s: "ㄴ", d: "ㅇ", f: "ㄹ", g: "ㅎ",
  h: "ㅗ", j: "ㅓ", k: "ㅏ", l: "ㅣ", z: "ㅋ", x: "ㅌ", c: "ㅊ", v: "ㅍ", b: "ㅠ", n: "ㅜ", m: "ㅡ", Q: "ㅃ", W: "ㅉ", E: "ㄸ", R: "ㄲ", T: "ㅆ", O: "ㅒ", P: "ㅖ" };
const JOIN_V = { "ㅗㅏ": "ㅘ", "ㅗㅐ": "ㅙ", "ㅗㅣ": "ㅚ", "ㅜㅓ": "ㅝ", "ㅜㅔ": "ㅞ", "ㅜㅣ": "ㅟ", "ㅡㅣ": "ㅢ" };
const JOIN_C = Object.fromEntries(Object.entries(SPLIT).filter(([k]) => JONG.includes(k)).map(([k, v]) => [v, k]));

/** 두벌식 자판에서 친 영문 → 한글('rmfTmrl' → '글쓰기'). 한글 음절이 하나도 안 생기면 null */
export function fromQwerty(text) {
  const s = String(text ?? "");
  if (!/[A-Za-z]/.test(s)) return null;
  let out = "", cho = "", jung = "", jong = "";
  const flush = () => {
    out += cho && jung ? compose(cho, jung, jong) : cho + jung + jong;
    cho = jung = jong = "";
  };
  for (const ch of s) {
    const j = KEYS[ch] || KEYS[ch.toLowerCase()];
    if (!j) { flush(); out += ch; continue; }
    if (JUNG.includes(j)) {
      if (jong) { // 받침이 다음 글자 첫소리로 넘어간다(겹받침은 뒤 낱자만)
        const sp = SPLIT[jong];
        const move = sp ? sp[1] : jong;
        jong = sp ? sp[0] : "";
        flush();
        cho = move;
        jung = j;
      } else if (cho && !jung) jung = j;
      else if (jung && JOIN_V[jung + j]) jung = JOIN_V[jung + j];
      else { flush(); jung = j; }
    } else if (!cho && !jung) cho = j;
    else if (cho && jung && !jong && JONG.includes(j)) jong = j;
    else if (jong && JOIN_C[jong + j]) jong = JOIN_C[jong + j];
    else { flush(); cho = j; }
  }
  flush();
  return /[가-힣]/.test(out) ? out : null;
}

// ---------------------------------------------------------------- 특별 낱말 (SNUTT 와 같게)

const MAJOR = new Set(["전선", "전필"]);
const GRAD = new Set(["석사", "박사", "석박사통합"]);
const meets = (c, f) => c.sections.some((s) => s.meetings.some(f));
/** 특별 낱말 → { test(과목), title: 과목명에 이어진 그대로 있어도 맞나 } 또는 null. typing 이면 강의실 번호는 앞부분만 맞아도 */
function special(w, typing = false) {
  if (w === "전공") return { title: true, test: (c) => MAJOR.has(c.cls) };
  if (["교양", "전선", "전필", "교직", "일선", "공통"].includes(w)) return { title: true, test: (c) => c.cls === w };
  if (w === "학부" || w === "학사") return { title: true, test: (c) => !GRAD.has(c.program) };
  if (w === "대학원" || w === "석박") return { title: true, test: (c) => GRAD.has(c.program) };
  if (w === "석사" || w === "박사") return { title: true, test: (c) => c.program === w || c.program === "석박사통합" };
  let m = /^(\d+(?:\.\d+)?)학점$/.exec(w);
  if (m) return { test: (c) => Number(c.credit) === Number(m[1]) };
  m = /^[#*]?(\d+(?:-\d+)?)동$/.exec(w);
  if (m) return { test: (c) => meets(c, (x) => String(x.building) === m[1]) };
  m = /^[#*]?(\d+(?:-\d+|-[A-Za-z])?-[A-Za-z]?\d+[A-Za-z]?(?:-\d+)?)$/.exec(w); // SNUTT 의 강의실 꼴: 301-118, 43-1-101, 43-1(43-1동)
  if (m) {
    const p = m[1].toUpperCase();
    return { test: (c) => meets(c, (x) => {
      const key = `${x.building}-${String(x.room ?? "").toUpperCase()}`;
      return String(x.building) === p || key === p || key.startsWith(typing ? p : p + "-");
    }) };
  }
  return null;
}
// 글자 건너뛰기로 안 되는 줄임(SNUTT 에는 없다). 낱말이 이것과 똑같을 때만 함께 찾는다
const ALIAS = { "일물": "물리학", "일화": "화학", "일생": "생물학" };

// ---------------------------------------------------------------- 색인과 검색

const byText = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

/** 과목 목록(engine.parseCourses) → 검색 색인. 과목 자료를 읽은 뒤 한 번 만든다. */
export function indexCourses(courses) {
  const memo = new Map(); // 학과·교수 이름은 여러 과목이 같이 쓴다
  const shared = (text) => {
    let f = memo.get(text);
    if (!f) memo.set(text, (f = field(text)));
    return f;
  };
  const list = courses.map((c) => {
    const idKey = String(c.id ?? "").toLowerCase();
    let idBare = "";
    const idBarePos = [];
    for (let i = 0; i < idKey.length; i++) if (/[0-9a-z]/.test(idKey[i])) { idBare += idKey[i]; idBarePos.push(i); }
    const profs = [...new Set(c.sections.map((s) => String(s.instructor ?? "").trim()).filter(Boolean))];
    const secs = new Set(c.sections.map((s) => String(s.no ?? "")));
    const name = String(c.name ?? "");
    return { c, name: field(name, true), dept: shared(String(c.dept ?? "")), idKey, idBare, idBarePos, secs,
      profs: profs.map((p) => ({ name: p, f: shared(p) })), sortName: name.replace(TAG, ""), order: 0 };
  });
  list.slice().sort((a, b) => byText(a.sortName, b.sortName) || byText(String(a.c.id), String(b.c.id))).forEach((e, k) => { e.order = k; });
  return list;
}

const S = { initials: 3, head: 3.2, dept: 3.4, fuzzy: 4, id: 5, prof: 7, special: 8 };
// 과목명 안에만 이어져 맞은 것(2점)은, 그 낱말이 결과 어느 과목명에서도 낱말 머리로 이어져 맞지 않으면
// 줄임말로 보고 3.8 로 내린다: '수연' → 수학연습(처음부터 건너뛴 줄임 3.4)이 화학특수연구(안 2 → 3.8)보다 앞. '구조' 는 구조역학이 있어 그대로
const LATE = 1.8;

/**
 * 건너뛴 맞춤의 점수: 낱말 머리글자 줄임 3(과목명 처음이 아니면 3.2) · 과목명 처음부터 3.2 · 그 밖 4,
 * 건너뛴 횟수와 건너뛴 글자 수(1 까지)만큼 뒤로: '수연' → 수학연습(3.4)이 수의유전체의학 연구(3.7)보다 앞
 */
function fuzzyScore(f, t) {
  const tier = f.initials ? S.initials + (f.head ? 0 : 0.2) : f.head ? S.head : S.fuzzy;
  return tier + f.gaps * 0.1 + Math.min(f.spread * 0.1, 1) + f.idx[0] * 0.002 + (f.partial ? 0.3 : 0) + t.n * 0.0001;
}

/**
 * 낱말 하나(또는 그 별칭·영문 자판 변환)로 찾을 것들. 학과·교수는 두 글자부터 —
 * 낱말이 여럿이면 한 글자도 이름·학과 앞부분으로 본다('글쓰기 나' → 나민애 교수 과목이 사라지지 않게)
 */
function wordPlan(w, q, multi = false) {
  const hangul = hasHangul(w);
  const id = !hangul && q.n >= 3 && /[0-9a-z]/i.test(w) ? w.toLowerCase() : null;
  const bare = id && id.replace(/[^0-9a-z]/g, "");
  let deptQ = null; // 학과 낱말 머리부터 건너뛰며: '과'·'부' 는 떼고, '학' 으로 끝나면 안 찾는다
  if (hangul && !w.endsWith("학")) {
    deptQ = /[과부]$/.test(w) && q.n >= 3 ? queryField(w.slice(0, -1), false) : q;
    if (deptQ.n < 2) deptQ = null;
  }
  const some = q.n >= 2 || (multi && q.n === 1);
  return { w, q, fuzzy: hangul && q.n >= 2, id, bare: bare && bare.length >= 6 ? bare : null,
    sec: /^\d{3}$/.test(w) ? w : null, dept: some && !w.endsWith("학"), deptQ, prof: some };
}

/**
 * 낱말 하나를 과목 하나에 맞춰 본다 → { score, kind, mark, demo, edge } 또는 null.
 * demo: 줄임말로 볼 때(LATE)의 결과, edge: 과목명에 낱말 머리로 이어져 맞았나
 */
function matchWord(e, p) {
  const q = p.q;
  let best = null, demo = null, edge = false;
  const take = (score, kind, mark, late = 0) => {
    if (!best || score < best.score) best = { score, kind, mark };
    if (!demo || score + late < demo.score) demo = { score: score + late, kind, mark };
  };
  const t = e.name;
  if (fits(t, q)) { // 과목명: 이어진 그대로, 아니면(안에만 이어졌으면 함께) 건너뛰며
    const r = contiguous(q, t);
    let inside = false;
    if (r) {
      edge = !!(t.flag[r.at] & (HEAD | WORD));
      inside = !edge && !r.partial;
      take(r.score + r.at * 0.001 + t.n * 0.0001, "name", { f: "name", at: r.at, len: r.len }, inside && p.fuzzy ? LATE : 0);
    }
    if (p.fuzzy && (!r || inside)) {
      const f = fuzzy(q, t);
      if (f) take(fuzzyScore(f, t), f.initials ? "initials" : "fuzzy", { f: "name", idx: f.idx });
    }
  }
  if (p.id) { // 교과목번호: 친 그대로, 아니면 마침표 없이(여섯 글자 이상)
    let key = e.idKey, at = key.indexOf(p.id), len = p.id.length, a = at, b = at + len;
    if (at < 0 && p.bare) {
      key = e.idBare;
      at = key.indexOf(p.bare);
      len = p.bare.length;
      if (at >= 0) { a = e.idBarePos[at]; b = e.idBarePos[at + len - 1] + 1; }
    }
    if (at >= 0) {
      const full = at === 0 && len === key.length;
      const seg = at === 0 || key[at - 1] === "." || (at === 1 && key[0] >= "a" && key[0] <= "z");
      take((full ? 0.5 : seg ? S.id : S.id + 0.5) + (key === e.idKey ? 0 : 0.3), "id", { f: "id", a, b });
    }
  }
  if (p.sec && e.secs.has(p.sec)) take(4.5, "special", null); // 분반 번호(001): 수강편람에서 '교과목번호 분반' 을 붙여 넣을 때
  if (p.dept) { // 학과: 낱말 머리부터만('컴공과', '수리', '인지'). 안에만 이어진 것('대학' → 약학대학)은 안 찾는다
    const d = e.dept;
    const r = fits(d, q) ? contiguous(q, d) : null;
    if (r && d.flag[r.at] & (HEAD | WORD)) take(S.dept + r.at * 0.001 + (r.partial ? 0.2 : 0), "dept", { f: "dept", at: r.at, len: r.len });
    else if (p.deptQ && fits(d, p.deptQ)) {
      const f = fuzzy(p.deptQ, d, true);
      if (f) take(S.dept + 0.05 + f.gaps * 0.05 + f.idx[0] * 0.001, "dept", { f: "dept", idx: f.idx });
    }
  }
  if (p.prof) { // 교수: 이름 전체(초성도)면 과목명 낱말 머리 다음으로
    for (let k = 0; k < e.profs.length; k++) {
      const pf = e.profs[k].f;
      if (!fits(pf, q)) continue;
      const r = contiguous(q, pf);
      if (!r || (q.n < 2 && r.at)) continue; // 한 글자는 이름 앞부분만
      const full = r.at === 0 && r.len === pf.n && !r.partial;
      take(full ? 1.5 : r.at === 0 ? S.prof - 0.2 : S.prof, "prof", { f: "prof", k, at: r.at, len: r.len });
      if (full) break;
    }
  }
  return best && { ...best, demo, edge };
}

function makePlan(w, typing, multi) {
  const sp = special(w, typing);
  const q = queryField(w, typing);
  if (!q.n && !sp) return null;
  const p = { ...wordPlan(w, q, multi), sp };
  const alias = ALIAS[w];
  if (alias) p.alias = { ...wordPlan(alias, queryField(alias, false)), dept: false, deptQ: null };
  if (!hasHangul(w)) {
    const alt = fromQwerty(w);
    if (alt) p.alt = wordPlan(alt, queryField(alt, typing), multi);
  }
  return p;
}

/** r 과 a(점수 + extra) 중 나은 것. 줄임말로 볼 때의 결과(demo)도 따로 고른다 */
function pick(r, a, extra) {
  if (!a) return r;
  const s = { score: a.score + extra, kind: a.kind, mark: a.mark };
  const d = { score: a.demo.score + extra, kind: a.demo.kind, mark: a.demo.mark };
  if (!r) return { ...s, demo: d, edge: a.edge };
  const out = s.score < r.score ? s : { score: r.score, kind: r.kind, mark: r.mark };
  return { ...out, demo: d.score < r.demo.score ? d : r.demo, edge: r.edge || a.edge };
}

/**
 * 낱말 하나(계획 p)를 과목 하나에 맞춰 본다. filter: 낱말이 여럿인 검색(특별 낱말은 거르는 말로 먼저 본다).
 * 특별 낱말 가운데 과목명에도 나오는 말(교양·전공·대학원 …)은 과목명의 낱말 머리에 그 말이 있어도 맞는다('교양소설', '전공탐색').
 * 과목명 안쪽에만 있는 것('유전공학' 의 전공)은 치지 않는다.
 *  - 낱말 하나만 쳤으면 과목명에 그 말이 있는 과목이 앞(0·1점), 걸러진 과목(8점)이 뒤
 *  - 낱말이 여럿이면 걸러진 과목이 먼저(8점): '교양 3학점' 은 교양이면서 3학점인 과목이지 '교양소설'(전선)이 아니다.
 *    과목명에만 그 말이 있는 과목은 맨 뒤(8.2점)에 남긴다
 */
function matchPlan(e, p, filter = false) {
  if (p.sp) {
    const pass = p.sp.test(e.c);
    let r = pass ? { score: S.special, kind: "special", mark: null } : null;
    if (p.sp.title && !(filter && pass) && fits(e.name, p.q)) {
      const t = contiguous(p.q, e.name);
      if (t && e.name.flag[t.at] & (HEAD | WORD)) {
        r = { score: filter ? S.special + 0.2 : t.score + t.at * 0.001 + e.name.n * 0.0001, kind: "name", mark: { f: "name", at: t.at, len: t.len } };
      }
    }
    return r && { ...r, demo: r, edge: true };
  }
  let r = matchWord(e, p);
  if (p.alias) r = pick(r, matchWord(e, p.alias), 0.2);
  if (p.alt && (!r || r.score > 2)) r = pick(r, matchWord(e, p.alt), 0.5);
  return r;
}

/**
 * 검색 → { words, hits }. hits = [{ c, score, kind, marks }] 좋은 순.
 * raw 는 검색창 값 그대로: 끝이 띄어쓰기가 아니면 마지막 낱말을 아직 치는 중으로 본다.
 */
export function searchCourses(index, raw, { limit = Infinity } = {}) {
  const text = String(raw ?? "").normalize("NFC");
  const words = text.trim() ? text.trim().split(/\s+/) : [];
  const typing = !/\s$/.test(text);
  const plans = words.map((w, i) => makePlan(w, typing && i === words.length - 1, words.length > 1)).filter(Boolean);
  if (!plans.length) return { words, hits: [] };
  // 띄어 쓴 검색어 전체가 과목명에 이어져 있으면 그것이 가장 좋다('대학 글쓰기')
  let whole = null, wholeAlt = null;
  if (words.length > 1) {
    whole = queryField(words.join(""), typing);
    const alt = words.map((w) => (hasHangul(w) ? w : fromQwerty(w) ?? w)).join("");
    if (alt !== words.join("")) wholeAlt = queryField(alt, typing);
  }
  const found = [];
  for (const e of index) {
    if (whole) {
      let r = fits(e.name, whole) ? contiguous(whole, e.name) : null, extra = 0;
      if (!r && wholeAlt && fits(e.name, wholeAlt)) { r = contiguous(wholeAlt, e.name); extra = 0.5; }
      if (r) {
        found.push({ e, score: r.score + extra + r.at * 0.001 + e.name.n * 0.0001, kind: "name", parts: [{ f: "name", at: r.at, len: r.len }] });
        continue;
      }
    }
    const rs = [];
    for (const p of plans) {
      const r = matchPlan(e, p, plans.length > 1);
      if (!r) break;
      rs.push(r);
    }
    if (rs.length === plans.length) found.push({ e, rs });
  }
  const edge = plans.map((_, w) => found.some((f) => f.rs && f.rs[w].edge));
  for (const f of found) {
    if (!f.rs) continue;
    let total = 0, top = null;
    f.parts = [];
    f.rs.forEach((r0, w) => {
      const r = edge[w] ? r0 : r0.demo;
      total += r.score;
      if (!top || r.score < top.score) top = r;
      if (r.mark) f.parts.push(r.mark);
    });
    f.score = total / plans.length + (plans.length - 1) * 0.01;
    f.kind = top.kind;
  }
  found.sort((a, b) => a.score - b.score || a.e.order - b.e.order);
  const shown = Number.isFinite(limit) ? found.slice(0, limit) : found;
  return { words, hits: shown.map(({ e, score, kind, parts }) => new Hit(e, score, kind, parts)) };
}

/** 결과 하나. 강조 범위(marks)는 화면에 그릴 때 처음 읽으면 만든다(결과가 많을 때 아끼려고) */
class Hit {
  constructor(e, score, kind, parts) {
    this.c = e.c;
    this.score = score;
    this.kind = kind;
    this._e = e;
    this._parts = parts;
    this._marks = null;
  }
  get marks() {
    return this._marks || (this._marks = buildMarks(this._e, this._parts));
  }
}

/** 맞은 자리들 → { name?, id?, dept?: 범위들, prof?: { name, ranges } } */
function buildMarks(e, parts) {
  const out = {};
  for (const p of parts) {
    if (p.f === "id") { out.id = joinRanges([...(out.id || []), [p.a, p.b]]); continue; }
    const t = p.f === "name" ? e.name : p.f === "dept" ? e.dept : e.profs[p.k].f;
    const rs = p.idx ? toRanges(t, p.idx) : [[t.pos[p.at], t.pos[p.at + p.len - 1] + 1]];
    if (p.f !== "prof") out[p.f] = joinRanges([...(out[p.f] || []), ...rs]);
    else if (!out.prof) out.prof = { name: e.profs[p.k].name, ranges: rs };
    else if (out.prof.name === e.profs[p.k].name) out.prof.ranges = joinRanges([...out.prof.ranges, ...rs]);
  }
  return out;
}
/** 칸 글자 위치들 → 원래 글자 범위. 이어진 글자는 하나로(사이 띄어쓰기도 함께) */
function toRanges(t, idxs) {
  const out = [];
  for (let i = 0; i < idxs.length; i++) {
    const k = idxs[i];
    if (i > 0 && k === idxs[i - 1] + 1) out[out.length - 1][1] = t.pos[k] + 1;
    else out.push([t.pos[k], t.pos[k] + 1]);
  }
  return out;
}
function joinRanges(rs) {
  const out = [];
  for (const r of rs.slice().sort((x, y) => x[0] - y[0])) {
    const last = out[out.length - 1];
    if (last && r[0] <= last[1]) last[1] = Math.max(last[1], r[1]);
    else out.push([r[0], r[1]]);
  }
  return out;
}

/** 글자와 강조 범위 → [{ text, mark }] (화면이 mark 인 조각을 굵게) */
export function splitMarks(text, ranges) {
  const s = String(text ?? "");
  if (!ranges || !ranges.length) return [{ text: s, mark: false }];
  const out = [];
  let at = 0;
  for (const [a, b] of joinRanges(ranges)) {
    if (a > at) out.push({ text: s.slice(at, a), mark: false });
    if (b > a) out.push({ text: s.slice(Math.max(a, at), b), mark: true });
    at = Math.max(at, b);
  }
  if (at < s.length) out.push({ text: s.slice(at), mark: false });
  return out;
}

/** 비교용 글자 열: 띄어쓰기·문장부호를 빼고 소문자로(같은 검색어를 하나로 칠 때) */
export function normKey(text) {
  return field(text).key;
}
