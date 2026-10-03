# 스토어 앱 (Capacitor)

2026-10-01. 백엔드 세션. Google Play·App Store 에 낼 앱이다. 웹 화면(`web/`)을 Capacitor 8 로 감싸
안드로이드와 iOS 를 한 번에 낸다(10/1 방향: 홈 화면 위젯 때문에 안드로이드도 TWA 대신 Capacitor).
화면 코드(HTML·CSS·JS)는 웹과 같고, 앱에만 있는 것은 아래 셋이다.

- 네이티브 프로젝트: `app/android/`(Android Studio), `app/ios/`(Xcode, Swift Package Manager)
- 앱 연결 스크립트: `app/src/native.js` → 앱 묶음의 `js/native.js` (자료 새로 받기, 안드로이드 뒤로 가기)
- 앱 묶음 만들기: `scripts/build_app.py` (web/ → `app/www/`, 글꼴 내장), 아이콘: `scripts/app_icons.py`

원격 주소만 띄우는 래퍼(`server.url`)가 아니다. 화면 파일과 과목 자료 스냅샷을 앱에 넣어 첫 실행부터 오프라인으로 돌고,
그 뒤로는 자료(JSON)만 새로 받는다(디자인 규칙 '스토어 출시' > '앱다움').

## 구조

```
app/
  package.json, package-lock.json   Capacitor 8.5.2 (core·cli·android·ios) + 플러그인 app·browser·haptics, 글꼴 pretendard
  capacitor.config.json             앱 아이디·이름, 시스템 바(SystemBars)
  src/native.js                     앱 연결 스크립트 (웹에서는 아무것도 안 한다)
  assets/icons/                     디자인 세션 아이콘 원본(design\v3\app-icons, 10/1 판)
  android/                          네이티브 안드로이드 프로젝트 (커밋한다. 빌드 결과·복사본은 .gitignore)
  ios/                              네이티브 iOS 프로젝트 (커밋한다)
  www/                              build_app.py 가 만드는 묶음 (git 에 안 올림)
  node_modules/                     npm ci (git 에 안 올림)
.github/workflows/app.yml           안드로이드 디버그 APK·iOS 시뮬레이터 빌드
```

- 앱 아이디 `com.ttwizard.app`(10/1 사용자 결정: 개인 GitHub 아이디와 떼어 두고, 나중에 `ttwizard.com` 같은 주소를 사면 그대로 맞게), 이름 `TT Wizard`.
  **스토어에 처음 올린 뒤에는 앱 아이디를 바꿀 수 없다.** 안드로이드 `namespace`·`applicationId`·`MainActivity` 패키지, iOS `PRODUCT_BUNDLE_IDENTIFIER`,
  `capacitor.config.json` 이 같아야 한다(`tests/test_app.py`).
- 안드로이드: minSdk 24, compile·targetSdk 36(Play 2026-08-31 요건), AGP 8.13, Gradle 8.14.3, JDK 21.
- iOS: 15.0 이상, Xcode 26 이상(Capacitor 8 요건), iPhone 전용(`TARGETED_DEVICE_FAMILY = 1`, 디자인 규칙의 권장. iPad 를 넣으려면 `1,2` 와 iPad 스크린샷).

## 빌드

### GitHub Actions (PC 에 아무것도 안 깔고)

`web/`·`app/`·`scripts/build_app.py` 가 바뀌어 main 에 올라가면 `app` 워크플로가 돈다(Actions 화면의 Run workflow 로도).

- 안드로이드: 디버그 APK. 실행 화면 아래 **Artifacts > tt-wizard-android-debug** 를 받아 압축을 풀고 안드로이드 폰에 옮겨 설치한다
  (설치할 때 '출처를 알 수 없는 앱' 허용을 묻는다). 14일 동안 받을 수 있다.
- iOS: 시뮬레이터용으로 서명 없이 빌드해 컴파일만 확인한다. 아이폰에 설치하거나 TestFlight 에 올리려면 Apple 개발자 계정과 서명이 필요하다.

