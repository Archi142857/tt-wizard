"""스토어 앱(Capacitor, app/): 웹 화면 묶기(scripts/build_app.py), 앱 연결 스크립트(app/src/native.js), 네이티브 프로젝트 설정.
안드로이드·iOS 빌드 자체는 GitHub Actions(app.yml)가 한다. node 가 없으면 연결 스크립트 확인은 건너뛴다."""

import json
import plistlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import build_app  # noqa: E402

APP = ROOT / "app"
RES = APP / "android" / "app" / "src" / "main" / "res"
IOS = APP / "ios" / "App"


def fake_web(tmp_path: Path) -> Path:
    """진짜 화면 파일 + 가짜 자료, 그리고 빠져야 할 것들(sw.js, model/, field/, vendor/three/, js/package.json)."""
    web = tmp_path / "web"
    web.mkdir()
    for name in ("index.html", "style.css", "sw.js", "manifest.webmanifest"):
        shutil.copy2(ROOT / "web" / name, web / name)
    shutil.copytree(ROOT / "web" / "js", web / "js")
    shutil.copytree(ROOT / "web" / "icons", web / "icons")
    shutil.copytree(ROOT / "web" / "vendor" / "leaflet", web / "vendor" / "leaflet")
    for extra in ("model/index.html", "field/index.html", "vendor/three/three.min.js"):
        (web / extra).parent.mkdir(parents=True, exist_ok=True)
        (web / extra).write_text("x", encoding="utf-8")
    (web / "data" / "semesters").mkdir(parents=True)
    for name in ("campus.json", "courses.json", "routes.json", "semesters.json", "semesters/2025-1.json"):
        (web / "data" / name).write_text("{}", encoding="utf-8")
    return web


def test_build_app_bundle(tmp_path, monkeypatch):
    web = fake_web(tmp_path)
    font = tmp_path / "pretendard"
    sub = font / "dist" / "web" / "variable"
    (sub / "woff2-dynamic-subset").mkdir(parents=True)
    (sub / build_app.FONT_CSS).write_text("@font-face{}", encoding="utf-8")
    (sub / "woff2-dynamic-subset" / "PretendardVariable.subset.0.woff2").write_bytes(b"w")
    (font / "dist" / "LICENSE.txt").write_text("SIL Open Font License", encoding="utf-8")
    monkeypatch.setattr(build_app, "FONT", font)
    out = tmp_path / "www"
    info = build_app.build(web=web, out=out, remote="https://example.org/tt", tag="T1")

    files = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}
    assert {"index.html", "js/app.js", "js/engine.js", "js/search-worker.js", "js/search.js", "js/native.js", "data/courses.json",
            "data/semesters/2025-1.json", "vendor/leaflet/leaflet.js", "vendor/pretendard/LICENSE.txt",
            "vendor/pretendard/woff2-dynamic-subset/PretendardVariable.subset.0.woff2", "app-build.json"} <= files
    assert not [f for f in files if f == "sw.js" or f.startswith(("model/", "field/", "vendor/three/")) or f.endswith("package.json")]
    html = (out / "index.html").read_text(encoding="utf-8")
    assert "cdn.jsdelivr.net" not in html and 'href="vendor/pretendard/' in html
    assert html.index('<script src="js/native.js"></script>') < html.index("</head>") < html.index('src="js/app.js"')
    native = (out / "js" / "native.js").read_text(encoding="utf-8")
    assert 'var BUILD = "T1"' in native and 'var REMOTE = "https://example.org/tt/"' in native and "__" not in native.split("var BUILD")[1][:40]
    assert info["font"] == "앱에 넣음" and info["files"] == len(files) - 1  # app-build.json 은 센 뒤에 쓴다
    assert json.loads((out / "app-build.json").read_text(encoding="utf-8"))["build"] == "T1"

    # npm ci 전(글꼴 없음): CDN 그대로, 나머지는 같다
    monkeypatch.setattr(build_app, "FONT", tmp_path / "none")
    info = build_app.build(web=web, out=out, tag="T2")
    assert info["font"] == "CDN" and "cdn.jsdelivr.net" in (out / "index.html").read_text(encoding="utf-8")


def test_patch_index_stops_on_unknown_markup():
    with pytest.raises(SystemExit):
        build_app.patch_index("<html><head></head><body><script type=module src=\"js/app.js\"></script></body></html>", True)
    with pytest.raises(SystemExit):
        build_app.patch_index("<html><body>no head</body></html>", False)


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_native_shim():
    run = subprocess.run(["node", str(ROOT / "tests" / "native_runner.mjs")], capture_output=True, text=True, timeout=60)
    assert run.returncode == 0, run.stderr
    r = json.loads(run.stdout)
    assert r["webUntouched"]
    n = r["network"]
    assert (n["source"], n["from"], n["url"]) == ("network", "remote", "https://remote.example/tt/data/campus.json")
    assert n["saved"] and n["savedBuild"] == "B1" and n["other"] == n["post"] == "bundle" and n["platform"] == "android"
    f = r["fallback"]
    assert f["saved"] == ["saved", "remote"] and f["bundled"] == [None, "bundle"]
    assert f["oldBuild"] == "bundle" and f["notFound"] == "bundle"  # 빌드가 다른 저장본, 404 HTML 은 쓰지 않는다
    assert r["offline"] == {"from": "bundle", "remoteCalls": 0}
    assert r["slow"]["first"] == "bundle" and r["slow"]["waitedMs"] == 3000 and '"late"' in r["slow"]["savedLate"]
    assert r["back"] == {"closed": True, "kept": True, "historyBack": 1, "minimized": 1}
    assert r["basemap"] == {"from": "bundle", "remoteCalls": 0}  # 바탕 지도는 앱에 넣은 것만
    # 안드로이드 상태 바 글자색: 기기 테마가 바뀌거나 앱으로 돌아오면 DEFAULT 를 다시 요청, 이벤트 테마 중에는 그대로, iOS·플러그인 없음은 듣지 않는다
    assert r["bars"] == {"listening": [1, 1], "start": 0, "afterChange": ["DEFAULT"], "withTheme": 1,
                         "afterThemeOff": ["DEFAULT", "DEFAULT"], "ios": 0, "noPlugin": 0, "threw": False}


