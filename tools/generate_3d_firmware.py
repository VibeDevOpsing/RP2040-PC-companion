#!/usr/bin/env python3
"""
3D Raymarched Volumetric Grok Bot Asset & Firmware Generator
for Waveshare RP2040-Zero + ST7735R 160x80 IPS Display.

Generates:
  - 64-color studio porcelain-pearl palette with sub-pixel anti-aliasing
  - 4 raymarched 3D Grok Bot body poses (66x75 px: STAND, STEP_L, STEP_R, REST)
  - 7 anti-aliased 3D eye expression tiles (32x20 px)
  - 5 volumetric 3D interactive prop tiles (32x24 px: Coffee Mug, Laptop, Lightbulb)
  - High-contrast 6x8 Bold Comic Font (FONT_6X8_BOLD) with 2px vertical stems
  - Hardware-composited CircuitPython `code.py` with 40 FPS delta-time pacing,
    palette/LED dirty-flag caching, and live multi-thought LLM streaming (`~` delimited).
"""

import math
import os
import struct
import zlib

ALPHA = ".0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#"


def idx_to_ch(idx: int) -> str:
    return ALPHA[idx]


def save_png(path: str, w: int, h: int, rgb_rows: list) -> None:
    """Writes an uncompressed/zlib-compressed 24-bit RGB PNG preview image."""
    raw = b"".join(b"\x00" + bytes(r) for r in rgb_rows)

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack("!I", len(data))
            + tag
            + data
            + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    ihdr = struct.pack("!IIBBBBB", w, h, 8, 2, 0, 0, 0)
    with open(path, "wb") as f:
        f.write(
            b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b"")
        )


# ─── 1. 64-COLOR 3D STUDIO PALETTE ──────────────────────────────────────────
PALETTE = [(0, 0, 0)] * 64
PALETTE[0] = (10, 13, 22)    # 0: Studio Dark Backdrop (Transparent on FG)
PALETTE[1] = (13, 17, 29)    # 1: Studio Mid Backdrop
PALETTE[2] = (18, 23, 38)    # 2: Studio Soft Horizon
PALETTE[3] = (22, 29, 46)    # 3: Studio Matte Floor

# Indices 4..23: 20 Continuous 3D Studio Porcelain-Pearl Shades
for i in range(20):
    t = i / 19.0
    c = pow(t, 0.80)
    r = int(98 + 157 * c)
    g = int(108 + 147 * c)
    b = int(128 + 127 * c)
    PALETTE[4 + i] = (r, g, b)

# Indices 24..27: 4 Sub-pixel Anti-Aliasing Silhouette Edge Shades
for i in range(4):
    cov = (i + 1) / 5.0
    sr, sg, sb = PALETTE[5]
    br, bg_c, bb = PALETTE[1]
    PALETTE[24 + i] = (
        int(br * (1 - cov) + sr * cov),
        int(bg_c * (1 - cov) + sg * cov),
        int(bb * (1 - cov) + sb * cov),
    )

# Indices 28..35: 8 Anti-Aliased 3D Eye & Recessed Socket Shades + Gloss + Blush
PALETTE[28] = (164, 174, 190)  # Outer socket rim AO
PALETTE[29] = (118, 126, 142)  # Inner socket rim AA
PALETTE[30] = (66, 71, 85)     # Eye outer AA edge
PALETTE[31] = (28, 31, 40)     # Eye inner AA edge
PALETTE[32] = (4, 6, 10)       # Pitch-Black Obsidian Core (for Eyes & Ultra-Crisp Callout Text!)
PALETTE[33] = (29, 34, 47)     # Subtle 3D Eye Lower Gloss
PALETTE[34] = (52, 62, 84)     # Subtle 3D Eye Top Gloss
PALETTE[35] = (244, 136, 166)  # Soft Rosy Blush

# Indices 36..38: 3 Concentric Soft Floor Contact Shadow Shades
PALETTE[36] = (7, 9, 15)       # Deepest contact shadow center
PALETTE[37] = (12, 16, 26)     # Mid contact shadow
PALETTE[38] = (17, 23, 37)     # Outer soft penumbra on floor

# Indices 39..63: 3D Props & High-Contrast Callout Colors
PALETTE[39] = (52, 27, 14)     # Espresso dark
PALETTE[40] = (110, 60, 28)    # Espresso mid
PALETTE[41] = (188, 128, 76)   # Crema
PALETTE[42] = (175, 16, 30)    # High-contrast Crimson Alert Text / Mug shadow
PALETTE[43] = (220, 38, 54)    # 3D Red mug mid / Alert border
PALETTE[44] = (250, 82, 96)    # 3D Red mug specular highlight
PALETTE[45] = (28, 38, 54)     # 3D Laptop dark aluminum
PALETTE[46] = (58, 72, 94)     # 3D Laptop mid aluminum
PALETTE[47] = (100, 116, 139)  # 3D Laptop light aluminum
PALETTE[48] = (148, 163, 184)  # 3D Laptop edge specular
PALETTE[49] = (6, 78, 59)      # Screen dark green
PALETTE[50] = (16, 185, 129)   # Screen mid emerald
PALETTE[51] = (78, 255, 155)   # Screen bright neon code
PALETTE[52] = (180, 83, 9)     # Bulb base gold shadow
PALETTE[53] = (245, 158, 11)   # Bulb warm gold
PALETTE[54] = (253, 224, 71)   # Bulb bright yellow
PALETTE[55] = (254, 249, 195)  # Bulb white-gold core
PALETTE[56] = (56, 189, 248)   # Hologram cyan accent
PALETTE[57] = (168, 85, 247)   # Violet accent
PALETTE[58] = (212, 222, 236)  # Callout 1px bottom rim shade
PALETTE[59] = (241, 245, 249)  # Callout corner AA
PALETTE[60] = (255, 255, 255)  # Pure Bright White Callout Fill
PALETTE[61] = (38, 52, 74)     # Crisp Dark Slate Callout Border
PALETTE[62] = (150, 168, 194)  # Steam soft mid
PALETTE[63] = (218, 228, 242)  # Steam bright wisp


def smin(a: float, b: float, k: float) -> float:
    h = max(k - abs(a - b), 0.0) / k
    return min(a, b) - h * h * k * 0.25


def sd_capsule(
    px: float, py: float, pz: float,
    ax: float, ay: float, az: float,
    bx: float, by: float, bz: float,
    r: float,
) -> float:
    pax, pay, paz = px - ax, py - ay, pz - az
    bax, bay, baz = bx - ax, by - ay, bz - az
    h = max(0.0, min(1.0, (pax * bax + pay * bay + paz * baz) / (bax * bax + bay * bay + baz * baz + 1e-6)))
    dx, dy, dz = pax - bax * h, pay - bay * h, paz - baz * h
    return math.sqrt(dx * dx + dy * dy + dz * dz) - r