### PC (Windows, 안드로이드)

Android Studio Otter(2025.2.1) 이상을 깐다(JDK 21 이 함께 온다). Node 22 이상.

```
cd /d "D:\프로젝트 파일\코딩\TT Wizard\tt-wizard"
.venv\Scripts\python scripts\export_web.py
cd app
npm ci
cd ..
.venv\Scripts\python scripts\build_app.py
cd app
npx cap sync android
npx cap open android
```

Android Studio 에서 폰을 USB 로 잇고(개발자 옵션 > USB 디버깅) Run. 웹 화면(`web/`)을 고친 뒤에는 `build_app.py` 와 `npx cap sync` 를 다시 돌린다.

### Mac (iOS)

Xcode 26 이상. 위와 같고 마지막 두 줄만 `npx cap sync ios`, `npx cap open ios`. Signing & Capabilities 에서 팀을 고른다.

## 앱 연결 스크립트 (`app/src/native.js`)

`build_app.py` 가 `index.html` `<head>` 끝에 넣어 `app.js`(모듈)보다 먼저 돈다. 웹·PWA 에서는 바로 끝난다(Capacitor 가 없으면).

- **자료**: `data/*.json` 을 웹 서버(`https://archi142857.github.io/tt-wizard/`)에서 네이티브 HTTP(CapacitorHttp, 웹뷰 CORS 를 타지 않음)로 받는다.
  3초 안에 안 오면 지난번에 받아 둔 것(IndexedDB), 그것도 없으면 앱에 넣은 스냅샷을 쓴다. 늦게 온 응답은 저장해 다음 실행에 쓴다.
  받아 둔 것은 앱 빌드(`BUILD`)마다 따로 두므로 앱을 새로 내면 새 스냅샷이 옛 저장본보다 먼저다. 웹 서비스 워커(네트워크 먼저, 3초)와 같은 방식이다.
- **자료 모양은 이미 낸 앱과 맞아야 한다.** 앱은 화면 코드를 품고 있고 자료만 새로 받으므로, `export_web.py` 의 JSON 은
  칸을 더하기만 하고 빼거나 뜻을 바꾸지 않는다. 꼭 바꿔야 하면 새 주소(예: `.../app-data/v2/`)에 내고 앱의 `REMOTE` 를 바꿔 새 판을 낸다.
- **안드로이드 뒤로 가기**: 열린 시트(`<dialog>`)를 닫고(`cancel` 이벤트, 화면이 막으면 그대로), 아니면 이전 화면(웹 방문 기록),
  첫 화면이면 앱을 내린다(`minimizeApp`, 다시 열면 그대로). iOS 는 가장자리 스와이프로 뒤로(`MainViewController`).
- `<html data-platform="android|ios">` 를 붙인다. `window.TTW_APP` 에 빌드·주소·플랫폼.
- **안드로이드 상태 바 글자색**: 기본은 기기 테마를 따른다(`capacitor.config.json` 의 `SystemBars.style: "DEFAULT"`). 그런데 SystemBars 플러그인(8.5.2)은
  `DEFAULT` 를 받은 순간의 기기 테마로 바꿔 기억하고 기기 설정이 바뀔 때 그 값을 다시 입혀서, 앱을 켜 둔 채 기기가 다크로 바뀌면 화면은 어두워지는데
  시계·아이콘이 어두운 글자로 남는다. 그래서 기기 테마가 바뀔 때(`prefers-color-scheme`)와 앱으로 돌아올 때 `DEFAULT` 를 다시 요청한다.
  이벤트 테마가 켜져 있으면(`<html data-theme>`) 화면이 정한 글자색(`app.js` `applyTheme` 의 `setStyle("DARK")`)을 건드리지 않는다. iOS 는 스스로 따라간다.