def test_native_projects_match_config():
    """앱 아이디·판·시작 화면 색·아이콘·개인정보 매니페스트가 서로 맞다(네이티브 파일을 손으로 고칠 때 깨지기 쉬운 것)."""
    config = json.loads((APP / "capacitor.config.json").read_text(encoding="utf-8"))
    app_id = config["appId"]
    gradle = (APP / "android" / "app" / "build.gradle").read_text(encoding="utf-8")
    pbx = (IOS / "App.xcodeproj" / "project.pbxproj").read_text(encoding="utf-8")
    assert f'applicationId "{app_id}"' in gradle and f'namespace = "{app_id}"' in gradle
    assert pbx.count(f"PRODUCT_BUNDLE_IDENTIFIER = {app_id};") == 2
    activity = APP / "android" / "app" / "src" / "main" / "java" / Path(*app_id.split(".")) / "MainActivity.java"
    assert activity.exists() and activity.read_text(encoding="utf-8").startswith(f"package {app_id};")

    web_version = re.search(r'const APP_VERSION = "([^"]+)"', (ROOT / "web" / "js" / "app.js").read_text(encoding="utf-8")).group(1)
    android_version = re.search(r'versionName "([^"]+)"', gradle).group(1)
    ios_versions = set(re.findall(r"MARKETING_VERSION = ([^;]+);", pbx))
    assert android_version == web_version and ios_versions == {web_version}, (
        f"웹 APP_VERSION {web_version} 에 맞춰 app/android/app/build.gradle versionName 과 iOS MARKETING_VERSION 을 올리세요")
    assert int(re.search(r"targetSdkVersion = (\d+)", (APP / "android" / "variables.gradle").read_text(encoding="utf-8")).group(1)) >= 36
    assert pbx.count("TARGETED_DEVICE_FAMILY = 1;") == 2  # 처음에는 iPhone 만 (디자인 규칙 '스토어 등록 자료')

    colors = {d: re.search(r"#[0-9A-Fa-f]{6}", (RES / d / "colors.xml").read_text(encoding="utf-8")).group(0).upper()
              for d in ("values", "values-night")}
    assert colors == {"values": "#EEF0FF", "values-night": "#16171B"}
    launch = json.loads((IOS / "App" / "Assets.xcassets" / "LaunchBackground.colorset" / "Contents.json").read_text(encoding="utf-8"))
    assert [c.get("appearances", [{}])[0].get("value", "any") for c in launch["colors"]] == ["any", "dark"]
    assert 'name="LaunchBackground"' in (IOS / "App" / "Base.lproj" / "LaunchScreen.storyboard").read_text(encoding="utf-8")

    for density in ("mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi"):
        for name in ("ic_launcher", "ic_launcher_round", "ic_launcher_foreground", "ic_launcher_background", "ic_launcher_monochrome"):
            assert (RES / f"mipmap-{density}" / f"{name}.png").exists(), (density, name)
        for name in ("ic_launcher_foreground", "ic_launcher_background"):
            assert (RES / f"mipmap-night-{density}" / f"{name}.png").exists(), (density, name)
    assert "<monochrome" in (RES / "mipmap-anydpi-v26" / "ic_launcher.xml").read_text(encoding="utf-8")
    icon = json.loads((IOS / "App" / "Assets.xcassets" / "AppIcon.appiconset" / "Contents.json").read_text(encoding="utf-8"))
    assert [i.get("appearances", [{}])[0].get("value", "any") for i in icon["images"]] == ["any", "dark"]

    info = plistlib.loads((IOS / "App" / "Info.plist").read_bytes())
    assert info["ITSAppUsesNonExemptEncryption"] is False and info["CFBundleDevelopmentRegion"] == "ko"
    privacy = plistlib.loads((IOS / "App" / "PrivacyInfo.xcprivacy").read_bytes())
    assert privacy["NSPrivacyTracking"] is False and privacy["NSPrivacyCollectedDataTypes"] == []
    assert privacy["NSPrivacyAccessedAPITypes"][0]["NSPrivacyAccessedAPITypeReasons"] == ["CA92.1"]
    assert pbx.count("PrivacyInfo.xcprivacy in Resources") == 2  # 빌드 파일 + Resources 단계
    swift = (IOS / "App" / "SceneDelegate.swift").read_text(encoding="utf-8")
    assert "rootViewController = MainViewController()" in swift and "allowsBackForwardNavigationGestures = true" in swift
    assert 'customClass="MainViewController"' in (IOS / "App" / "Base.lproj" / "Main.storyboard").read_text(encoding="utf-8")