def grok_pose_sdf(x: float, y: float, z: float, pose: str = "STAND"):
    if pose == "REST":
        r_torso = 0.56 + 0.055 * max(0.0, min(1.0, (y + 0.20)))
        d_torso = sd_capsule(x, y, z, 0.0, -0.16, 0.0, 0.0, 0.34, 0.0, r_torso)
        d_leg_l = sd_capsule(x, y, z, -0.31, 0.44, -0.04, -0.34, 0.58, -0.28, 0.205)
        d_leg_r = sd_capsule(x, y, z,  0.31, 0.44, -0.04,  0.34, 0.58, -0.28, 0.205)
        d_body = smin(d_torso, min(d_leg_l, d_leg_r), 0.11)
        d_notch = sd_capsule(x, y, z, 0.0, 0.50, -0.20, 0.0, 0.88, -0.20, 0.14)
        d_body = -smin(-d_body, d_notch, 0.08)
        d_arm_l = sd_capsule(x, y, z, -0.56, 0.16, 0.02, -0.65, 0.45, -0.06, 0.16)
        d_arm_r = sd_capsule(x, y, z,  0.56, 0.16, 0.02,  0.65, 0.45, -0.06, 0.16)
        d_arms = min(d_arm_l, d_arm_r)
        return smin(d_body, d_arms, 0.055), abs(d_arms - d_body), d_notch

    leg_l = 0.11 if pose == "STEP_L" else (-0.03 if pose == "STEP_R" else 0.0)
    leg_r = 0.11 if pose == "STEP_R" else (-0.03 if pose == "STEP_L" else 0.0)

    r_torso = 0.55 + 0.045 * max(0.0, min(1.0, (y + 0.25)))
    d_torso = sd_capsule(x, y, z, 0.0, -0.35, 0.0, 0.0, 0.24, 0.0, r_torso)
    d_leg_l = sd_capsule(x, y, z, -0.26, 0.28, 0.0, -0.25, 0.68 - leg_l, 0.0, 0.235)
    d_leg_r = sd_capsule(x, y, z,  0.26, 0.28, 0.0,  0.25, 0.68 - leg_r, 0.0, 0.235)
    d_body = smin(d_torso, min(d_leg_l, d_leg_r), 0.14)
    d_notch = sd_capsule(x, y, z, 0.0, 0.58, 0.0, 0.0, 0.95, 0.0, 0.12)
    d_body = -smin(-d_body, d_notch, 0.09)

    al_y = -0.05 if pose == "STEP_R" else (0.05 if pose == "STEP_L" else 0.0)
    ar_y = -0.05 if pose == "STEP_L" else (0.06 if pose == "STEP_R" else 0.0)
    d_arm_l = sd_capsule(x, y, z, -0.56, 0.04, 0.02, -0.66, 0.35 + al_y, 0.06, 0.165)
    d_arm_r = sd_capsule(x, y, z,  0.56, 0.04, 0.02,  0.66, 0.35 + ar_y, 0.06, 0.165)
    d_arms = min(d_arm_l, d_arm_r)
    d = smin(d_body, d_arms, 0.055)
    return d, abs(d_arms - d_body), d_notch


def raymarch_grok_pose(W: int, H: int, pose: str) -> list:
    rows_str = []
    scale = 38.0
    for py in range(H):
        ny = (py - 37.0) / scale
        chars = []
        for px in range(W):
            nx = (px - W * 0.5) / scale
            z = -1.1
            hit = False
            min_d = 99.0
            for _ in range(30):
                d, _, _ = grok_pose_sdf(nx, ny, z, pose)
                if d < min_d:
                    min_d = d
                if d < 0.003:
                    hit = True
                    break
                z += max(0.015, d * 0.85)
                if z > 0.75:
                    break
            if not hit:
                cov = max(0.0, min(1.0, (0.024 - min_d) / 0.022))
                if cov < 0.15:
                    chars.append(idx_to_ch(0))
                else:
                    aa_i = min(3, int(cov * 4))
                    chars.append(idx_to_ch(24 + aa_i))
            else:
                eps = 0.006
                dx = grok_pose_sdf(nx + eps, ny, z, pose)[0] - grok_pose_sdf(nx - eps, ny, z, pose)[0]
                dy = grok_pose_sdf(nx, ny + eps, z, pose)[0] - grok_pose_sdf(nx, ny - eps, z, pose)[0]
                dz = grok_pose_sdf(nx, ny, z + eps, pose)[0] - grok_pose_sdf(nx, ny, z - eps, pose)[0]
                inv = 1.0 / max(1e-6, math.sqrt(dx * dx + dy * dy + dz * dz))
                vnx, vny, vnz = dx * inv, dy * inv, dz * inv
                _, arm_seam, d_notch = grok_pose_sdf(nx, ny, z, pose)
                ao_arm = min(1.0, max(0.40, arm_seam * 5.2))
                ao_notch = min(1.0, max(0.52, d_notch * 5.0))
                ao = min(ao_arm, ao_notch)
                key = max(0.0, vnx * (-0.25) + vny * (-0.55) + vnz * (-0.79))
                fill = max(0.0, vnx * (0.30) + vny * (0.10) + vnz * (-0.94)) * 0.28
                fresnel = max(0.0, -vnz)
                spec = pow(max(0.0, vnx * (-0.15) + vny * (-0.42) + vnz * (-0.89)), 14.0) * 0.30
                lit = max(
                    0.0,
                    min(1.0, (0.18 + 0.56 * key + fill + spec) * (0.46 + 0.54 * pow(fresnel, 0.62)) * ao),
                )
                sh_i = max(0, min(19, int(lit * 19.99)))
                chars.append(idx_to_ch(4 + sh_i))
        rows_str.append("".join(chars))
    return rows_str


