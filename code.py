import board
import displayio
import busio
import digitalio
import supervisor
import sys
import time
import math
from fourwire import FourWire
from adafruit_st7735r import ST7735R

try:
    import neopixel
    HAS_NEOPIXEL = True
except ImportError:
    HAS_NEOPIXEL = False

# ─── 1. HARDWARE INIT (Waveshare RP2040-Zero + ST7735R 160x80) ──────────────
displayio.release_displays()

backlight = digitalio.DigitalInOut(board.GP5)
backlight.direction = digitalio.Direction.OUTPUT
backlight.value = True

spi = busio.SPI(clock=board.GP2, MOSI=board.GP3)
display_bus = FourWire(spi, command=board.GP1, chip_select=board.GP0, reset=board.GP4)

display = ST7735R(
    display_bus,
    width=160, height=80,
    colstart=26, rowstart=1,
    rotation=270, invert=True, bgr=False,
    auto_refresh=False
)

led = None
if HAS_NEOPIXEL and hasattr(board, "GP16"):
    try:
        led = neopixel.NeoPixel(board.GP16, 1, brightness=0.18, auto_write=False)
        led[0] = (0, 80, 160)
        led.show()
    except Exception:
        led = None

# ─── 2. CRISP 8-BIT PICO-8 / NES INSPIRED PALETTE (32 COLORS) ───────────────
NUM_COLORS = 32
bg_bmp = displayio.Bitmap(160, 80, NUM_COLORS)
fg_bmp = displayio.Bitmap(160, 80, NUM_COLORS)

bg_pal = displayio.Palette(NUM_COLORS)
fg_pal = displayio.Palette(NUM_COLORS)

COLORS = [
    0x06070C,  # 0: Crisp 8-bit Black Outline (Transparent on FG)
    0x111526,  # 1: Wall dark navy brick
    0x1A2038,  # 2: Wall mid indigo
    0x262F52,  # 3: Wall highlight / mortar
    0x06070C,  # 4: Solid black (for FG drawing where 0 is transparent!)
    0x211209,  # 5: Deep wood shadow
    0x452614,  # 6: Dark walnut wood
    0x784727,  # 7: Warm oak wood
    0xAD6E3E,  # 8: Bright wood bevel edge
    0x99B2CC,  # 9: Yeti/Bear fur deep shadow (cool ice-gray)
    0xCFE2F5,  # 10: Yeti/Bear fur mid-shadow (soft frost blue-white)
    0xFFFFFF,  # 11: Yeti/Bear pure snow white fur
    0x38170D,  # 12: Dark coffee / dark brown
    0x85371E,  # 13: Terracotta pot / chair leather shadow
    0xCC5A33,  # 14: Terracotta highlight / chair leather
    0x1D4ED8,  # 15: Scarf / Bandana shadow (changes with mood)
    0x3B82F6,  # 16: Scarf / Bandana main (changes with mood)
    0x7DD3FC,  # 17: Yeti horns / ice cyan highlight
    0x27303F,  # 18: Dark monitor/keyboard casing
    0x55647A,  # 19: Medium gray plastic/metal
    0x9BA9BD,  # 20: Light gray keycaps / silver monitor edge
    0x0C4A2B,  # 21: Dark cactus / forest green
    0x199E56,  # 22: Mid emerald green
    0x4EFF9B,  # 23: Bright 8-bit neon green (code / hills)
    0x0A1936,  # 24: Night sky deep blue
    0x2563EB,  # 25: Day sky upper blue
    0x60B5FF,  # 26: Day sky bright cyan-blue
    0x7F1124,  # 27: Dark crimson
    0xEF2B41,  # 28: Bright 8-bit red (mug / heart / alert)
    0xFF82A9,  # 29: Cute cheek blush pink / sunset pink
    0xFFCC22,  # 30: Bright 8-bit gold / sun / frame
    0xFFFFFF,  # 31: Pure crisp white
]

for idx, col in enumerate(COLORS):
    bg_pal[idx] = col
    fg_pal[idx] = col

fg_pal.make_transparent(0)

bg_grid = displayio.TileGrid(bg_bmp, pixel_shader=bg_pal)
fg_grid = displayio.TileGrid(fg_bmp, pixel_shader=fg_pal)

root_group = displayio.Group()
root_group.append(bg_grid)
root_group.append(fg_grid)
display.root_group = root_group

# ─── 3. 8-BIT DRAWING PRIMITIVES ────────────────────────────────────────────
def fill_rect(b, x, y, w, h, c):
    x0 = max(0, x)
    y0 = max(0, y)
    x1 = min(160, x + w)
    y1 = min(80, y + h)
    for py in range(y0, y1):
        for px in range(x0, x1):
            b[px, py] = c

def draw_hline(b, x, y, w, c):
    if 0 <= y < 80:
        for px in range(max(0, x), min(160, x + w)):
            b[px, y] = c

def draw_vline(b, x, y, h, c):
    if 0 <= x < 160:
        for py in range(max(0, y), min(80, y + h)):
            b[x, py] = c

def set_px(b, x, y, c):
    if 0 <= x < 160 and 0 <= y < 80:
        b[x, y] = c

def draw_border(b, x, y, w, h, c):
    draw_hline(b, x, y, w, c)
    draw_hline(b, x, y + h - 1, w, c)
    draw_vline(b, x, y, h, c)
    draw_vline(b, x + w - 1, y, h, c)

