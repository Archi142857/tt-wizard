// TT Wizard 서비스 워커: 폰 홈 화면에 설치한 앱이 네트워크가 없어도 열리게 한다.
// - 같은 사이트의 파일(화면·엔진·편람·이동시간)만 다룬다. 지도 타일(OpenStreetMap)·글꼴은 브라우저에 맡긴다
//   (OSM 타일 정책: 미리 받아 두거나 따로 쌓지 않는다)
// - 늘 네트워크를 먼저 본다. 새로 배포하거나 편람이 갱신되면 바로 반영된다. 저장해 둔 것이 있으면 3초까지 기다리고,
//   늦거나 끊기면 저장해 둔 것을 쓴다(그 뒤에 온 응답은 다음을 위해 저장)
// - 3D·2D 모델(web/model/, 파일이 커서)은 다루지 않는다
const CACHE = "ttw-v1";
const SHELL = [
  "./", "index.html", "style.css", "js/app.js", "js/engine.js", "manifest.webmanifest",
  "vendor/leaflet/leaflet.css", "vendor/leaflet/leaflet.js", "icons/icon-192.png", "icons/favicon-32.png",
  "data/campus.json", "data/courses.json", "data/semesters.json",
];
const WAIT_MS = 3000;

self.addEventListener("install", (event) => {
  // 하나가 없어도(예: 학기 목록이 없는 옛 배포) 나머지는 저장한다
  event.waitUntil(caches.open(CACHE)
    .then((cache) => Promise.all(SHELL.map((url) => cache.add(url).catch(() => null))))
    .then(() => self.skipWaiting()));
});

self.addEventListener("activate", (event) => {
  event.waitUntil(caches.keys()
    .then((keys) => Promise.all(keys.filter((k) => k.startsWith("ttw-") && k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== self.location.origin || url.pathname.includes("/model/")) return;
  const net = fetch(req);
  // 응답이 오면 바로 복사해 저장한다(화면이 본문을 읽기 전에 복사해야 한다). 늦게 와도 저장까지 워커가 살아 있게
  event.waitUntil(net.then((res) => {
    const copy = res.ok ? res.clone() : null;
    return copy && caches.open(CACHE).then((cache) => cache.put(req, copy));
  }).catch(() => null));
  event.respondWith(respond(req, net));
});

async function respond(req, net) {
  const cache = await caches.open(CACHE);
  const cached = await cache.match(req, { ignoreSearch: true });
  if (!cached) {
    try {
      return await net;
    } catch (err) {
      const shell = req.mode === "navigate" ? await cache.match("index.html") : null;
      if (shell) return shell;
      throw err;
    }
  }
  const late = new Promise((resolve) => setTimeout(() => resolve(null), WAIT_MS));
  const res = await Promise.race([net.catch(() => null), late]);
  return res && res.ok ? res : cached;
}