def render_3d_eyes_tile(mode: str = "NORMAL") -> list:
    W, H = 32, 20
    rows_str = []
    for py in range(H):
        ny = (py - H * 0.5) / 17.8
        chars = []
        for px in range(W):
            nx = (px - W * 0.5) / 17.8
            if mode in ("NORMAL", "HALF", "THINK"):
                top_l = -0.05 if mode == "HALF" else -0.32
                bot_l = 0.14 if mode == "HALF" else 0.32
                top_r = -0.08 if mode == "THINK" else top_l
                bot_r = 0.20 if mode == "THINK" else bot_l
                el = sd_capsule(nx, ny, 0, -0.44, top_l, 0, -0.44, bot_l, 0, 0.205)
                er = sd_capsule(nx, ny, 0,  0.44, top_r, 0,  0.44, bot_r, 0, 0.205)
                d = min(el, er)
                if d > 0.08:
                    chars.append(".")
                elif d > 0.028:
                    chars.append(idx_to_ch(28))
                elif d > 0.0:
                    chars.append(idx_to_ch(29))
                elif d > -0.04:
                    chars.append(idx_to_ch(30))
                elif d > -0.08:
                    chars.append(idx_to_ch(31))
                else:
                    if ny < top_l + 0.15:
                        chars.append(idx_to_ch(34))
                    elif ny < top_l + 0.25:
                        chars.append(idx_to_ch(33))
                    else:
                        chars.append(idx_to_ch(32))
            elif mode == "BLINK":
                el = sd_capsule(nx, ny, 0, -0.60, 0.04, 0, -0.28, 0.04, 0, 0.09)
                er = sd_capsule(nx, ny, 0,  0.28, 0.04, 0,  0.60, 0.04, 0, 0.09)
                d = min(el, er)
                if d > 0.055:
                    chars.append(".")
                elif d > 0.0:
                    chars.append(idx_to_ch(29))
                elif d > -0.038:
                    chars.append(idx_to_ch(30))
                else:
                    chars.append(idx_to_ch(32))
            elif mode == "HAPPY":
                dl = abs(math.sqrt((nx + 0.44) ** 2 + (ny - 0.15) ** 2) - 0.20) if ny <= 0.14 else 9.0
                dr = abs(math.sqrt((nx - 0.44) ** 2 + (ny - 0.15) ** 2) - 0.20) if ny <= 0.14 else 9.0
                d = min(dl, dr) - 0.075
                bl = math.sqrt(((nx + 0.68) * 0.85) ** 2 + (ny - 0.30) ** 2)
                br_d = math.sqrt(((nx - 0.68) * 0.85) ** 2 + (ny - 0.30) ** 2)
                if min(bl, br_d) < 0.16:
                    chars.append(idx_to_ch(35))
                elif d > 0.055:
                    chars.append(".")
                elif d > 0.0:
                    chars.append(idx_to_ch(29))
                elif d > -0.038:
                    chars.append(idx_to_ch(30))
                else:
                    chars.append(idx_to_ch(32))
            elif mode == "SLEEP":
                dl = abs(math.sqrt((nx + 0.44) ** 2 + (ny + 0.02) ** 2) - 0.19) if ny >= -0.01 else 9.0
                dr = abs(math.sqrt((nx - 0.44) ** 2 + (ny + 0.02) ** 2) - 0.19) if ny >= -0.01 else 9.0
                d = min(dl, dr) - 0.075
                if d > 0.055:
                    chars.append(".")
                elif d > 0.0:
                    chars.append(idx_to_ch(29))
                elif d > -0.038:
                    chars.append(idx_to_ch(30))
                else:
                    chars.append(idx_to_ch(32))
            else:  # PARTY / VISOR
                d = sd_capsule(nx, ny, 0, -0.68, -0.04, 0, 0.68, -0.04, 0, 0.24)
                if d > 0.05:
                    chars.append(".")
                elif d > -0.03:
                    chars.append(idx_to_ch(32))
                elif abs(ny + 0.10) < 0.07 and abs(nx) < 0.56:
                    chars.append(idx_to_ch(54 if nx < 0 else 56))
                else:
                    chars.append(idx_to_ch(31))
        rows_str.append("".join(chars))
    return rows_str


def render_3d_coffee_prop(steam_phase: int = 0) -> list:
    W, H = 32, 24
    rows_str = []
    for py in range(H):
        chars = []
        for px in range(W):
            hx = (px - 5.8) / 5.0
            hy = (py - 16.0) / 4.4
            hr2 = hx * hx + hy * hy
            if hr2 <= 1.0:
                hz = math.sqrt(1.0 - hr2)
                lit = max(0.15, min(1.0, 0.25 + 0.55 * (hx * (-0.3) + hy * (-0.5) + hz * 0.8) + 0.25 * hz))
                chars.append(idx_to_ch(4 + int(lit * 19)))
                continue

            mx = (px - 13.0) / 7.0
            hd_d = abs(math.sqrt((px - 19.8) ** 2 + (py - 14.2) ** 2) - 3.6)
            if px >= 18 and 9 <= py <= 19 and hd_d <= 1.45:
                chars.append(idx_to_ch(19 if hd_d < 0.75 else 12))
                continue

            if abs(mx) <= 1.0 and 7 <= py <= 21:
                top_d = ((px - 13.0) / 6.0) ** 2 + ((py - 8.3) / 1.7) ** 2
                if py <= 9 and top_d <= 1.0:
                    chars.append(idx_to_ch(41 if top_d < 0.35 else (40 if top_d < 0.75 else 39)))
                    continue
                mz = math.sqrt(max(0.0, 1.0 - mx * mx))
                cyl_lit = max(0.1, min(1.0, 0.22 + 0.55 * (mx * (-0.45) + mz * 0.85) + 0.25 * pow(mz, 4)))
                if py == 21 and abs(mx) > 0.72:
                    chars.append(".")
                    continue
                if 13 <= py <= 16:
                    chars.append(idx_to_ch(44 if cyl_lit > 0.78 else (43 if cyl_lit > 0.45 else 42)))
                else:
                    chars.append(idx_to_ch(4 + int(cyl_lit * 19)))
                continue

            if 1 <= py <= 6:
                wave = math.sin(py * 0.9 + steam_phase * 1.6) * 1.4
                sd1 = abs(px - (11.0 + wave))
                sd2 = abs(px - (15.0 - wave))
                if min(sd1, sd2) < 0.95:
                    chars.append(idx_to_ch(63 if py % 2 == 0 else 62))
                    continue

            chars.append(".")
        rows_str.append("".join(chars))
    return rows_str


def render_3d_laptop_prop(type_phase: int = 0) -> list:
    W, H = 32, 24
    rows_str = []
    for py in range(H):
        chars = []
        for px in range(W):
            h1_y = 15.5 + (1.3 if type_phase == 0 else -1.1)
            h2_y = 17.5 + (-1.1 if type_phase == 0 else 1.3)
            for hcx, hcy in ((4.8, h1_y), (10.5, h2_y)):
                hx = (px - hcx) / 4.2
                hy = (py - hcy) / 3.8
                if hx * hx + hy * hy <= 1.0:
                    hz = math.sqrt(1.0 - hx * hx - hy * hy)
                    lit = max(0.2, min(1.0, 0.3 + 0.6 * (hx * (-0.3) + hy * (-0.5) + hz * 0.8)))
                    chars.append(idx_to_ch(4 + int(lit * 19)))
                    break
            else:
                slant = (16 - py) * 0.36
                lx0 = 9.0 + slant
                lx1 = 28.5 + slant
                if 4 <= py <= 16 and lx0 <= px <= lx1:
                    if py in (4, 16) or px - lx0 < 1.3 or lx1 - px < 1.3:
                        chars.append(idx_to_ch(48 if py == 4 else 47))
                    else:
                        code_row = (py + type_phase) % 3 == 0
                        if code_row and (lx0 + 3 <= px <= lx1 - 4) and ((px + py) % 4 != 0):
                            chars.append(idx_to_ch(51 if (px % 2 == 0) else 50))
                        else:
                            chars.append(idx_to_ch(49))
                elif 17 <= py <= 19 and 3 <= px <= 28:
                    chars.append(idx_to_ch(48 if py == 17 else (46 if py == 18 else 45)))
                elif py < 4 and ((px + py + type_phase) % 7 == 0) and 10 <= px <= 27:
                    chars.append(idx_to_ch(51))
                else:
                    chars.append(".")
        rows_str.append("".join(chars))
    return rows_str


