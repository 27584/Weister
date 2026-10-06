from PIL import Image, ImageDraw, ImageFont
import os

# 输出目录：项目根的 electron/build/（脚本在 scripts/ 下）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "electron", "build")
os.makedirs(OUT_DIR, exist_ok=True)

# 品牌色（与主界面一致）
INK = (26, 31, 43)      # #1a1f2b 深墨
WHITE = (255, 255, 255)

def make_icon(size):
    """生成单个尺寸图标：深墨圆角方块 + 白色 W"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = int(size * 0.22)
    # 圆角矩形底
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=INK)

    # 字母 W —— 用系统字体，找不到则用几何绘制
    text = "W"
    font = None
    for fp in [r"C:\Windows\Fonts\segoeuib.ttf", r"C:\Windows\Fonts\arialbd.ttf",
               r"C:\Windows\Fonts\seguisb.ttf"]:
        if os.path.exists(fp):
            try:
                font = ImageFont.truetype(fp, int(size * 0.56))
                break
            except Exception:
                pass

    if font:
        bbox = d.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        x = (size - tw) / 2 - bbox[0]
        y = (size - th) / 2 - bbox[1]
        d.text((x, y), text, font=font, fill=WHITE)
    else:
        # 几何 W 兜底
        w = size * 0.5
        h = size * 0.42
        cx, cy = size / 2, size / 2
        lw = max(2, int(size * 0.09))
        pts = [
            (cx - w/2, cy - h/2), (cx - w/4, cy + h/2),
            (cx, cy - h/6), (cx + w/4, cy + h/2), (cx + w/2, cy - h/2)
        ]
        d.line(pts, fill=WHITE, width=lw, joint="curve")
    return img

sizes = [16, 24, 32, 48, 64, 128, 256]
imgs = [make_icon(s) for s in sizes]

out = os.path.join(OUT_DIR, "icon.ico")
imgs[-1].save(out, format="ICO", sizes=[(s, s) for s in sizes])
print("saved", out, os.path.getsize(out), "bytes")

# 同时存一份 PNG 供网页/其他用途
imgs[-1].save(os.path.join(OUT_DIR, "icon.png"))
print("saved", os.path.join(OUT_DIR, "icon.png"))
