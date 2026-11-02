"""Draws all the Cat Lock artwork: a white cat asleep on a keyboard.

icon.ico / icon.png   logo: the sleeping cat on a charcoal tile (window, taskbar, shortcut)
tray_watch.ico        tray: asleep on a blue keyboard, gold z (watching)
tray_cat.ico          tray: eyes open on a red keyboard (cat on the keyboard!)
tray_off.ico          tray: grey (Cat Lock is off)
art\\card_<state>@<zoom>.png   the cat in the window's status card
art\\head@<zoom>.png           the small cat by the title
art\\paw_<colour>@<zoom>.png   paw prints for the list of blocked keys
tray_preview.png      everything at real sizes, to check by eye
Run: python make_art.py
"""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).resolve().parent
ART = HERE / "art"
SS = 4                      # drawn 4x bigger, then shrunk, for smooth edges
S = 256 * SS
ICO_SIZES = [16, 20, 24, 32, 40, 48, 64, 256]
ZOOMS = [100, 125, 150, 175, 200, 250, 300]     # Windows display scaling, in %
TILE = (43, 45, 49)

STYLES = {
    "watch": dict(board=(39, 132, 227), keys=(150, 200, 250), fur=(250, 250, 250), line=(60, 63, 68),
                  asleep=True, z=(232, 185, 49)),
    "cat": dict(board=(224, 72, 72), keys=(250, 175, 175), fur=(250, 250, 250), line=(60, 63, 68),
                asleep=False, z=None),
    "off": dict(board=(110, 114, 121), keys=(160, 164, 170), fur=(200, 202, 206), line=(80, 83, 88),
                asleep=True, z=None),
}


def s(*v):
    return [int(x * SS) for x in v]


def draw_cat(style):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fur, line, o = style["fur"] + (255,), style["line"] + (255,), 9   # o = outline width

    # keyboard
    d.rounded_rectangle(s(6, 150, 250, 244), radius=26 * SS, fill=line)
    d.rounded_rectangle(s(12, 156, 244, 238), radius=21 * SS, fill=style["board"] + (255,))
    for row, y in enumerate((196, 219)):
        for i in range(7):
            x = 22 + row * 9 + i * 31
            if x + 22 < 240:
                d.rounded_rectangle(s(x, y, x + 22, y + 14), radius=4 * SS, fill=style["keys"] + (255,))

    # cat: outline shapes first, then fur on top, so the outline wraps the whole cat
    body = (30, 88, 196, 186)
    head = (134, 76, 226, 160)
    ears = [[(142, 104), (148, 52), (180, 84)], [(184, 80), (216, 48), (222, 108)]]
    tail = (26, 104, 196, 200)          # tail curls round the front, along the bottom
    for grow, col in ((o, line), (0, fur)):
        d.ellipse(s(body[0] - grow, body[1] - grow, body[2] + grow, body[3] + grow), fill=col)
        d.ellipse(s(head[0] - grow, head[1] - grow, head[2] + grow, head[3] + grow), fill=col)
        for ear in ears:
            cx = sum(p[0] for p in ear) / 3
            cy = sum(p[1] for p in ear) / 3
            pts = []
            for px_, py_ in ear:
                dx, dy = px_ - cx, py_ - cy
                k = 1 + grow / max(1, (dx * dx + dy * dy) ** 0.5) * 1.8
                pts += s(cx + dx * k, cy + dy * k)
            d.polygon(pts, fill=col)
        d.arc(s(*tail), 35, 150, fill=col, width=(22 + 2 * grow) * SS)
    # pink inside the ears
    pink = (246, 170, 190, 255) if style is not STYLES["off"] else (190, 180, 185, 255)
    d.polygon(s(151, 96, 154, 66, 172, 86), fill=pink)
    d.polygon(s(190, 82, 211, 62, 214, 100), fill=pink)
    # a soft line where the head rests on the body
    d.arc(s(126, 70, 230, 168), 95, 175, fill=line, width=5 * SS)

    # face
    if style["asleep"]:
        d.arc(s(150, 108, 174, 128), 20, 160, fill=line, width=6 * SS)
        d.arc(s(186, 106, 210, 126), 20, 160, fill=line, width=6 * SS)
    else:
        for cx in (162, 198):
            d.ellipse(s(cx - 10, 104, cx + 10, 126), fill=line)
            d.ellipse(s(cx - 6, 107, cx + 6, 123), fill=(120, 200, 90, 255))
            d.ellipse(s(cx - 2, 108, cx + 2, 122), fill=line)
    d.polygon(s(174, 134, 186, 134, 180, 141), fill=(236, 120, 150, 255))

    if style["z"]:
        try:
            font = ImageFont.truetype("arialbd.ttf", 64 * SS)
            small = ImageFont.truetype("arialbd.ttf", 42 * SS)
        except OSError:
            font = small = ImageFont.load_default()
        z = style["z"] + (255,)
        for txt, f, xy in (("z", font, (40, 10)), ("z", small, (92, 0))):
            d.text(s(*xy), txt, font=f, fill=z, stroke_width=4 * SS, stroke_fill=line)
    return img.resize((256, 256), Image.LANCZOS)