def draw_8bit_box(b, x, y, w, h, fill_c, hi_c, sh_c, out_c=4):
    fill_rect(b, x, y, w, h, fill_c)
    draw_hline(b, x + 1, y + 1, w - 2, hi_c)
    draw_vline(b, x + 1, y + 1, h - 2, hi_c)
    draw_hline(b, x + 1, y + h - 2, w - 2, sh_c)
    draw_vline(b, x + w - 2, y + 1, h - 2, sh_c)
    draw_border(b, x, y, w, h, out_c)

CHAR_MAP = {
    ".": -1,
    "0": 4,   # Solid black outline on FG!
    "1": 1, "2": 2, "3": 3, "4": 4,
    "5": 5, "6": 6, "7": 7, "8": 8,
    "s": 9, "S": 10, "W": 11,         # Yeti/Snow Bear Fur: deep shadow, frost shadow, snow white
    "h": 12, "m": 13, "M": 14,        # Brown/Terracotta
    "c": 15, "C": 16, "I": 17,        # Scarf (c/C) & Ice Horns/Snout (I)
    "d": 18, "g": 19, "G": 20,        # Monitor/Keyboard grays
    "f": 21, "e": 22, "E": 23,        # Greens
    "n": 24, "b": 25, "B": 26,        # Sky blues
    "r": 27, "R": 28, "P": 29,        # Red / Blush Pink
    "Y": 30,                          # Gold
}

def blit_sprite(b, x, y, rows):
    for ry, row in enumerate(rows):
        py = y + ry
        if py < 0 or py >= 80:
            continue
        for rx, ch in enumerate(row):
            if ch == ".":
                continue
            px = x + rx
            if 0 <= px < 160:
                b[px, py] = CHAR_MAP.get(ch, 4)