def render_3d_bulb_prop(pulse: int = 0) -> list:
    W, H = 32, 24
    rows_str = []
    for py in range(H):
        chars = []
        for px in range(W):
            hx = (px - 5.0) / 4.4
            hy = (py - 18.5) / 4.0
            if hx * hx + hy * hy <= 1.0:
                hz = math.sqrt(1.0 - hx * hx - hy * hy)
                lit = max(0.2, min(1.0, 0.3 + 0.6 * (hx * (-0.3) + hy * (-0.5) + hz * 0.8)))
                chars.append(idx_to_ch(4 + int(lit * 19)))
                continue
            bx = (px - 23.5) / 5.8
            by = (py - 7.5) / 5.8
            br2 = bx * bx + by * by
            if br2 <= 1.0:
                if br2 < 0.25 or (bx < -0.15 and by < -0.15 and br2 < 0.55):
                    chars.append(idx_to_ch(55))
                elif br2 < 0.72:
                    chars.append(idx_to_ch(54))
                else:
                    chars.append(idx_to_ch(53))
            elif 12 <= py <= 14 and abs(px - 23.5) <= 3.2:
                chars.append(idx_to_ch(53 if py == 12 else 47))
            elif 15 <= py <= 16 and abs(px - 23.5) <= 2.2:
                chars.append(idx_to_ch(46))
            elif pulse == 0 and 1.15 <= br2 <= 1.65 and ((px + py) % 2 == 0):
                chars.append(idx_to_ch(54))
            else:
                chars.append(".")
        rows_str.append("".join(chars))
    return rows_str


# ─── ULTRA-CRISP 6x8 BOLD COMIC FONT (2-PIXEL THICK STEMS FOR IPS LCD!) ─────
FONT_6X8_BOLD = {
    "A": ("011110", "110011", "110011", "110011", "111111", "110011", "110011", "110011"),
    "B": ("111110", "110011", "110011", "111110", "110011", "110011", "110011", "111110"),
    "C": ("011111", "110000", "110000", "110000", "110000", "110000", "110000", "011111"),
    "D": ("111110", "110011", "110011", "110011", "110011", "110011", "110011", "111110"),
    "E": ("111111", "110000", "110000", "111110", "110000", "110000", "110000", "111111"),
    "F": ("111111", "110000", "110000", "111110", "110000", "110000", "110000", "110000"),
    "G": ("011111", "110000", "110000", "110111", "110011", "110011", "110011", "011111"),
    "H": ("110011", "110011", "110011", "111111", "110011", "110011", "110011", "110011"),
    "I": ("011110", "001100", "001100", "001100", "001100", "001100", "001100", "011110"),
    "J": ("001111", "000110", "000110", "000110", "000110", "110110", "110110", "011100"),
    "K": ("110011", "110110", "111100", "111000", "111100", "110110", "110011", "110011"),
    "L": ("110000", "110000", "110000", "110000", "110000", "110000", "110000", "111111"),
    "M": ("100001", "110011", "111111", "101101", "100001", "100001", "100001", "100001"),
    "N": ("110001", "111001", "111101", "110111", "110011", "110001", "110001", "110001"),
    "O": ("011110", "110011", "110011", "110011", "110011", "110011", "110011", "011110"),
    "P": ("111110", "110011", "110011", "111110", "110000", "110000", "110000", "110000"),
    "Q": ("011110", "110011", "110011", "110011", "110011", "110111", "110011", "011111"),
    "R": ("111110", "110011", "110011", "111110", "111100", "110110", "110011", "110011"),
    "S": ("011111", "110000", "110000", "011110", "000011", "000011", "110011", "011110"),
    "T": ("111111", "001100", "001100", "001100", "001100", "001100", "001100", "001100"),
    "U": ("110011", "110011", "110011", "110011", "110011", "110011", "110011", "011110"),
    "V": ("110011", "110011", "110011", "110011", "110011", "011110", "001100", "001100"),
    "W": ("100001", "100001", "100001", "100001", "101101", "111111", "110011", "100001"),
    "X": ("110011", "110011", "011110", "001100", "001100", "011110", "110011", "110011"),
    "Y": ("110011", "110011", "011110", "001100", "001100", "001100", "001100", "001100"),
    "Z": ("111111", "000011", "000110", "001100", "011000", "110000", "110000", "111111"),
    "0": ("011110", "110011", "110111", "110111", "111011", "111011", "110011", "011110"),
    "1": ("001100", "011100", "111100", "001100", "001100", "001100", "001100", "011110"),
    "2": ("011110", "110011", "000011", "000110", "001100", "011000", "110000", "111111"),
    "3": ("111110", "000011", "000011", "011110", "000011", "000011", "110011", "011110"),
    "4": ("110011", "110011", "110011", "111111", "000011", "000011", "000011", "000011"),
    "5": ("111111", "110000", "110000", "111110", "000011", "000011", "110011", "011110"),
    "6": ("011110", "110000", "110000", "111110", "110011", "110011", "110011", "011110"),
    "7": ("111111", "110011", "000011", "000110", "001100", "001100", "001100", "001100"),
    "8": ("011110", "110011", "110011", "011110", "110011", "110011", "110011", "011110"),
    "9": ("011110", "110011", "110011", "011111", "000011", "000011", "110011", "011110"),
    "!": ("001100", "001100", "001100", "001100", "001100", "000000", "001100", "001100"),
    "?": ("011110", "110011", "000011", "000110", "001100", "000000", "001100", "001100"),
    ".": ("000000", "000000", "000000", "000000", "000000", "000000", "011100", "011100"),
    ",": ("000000", "000000", "000000", "000000", "000000", "001100", "001100", "011000"),
    "-": ("000000", "000000", "000000", "111111", "000000", "000000", "000000", "000000"),
    "+": ("000000", "001100", "001100", "111111", "001100", "001100", "000000", "000000"),
    "/": ("000011", "000110", "001100", "001100", "011000", "011000", "110000", "000000"),
    ":": ("000000", "001100", "001100", "000000", "000000", "001100", "001100", "000000"),
    "~": ("000000", "000000", "011101", "110111", "100010", "000000", "000000", "000000"),
    "%": ("110011", "110110", "001100", "001100", "011000", "011011", "110011", "000000"),
    "#": ("010100", "111110", "010100", "010100", "111110", "010100", "000000", "000000"),
    ">": ("110000", "011000", "001100", "000110", "001100", "011000", "110000", "000000"),
    "<": ("000011", "000110", "001100", "011000", "001100", "000110", "000011", "000000"),
    "_": ("000000", "000000", "000000", "000000", "000000", "000000", "000000", "111111"),
    " ": ("000000", "000000", "000000", "000000", "000000", "000000", "000000", "000000"),
}