화면 쪽(`web/js/app.js`, 프론트엔드)은 `window.Capacitor` 가 있으면 셸을 `ios` 로 판별해 서비스 워커·설치 안내·새 버전 알림을 끄고,
외부 링크는 Capacitor Browser(안드로이드는 Custom Tab, iOS 는 인앱 Safari), 완료 때 햅틱을 쓴다. 안드로이드도 Capacitor 가 되면서
`ios` 라는 이름이 맞지 않아 프론트엔드에 플랫폼별로 나눠 달라고 요청했다(공유 폴더 `요청_프론트엔드.md`).

## 앱에서만 다른 것

| 항목 | 어디서 |
| --- | --- |
| 글꼴 Pretendard 내장(웹은 CDN) | `build_app.py` 가 `node_modules/pretendard` 의 가변 동적 서브셋(CSS + woff2 92개, 3 MB)과 OFL 라이선스를 넣고 `<link>` 를 바꾼다 |
| 시작 화면: bg 단색(라이트 `#EEF0FF`, 다크 `#16171B`), 로고 없음 | 안드로이드 `values(-night)/colors.xml` `launch_background`·`styles.xml`(12 이상은 시스템 스플래시 = 아이콘 + 바탕색), iOS `LaunchScreen.storyboard` + 색 에셋 `LaunchBackground` |
| 첫 화면 전 흰 화면 번쩍임 막기 | 웹뷰 바탕을 같은 색으로: `MainActivity.java`, iOS `MainViewController`(`SceneDelegate.swift`) |
| 시스템 바·안전 영역 | Capacitor 8 SystemBars(`insetsHandling: css`): 안드로이드 15 의 edge-to-edge 에서 `env(safe-area-inset-*)` 가 맞게 나온다. 옛 웹뷰(140 미만)는 `--safe-area-inset-*` 변수로 준다 |
| 예측 뒤로 가기(안드로이드 13+) | `AndroidManifest.xml` `enableOnBackInvokedCallback` |
| 지도 바탕 | 타일을 쓰지 않고 우리 자료(`data/basemap.json`)로 그린다(10/1, `docs/basemap.md`). 앱은 앱에 넣은 것만 쓴다(`native.js` `BUNDLED_ONLY`). OSM 타일용 User-Agent 꼬리표(`appendUserAgent`)는 뗐다 |
| iOS 개인정보 매니페스트 | `PrivacyInfo.xcprivacy`: 추적·수집 없음, UserDefaults `CA92.1` |
| iOS 수출 규정 질문 생략 | `Info.plist` `ITSAppUsesNonExemptEncryption = false`(HTTPS 만 쓴다) |
| 한국어 시스템 문구(인앱 Safari 의 '완료' 등) | `CFBundleDevelopmentRegion = ko` |

## 아이콘

디자인 세션 판(규칙 '로고' > '앱 아이콘 파일')을 `app/assets/icons/` 에 두고 `python scripts/app_icons.py` 로 만든다(Pillow).

- 안드로이드 적응형 아이콘: 앞면·단색(Android 13 테마 아이콘)은 108dp 층 가운데 72dp(사방 16.7 % 여백), 뒷면은 층 전체.
  다크 테마는 `mipmap-night-*`(파랑 바탕·흰 심볼). 안드로이드 7.x(API 24·25)는 `ic_launcher.png`(웹 `icon-512.png`)·`ic_launcher_round.png`.
- iOS: `AppIcon` 1024 한 장(알파 없음) + Dark 모양(`app-icon-1024-dark.png`).
- Play 등록 아이콘(`play-icon-512.png`)과 App Store 등록 아이콘은 콘솔에 따로 올린다.

## 판(버전)

- 웹 `APP_VERSION`(`web/js/app.js`) = 안드로이드 `versionName`(`app/android/app/build.gradle`) = iOS `MARKETING_VERSION`(pbxproj 두 곳).
  `tests/test_app.py` 가 확인한다. 웹 판을 올리면 두 곳도 같이 올린다.
- 스토어에 올릴 때마다 안드로이드 `versionCode`, iOS `CURRENT_PROJECT_VERSION` 을 1씩 올린다.

## 아직 안 한 것 (출시 전에)