def draw_logo(cat):
    """The sleeping cat on a charcoal tile."""
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(img).rounded_rectangle(s(8, 8, 248, 248), radius=48 * SS, fill=TILE + (255,))
    img = img.resize((256, 256), Image.LANCZOS)
    img.alpha_composite(cat.resize((216, 216), Image.LANCZOS), (20, 22))
    return img


def draw_paw(colour):
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    c = colour + (255,)
    d.ellipse(s(66, 116, 190, 214), fill=c)                        # big pad
    for x, y in ((46, 64), (92, 26), (148, 26), (194, 64)):        # four toes
        d.ellipse(s(x - 26, y - 30, x + 26, y + 30), fill=c)
    return img.resize((256, 256), Image.LANCZOS)


def sized(img, logical, zoom):
    n = max(1, round(logical * zoom / 100))
    return img.resize((n, n), Image.LANCZOS)


def main():
    cats = {name: draw_cat(st) for name, st in STYLES.items()}
    logo = draw_logo(cats["watch"])
    logo.save(HERE / "icon.ico", sizes=[(n, n) for n in ICO_SIZES])
    logo.save(HERE / "icon.png")
    for name, img in cats.items():
        img.save(HERE / f"tray_{name}.ico", sizes=[(n, n) for n in ICO_SIZES])

    ART.mkdir(exist_ok=True)
    paws = {"gold": draw_paw((232, 185, 49)), "red": draw_paw((255, 107, 107))}
    for zoom in ZOOMS:
        for name, img in cats.items():
            sized(img, 76, zoom).save(ART / f"card_{name}@{zoom}.png")
        sized(cats["watch"], 30, zoom).save(ART / f"head@{zoom}.png")
        for name, img in paws.items():
            sized(img, 13, zoom).save(ART / f"paw_{name}@{zoom}.png")

    # preview sheet: logo + tray icons big, then 16/24/32 on a dark and a light taskbar
    sheet = Image.new("RGBA", (4 * 280 + 20, 420), (30, 31, 34, 255))
    d = ImageDraw.Draw(sheet)
    for i, img in enumerate([logo] + list(cats.values())):
        x = 20 + i * 280
        sheet.alpha_composite(img, (x, 10))
        for bg, y in (((32, 32, 32), 290), ((238, 238, 238), 350)):
            d.rectangle((x, y, x + 256, y + 50), fill=bg + (255,))
            cx = x + 10
            for n in (16, 24, 32):
                sheet.alpha_composite(img.resize((n, n), Image.LANCZOS), (cx, y + 25 - n // 2))
                cx += n + 20
    sheet.save(HERE / "tray_preview.png")


if __name__ == "__main__":
    main()