def generate_firmware_source() -> str:
    bot_tiles = [
        raymarch_grok_pose(66, 75, "STAND"),
        raymarch_grok_pose(66, 75, "STEP_L"),
        raymarch_grok_pose(66, 75, "STEP_R"),
        raymarch_grok_pose(66, 75, "REST"),
    ]
    eye_tiles = [
        render_3d_eyes_tile("NORMAL"),
        render_3d_eyes_tile("HALF"),
        render_3d_eyes_tile("BLINK"),
        render_3d_eyes_tile("HAPPY"),
        render_3d_eyes_tile("THINK"),
        render_3d_eyes_tile("SLEEP"),
        render_3d_eyes_tile("PARTY"),
    ]
    prop_tiles = [
        render_3d_coffee_prop(0),
        render_3d_coffee_prop(1),
        render_3d_laptop_prop(0),
        render_3d_laptop_prop(1),
        render_3d_bulb_prop(0),
    ]

    pal_hex_list = [f"0x{r:02X}{g:02X}{b:02X}" for (r, g, b) in PALETTE]

    def format_tuple_rows(name: str, rows: list) -> str:
        lines = [f"{name} = ("]
        for r in rows:
            lines.append(f'    "{r}",')
        lines.append(")")
        return "\n".join(lines)

    font_lines = ["FONT_6X8_BOLD = {"]
    for k, v in FONT_6X8_BOLD.items():
        font_lines.append(f'    "{k}": {repr(v)},')
    font_lines.append("}")
    font_block = "\n".join(font_lines)

    # Precompute 64-entry sine lookup table for O(1) breathing/bobbing & LED pulse
    sin_table_vals = ", ".join(f"{math.sin(i * 2.0 * math.pi / 64.0):.3f}" for i in range(64))

    return f'''import board
import displayio
import busio
import digitalio
import gc
import supervisor
import sys
import time
from fourwire import FourWire
from adafruit_st7735r import ST7735R

try:
    from neopixel_write import neopixel_write
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

led_pin = None
led_buf = bytearray(3)
_last_led_rgb = (-1, -1, -1)
if HAS_NEOPIXEL:
    try:
        pin_obj = getattr(board, "NEOPIXEL", getattr(board, "GP16", None))
        if pin_obj is not None:
            led_pin = digitalio.DigitalInOut(pin_obj)
            led_pin.direction = digitalio.Direction.OUTPUT
            led_buf[0] = 30
            led_buf[1] = 0
            led_buf[2] = 55
            neopixel_write(led_pin, led_buf)
    except Exception:
        led_pin = None

# ─── 2. 64-COLOR 3D RAYMARCHED STUDIO PALETTE & HARDWARE TILEGRIDS ──────────
NUM_COLORS = 64
ALPHA = "{ALPHA}"
CHAR_TO_IDX = {{ch: i for i, ch in enumerate(ALPHA)}}
SIN_64 = ({sin_table_vals})

BASE_PALETTE = (
    {", ".join(pal_hex_list[:16])},
    {", ".join(pal_hex_list[16:32])},
    {", ".join(pal_hex_list[32:48])},
    {", ".join(pal_hex_list[48:64])},
)

bg_pal = displayio.Palette(NUM_COLORS)
fg_pal = displayio.Palette(NUM_COLORS)
for i, col in enumerate(BASE_PALETTE):
    bg_pal[i] = col
    fg_pal[i] = col
fg_pal.make_transparent(0)

# Subtle 3D Studio Lighting Tint Themes (tints the 20 porcelain shades 4..23!)
STUDIO_TINTS = {{
    "CYBER":   (0, 2, 6),      # Cool Studio White-Blue
    "VIOLET":  (4, -2, 10),    # Kiro Lavender-Pearl
    "TEAL":    (-4, 4, 6),     # Aqua Studio Pearl
    "EMERALD": (-4, 6, 2),     # Mint Studio Pearl
    "INDIGO":  (-6, -4, 12),   # Starlight Sleep Pearl
    "CRIMSON": (16, -8, -6),   # Warm Alert Rose-Pearl
    "GOLD":    (12, 6, -6),    # Warm Solar Cream-Pearl
}}

_active_theme = None

def apply_slime_theme(theme_name):
    """Updates 3D porcelain palette ONLY when theme changes to avoid full-screen SPI dirty redraws."""
    global _active_theme
    if theme_name == _active_theme:
        return
    _active_theme = theme_name
    dr, dg, db = STUDIO_TINTS.get(theme_name, (0, 2, 6))
    for i in range(20):
        base = BASE_PALETTE[4 + i]
        r = max(0, min(255, ((base >> 16) & 0xFF) + dr))
        g = max(0, min(255, ((base >> 8) & 0xFF) + dg))
        b = max(0, min(255, (base & 0xFF) + db))
        fg_pal[4 + i] = (r << 16) | (g << 8) | b

# Allocate Hardware-Composited TileGrid Layers (Zero per-frame full-screen redraw!)
bg_bmp = displayio.Bitmap(160, 80, 4)
shadow_bmp = displayio.Bitmap(56, 8, NUM_COLORS)
bot_bmp = displayio.Bitmap(66 * 4, 75, NUM_COLORS)
eyes_bmp = displayio.Bitmap(32 * 7, 20, NUM_COLORS)
prop_bmp = displayio.Bitmap(32 * 6, 24, NUM_COLORS)
callout_bmp = displayio.Bitmap(88, 28, NUM_COLORS)

bg_grid = displayio.TileGrid(bg_bmp, pixel_shader=bg_pal)
shadow_grid = displayio.TileGrid(shadow_bmp, pixel_shader=fg_pal, x=10, y=71)
bot_grid = displayio.TileGrid(bot_bmp, pixel_shader=fg_pal, width=1, height=1, tile_width=66, tile_height=75, x=4, y=2)
eyes_grid = displayio.TileGrid(eyes_bmp, pixel_shader=fg_pal, width=1, height=1, tile_width=32, tile_height=20, x=21, y=18)
prop_grid = displayio.TileGrid(prop_bmp, pixel_shader=fg_pal, width=1, height=1, tile_width=32, tile_height=24, x=46, y=30)
callout_grid = displayio.TileGrid(callout_bmp, pixel_shader=fg_pal, x=70, y=10)

root_group = displayio.Group()
root_group.append(bg_grid)
root_group.append(shadow_grid)
root_group.append(bot_grid)
root_group.append(eyes_grid)
root_group.append(prop_grid)
root_group.append(callout_grid)
display.root_group = root_group

# ─── 3. PRE-RAYMARCHED 3D STUDIO ASSETS (66x75 GIANT BOT!) ──────────────────
{format_tuple_rows("BOT_STAND", bot_tiles[0])}
{format_tuple_rows("BOT_STEP_L", bot_tiles[1])}
{format_tuple_rows("BOT_STEP_R", bot_tiles[2])}
{format_tuple_rows("BOT_REST", bot_tiles[3])}

{format_tuple_rows("EYE_NORMAL", eye_tiles[0])}
{format_tuple_rows("EYE_HALF", eye_tiles[1])}
{format_tuple_rows("EYE_BLINK", eye_tiles[2])}
{format_tuple_rows("EYE_HAPPY", eye_tiles[3])}
{format_tuple_rows("EYE_THINK", eye_tiles[4])}
{format_tuple_rows("EYE_SLEEP", eye_tiles[5])}
{format_tuple_rows("EYE_PARTY", eye_tiles[6])}

{format_tuple_rows("PROP_COFFEE_0", prop_tiles[0])}
{format_tuple_rows("PROP_COFFEE_1", prop_tiles[1])}
{format_tuple_rows("PROP_LAPTOP_0", prop_tiles[2])}
{format_tuple_rows("PROP_LAPTOP_1", prop_tiles[3])}
{format_tuple_rows("PROP_BULB", prop_tiles[4])}

def load_tile(bmp, tile_idx, tile_w, rows):
    x_off = tile_idx * tile_w
    for ry, row in enumerate(rows):
        for rx, ch in enumerate(row):
            if ch != ".":
                bmp[x_off + rx, ry] = CHAR_TO_IDX[ch]

# Populate Studio Backdrop & 3D Soft Contact Shadow
for y in range(80):
    c = 0 if y < 50 else (1 if y < 62 else (2 if y < 67 else 3))
    for x in range(160):
        bg_bmp[x, y] = c

for py in range(8):
    ny = (py - 3.5) / 3.7
    for px in range(56):
        nx = (px - 27.5) / 27.5
        r2 = nx * nx + ny * ny
        if r2 < 0.35:
            shadow_bmp[px, py] = 36
        elif r2 < 0.68:
            shadow_bmp[px, py] = 37
        elif r2 <= 1.0:
            shadow_bmp[px, py] = 38

# Unpack 3D Raymarched Tiles into TileGrid Bitmaps once at boot
for idx, t_rows in enumerate((BOT_STAND, BOT_STEP_L, BOT_STEP_R, BOT_REST)):
    load_tile(bot_bmp, idx, 66, t_rows)

for idx, e_rows in enumerate((EYE_NORMAL, EYE_HALF, EYE_BLINK, EYE_HAPPY, EYE_THINK, EYE_SLEEP, EYE_PARTY)):
    load_tile(eyes_bmp, idx, 32, e_rows)

for idx, p_rows in enumerate((PROP_COFFEE_0, PROP_COFFEE_1, PROP_LAPTOP_0, PROP_LAPTOP_1, PROP_BULB)):
    load_tile(prop_bmp, idx + 1, 32, p_rows)

# Free temporary string tables from RAM after unpacking into Bitmaps
del BOT_STAND, BOT_STEP_L, BOT_STEP_R, BOT_REST
del EYE_NORMAL, EYE_HALF, EYE_BLINK, EYE_HAPPY, EYE_THINK, EYE_SLEEP, EYE_PARTY
del PROP_COFFEE_0, PROP_COFFEE_1, PROP_LAPTOP_0, PROP_LAPTOP_1, PROP_BULB
gc.collect()

# ─── 4. ULTRA-CRISP 6x8 BOLD SIDE COMIC CALLOUT RENDERER ────────────────────
{font_block}

def split_callout_lines(text):
    """Greedy 2x10-char word wrap (mirrors host `layout_bubble_lines`)."""
    words = text.strip().upper().split()
    if not words:
        return ("...",)
    line1 = words[0][:10]
    i = 1
    while i < len(words) and len(line1) + 1 + len(words[i]) <= 10:
        line1 += " " + words[i]
        i += 1
    if i >= len(words):
        return (line1,)
    return (line1, " ".join(words[i:])[:10])

_last_callout_key = None

def update_callout_bitmap(text, place_right, alert=False):
    """Redraws callout_bmp ONLY when text or side changes — 0 CPU cost on normal frames!"""
    global _last_callout_key
    key = (text, place_right, alert)
    if key == _last_callout_key:
        return
    _last_callout_key = key

    callout_bmp.fill(0)
    lines = split_callout_lines(text)
    max_chars = max(len(l) for l in lines)
    text_w = max_chars * 7 - 1
    bw = min(80, max(36, text_w + 10))
    bh = 16 if len(lines) == 1 else 26

    bx = 6 if place_right else (88 - 6 - bw)
    by = 1

    border_c = 43 if alert else 61
    fill_c = 60
    shadow_c = 58
    text_c = 42 if alert else 32

    # Crisp high-contrast rounded comic box inside callout_bmp
    for py in range(by, by + bh):
        for px in range(bx, bx + bw):
            is_top = (py == by)
            is_bot = (py == by + bh - 1)
            is_l = (px == bx)
            is_r = (px == bx + bw - 1)
            if (is_top or is_bot) and (is_l or is_r):
                continue
            if is_top or is_bot or is_l or is_r:
                callout_bmp[px, py] = border_c
            elif py == by + bh - 2:
                callout_bmp[px, py] = shadow_c
            else:
                callout_bmp[px, py] = fill_c

    # Anti-aliased inner corner pixels
    callout_bmp[bx + 1, by + 1] = border_c
    callout_bmp[bx + bw - 2, by + 1] = border_c
    callout_bmp[bx + 1, by + bh - 2] = border_c
    callout_bmp[bx + bw - 2, by + bh - 2] = border_c

    # Horizontal triangular callout pointer (<-- or -->)
    ay = by + bh // 2
    if place_right:
        for dx in range(1, 6):
            hh = max(0, (5 - dx) // 2)
            for py in range(ay - hh, ay + hh + 1):
                callout_bmp[bx - dx + 1, py] = fill_c
            callout_bmp[bx - dx + 1, ay - hh - 1] = border_c
            callout_bmp[bx - dx + 1, ay + hh + 1] = border_c
        callout_bmp[bx - 5, ay] = border_c
    else:
        rx_edge = bx + bw - 1
        for dx in range(1, 6):
            hh = max(0, (5 - dx) // 2)
            for py in range(ay - hh, ay + hh + 1):
                callout_bmp[rx_edge + dx - 1, py] = fill_c
            callout_bmp[rx_edge + dx - 1, ay - hh - 1] = border_c
            callout_bmp[rx_edge + dx - 1, ay + hh + 1] = border_c
        callout_bmp[rx_edge + 5, ay] = border_c

    # Draw ultra-crisp 6x8 BOLD pixel text (2px stems!) on pure white interior
    for idx, line_str in enumerate(lines):
        lw = len(line_str) * 7 - 1
        cx = bx + (bw - lw) // 2
        ty = by + 4 + idx * 10
        for ch in line_str:
            glyph = FONT_6X8_BOLD.get(ch, FONT_6X8_BOLD[" "])
            for ry in range(8):
                r_str = glyph[ry]
                for rx in range(6):
                    if r_str[rx] == "1":
                        callout_bmp[cx + rx, ty + ry] = text_c
            cx += 7

# ─── 5. USB SERIAL PROTOCOL & NeoPixel LED SYNC ─────────────────────────────
try:
    import usb_cdc
    serial_data = usb_cdc.data
except Exception:
    serial_data = None

def set_neopixel_state(state, frame):
    """Updates GP16 NeoPixel with dirty-check to avoid redundant interrupt-blocking writes."""
    global _last_led_rgb
    if led_pin is None:
        return
    s_val = SIN_64[(frame << 1) & 63]
    pulse = 0.65 + 0.35 * s_val
    if state == "OVERLOAD":
        r, g, b = (90, 5, 5) if (frame & 1 == 0) else (20, 0, 0)
    elif state == "CODING":
        r, g, b = 0, int(38 * pulse), int(75 * pulse)
    elif state == "COFFEE":
        r, g, b = int(55 * pulse), int(32 * pulse), int(5 * pulse)
    elif state == "THINKING":
        r, g, b = int(42 * pulse), int(10 * pulse), int(75 * pulse)
    elif state == "CHILL":
        r, g, b = int(5 * pulse), int(55 * pulse), int(25 * pulse)
    elif state == "PARTY":
        r = int(45 + 40 * SIN_64[(frame * 3) & 63])
        g = int(45 + 40 * SIN_64[(frame * 3 + 21) & 63])
        b = int(45 + 40 * SIN_64[(frame * 3 + 42) & 63])
    else:
        r, g, b = int(4 * pulse), int(6 * pulse), int(22 * pulse)

    g_c = max(0, min(255, g))
    r_c = max(0, min(255, r))
    b_c = max(0, min(255, b))
    rgb_tuple = (g_c, r_c, b_c)
    if rgb_tuple == _last_led_rgb:
        return
    _last_led_rgb = rgb_tuple
    led_buf[0] = g_c
    led_buf[1] = r_c
    led_buf[2] = b_c
    try:
        neopixel_write(led_pin, led_buf)
    except Exception:
        pass

# ─── 6. HIGH-FPS 3D HARDWARE-COMPOSITED ANIMATION LOOP ──────────────────────
# Fallback thoughts used ONLY when running standalone without host_companion.py
DEFAULT_PHRASES = {{
    "CODING":   ("DEEP WORK", "LGTM!", "SHIP IT!", "TYPING...", "0 BUGS?", "CLEAN CODE"),
    "COFFEE":   ("NEED COFFEE", "SIPPING~", "CAFFEINE+", "BRB COFFEE", "HOT BREW!"),
    "THINKING": ("HMM...", "WAIT WTF?", "BIG BRAIN", "OTF MODE", "LET ME SEE", "WHY THO?"),
    "CHILL":    ("VIBING~", "CHILL MODE", "COZY AF", "LOFI BEAT", "RESTING"),
    "SLEEP":    ("ZZZ...", "SLEEP MODE", "DREAMING~", "AFK ZZZ"),
    "OVERLOAD": ("WTF?!", "CPU 99%!", "SEGFAULT!", "PANIC!!", "HOT CPU!"),
    "PARTY":    ("HELL YEAH!", "DEPLOYED!", "GG EZ!", "10X VIBE!"),
}}

STATE_TO_THEME = {{
    "CODING":   "CYBER",
    "COFFEE":   "TEAL",
    "THINKING": "VIOLET",
    "CHILL":    "EMERALD",
    "SLEEP":    "INDIGO",
    "OVERLOAD": "CRIMSON",
    "PARTY":    "GOLD",
}}

WALK_SEQ = (0, 1, 0, 2)
TARGET_FRAME_DT = 0.028  # ~36 FPS smooth hardware TileGrid animation

def map_incoming_state(act, mood, evt, poster, cpu):
    if cpu >= 85 or mood == "panicking" or poster == "fire_panic":
        return "OVERLOAD"
    if act == "sleeping" or mood == "sleepy" or poster == "zzz_dream":
        return "SLEEP"
    if evt == "cheer" or poster == "rocket_launch":
        return "PARTY"
    if evt == "sip_coffee" or poster == "coffee_need" or mood == "tired":
        return "COFFEE"
    if poster in ("brain_idea", "bug_alert") or mood in ("curious", "stressed"):
        return "THINKING"
    if act in ("music", "browsing") and poster in ("music_eq", "chill_play", "heart_love", "zen_mountain"):
        return "CHILL"
    if act in ("coding", "terminal") or poster == "code_matrix":
        return "CODING"
    return "COFFEE"

apply_slime_theme("CYBER")

current_state = "COFFEE"
llm_thoughts = ()
llm_thoughts_until = 0.0
phrase_idx = 0
last_phrase_cycle = time.monotonic()

slime_x = 36.0
slime_vx = 1.2
eye_look_x = 2.5
eye_look_y = 0.0
sip_lift = 0.0
frame = 0
serial_buf = ""

while True:
    frame_start = time.monotonic()

    # 1. Read USB Serial (Console + Data)
    while supervisor.runtime.serial_bytes_available:
        ch = sys.stdin.read(1)
        if ch:
            serial_buf += ch
    if serial_data is not None and serial_data.in_waiting > 0:
        try:
            raw = serial_data.read(serial_data.in_waiting)
            if raw:
                serial_buf += raw.decode("utf-8", "ignore")
        except Exception:
            pass

    if "\\n" in serial_buf:
        lines = serial_buf.split("\\n")
        serial_buf = lines[-1]
        for line in lines[:-1]:
            line = line.strip()
            if not line:
                continue
            kv = {{}}
            for part in line.split("|"):
                if ":" in part:
                    k, v = part.split(":", 1)
                    kv[k.strip().upper()] = v.strip()
            if kv:
                act = kv.get("ACT", "coding").lower()
                mood = kv.get("MOOD", "focused").lower()
                evt = kv.get("EVT", "none").lower()
                poster = kv.get("POSTER", "code_matrix").lower()
                state_override = kv.get("STATE", "").upper()
                theme_override = kv.get("THEME", "").upper()
                msg_in = kv.get("MSG", "").strip()
                try:
                    cpu_val = int(kv.get("CPU", "15"))
                except ValueError:
                    cpu_val = 15

                if state_override in DEFAULT_PHRASES:
                    current_state = state_override
                else:
                    current_state = map_incoming_state(act, mood, evt, poster, cpu_val)

                theme_key = theme_override if theme_override in STUDIO_TINTS else STATE_TO_THEME.get(current_state, "CYBER")
                apply_slime_theme(theme_key)

                if "MSG" in kv:
                    # Live LLM thoughts, '~' separated. Empty MSG -> built-in phrase pool.
                    parsed = tuple(t.strip()[:21].upper() for t in msg_in.split("~") if t.strip())
                    if parsed != llm_thoughts:
                        llm_thoughts = parsed
                        phrase_idx = 0
                        last_phrase_cycle = frame_start
                    llm_thoughts_until = frame_start + 180.0

    # 2. Smoothly update position & velocity
    sipping = (current_state == "COFFEE") and ((frame % 44) >= 28)
    if current_state == "COFFEE":
        if not sipping:
            slime_x += slime_vx
            if slime_x > 124.0:
                slime_x = 124.0
                slime_vx = -1.2
            elif slime_x < 36.0:
                slime_x = 36.0
                slime_vx = 1.2
    elif current_state == "THINKING":
        slime_x += slime_vx * 0.55
        if slime_x > 120.0:
            slime_x = 120.0
            slime_vx = -1.1
        elif slime_x < 36.0:
            slime_x = 36.0
            slime_vx = 1.1
    elif current_state == "PARTY":
        slime_x += slime_vx * 1.3
        if slime_x > 124.0:
            slime_x = 124.0
            slime_vx = -1.3
        elif slime_x < 36.0:
            slime_x = 36.0
            slime_vx = 1.3
    elif current_state == "CODING":
        target = 35.0
        if abs(slime_x - target) > 1.2:
            slime_x += (target - slime_x) * 0.18
    else:
        target = 38.0
        if abs(slime_x - target) > 1.2:
            slime_x += (target - slime_x) * 0.15

    # 3. Smoothly interpolate 3D eye gaze & O(1) table-lookup breathing bob
    target_look_x = 0.0 if (sipping or current_state in ("SLEEP", "CHILL")) else (3.5 if (current_state == "CODING" or slime_vx >= 0) else -3.5)
    target_look_y = 1.0 if current_state == "CODING" else (-1.0 if current_state == "THINKING" else 0.0)
    eye_look_x += (target_look_x - eye_look_x) * 0.35
    eye_look_y += (target_look_y - eye_look_y) * 0.35

    bob = int(SIN_64[(frame * 3) & 63] * 1.5)
    ix = int(slime_x)
    bx = ix - 33
    if current_state == "OVERLOAD":
        bx += (1 if (frame & 1 == 0) else -1)
    by = 2 + bob

    # 4. Update Giant 66x75 3D Body TileGrid & Shadow TileGrid
    shadow_grid.x = ix - 28
    shadow_grid.y = 71

    if current_state in ("SLEEP", "CHILL"):
        bot_grid[0] = 3  # REST / SITTING 3D POSE
        bot_grid.x = bx
        bot_grid.y = 4 + (1 if (frame & 15) < 8 else 0)
    elif current_state == "CODING" or sipping or current_state == "OVERLOAD":
        bot_grid[0] = 0  # STAND 3D POSE
        bot_grid.x = bx
        bot_grid.y = by
    else:
        bot_grid[0] = WALK_SEQ[(frame // 3) & 3]
        bot_grid.x = bx
        bot_grid.y = by

    # 5. Update 32x20 3D Anti-Aliased Eyes TileGrid (with 2-stage smooth eyelid blink!)
    blink_phase = frame % 52
    if current_state == "SLEEP":
        eyes_grid[0] = 5
    elif current_state == "PARTY":
        eyes_grid[0] = 6
    elif sipping or (current_state == "CHILL" and (frame % 28) < 12):
        eyes_grid[0] = 3  # Happy ^ ^ + Rosy Blush
    elif blink_phase in (48, 51):
        eyes_grid[0] = 1  # Half-Blink intermediate eyelid frame!
    elif blink_phase in (49, 50):
        eyes_grid[0] = 2  # Full Closed Blink!
    elif current_state == "THINKING":
        eyes_grid[0] = 4  # Inquisitive 3D Squint
    else:
        eyes_grid[0] = 0  # Iconic Tall 3D Vertical Capsule Eyes

    eyes_grid.x = bot_grid.x + 17 + int(eye_look_x)
    eyes_grid.y = bot_grid.y + (21 if bot_grid[0] == 3 else 16) + int(eye_look_y)

    # 6. Update 32x24 3D Interactive Prop TileGrid
    target_sip = 7.0 if sipping else 0.0
    sip_lift += (target_sip - sip_lift) * 0.35

    if current_state == "COFFEE":
        prop_grid[0] = 1 + ((frame >> 2) & 1)
        if sipping:
            prop_grid.x = ix - 10
        else:
            prop_grid.x = (bot_grid.x + 42) if slime_vx >= 0 else (bot_grid.x - 10)
        prop_grid.y = bot_grid.y + 28 - int(sip_lift)
    elif current_state == "CODING":
        prop_grid[0] = 3 + ((frame >> 1) & 1)
        prop_grid.x = bot_grid.x + 44
        prop_grid.y = 46
    elif current_state in ("THINKING", "OVERLOAD"):
        prop_grid[0] = 5
        prop_grid.x = bot_grid.x + 31
        prop_grid.y = bot_grid.y + 17 + (1 if (frame % 6) < 3 else 0)
    elif current_state == "CHILL":
        prop_grid[0] = 1 + ((frame // 5) & 1)
        prop_grid.x = bot_grid.x + 44
        prop_grid.y = 48
    else:
        prop_grid[0] = 0  # Hidden in SLEEP / PARTY

    # 7. Update Rock-Steady Ultra-Crisp 6x8 Bold Side Comic Callout Bubble
    if frame_start - last_phrase_cycle > 4.2:
        last_phrase_cycle = frame_start
        phrase_idx += 1

    if llm_thoughts and frame_start < llm_thoughts_until:
        active_speech = llm_thoughts[phrase_idx % len(llm_thoughts)]
    else:
        phrases = DEFAULT_PHRASES.get(current_state, DEFAULT_PHRASES["COFFEE"])
        active_speech = phrases[phrase_idx % len(phrases)]

    place_right = (slime_x <= 80.0)
    update_callout_bitmap(active_speech, place_right, alert=(current_state == "OVERLOAD"))

    if place_right:
        callout_grid.x = min(71, ix + 30)
    else:
        callout_grid.x = max(1, ix - 30 - 88)
    callout_grid.y = 10  # Locked steady — zero vertical blur!

    set_neopixel_state(current_state, frame)
    display.refresh(minimum_frames_per_second=0)
    frame += 1

    elapsed = time.monotonic() - frame_start
    if elapsed < TARGET_FRAME_DT:
        time.sleep(TARGET_FRAME_DT - elapsed)
'''


if __name__ == "__main__":
    import argparse

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    parser = argparse.ArgumentParser(description="Generate the 3D Grok Bot CircuitPython firmware (code.py)")
    parser.add_argument("-o", "--output", default=os.path.join(repo_root, "code.py"), help="Output path for generated code.py")
    args = parser.parse_args()

    out_code = generate_firmware_source()
    with open(args.output, "w") as f:
        f.write(out_code)
    print(f"Generated {args.output} ({len(out_code)} bytes)")