1. 서명: 안드로이드 업로드 키(keystore)를 만들어 저장소 비밀값으로 넣고(`TTW_KEYSTORE_FILE`·`TTW_KEYSTORE_PASSWORD`·`TTW_KEY_ALIAS`·`TTW_KEY_PASSWORD`,
   `build.gradle` 이 읽는다) Actions 에 서명한 AAB(`bundleRelease`) 단계를 더한다. iOS 는 Apple 개발자 계정의 인증서·프로비저닝(또는 Mac 의 Xcode 자동 서명).
2. 앱에서만 되는 쓸모(심사 4.2·Play 최소 기능): 시간표 저장, 이미지·캘린더 내보내기, 위젯, 수강편람 알림 중 하나 이상(`앱_확장_계획.md`).
3. 정보 화면의 개인정보 처리방침·문의 주소(`app.js` 의 `PRIVACY_URL`·`CONTACT_URL`), 스토어 등록 자료(디자인), 데이터 보안·개인정보 라벨.
4. iPad 지원 여부, 캠퍼스 마법 지도 자료의 스토어 배포 허락(신용범 님).
5. Google Play: 개인 계정이면 테스터 12명이 14일 동안 비공개 테스트를 한 뒤 프로덕션 신청.

## 폰에서 볼 것 (아직 안 봤다)

클라우드에서는 네이티브 빌드를 못 해서 아래는 코드와 가짜 Capacitor 로만 확인했다. Actions 의 디버그 APK 를 안드로이드 폰에 깔아 본다.

1. 비행기 모드로 처음 켜도 과목 검색과 시간표 만들기가 된다(앱에 넣은 자료). 켤 때 흰 화면이 번쩍이지 않는다.
2. 뒤로 가기: 열린 시트 닫기 → 이전 화면 → 첫 화면에서는 앱이 내려간다(다시 열면 그대로).
3. 상태 바의 시계·아이콘이 라이트·다크 기기 모두에서 보인다. 앱을 켜 둔 채 기기 테마를 바꾸고 돌아와도 보인다(위 '안드로이드 상태 바 글자색').
4. 이벤트 테마: 기기 날짜를 12월 1~25일로 옮기면 크리스마스 테마가 켜진다(앱은 주소로 켤 수 없다). 짙은 초록 바탕 위에서 상태 바 글자가 밝게 나오고,
   정보 화면에서 테마를 끄면 기기 테마에 맞게 돌아온다. 코드로는 `DARK` = 밝은 글자(안드로이드 `setAppearanceLightStatusBars(false)`, iOS `.lightContent`)다.
5. 정보 화면의 바깥 링크가 앱 안 브라우저(Custom Tab)로 열린다.

## 확인한 것 (10/1)

- 클라우드 세션은 안드로이드 SDK·Gradle·Maven 서버에 닿지 않아 네이티브 빌드는 Actions 에서만 한다.
- 앱 묶음을 가짜 Capacitor(안드로이드)로 브라우저에 띄워: 원격 자료 사용·저장, 실패 시 저장본, 저장본이 없으면 스냅샷,
  3초 넘게 늦으면 스냅샷으로 먼저 열고 늦은 응답은 다음에 사용, 뒤로 가기(시트 닫기 → 이전 화면 → 앱 내리기), 내장 글꼴(CDN 요청 없음).
  같은 것을 `tests/native_runner.mjs`(node)가 확인한다.
- 10/4: 화면 코드와 `native.js` 를 가짜 안드로이드 Capacitor 로 함께 띄워, 기본 테마에서는 기기 테마를 바꿀 때마다 `SystemBars.setStyle("DEFAULT")` 가 가고
  크리스마스 테마에서는 처음 `DARK` 한 번뿐인 것을 봤다. 플러그인 쪽 동작은 `@capacitor/android`·`@capacitor/ios` 8.5.2 소스로 읽었다
  (`Capacitor.Plugins.SystemBars` 는 번들러 없이도 네이티브가 만들어 준다).
