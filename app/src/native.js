// TT Wizard 앱(Capacitor) 연결 — 백엔드 세션.
// scripts/build_app.py 가 www/js/native.js 로 넣고, index.html <head> 에서 app.js(모듈)보다 먼저 부른다.
// 웹(브라우저·설치한 PWA)에서는 아무것도 하지 않는다. 화면 코드(web/js/app.js)는 그대로 두고 앱에서만 다른 것을 여기서 맞춘다.
//
// 1) 자료(data/*.json): 웹 서버(GitHub Pages)에서 새로 받는다(네이티브 HTTP, 없으면 fetch). 3초 안에 안 오거나 끊겼으면 지난번에 받아 둔 것,
//    그것도 없으면 앱에 넣은 것(빌드 때의 스냅샷)을 쓴다. 늦게 온 응답은 다음 실행을 위해 저장한다.
//    받아 둔 것은 앱 빌드(BUILD)마다 따로 둔다: 앱을 새로 내면 새 스냅샷이 옛 저장본보다 먼저다.
//    바탕 지도(data/basemap.json)는 크고 거의 안 바뀌어서 앱에 넣은 것만 쓴다(새 판은 앱 업데이트로 온다).
// 2) 안드로이드 뒤로 가기: 열린 시트(<dialog>)를 닫고(cancel 이벤트), 아니면 이전 화면, 첫 화면이면 앱을 내린다.
// 3) <html data-platform="android|ios">
(function () {
  "use strict";
  var cap = window.Capacitor;
  if (!cap || typeof cap.isNativePlatform !== "function" || !cap.isNativePlatform()) return;

  var BUILD = "__BUILD__"; // build_app.py 가 바꾼다
  var REMOTE = "__REMOTE__"; // 자료를 새로 받을 곳 (끝에 /)
  var WAIT_MS = 3000;
  var BUNDLED_ONLY = /^data\/basemap\.json$/; // 네트워크로 새로 받지 않는 자료
  var DB_NAME = "ttw-app";
  var STORE = "data";
  var platform = typeof cap.getPlatform === "function" ? cap.getPlatform() : "";
  var plugins = cap.Plugins || {};
  document.documentElement.setAttribute("data-platform", platform);

  var nativeFetch = window.fetch.bind(window);

  // ------------------------------------------------------------ 받아 둔 자료 (IndexedDB, 안 되면 저장 없이)

  var dbPromise = null;
  function db() {
    if (!dbPromise) {
      dbPromise = new Promise(function (resolve) {
        try {
          var req = indexedDB.open(DB_NAME, 1);
          req.onupgradeneeded = function () { req.result.createObjectStore(STORE); };
          req.onsuccess = function () { resolve(req.result); };
          req.onerror = function () { resolve(null); };
          req.onblocked = function () { resolve(null); };
        } catch (e) {
          resolve(null);
        }
      });
    }
    return dbPromise;
  }
  function get(path) {
    return db().then(function (d) {
      if (!d) return null;
      return new Promise(function (resolve) {
        try {
          var req = d.transaction(STORE, "readonly").objectStore(STORE).get(path);
          req.onsuccess = function () {
            var v = req.result;
            resolve(v && v.build === BUILD && typeof v.text === "string" ? v.text : null);
          };
          req.onerror = function () { resolve(null); };
        } catch (e) {
          resolve(null);
        }
      });
    });
  }
  function put(path, text) {
    return db().then(function (d) {
      if (!d) return;
      try {
        d.transaction(STORE, "readwrite").objectStore(STORE).put({ build: BUILD, time: Date.now(), text: text }, path);
      } catch (e) { /* 저장이 안 돼도 화면은 돈다 */ }
    });
  }

  // ------------------------------------------------------------ 자료 받기

  function isJson(text) {
    try { JSON.parse(text); return true; } catch (e) { return false; }
  }
  function respond(text, source) {
    return new Response(text, {
      status: 200,
      headers: { "Content-Type": "application/json; charset=utf-8", "X-TTW-Source": source },
    });
  }
  function dataPath(input) {
    var url;
    try { url = new URL(typeof input === "string" ? input : input.url, document.baseURI); } catch (e) { return null; }
    if (url.origin !== location.origin || !/^\/data\/[^/][^?#]*\.json$/.test(url.pathname)) return null;
    return { path: url.pathname.slice(1), search: url.search, local: url.href };
  }
  /** 웹 서버에서 글자 그대로 받기. 네이티브 HTTP(CapacitorHttp)는 웹뷰의 CORS 를 타지 않는다 */
  function remoteText(url) {
    var http = plugins.CapacitorHttp;
    if (http && typeof http.get === "function") {
      return http.get({ url: url, responseType: "text", headers: { "Cache-Control": "no-cache" } }).then(function (res) {
        if (!res || res.status < 200 || res.status >= 300) return null;
        return typeof res.data === "string" ? res.data : JSON.stringify(res.data);
      });
    }
    return nativeFetch(url, { cache: "no-cache", credentials: "omit" }).then(function (res) { return res.ok ? res.text() : null; });
  }
  function fromNetwork(d) {
    if (navigator.onLine === false) return Promise.resolve(null);
    return remoteText(REMOTE + d.path + d.search)
      .then(function (text) {
        if (text === null || !isJson(text)) return null;
        put(d.path, text);
        return text;
      })
      .catch(function () { return null; });
  }
  function fetchData(d, init) {
    var net = fromNetwork(d);
    var late = new Promise(function (resolve) { setTimeout(function () { resolve(undefined); }, WAIT_MS); });
    return Promise.race([net, late]).then(function (text) {
      if (typeof text === "string") return respond(text, "network");
      // 늦거나(undefined) 실패(null): 받아 둔 것 → 앱에 넣은 것. 늦은 응답은 fromNetwork 가 저장해 둔다
      return get(d.path).then(function (saved) {
        if (saved !== null) return respond(saved, "saved");
        return nativeFetch(d.local, init);
      });
    });
  }

  window.fetch = function (input, init) {
    var method = (init && init.method) || (input && typeof input === "object" && input.method) || "GET";
    var d = String(method).toUpperCase() === "GET" ? dataPath(input) : null;
    return d && !BUNDLED_ONLY.test(d.path) ? fetchData(d, init) : nativeFetch(input, init);
  };

  // ------------------------------------------------------------ 안드로이드 뒤로 가기

  var App = plugins.App;
  if (platform === "android" && App && typeof App.addListener === "function") {
    App.addListener("backButton", function (ev) {
      var open = document.querySelectorAll("dialog[open]");
      if (open.length) {
        var dialog = open[open.length - 1];
        var cancel = new Event("cancel", { cancelable: true });
        if (dialog.dispatchEvent(cancel)) dialog.close();
        return;
      }
      if (ev && ev.canGoBack) {
        history.back();
        return;
      }
      if (typeof App.minimizeApp === "function") App.minimizeApp();
      else if (typeof App.exitApp === "function") App.exitApp();
    });
  }

  window.TTW_APP = { build: BUILD, remote: REMOTE, platform: platform };
})();