# ─── 4. STATIC 8-BIT ROOM & DESK (LAYER 0 BG) ───────────────────────────────
def build_static_room():
    # 1. Crisp 8-Bit Brick Wall (y=0..45)
    fill_rect(bg_bmp, 0, 0, 160, 46, 2)
    for by in range(0, 46, 8):
        draw_hline(bg_bmp, 0, by, 160, 1)
        off = 8 if ((by // 8) % 2 == 1) else 0
        for bx in range(off, 160, 16):
            draw_vline(bg_bmp, bx, by, 8, 1)
            draw_hline(bg_bmp, bx + 1, by + 1, 14, 3)

    # 2. Wood Wainscoting Wall Panels (y=46..58)
    draw_hline(bg_bmp, 0, 46, 160, 4)
    draw_hline(bg_bmp, 0, 47, 160, 8)
    fill_rect(bg_bmp, 0, 48, 160, 11, 6)
    for px in range(4, 156, 20):
        draw_border(bg_bmp, px, 49, 16, 8, 5)
        draw_hline(bg_bmp, px + 1, 56, 14, 7)

    # 3. Left Wall Framed Mountain Landscape Painting (x=3..48, y=4..41)
    fill_rect(bg_bmp, 5, 6, 46, 38, 1)  # Cast drop shadow
    draw_8bit_box(bg_bmp, 3, 4, 46, 38, 7, 8, 6, 4)
    draw_border(bg_bmp, 5, 6, 42, 34, 30)  # Gold inner frame trim

    # 4. Right Wall Ornate Picture Frame + Gallery Lamp (x=105..152, y=4..41)
    fill_rect(bg_bmp, 108, 6, 47, 38, 1)  # Drop shadow
    draw_8bit_box(bg_bmp, 105, 4, 48, 38, 7, 8, 6, 4)
    draw_border(bg_bmp, 107, 6, 44, 34, 30)
    # Brass Gallery Lamp above frame
    fill_rect(bg_bmp, 121, 1, 17, 3, 30)
    draw_hline(bg_bmp, 122, 1, 15, 31)

    # 5. Cozy Wooden Desk Surface (y=58..79) — No printer on the left!
    draw_hline(bg_bmp, 0, 58, 160, 4)
    draw_hline(bg_bmp, 0, 59, 160, 8)
    fill_rect(bg_bmp, 0, 60, 160, 11, 7)
    # Crisp 8-bit wood plank lines
    for gy, gx in ((63, 20), (66, 85), (69, 40)):
        draw_hline(bg_bmp, 0, gy, 160, 6)
        draw_hline(bg_bmp, gx, gy, 18, 8)
    # Desk front edge & drawers
    draw_hline(bg_bmp, 0, 71, 160, 8)
    draw_hline(bg_bmp, 0, 72, 160, 6)
    draw_hline(bg_bmp, 0, 73, 160, 4)
    fill_rect(bg_bmp, 0, 74, 160, 6, 5)
    for dx in (8, 118):
        draw_8bit_box(bg_bmp, dx, 74, 34, 6, 6, 7, 5, 4)
        fill_rect(bg_bmp, dx + 14, 76, 6, 2, 30)

    # 6. Far-Right Potted Cactus (x=137..155, y=47..65)
    fill_rect(bg_bmp, 137, 63, 16, 3, 5)
    CACTUS_SPRITE = [
        "......0000......",
        ".....0rPPr0.....",
        "....00eEEe00....",
        "...0fEeEEeEf0...",
        ".000fEeEEeEf0...",
        "0eEefEeEEeEf000.",
        "0fEefEeEEeEfEeE0",
        ".000fEeEEeEfEe0.",
        "...0fEeEEeEf00..",
        "...0fEeEEeEf0...",
        "..000000000000..",
        ".0mMMmmmmmmmmh0.",
        ".0mMMmmmmmmmmh0.",
        "..00mMMmmmmh00..",
        "...0mMMmmmmh0...",
        "...0mMMmmmmh0...",
        "...0hhhhhhhh0...",
        "....00000000....",
    ]
    blit_sprite(bg_bmp, 137, 47, CACTUS_SPRITE)

build_static_room()

# ─── 5. MOUNTAIN & FOREST LANDSCAPE PAINTING (x=6..45, y=7..38 -> 40x32) ────
def draw_big_window(frame, hour, cpu_load):
    wx, wy, ww, wh = 6, 7, 40, 32

    is_day = 7 <= hour < 18
    is_sunset = 18 <= hour < 21

    # ── 1. Sky Background (Day Blue / Sunset / Starry Night / CPU Storm) ──
    if cpu_load >= 85:
        fill_rect(fg_bmp, wx, wy, ww, 14, 27)
        fill_rect(fg_bmp, wx, wy + 14, ww, 18, 28)
        if (frame // 2) % 2 == 0:
            for i in range(5):
                set_px(fg_bmp, wx + 22 - (i % 2), wy + 2 + i * 2, 31)
    elif is_day:
        # Bright blue daytime sky
        fill_rect(fg_bmp, wx, wy, ww, 11, 25)
        fill_rect(fg_bmp, wx, wy + 11, ww, 13, 26)
        # Golden Sun in top-right sky
        sx, sy = wx + 29, wy + 3
        fill_rect(fg_bmp, sx + 1, sy, 5, 7, 30)
        fill_rect(fg_bmp, sx, sy + 1, 7, 5, 30)
        fill_rect(fg_bmp, sx + 2, sy + 2, 3, 3, 31)
        # Slowly drifting 8-bit white cloud
        cl_x = wx + 2 + ((frame // 8) % 22)
        fill_rect(fg_bmp, cl_x, wy + 5, 9, 3, 31)
        fill_rect(fg_bmp, cl_x + 2, wy + 4, 5, 2, 31)
    elif is_sunset:
        # Warm evening sunset sky
        fill_rect(fg_bmp, wx, wy, ww, 8, 2)
        fill_rect(fg_bmp, wx, wy + 8, ww, 8, 29)
        fill_rect(fg_bmp, wx, wy + 16, ww, 8, 30)
        # Setting sun behind mountain ridge
        fill_rect(fg_bmp, wx + 26, wy + 11, 8, 7, 28)
        fill_rect(fg_bmp, wx + 27, wy + 12, 6, 5, 30)
    else:
        # Dark starry night sky
        fill_rect(fg_bmp, wx, wy, ww, 24, 24)
        # Crescent Moon
        fill_rect(fg_bmp, wx + 30, wy + 3, 5, 5, 30)
        fill_rect(fg_bmp, wx + 31, wy + 4, 3, 3, 31)
        fill_rect(fg_bmp, wx + 32, wy + 3, 3, 3, 24)
        # Twinkling stars across the night sky
        for idx, (stx, sty) in enumerate(((4, 3), (12, 5), (21, 3), (25, 8), (7, 10), (36, 11))):
            col = 31 if ((frame // 6 + idx) % 2 == 0) else 17
            set_px(fg_bmp, wx + stx, wy + sty, col)

    # ── 2. Layered 8-Bit Snow-Capped Mountains ──
    # Distant right peak (peak at wx+28, wy+11)
    m2_light = 20 if is_day else (14 if is_sunset else 19)
    m2_dark = 19 if is_day else (13 if is_sunset else 18)
    for r in range(14):
        w_half = r + 1
        py = wy + 11 + r
        x_left = max(wx, wx + 28 - w_half)
        x_mid = wx + 28
        x_right = min(wx + ww, wx + 28 + w_half)
        snow_l = 31 if r < 4 else m2_light
        snow_r = 10 if r < 4 else m2_dark
        draw_hline(fg_bmp, x_left, py, x_mid - x_left, snow_l)
        draw_hline(fg_bmp, x_mid, py, x_right - x_mid, snow_r)

    # Main grand mountain peak on left-center (peak at wx+13, wy+8)
    m1_light = 20 if is_day else (16 if is_sunset else 16)
    m1_dark = 18 if is_day else (15 if is_sunset else 15)
    for r in range(17):
        w_half = r + 1
        py = wy + 8 + r
        x_left = max(wx, wx + 13 - w_half)
        x_mid = wx + 13
        x_right = min(wx + ww, wx + 13 + w_half)
        # Jagged snow cap line (rows 0..5)
        is_snow = (r < 5) or (r == 5 and (r % 2 == 0))
        col_l = 31 if is_snow else m1_light
        col_r = 10 if is_snow else m1_dark
        draw_hline(fg_bmp, x_left, py, x_mid - x_left, col_l)
        draw_hline(fg_bmp, x_mid, py, x_right - x_mid, col_r)

    # ── 3. Evergreen Pine Forest along the Mountain Base (y=wy+22..wy+31) ──
    fill_rect(fg_bmp, wx, wy + 25, ww, 7, 21)
    tree_hi = 23 if is_day else (22 if is_sunset else 22)
    tree_sh = 22 if is_day else (21 if is_sunset else 21)
    # Draw row of 8-bit pixel pine trees across the foreground
    for tx in range(wx + 2, wx + ww - 2, 5):
        ty = wy + 20 + ((tx * 3) % 3)
        # 3-tiered pine tree crown
        for tier in range(3):
            tw = 3 + tier * 2
            t_y = ty + tier * 2
            draw_hline(fg_bmp, tx - tier, t_y, tw // 2 + 1, tree_hi)
            draw_hline(fg_bmp, tx, t_y, tw // 2 + 1, tree_sh)
            draw_hline(fg_bmp, tx - tier, t_y + 1, tw, 21)

# ─── 6. 8-BIT DYNAMIC WALL PAINTING (x=108..149, y=7..38 -> 42x32) ──────────
def draw_8bit_painting(frame, poster_type):
    cx, cy, cw, ch = 108, 7, 42, 32

    if poster_type == "code_matrix":
        fill_rect(fg_bmp, cx, cy, cw, ch, 24)
        for col in range(2, cw - 2, 5):
            drop = (frame * 2 + col * 7) % (ch - 5)
            draw_vline(fg_bmp, cx + col, cy + drop, 3, 21)
            draw_vline(fg_bmp, cx + col, cy + drop + 2, 2, 22)
            set_px(fg_bmp, cx + col, cy + drop + 4, 23)
            set_px(fg_bmp, cx + col, cy + drop + 5, 31)
        draw_8bit_box(fg_bmp, cx + 8, cy + 6, 26, 19, 24, 23, 21, 4)
        fill_rect(fg_bmp, cx + 9, cy + 7, 24, 3, 22)
        set_px(fg_bmp, cx + 11, cy + 8, 28)
        set_px(fg_bmp, cx + 13, cy + 8, 30)
        set_px(fg_bmp, cx + 15, cy + 8, 23)
        draw_hline(fg_bmp, cx + 12, cy + 13, 10, 23)
        draw_hline(fg_bmp, cx + 12, cy + 16, 14, 26)
        if (frame // 4) % 2 == 0:
            fill_rect(fg_bmp, cx + 27, cy + 15, 3, 3, 31)

    elif poster_type == "bug_alert":
        fill_rect(fg_bmp, cx, cy, cw, ch, 27 if (frame // 4) % 2 == 0 else 24)
        bx = cx + 8 + ((frame // 3) % 3) - 1
        by = cy + 9
        BUG_SPRITE = [
            "....00..00....",
            "...0Y0000Y0...",
            "..00rrrrrr00..",
            ".0rRPPPPPPrr0.",
            "00rRPWrrWPRr00",
            ".0rRRRRRRRRr0.",
            "00rR0RRRR0Rr00",
            ".0rRRRRRRRRr0.",
            "00rrRRRRRRrr00",
            "..00rrrrrr00..",
            "....000000....",
        ]
        blit_sprite(fg_bmp, bx, by, BUG_SPRITE)
        draw_8bit_box(fg_bmp, cx + 27, cy + 7, 9, 17, 30, 31, 14, 4)
        fill_rect(fg_bmp, cx + 30, cy + 10, 3, 7, 4)
        fill_rect(fg_bmp, cx + 30, cy + 19, 3, 3, 4)

    elif poster_type == "coffee_need":
        fill_rect(fg_bmp, cx, cy, cw, 22, 2)
        fill_rect(fg_bmp, cx, cy + 22, cw, 10, 7)
        draw_hline(fg_bmp, cx, cy + 22, cw, 8)
        CUP_SPRITE = [
            "....000000000000....",
            "..00WWWWWWWWWWWW00..",
            ".0WWmmmmmmmmmmmmWW0.",
            ".0WWRRRRRRRRRrrrgg00",
            ".0WWRRRRRRRRRrrrggG0",
            ".0WWRRRRRRRRRrrrggG0",
            "..0WRRRRRRRRRrrgg00.",
            "..00RRRRRRRRRrrg0...",
            "...00rrrrrrrrgg0....",
            ".00WWWWWWWWWWWWWW00.",
            "0WWWWWWWWWWWWWWWWWW0",
            ".000000000000000000.",
        ]
        blit_sprite(fg_bmp, cx + 11, cy + 14, CUP_SPRITE)
        s = (frame // 3) % 5
        for sx in (cx + 16, cx + 21, cx + 25):
            set_px(fg_bmp, sx + ((s + sx) % 2), cy + 11 - s, 31)
            set_px(fg_bmp, sx, cy + 9 - s, 20)

    elif poster_type == "brain_idea":
        fill_rect(fg_bmp, cx, cy, cw, ch, 24)
        BULB_SPRITE = [
            "....000000....",
            "..00YYYYYY00..",
            ".0YYWWYYYYYY0.",
            "0YYWWYYYYYYYY0",
            "0YYYYYYYYYYYY0",
            "0YYYYYYYYYYYY0",
            ".0YYYYYYYYYY0.",
            "..00YYYYYY00..",
            "...0GGGGGG0...",
            "...0dddddd0...",
            "...0GGGGGG0...",
            "....00dd00....",
        ]
        blit_sprite(fg_bmp, cx + 14, cy + 7, BULB_SPRITE)
        if (frame // 3) % 2 == 0:
            for rx_p, ry_p in ((cx + 9, cy + 12), (cx + 31, cy + 12), (cx + 11, cy + 6), (cx + 29, cy + 6)):
                fill_rect(fg_bmp, rx_p, ry_p, 2, 2, 30)

    elif poster_type == "fire_panic":
        fill_rect(fg_bmp, cx, cy, cw, ch, 27)
        for col in range(2, cw - 2, 3):
            h_red = 10 + ((frame * 3 + col * 5) % 18)
            fill_rect(fg_bmp, cx + col, cy + ch - h_red, 3, h_red, 28)
            fill_rect(fg_bmp, cx + col, cy + ch - (h_red // 2), 3, h_red // 2, 30)
            fill_rect(fg_bmp, cx + col, cy + ch - (h_red // 4), 2, h_red // 4, 31)

    elif poster_type == "music_eq":
        fill_rect(fg_bmp, cx, cy, cw, ch, 1)
        for i in range(8):
            bh = 4 + ((frame * (i + 2) + i * 7) % 24)
            bx = cx + 4 + i * 4
            fill_rect(fg_bmp, bx, cy + ch - 2 - bh, 3, bh, 26)
            fill_rect(fg_bmp, bx, cy + ch - 2 - (bh // 2), 3, bh // 2, 23)
            draw_hline(fg_bmp, bx, cy + ch - 2 - bh, 3, 31)

    elif poster_type == "chill_play":
        fill_rect(fg_bmp, cx, cy, cw, ch, 2)
        draw_8bit_box(fg_bmp, cx + 5, cy + 4, 32, 24, 28, 29, 27, 4)
        for py in range(-5, 6):
            w_row = 6 - abs(py)
            draw_hline(fg_bmp, cx + 18, cy + 16 + py, w_row, 31)

    elif poster_type == "rocket_launch":
        fill_rect(fg_bmp, cx, cy, cw, ch, 24)
        for st in range(6):
            sy = cy + ((st * 6 + frame * 2) % (ch - 2))
            set_px(fg_bmp, cx + 4 + st * 6, sy, 31)
        rx, ry = cx + 16, cy + 4 + ((frame // 2) % 2)
        ROCKET_SPRITE = [
            "....00....",
            "...0rR0...",
            "..0rRRR0..",
            "..0WGGG0..",
            ".0WWGGGG0.",
            ".0WWbBGG0.",
            ".0WWbBGG0.",
            ".0WWGGGG0.",
            "0rWWGGGGrr",
            "0RWWGGGGRR",
            "0000000000",
        ]
        blit_sprite(fg_bmp, rx, ry, ROCKET_SPRITE)
        fh = 4 + (frame % 4)
        fill_rect(fg_bmp, rx + 2, ry + 11, 6, fh, 28)
        fill_rect(fg_bmp, rx + 3, ry + 11, 4, fh - 1, 30)

    elif poster_type == "heart_love":
        fill_rect(fg_bmp, cx, cy, cw, ch, 1)
        beat = 1 if (frame // 5) % 2 == 0 else 0
        HEART_SPRITE = [
            "..0000..0000..",
            ".0RRRR00RRRR0.",
            "0RWWWRRRRRRRR0",
            "0RWWWRRRRRrrR0",
            "0RRRRRRRRrrrR0",
            ".0RRRRRRrrrr0.",
            "..0RRRRrrrr0..",
            "...0RRRrrr0...",
            "....0RRrr0....",
            ".....0Rr0.....",
            "......00......",
        ]
        blit_sprite(fg_bmp, cx + 14, cy + 10 - beat, HEART_SPRITE)

    elif poster_type == "zzz_dream":
        fill_rect(fg_bmp, cx, cy, cw, ch, 24)
        fill_rect(fg_bmp, cx + 27, cy + 5, 7, 7, 30)
        cl_x = cx + 5 + ((frame // 5) % 12)
        CLOUD_SPRITE = [
            "....00000.....",
            "..00WWWWW000..",
            ".0WWWWWWWWWW0.",
            "0WWWWWWWWGGGg0",
            "0GGGggggggggg0",
            ".000000000000.",
        ]
        blit_sprite(fg_bmp, cl_x, cy + 17, CLOUD_SPRITE)

    else:
        # "zen_mountain"
        fill_rect(fg_bmp, cx, cy, cw, 16, 25)
        fill_rect(fg_bmp, cx, cy + 16, cw, 8, 29)
        fill_rect(fg_bmp, cx + 23, cy + 6, 10, 10, 30)
        for r in range(13):
            mw = 4 + r * 2
            mx = cx + 17 - r
            my = cy + 11 + r
            col_l = 31 if r < 5 else 16
            col_r = 20 if r < 5 else 15
            draw_hline(fg_bmp, mx, my, mw // 2 + 1, col_l)
            draw_hline(fg_bmp, mx + mw // 2 + 1, my, mw // 2, col_r)
        fill_rect(fg_bmp, cx, cy + 24, cw, 8, 24)

# ─── 7. CUTE 8-BIT SNOW BEAR / YETI + SIDE MONITOR + KEYBOARD ───────────────
# Strict non-overlapping clear zones so BOTH Wall Paintings (y<42) are NEVER touched!
def clear_center_stage():
    fill_rect(fg_bmp, 50, 18, 54, 24, 0)   # Upper Yeti head/chair zone between paintings
    fill_rect(fg_bmp, 18, 42, 110, 26, 0)  # Lower desk zone (monitor + keyboard + paws + mug)

def update_scarf_palette(mood, activity, cpu_load):
    if mood in ("stressed", "panicking") or cpu_load >= 85:
        fg_pal[15], fg_pal[16] = 0x991B1B, 0xEF4444
    elif mood == "vibing" or activity == "music":
        fg_pal[15], fg_pal[16] = 0x5B21B6, 0xA855F7
    elif mood == "happy":
        fg_pal[15], fg_pal[16] = 0x065F46, 0x10B981
    elif mood in ("tired", "sleepy") or activity == "sleeping":
        fg_pal[15], fg_pal[16] = 0x334155, 0x64748B
    else:
        fg_pal[15], fg_pal[16] = 0x1D4ED8, 0x3B82F6

# Cute 8-bit Fluffy Snow Bear / Yeti Sprite (34x38 full seated body + ears + little ice horns + scarf!)
YETI_BODY_SPRITE = [
    "....0000....000........000....0000....",
    "...0WWWW0..0III0..00..0III0..0WWWW0...",
    "..0WSPPSW0.0Ibb00WWWW00bbI0.0WSPPSW0..",
    "..0WSPPSW00WWWWWWWWWWWWWWWW00WSPPSW0..",
    "...00WW00WWWWWWWWWWWWWWWWWWWW00WW00...",
    "....0WWWWWWWWWWWWWWWWWWWWWWWWWWWW0....",
    "...0WWWWWWWWWWWWWWWWWWWWWWWWWWWWWW0...",
    "..0WWSSSSSSSSWWWWWWWWWWWWSSSSSSSSWW0..",
    "..0WWSSSSSSSSWWWWWWWWWWWWSSSSSSSSWW0..",
    ".0WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW0.",
    ".0WWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWW0.",
    ".0WWWWWPPWWWWWWWW0000WWWWWWWWPPWWWWW0.",
    ".0WWWWWPPWWWWWWW044440WWWWWWWPPWWWWW0.",
    "..0WWWWWWWWWWWWWW0000WWWWWWWWWWWWWW0..",
    "..0SSWWWWWWWWWWWWW44WWWWWWWWWWWWWSS0..",
    "...00SSWWWWWWWWWWW00WWWWWWWWWWWSS00...",
    "....00cCCCCCCCCCCCCCCCCCCCCCCCCc00....",
    "...0cCCCCCCCCCCCCCCCCCCCCCCCCCCCc0....",
    "..0s00ccccccccccccCCCccccccccccc00s0..",
    ".0sSWW00000000000cCCCc0000000000WWSs0.",
    ".0sSWWWWWWWWWWWWWcCCCcWWWWWWWWWWWWSs0.",
    "0sSWWWWWWWWWWWWWWcCCCcWWWWWWWWWWWWWSs0",
    "0sSWWWWWSSSSWWWWWW000WWWWWWSSSSWWWWWS0",
    "0sSWWWWSSSSSSWWWWWWWWWWWWSSSSSSWWWWWS0",
    "0sSWWWWSSSSSSSSWWWWWWWWSSSSSSSSWWWWWS0",
    "0sSSWWWWSSSSSSSSWWWWWWWWSSSSSSSSWWWSs0",
    ".0sSWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWWS0.",
    ".0sSSWWWWWWWWWWWWWWWWWWWWWWWWWWWWSSs0.",
]

def draw_yeti_and_desk_setup(frame, mood, activity, energy, cpu_load, event_name):
    clear_center_stage()
    update_scarf_palette(mood, activity, cpu_load)

    bob = 2 if activity == "sleeping" else (
        (1 if (frame // 3) % 2 == 0 else -1) if (activity == "music" or mood == "vibing")
        else (1 if (frame // 12) % 2 == 1 else 0)
    )

    hx = 56
    hy = 29 + bob

    # 1. Cozy Gaming / Desk Chair Backrest behind the Snow Bear (grounded & full!)
    draw_8bit_box(fg_bmp, hx + 4, 26, 30, 33, 14, 28, 13, 4)
    draw_border(fg_bmp, hx + 7, 29, 24, 28, 12)

    # 2. Full Fluffy Snow Bear / Yeti Seated Body (reaches all the way into the desk at y=58!)
    blit_sprite(fg_bmp, hx, hy, YETI_BODY_SPRITE)

    # 3. Expressive 8-Bit Eyes & Snout on the Snow Bear
    gaze_x = -2 if activity in ("coding", "debugging", "terminal") else (1 if activity == "browsing" else 0)
    is_blinking = (frame % 64) in (0, 1, 2)
    lx = hx + 9 + gaze_x
    rx = hx + 24 + gaze_x
    ey = hy + 7

    if activity == "sleeping" or is_blinking:
        draw_hline(fg_bmp, lx, ey + 2, 5, 4)
        draw_hline(fg_bmp, rx, ey + 2, 5, 4)
    elif mood in ("happy", "vibing") or event_name == "cheer":
        for ex in (lx, rx):
            draw_hline(fg_bmp, ex + 1, ey, 3, 4)
            set_px(fg_bmp, ex, ey + 1, 4)
            set_px(fg_bmp, ex + 4, ey + 1, 4)
            set_px(fg_bmp, ex, ey + 2, 4)
            set_px(fg_bmp, ex + 4, ey + 2, 4)
    elif mood in ("stressed", "panicking") or cpu_load >= 85:
        for ex in (lx, rx):
            draw_8bit_box(fg_bmp, ex, ey - 1, 5, 5, 31, 31, 20, 4)
            fill_rect(fg_bmp, ex + 2, ey + 1, 2, 2, 4)
        # Sweat drop
        dy = hy + 4 + ((frame // 3) % 4)
        blit_sprite(fg_bmp, hx + 33, dy, [".0.", "0I0", "0b0", ".0."])
    elif mood in ("tired", "bored") or energy < 30:
        for ex in (lx, rx):
            fill_rect(fg_bmp, ex, ey + 1, 5, 3, 4)
            draw_hline(fg_bmp, ex, ey, 5, 9)
            set_px(fg_bmp, ex + 1, ey + 2, 31)
    else:
        # Big glossy 8-bit dark eyes with bright snow shine
        for ex in (lx, rx):
            fill_rect(fg_bmp, ex, ey - 1, 5, 5, 4)
            fill_rect(fg_bmp, ex + 1, ey, 2, 2, 31)
            set_px(fg_bmp, ex + 3, ey + 3, 17)
        if activity in ("coding", "debugging", "terminal"):
            # Focused eyebrows
            draw_hline(fg_bmp, lx, ey - 2, 5, 4)
            draw_hline(fg_bmp, rx, ey - 2, 5, 4)

    # 8-Bit Headphones over Snow Bear's ears when listening to music!
    if activity == "music" or mood == "vibing":
        draw_hline(fg_bmp, hx + 4, hy - 1, 30, 28)
        draw_8bit_box(fg_bmp, hx + 1, hy + 5, 5, 8, 28, 29, 27, 4)
        draw_8bit_box(fg_bmp, hx + 32, hy + 5, 5, 8, 28, 29, 27, 4)

    # 4. Side-Angled Desktop Monitor on the Left (x=22..52, y=42..64)
    # Sits cleanly on the desk below the Left Mountain Painting!
    fill_rect(fg_bmp, 24, 63, 26, 2, 5)  # Monitor desk shadow
    # Monitor stand base & neck
    draw_8bit_box(fg_bmp, 28, 60, 16, 4, 19, 20, 18, 4)
    draw_8bit_box(fg_bmp, 33, 57, 6, 4, 18, 19, 4, 4)
    # 3/4 Angled Monitor Casing (side depth on left, glowing screen on right facing Yeti!)
    draw_8bit_box(fg_bmp, 22, 43, 8, 15, 18, 19, 4, 4)    # Left 3D depth side of monitor
    draw_8bit_box(fg_bmp, 28, 42, 24, 16, 19, 20, 18, 4)  # Front angled bezel facing Yeti
    # Inner glowing screen (x=31..49, y=44..55)
    scr_bg = 27 if (mood in ("stressed", "panicking") or cpu_load >= 85) else 24
    fill_rect(fg_bmp, 31, 44, 19, 12, scr_bg)
    # Animated scrolling code lines on the monitor screen!
    code_col = 28 if scr_bg == 27 else (30 if activity == "browsing" else 23)
    scroll = (frame // 3) % 4 if activity in ("coding", "debugging", "terminal") else 0
    for row_i in range(3):
        ly_code = 46 + row_i * 3
        lw = 6 + ((row_i * 5 + scroll * 3) % 11)
        draw_hline(fg_bmp, 33, ly_code, lw, code_col if row_i % 2 == 0 else 26)
    # Power LED on monitor bezel
    set_px(fg_bmp, 49, 56, 23 if activity != "sleeping" else 30)

    # 5. Mechanical Keyboard Lying Flat on Desk in Front of Yeti (x=56..94, y=60..66)
    fill_rect(fg_bmp, 57, 65, 38, 2, 5)  # Keyboard shadow
    draw_8bit_box(fg_bmp, 56, 60, 38, 6, 18, 20, 19, 4)
    # Individual 8-bit keycaps row
    for kx in range(59, 91, 3):
        set_px(fg_bmp, kx, 62, 31)
        set_px(fg_bmp, kx + 1, 62, 20)
        set_px(fg_bmp, kx, 63, 20)

    # 6. Fluffy Snow Bear Paws Tapping Directly on the Keyboard!
    PAW_SPRITE = [
        ".000000.",
        "0WWWWWW0",
        "0WSSSSW0",
        "0s0ss0s0",
        ".000000.",
    ]
    if event_name == "cheer":
        w = (frame // 3) % 2
        blit_sprite(fg_bmp, hx - 2, hy + 12 + w, PAW_SPRITE)
        blit_sprite(fg_bmp, hx + 32, hy + 12 - w, PAW_SPRITE)
    elif activity in ("coding", "debugging", "terminal"):
        # Fast alternating Bongo-style paw slams right onto the keyboard keys!
        l_down = (frame // 2) % 2 == 0
        ly_paw = 59 if l_down else 56
        ry_paw = 56 if l_down else 59
        blit_sprite(fg_bmp, 60, ly_paw, PAW_SPRITE)
        blit_sprite(fg_bmp, 79, ry_paw, PAW_SPRITE)
        # Depress keycap & show 8-bit click spark!
        if l_down:
            fill_rect(fg_bmp, 62, 62, 4, 2, 23)
            set_px(fg_bmp, 59, 58, 30)
        else:
            fill_rect(fg_bmp, 81, 62, 4, 2, 23)
            set_px(fg_bmp, 87, 58, 30)
    elif activity == "sleeping":
        # Paws resting peacefully together on desk next to keyboard
        blit_sprite(fg_bmp, 65, 58, PAW_SPRITE)
        blit_sprite(fg_bmp, 75, 58, PAW_SPRITE)
    else:
        # Paws resting on edge of keyboard
        blit_sprite(fg_bmp, 60, 58, PAW_SPRITE)
        blit_sprite(fg_bmp, 79, 58, PAW_SPRITE)

    # 7. Steaming Red Coffee Mug on Right Side of Desk (x=105..118, y=53..63)
    mug_x = 106 if event_name != "sip_coffee" else 84
    mug_y = 53 if event_name != "sip_coffee" else 44
    if event_name != "sip_coffee":
        fill_rect(fg_bmp, mug_x + 1, mug_y + 10, 11, 2, 5)
    MUG_SPRITE = [
        ".00000000...",
        "0WWWWWWWW0..",
        "0rRmmmmrh000",
        "0rRmmmmrh0G0",
        "0rRmmmmrh0G0",
        "0rRmmmmrh000",
        "0rRmmmmrh0..",
        "0hhhhhhhh0..",
        ".00000000...",
    ]
    blit_sprite(fg_bmp, mug_x, mug_y, MUG_SPRITE)
    s_off = (frame // 4) % 4
    set_px(fg_bmp, mug_x + 3, mug_y - 2 - s_off, 31)
    set_px(fg_bmp, mug_x + 6, mug_y - 3 - ((s_off + 2) % 4), 20)

    # 8. Small Energy Crystal Bar on Desk Corner (x=97..101, y=52..62)
    draw_8bit_box(fg_bmp, 97, 51, 5, 12, 24, 20, 18, 4)
    eh = int(10 * max(0, min(100, energy)) / 100)
    ecol = 23 if energy > 50 else (30 if energy > 25 else 28)
    if eh > 0:
        fill_rect(fg_bmp, 98, 62 - eh, 3, eh, ecol)

# ─── 8. NEOPIXEL BREATHING CONTROLLER ───────────────────────────────────────
MOOD_RGB = {
    "focused":   (0, 140, 255),
    "happy":     (0, 255, 100),
    "curious":   (80, 200, 255),
    "vibing":    (180, 40, 255),
    "bored":     (255, 160, 0),
    "tired":     (60, 90, 160),
    "sleepy":    (30, 50, 110),
    "stressed":  (255, 50, 20),
    "panicking": (255, 0, 40),
}

def update_neopixel(frame, mood, cpu_load):
    if not led:
        return
    base = MOOD_RGB.get(mood, (0, 140, 255))
    if cpu_load >= 85:
        base = (255, 20, 0)
    speed = 0.28 if (mood in ("stressed", "panicking") or cpu_load >= 85) else 0.10
    pulse = 0.35 + 0.65 * (0.5 + 0.5 * math.sin(frame * speed))
    led[0] = (int(base[0] * pulse), int(base[1] * pulse), int(base[2] * pulse))
    led.show()

# ─── 9. STATE & SERIAL PROTOCOL ─────────────────────────────────────────────
state = {
    "mood": "focused",
    "act": "coding",
    "nrg": 95,
    "cpu": 15,
    "evt": "none",
    "poster": "code_matrix",
    "hour": 14,  # Default daytime so window is bright & sunny right away!
}

evt_timer = 0
serial_buf = ""

def apply_packet(line):
    global evt_timer
    for part in line.split("|"):
        if ":" not in part:
            continue
        k, v = part.split(":", 1)
        k = k.strip().upper()
        v = v.strip()
        if k == "MOOD" and v:
            state["mood"] = v.lower()
        elif k == "ACT" and v:
            state["act"] = v.lower()
        elif k == "NRG":
            try:
                state["nrg"] = max(0, min(100, int(v)))
            except ValueError:
                pass
        elif k == "CPU":
            try:
                state["cpu"] = max(0, min(100, int(v)))
            except ValueError:
                pass
        elif k == "EVT" and v:
            state["evt"] = v.lower()
            if state["evt"] != "none":
                evt_timer = 60
        elif k == "POSTER" and v:
            state["poster"] = v.lower()
        elif k == "HOUR":
            try:
                state["hour"] = int(v) % 24
            except ValueError:
                pass

try:
    import usb_cdc
    cdc_data = usb_cdc.data
except Exception:
    cdc_data = None

# ─── 10. MAIN 8-BIT RENDER LOOP ─────────────────────────────────────────────
frame = 0
print("8-Bit Snow Bear Yeti Companion Ready!")

while True:
    # 1. Read from CircuitPython Console serial port (e.g. /dev/cu.usbmodem11201)
    while supervisor.runtime.serial_bytes_available:
        n = supervisor.runtime.serial_bytes_available
        serial_buf += sys.stdin.read(n)

    # 2. Also read from secondary USB CDC Data port if used (e.g. /dev/cu.usbmodem11203)
    if cdc_data and cdc_data.in_waiting:
        raw = cdc_data.read(cdc_data.in_waiting)
        if raw:
            try:
                serial_buf += raw.decode("utf-8", "ignore")
            except Exception:
                pass

    if "\n" in serial_buf:
        lines = serial_buf.split("\n")
        for ln in lines[:-1]:
            if ln.strip():
                apply_packet(ln.strip())
        serial_buf = lines[-1]

    if evt_timer > 0:
        evt_timer -= 1
        if evt_timer == 0:
            state["evt"] = "none"

    draw_yeti_and_desk_setup(frame, state["mood"], state["act"], state["nrg"], state["cpu"], state["evt"])
    draw_big_window(frame, state["hour"], state["cpu"])
    draw_8bit_painting(frame, state["poster"])
    display.refresh()

    update_neopixel(frame, state["mood"], state["cpu"])

    frame = (frame + 1) % 100000
    time.sleep(0.05)
