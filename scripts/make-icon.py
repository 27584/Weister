from PIL import Image, ImageDraw, ImageFont
import os
import sys

# 输出目录：项目根的 electron/build/（脚本在 scripts/ 下）
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, "electron", "build")
os.makedirs(OUT_DIR, exist_ok=True)

# 品牌色（与主界面一致）
INK = (26, 31, 43)      # #1a1f2b 深墨
WHITE = (255, 255, 255)

# 候选字体：按平台候选目录搜索，不写死盘符或用户名。
# 全部候选都落空时，make_icon 会退回几何绘制（见文件末尾）。
FONT_FILES = [
    "segoeuib.ttf", "arialbd.ttf", "seguisb.ttf",           # Windows
    "DejaVuSans-Bold.ttf", "LiberationSans-Bold.ttf",       # Linux
    "HelveticaNeue.ttc", "SF-Pro-Display-Bold.otf",         # macOS
]


def font_dirs():
    """候选字体目录（全部来自环境变量/家目录，无写死路径）。"""
    dirs = []
    windir = os.environ.get("WINDIR") or os.environ.get("SystemRoot")
    if windir:
        dirs.append(os.path.join(windir, "Fonts"))
    local = os.environ.get("LOCALAPPDATA")
    if local:
        # Windows 10+ 允许把字体装到用户目录
        dirs.append(os.path.join(local, "Microsoft", "Windows", "Fonts"))
    if sys.platform == "darwin":
        dirs += ["/System/Library/Fonts", "/Library/Fonts",
                 os.path.expanduser("~/Library/Fonts")]
    else:
        dirs += ["/usr/share/fonts", "/usr/local/share/fonts",
                 os.path.expanduser("~/.fonts"),
                 os.path.expanduser("~/.local/share/fonts")]
    return [d for d in dirs if d and os.path.isdir(d)]


def find_font(size):
    """返回可用的粗体 ImageFont；一个都找不到则返回 None。"""
    for d in font_dirs():
        # 目录本身 + 一层子目录（如 /usr/share/fonts/truetype/dejavu/）
        subdirs = [d]
        try:
            subdirs += [
                os.path.join(d, s)
                for s in os.listdir(d)
                if os.path.isdir(os.path.join(d, s))
            ]
        except OSError:
            pass
        for sub in subdirs:
            for name in FONT_FILES:
                fp = os.path.join(sub, name)
                if not os.path.exists(fp):
                    continue
                try:
                    return ImageFont.truetype(fp, size)
                except Exception:
                    continue
    return None

def make_icon(size):
    """生成单个尺寸图标：深墨圆角方块 + 白色 W"""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = int(size * 0.22)
    # 圆角矩形底
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=INK)

    # 字母 W —— 用系统字体，找不到则用几何绘制
    text = "W"
    font = find_font(int(size * 0.56))

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
