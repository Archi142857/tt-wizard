"""웹 앱(PWA) 아이콘 → web/icons/*.png. 한 번 만들어 커밋한다(Pillow 필요, matplotlib 과 같이 설치된다).

  python scripts/make_icons.py

그림: 파란 바탕 위 흰 시간표 칸(요일 세 칸의 수업 블록, 전필 파랑·전선 초록·교양 주황 = 화면과 같은 색)과
그 위를 지나 도착 핀까지 가는 S자 동선. 1024 px 로 그린 뒤 줄여서 가장자리를 매끄럽게 한다.
  icon-192.png, icon-512.png       둥근 사각형(바깥은 투명). 설치 목록·데스크톱용
  icon-maskable-512.png            꽉 찬 사각형. 안드로이드가 원·둥근 사각형으로 자른다(그림은 가운데 80 % 안에)
  apple-touch-icon.png (180)       iOS 홈 화면. 꽉 찬 사각형(iOS 가 모서리를 깎는다)
  favicon-32.png                   브라우저 탭
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "icons"
S = 1024
ACCENT = (49, 130, 246)  # --accent #3182f6
INK = (25, 31, 40)  # --text #191f28
BLUE, GREEN, ORANGE = (77, 148, 245), (52, 179, 126), (240, 154, 62)  # 교과구분 색 (app.js CLS_COLORS)


def draw(full_bleed: bool, scale: float) -> Image.Image:
    """scale = 그림(흰 칸)이 차지하는 비율. maskable 은 작게 해서 잘려도 남게 한다."""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if full_bleed:
        d.rectangle([0, 0, S, S], fill=ACCENT)
    else:
        d.rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.225), fill=ACCENT)
    c, w = S / 2, S * scale

    def pt(x, y):  # 흰 칸 안의 비율 좌표 → 픽셀
        return c + (x - 0.5) * w, c + (y - 0.5) * w

    def box(x0, y0, x1, y1):
        return [*pt(x0, y0), *pt(x1, y1)]

    d.rounded_rectangle(box(0.0, 0.0, 1.0, 1.0), radius=int(w * 0.14), fill=(255, 255, 255))
    # 요일 세 칸의 수업 블록 (결과 화면 순위 카드의 주간 막대처럼)
    bars = [(0, 0.12, 0.34, BLUE), (0, 0.56, 0.72, ORANGE), (1, 0.22, 0.46, GREEN), (1, 0.70, 0.88, BLUE),
            (2, 0.46, 0.62, GREEN), (2, 0.74, 0.88, ORANGE)]
    for col, y0, y1, color in bars:
        x0 = 0.12 + col * 0.27
        d.rounded_rectangle(box(x0, y0, x0 + 0.22, y1), radius=int(w * 0.045), fill=color)
    # 동선: 왼쪽 아래에서 오른쪽 위 핀까지 S자 길
    p0, p1, p2, p3 = (0.2, 0.86), (0.72, 0.92), (0.26, 0.26), (0.79, 0.3)
    curve = []
    for i in range(801):
        t = i / 800
        x = (1 - t) ** 3 * p0[0] + 3 * (1 - t) ** 2 * t * p1[0] + 3 * (1 - t) * t ** 2 * p2[0] + t ** 3 * p3[0]
        y = (1 - t) ** 3 * p0[1] + 3 * (1 - t) ** 2 * t * p1[1] + 3 * (1 - t) * t ** 2 * p2[1] + t ** 3 * p3[1]
        curve.append(pt(x, y))
    lw = w * 0.075
    # 굵은 곡선은 원을 촘촘히 찍어 그린다(Pillow 의 굵은 꺾은선은 곡선에서 톱니가 생긴다). 흰 테두리 먼저
    for radius, color in ((lw * 0.95, (255, 255, 255)), (lw * 0.5, INK)):
        for x, y in curve:
            d.ellipse([x - radius, y - radius, x + radius, y + radius], fill=color)
    sx, sy = pt(*p0)
    r = lw * 0.95
    d.ellipse([sx - r, sy - r, sx + r, sy + r], fill=INK)
    d.ellipse([sx - r * 0.45, sy - r * 0.45, sx + r * 0.45, sy + r * 0.45], fill=(255, 255, 255))
    # 도착 핀
    tx, ty = pt(*p3)
    pr = w * 0.105
    cy = ty - pr * 1.55
    d.ellipse([tx - pr - lw * 0.45, cy - pr - lw * 0.45, tx + pr + lw * 0.45, cy + pr + lw * 0.45], fill=(255, 255, 255))
    d.polygon([(tx - pr * 0.8, cy + pr * 0.55), (tx + pr * 0.8, cy + pr * 0.55), (tx, ty + lw * 0.2)], fill=(255, 255, 255))
    d.ellipse([tx - pr, cy - pr, tx + pr, cy + pr], fill=INK)
    d.polygon([(tx - pr * 0.62, cy + pr * 0.72), (tx + pr * 0.62, cy + pr * 0.72), (tx, ty)], fill=INK)
    d.ellipse([tx - pr * 0.4, cy - pr * 0.4, tx + pr * 0.4, cy + pr * 0.4], fill=(255, 255, 255))
    return img


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rounded, full, mask = draw(False, 0.62), draw(True, 0.62), draw(True, 0.52)
    outputs = {
        "icon-192.png": (rounded, 192), "icon-512.png": (rounded, 512), "icon-maskable-512.png": (mask, 512),
        "apple-touch-icon.png": (full, 180), "favicon-32.png": (rounded, 32),
    }
    for name, (img, size) in outputs.items():
        out = img.resize((size, size), Image.LANCZOS)
        if name == "apple-touch-icon.png":
            out = out.convert("RGB")  # iOS 는 투명을 검게 칠한다
        out.save(OUT / name, optimize=True)
        print(f"  {name} {size}px")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
