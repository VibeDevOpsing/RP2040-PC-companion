import board
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
ALPHA = ".0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz!#"
CHAR_TO_IDX = {ch: i for i, ch in enumerate(ALPHA)}
SIN_64 = (0.000, 0.098, 0.195, 0.290, 0.383, 0.471, 0.556, 0.634, 0.707, 0.773, 0.831, 0.882, 0.924, 0.957, 0.981, 0.995, 1.000, 0.995, 0.981, 0.957, 0.924, 0.882, 0.831, 0.773, 0.707, 0.634, 0.556, 0.471, 0.383, 0.290, 0.195, 0.098, 0.000, -0.098, -0.195, -0.290, -0.383, -0.471, -0.556, -0.634, -0.707, -0.773, -0.831, -0.882, -0.924, -0.957, -0.981, -0.995, -1.000, -0.995, -0.981, -0.957, -0.924, -0.882, -0.831, -0.773, -0.707, -0.634, -0.556, -0.471, -0.383, -0.290, -0.195, -0.098)

BASE_PALETTE = (
    0x0A0D16, 0x0D111D, 0x121726, 0x161D2E, 0x626C80, 0x70798C, 0x7B8494, 0x858D9D, 0x8F96A4, 0x979EAB, 0xA0A6B2, 0xA8AEB9, 0xB0B5BF, 0xB8BCC5, 0xBFC3CB, 0xC7CAD2,
    0xCED1D7, 0xD5D8DD, 0xDCDFE3, 0xE3E5E9, 0xEAECEE, 0xF1F2F4, 0xF8F8F9, 0xFFFFFF, 0x202533, 0x343A49, 0x484F5F, 0x5C6475, 0xA4AEBE, 0x767E8E, 0x424755, 0x1C1F28,
    0x04060A, 0x1D222F, 0x343E54, 0xF488A6, 0x07090F, 0x0C101A, 0x111725, 0x341B0E, 0x6E3C1C, 0xBC804C, 0xAF101E, 0xDC2636, 0xFA5260, 0x1C2636, 0x3A485E, 0x64748B,
    0x94A3B8, 0x064E3B, 0x10B981, 0x4EFF9B, 0xB45309, 0xF59E0B, 0xFDE047, 0xFEF9C3, 0x38BDF8, 0xA855F7, 0xD4DEEC, 0xF1F5F9, 0xFFFFFF, 0x26344A, 0x96A8C2, 0xDAE4F2,
)

bg_pal = displayio.Palette(NUM_COLORS)
fg_pal = displayio.Palette(NUM_COLORS)
for i, col in enumerate(BASE_PALETTE):
    bg_pal[i] = col
    fg_pal[i] = col
fg_pal.make_transparent(0)

# Subtle 3D Studio Lighting Tint Themes (tints the 20 porcelain shades 4..23!)
STUDIO_TINTS = {
    "CYBER":   (0, 2, 6),      # Cool Studio White-Blue
    "VIOLET":  (4, -2, 10),    # Kiro Lavender-Pearl
    "TEAL":    (-4, 4, 6),     # Aqua Studio Pearl
    "EMERALD": (-4, 6, 2),     # Mint Studio Pearl
    "INDIGO":  (-6, -4, 12),   # Starlight Sleep Pearl
    "CRIMSON": (16, -8, -6),   # Warm Alert Rose-Pearl
    "GOLD":    (12, 6, -6),    # Warm Solar Cream-Pearl
}

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
BOT_STAND = (
    "..................................................................",
    "..................................................................",
    "..................................................................",
    "...........................OPQ99AAA98QPO..........................",
    "........................NP9ABCCCDDCCCBBA8PN.......................",
    ".......................PABCDDEEEEEEEEDDCBA9P......................",
    ".....................P9BCDEEFGGGGGGGFFEEDCCA8P....................",
    "....................QACDEFGGGHHHIHHHGGGFFEDCB9Q...................",
    "...................QBCDEFGHHIJJJJJIIIHHGFFEDCB9Q..................",
    "..................8BCEEGGIIJJKKKKKKJJIIHHGFEDCBA6.................",
    ".................QBCDFGHIJJKLLLMMMLLKJJIHHGFEECB9Q................",
    "................PACDFGHIJKLLMMMMMMMMLKKJIHHGFEDCB9P...............",
    "...............O9BDEFHIJKLMMMMMMMMMMMLKKJIHGGFEDCA8O..............",
    "...............8BCEFGHIJKMMMMMMMMMMMMMLKJJIHGFEDCB96..............",
    "..............PABDEFHIJKLMMMMMMMMMMMMMLKKJIHHGFEDCA8P.............",
    "..............8ACEFGHIJLMMMMMMMMMMMMMMLLKJIIHGFEDCB96.............",
    ".............O9BDEFGHIKLMMMMMMMMMMMMMMMLKJJIHGGFEDBA8O............",
    ".............QACDEGHIJKLMMMMMMMMMMMMMMMLKJJIHHGFEDCA8Q............",
    ".............8ACDEGHIJKLMMMMMMMMMMMMMMMLKJJIHHGFEDCA96............",
    "............O9BCEFGHIJKLMMMMMMMMMMMMMMLLKJJIHHGFEDCB97O...........",
    "............P9BCEFGHIJKKLMMMMMMMMMMMMMLKKJJIHHGFEDCB97P...........",
    "............Q9BCEFGHIIJKLMMMMMMMMMMMMLLKKJIIHHGFEDCB97Q...........",
    "............Q9BCDFGGHIJKKLMMMMMMMMMMLLKKJJIIHGGFEDCB97Q...........",
    "............59BCDEFGHIJJKKLLMMMMMMMLLKKKJJIHHGGFEDCB975...........",
    "............69BCDEFGHIIJJKKLLLMMMLLLLKKJJIIHHGFEEDCB975...........",
    "............69BCDEFGHIIJJKKLLLMMMLLLLKKJJIIHHGFEEDCB975...........",
    "............59BCDEFGHIIJJKKLLLMMMLLLLKKJJIIHHGFEEDCB975...........",
    "............59BCDEFGHIIJJKKLLLMMMLLLLKKJJIIHHGFEEDCB974...........",
    "............58BCDFFGHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB974...........",
    "............47BCDFFGHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB964...........",
    "............47ACDFFGHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB964...........",
    "...........O57ACDFFHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB864O..........",
    "..........P5569CDFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB8555P.........",
    "........P677669CDFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB856776P.......",
    ".......Q8899758CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB7578877Q......",
    "......P9AABA858CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA75799998P.....",
    "......7ABBBB958CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA758AA9A96.....",
    ".....O9BBBBB958BEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA7589A9AA7O....",
    ".....PABBAAA958BEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA758999AA9P....",
    ".....8BCBAA9958CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA758999ABA6....",
    "....O9CCCAA9858CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA757999BBA8O...",
    "....PBCCCAA9859CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHHGFEDDB857999BBBAP...",
    "....8CDDCAA9769DEFGHHIJKKLLMMMMMMMMLLLKKJJIIHHGFEDDB857999BCCA6...",
    "...OADDDCAA9769DEFGHHIJKKLLMMMMMMMMLLLKKJJIIHHGFEDDB856999BCCB8O..",
    "...PCEEDCAA977ADEFGHHIJKKLLMMMMMMMMLLLKKJJIIHHGFEDDB966999BCDCAP..",
    "...8DEEECA9967ADEFGHIIJKKLLMMMMMMMMLLLKKJJIIHHGFEEDB966899BCDDB6..",
    "..OAEFFECA9968BDEFGHIIJKKLLMMMMMMMMLLLKKJJIIHHGFEEDBA75999BDDDC8O.",
    "..PCFFFEB99958BDEFGHHIJJKKLLLMMMMLLLLKKKJJIIHGGFEDDBA75899BDEEDAP.",
    "..7DGGGEB99858BDEFFGHIIJJKKKLLLLLLLKKKKJJIIHHGGFEDCB974899BDEFEB5.",
    ".N9DHHGEB99858BCDEFGHHIIJJJKKKKKKKKKKJJJIIHHGGFFEDCB974899BDFFFC8N",
    ".O9EHHGEB99858BCDEFGGHHIIJJJKKKKKKKJJJJIIHHHGFFEDCCA974899BEFGFD8O",
    ".O8DGGGEB99857ACCEEFGGHHIIIJJJJJJJJJJIIIHHHGGFEEDCBA964899BEFFEC7O",
    "..7BEFEDB98857ABCDEEFGGHHIIIIJJJJJJIIIIHHHGGFFEDCCBA964889BCEED97.",
    "..Q9CDCB987757ABCDDEFFGGHHHIIIIIIIIIIHHHGGGFFEDDCBAA865788ABCCB8Q.",
    "..N69BAA8766569BBCDDEFFGGGHHHHHHHHHHHHHGGGFFEEDCBAA986566789AA97N.",
    "...O67877555468ABBCDDEFFFGGGHHHHHHHHGGGGFFFEEDCCBAA975455677887O..",
    "....OQ665543358ABBCCDDEFFFFGGGGGGGGGGGFFFEEEDCCBAAA9754344566QO...",
    "......OOPON.P58ABBBCCDDEEFFFFFFGGGFFFFFEEEDDCCBAAA9975P.NOPOO.....",
    ".............58ABBBCCCDDDEEEFFFFFFFFFEEEDDCCBBAAAA9975............",
    ".............Q7ABBCCCCCCDDDEEEEEEEEEEEDDDCCBBAAAAA997Q............",
    ".............P79BBCCCCBBCCCDDDDDDDDDDDDCCBBAABBBBA987P............",
    ".............O79BCCCCCCBBBCCCCCCDDDCCCCBBBABBBBBBA987O............",
    "..............69BCDDDDCCBBBBBBBCCBBBBBBAAABBBCCCBB986.............",
    "..............Q9BCDEEDDDCBBAAABBBBBAAAAAABBCCCDCCBA8Q.............",
    "..............P8BCDEEEEDCCBAA99AAAA9999ABBCCDDDCCB98P.............",
    "..............O7ACDDEEEDDCBBA998888899AABCCDDDDCBA97O.............",
    "...............59BCDDDDDCCBA98877777889ABCCCDDCCB986..............",
    "...............O79BCCDDCCBA9876665666789ABCCCCBBA97O..............",
    "................Q79ABBCCBA9866554Q3555689ABBBBA998Q...............",
    "................N5789AAA987665QPO.OPQ456789AA99886N...............",
    ".................N46788876655P.......P45567898875N................",
    "...................P56766554O.........O35566776P..................",
    ".....................OPQQPPN...........NPPQQPO....................",
    "..................................................................",
    "..................................................................",
)
BOT_STEP_L = (
    "..................................................................",
    "..................................................................",
    "..................................................................",
    "...........................OPQ99AAA98QPO..........................",
    "........................NP9ABCCCDDCCCBBA8PN.......................",
    ".......................PABCDDEEEEEEEEDDCBA9P......................",
    ".....................P9BCDEEFGGGGGGGFFEEDCCA8P....................",
    "....................QACDEFGGGHHHIHHHGGGFFEDCB9Q...................",
    "...................QBCDEFGHHIJJJJJIIIHHGFFEDCB9Q..................",
    "..................8BCEEGGIIJJKKKKKKJJIIHHGFEDCBA6.................",
    ".................QBCDFGHIJJKLLLMMMLLKJJIHHGFEECB9Q................",
    "................PACDFGHIJKLLMMMMMMMMLKKJIHHGFEDCB9P...............",
    "...............O9BDEFHIJKLMMMMMMMMMMMLKKJIHGGFEDCA8O..............",
    "...............8BCEFGHIJKMMMMMMMMMMMMMLKJJIHGFEDCB96..............",
    "..............PABDEFHIJKLMMMMMMMMMMMMMLKKJIHHGFEDCA8P.............",
    "..............8ACEFGHIJLMMMMMMMMMMMMMMLLKJIIHGFEDCB96.............",
    ".............O9BDEFGHIKLMMMMMMMMMMMMMMMLKJJIHGGFEDBA8O............",
    ".............QACDEGHIJKLMMMMMMMMMMMMMMMLKJJIHHGFEDCA8Q............",
    ".............8ACDEGHIJKLMMMMMMMMMMMMMMMLKJJIHHGFEDCA96............",
    "............O9BCEFGHIJKLMMMMMMMMMMMMMMLLKJJIHHGFEDCB97O...........",
    "............P9BCEFGHIJKKLMMMMMMMMMMMMMLKKJJIHHGFEDCB97P...........",
    "............Q9BCEFGHIIJKLMMMMMMMMMMMMLLKKJIIHHGFEDCB97Q...........",
    "............Q9BCDFGGHIJKKLMMMMMMMMMMLLKKJJIIHGGFEDCB97Q...........",
    "............59BCDEFGHIJJKKLLMMMMMMMLLKKKJJIHHGGFEDCB975...........",
    "............69BCDEFGHIIJJKKLLLMMMLLLLKKJJIIHHGFEEDCB975...........",
    "............69BCDEFGHIIJJKKLLLMMMLLLLKKJJIIHHGFEEDCB975...........",
    "............59BCDEFGHIIJJKKLLLMMMLLLLKKJJIIHHGFEEDCB975...........",
    "............59BCDEFGHIIJJKKLLLMMMLLLLKKJJIIHHGFEEDCB974...........",
    "............58BCDFFGHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB974...........",
    "............47BCDFFGHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB964...........",
    "............47ACDFFGHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB964...........",
    "...........O57ACDFFHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB864O..........",
    "..........P5569CDFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB8555P.........",
    "........P677669CDFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB856776P.......",
    ".......Q8899758CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB7578877Q......",
    "......P9AABA858CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA75799998P.....",
    "......7ABBBB958CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA758AA9A96.....",
    ".....O9BBBBB958BEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA7589A9AA8O....",
    ".....PABBAAA958BEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA758999AA9Q....",
    ".....7BBBAA9958CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA758999ABA8N...",
    "....N9BCBAAA858CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA757999BBB9P...",
    "....OACCCAAA859CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHHGFEDDB857999BCCA5...",
    "....QBCCCAA9769DEFGHHIJKKLLMMMMMMMMLLLKKJJIIHHGFEDDB857999BCCB9O..",
    "....8CDDCAA9769DEFGHHIJKKLLMMMMMMMMLLLKKJJIIHHGFEDDB857999BCDDBQ..",
    "...OACDDCAA977ADEFGHHIJKKLLMMMMMMMMLLLKKJJIIHHGFEDDB966899BDDDC7..",
    "...PBDEDCAA967ADEFGHIIJKKLLMMMMMMMMLLLKKJJIIHHGFEEDB975999BDEED9P.",
    "...QCEEDCAA968BDEFGHIIJKKLLMMMMMMMMLLLKKJJIIHHGFEEDBA75899BDEEEBQ.",
    "...9DEEDBA9968BDEFGHHIJJKKLLLMMMMLLLLKKKJJIIHGGFEDDBA75899BDEFFC8.",
    "..OAEFFEBA9958BDEFFGHIIJJKKKLLLLLLLKKKKJJIIHHGGFEDCBA74899BDFGFD8O",
    "..PCFGFEC99958BCDEFGHHIIJJJKKKKKKKKKKJJJIIHHGGFFEDCBA74899BDFFEC7O",
    "..8DGGGEC99857ACDEFGGHHIIJJJKKKKKKKJJJJIIHHHGFFEDCCA974799ACDEDA7.",
    ".N9EHHGFC99957ACCEEFGGHHIIIJJJJJJJJJJIIIHHHGGFEEDCBA9747889BCCB9Q.",
    ".O9EHIHFCA9957ABCDEEFGGHHIIIIJJJJJJIIIIHHHGGFFEDCCBA96466789AA97O.",
    ".O8DGHGFC999669BCDDEFFGGHHHIIIIIIIIIIHHHGGGFFEDDCBAA96455567787P..",
    "..7BEFFDB988669BBCDDEFFGGGHHHHHHHHHHHHHGGGFFEEDCBAA98644445665O...",
    "..Q9CDDCA877658ABBCDDEFFFGGGHHHHHHHHGGGGFFFEEDCCBAA9864OOPPPO.....",
    "..N59BBA9766557ABBCCDDEFFFFGGGGGGGGGGGFFFEEEDCCBAAA986P...........",
    "...O57887655447ABBBCCDDEEFFFFFFGGGFFFFFEEEDDCCBAAA9986O...........",
    "....NQ66554QP47ABBBBCCDDDEEEFFFFFFFFFEEEDDCCBBAAAA9985............",
    ".......OOO...Q69ABBCCCCCDDDEEEEEEEEEEEDDDCCBBAAAAA998Q............",
    ".............P69ABBBBBBBCCCDDDDDDDDDDDDCCBBAABBBBA987P............",
    "..............58AABBBBBBBBCCCCCCDDDCCCCBBBABBBBBBA987O............",
    "..............P79ABBBBBBBABBBBBCCBBBBBBAAABBBCCCBBA87.............",
    "...............579AABBBAAAAAAABBBBBAAAAAABBCCDDCCBA8Q.............",
    "...............O6799AAAAAA99999AAAA999AABCCDDEEDDBA8P.............",
    "................P578999999998888888899ABCCDEEEEDCB98P.............",
    ".................P56788887777766777789ABCDDEEEEDCB97N.............",
    "..................O56777666655555566689ABDDEEEDCBA85..............",
    "....................P555555544QPQQ456689ACDDDDCBA97P..............",
    "......................NOPQQPO....NOP45689ABCCCBA985...............",
    "....................................O356789AAA9986O...............",
    ".....................................OQ5577899886O................",
    "......................................OQ4566777Q..................",
    "........................................PQ44QPN...................",
    "..................................................................",
)
BOT_STEP_R = (
    "..................................................................",
    "..................................................................",
    "..................................................................",
    "...........................OPQ99AAA98QPO..........................",
    "........................NP9ABCCCDDCCCBBA8PN.......................",
    ".......................PABCDDEEEEEEEEDDCBA9P......................",
    ".....................P9BCDEEFGGGGGGGFFEEDCCA8P....................",
    "....................QACDEFGGGHHHIHHHGGGFFEDCB9Q...................",
    "...................QBCDEFGHHIJJJJJIIIHHGFFEDCB9Q..................",
    "..................8BCEEGGIIJJKKKKKKJJIIHHGFEDCBA6.................",
    ".................QBCDFGHIJJKLLLMMMLLKJJIHHGFEECB9Q................",
    "................PACDFGHIJKLLMMMMMMMMLKKJIHHGFEDCB9P...............",
    "...............O9BDEFHIJKLMMMMMMMMMMMLKKJIHGGFEDCA8O..............",
    "...............8BCEFGHIJKMMMMMMMMMMMMMLKJJIHGFEDCB96..............",
    "..............PABDEFHIJKLMMMMMMMMMMMMMLKKJIHHGFEDCA8P.............",
    "..............8ACEFGHIJLMMMMMMMMMMMMMMLLKJIIHGFEDCB96.............",
    ".............O9BDEFGHIKLMMMMMMMMMMMMMMMLKJJIHGGFEDBA8O............",
    ".............QACDEGHIJKLMMMMMMMMMMMMMMMLKJJIHHGFEDCA8Q............",
    ".............8ACDEGHIJKLMMMMMMMMMMMMMMMLKJJIHHGFEDCA96............",
    "............O9BCEFGHIJKLMMMMMMMMMMMMMMLLKJJIHHGFEDCB97O...........",
    "............P9BCEFGHIJKKLMMMMMMMMMMMMMLKKJJIHHGFEDCB97P...........",
    "............Q9BCEFGHIIJKLMMMMMMMMMMMMLLKKJIIHHGFEDCB97Q...........",
    "............Q9BCDFGGHIJKKLMMMMMMMMMMLLKKJJIIHGGFEDCB97Q...........",
    "............59BCDEFGHIJJKKLLMMMMMMMLLKKKJJIHHGGFEDCB975...........",
    "............69BCDEFGHIIJJKKLLLMMMLLLLKKJJIIHHGFEEDCB975...........",
    "............69BCDEFGHIIJJKKLLLMMMLLLLKKJJIIHHGFEEDCB975...........",
    "............59BCDEFGHIIJJKKLLLMMMLLLLKKJJIIHHGFEEDCB975...........",
    "............59BCDEFGHIIJJKKLLLMMMLLLLKKJJIIHHGFEEDCB974...........",
    "............58BCDFFGHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB974...........",
    "............47BCDFFGHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB964...........",
    "............47ACDFFGHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB964...........",
    "...........O57ACDFFHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB864O..........",
    "..........P5569CDFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB8555P.........",
    "........P677669CDFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB856776P.......",
    ".......Q8899758CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCB7578877Q......",
    "......P9AABA858CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA75799998P.....",
    "......7ABBBB958CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA758AA9A96.....",
    ".....O9BBBBB958BEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA7589A9AA7O....",
    ".....QABBAAA958BEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA758999AA9P....",
    "....N9BCBAA9958CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA758999AA95....",
    "....PACCCAA9858CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHGGFEDCA758999ABA7....",
    "....7CDDCAA9859CEFGHHIJJKLLMMMMMMMMLLLKKJJIIHHGFEDDB757999BBA8O...",
    "...OADEDCAA9769DEFGHHIJKKLLMMMMMMMMLLLKKJJIIHHGFEDDB857999BBBAQ...",
    "...QCEEECA99769DEFGHHIJKKLLMMMMMMMMLLLKKJJIIHHGFEDDB856999BCCA6...",
    "...9DFFECA9977ADEFGHHIJKKLLMMMMMMMMLLLKKJJIIHHGFEDDB866999BCCB8N..",
    "..PBFFFEC99968ADEFGHIIJKKLLMMMMMMMMLLLKKJJIIHHGFEEDB966899BCCC9P..",
    "..QDGGFEB99958BDEFGHIIJKKLLMMMMMMMMLLLKKJJIIHHGFEEDBA75999BCDCBQ..",
    "..9EHHGEB99858CDEFGHHIJJKKLLLMMMMLLLLKKKJJIIHGGFEDDBA75899BCDDB6..",
    ".O9EHHGEB99858BDEFFGHIIJJKKKLLLLLLLKKKKJJIIHHGGFEDCB97589ABDDDD8O.",
    ".O9DGGFEB99858BCDEFGHHIIJJJKKKKKKKKKKJJJIIHHGGFFEDCB97589ABDEEDAP.",
    "..7BEFECA98858BCDEFGGHHIIJJJKKKKKKKJJJJIIHHHGFFEDCCA965899BDEFEBQ.",
    "..Q9CDCB988758BCCEEFGGHHIIIJJJJJJJJJJIIIHHHGGFEEDCBA96589ACEFFFC8.",
    "..O69BA9876657ABCDEEFGGHHIIIIJJJJJJIIIIHHHGGFFEDCCBA865899CEGGFD8O",
    "...P6887655547ABCDDEFFGGHHHIIIIIIIIIIHHHGGGFFEDDCBAA865999CFGGFC7O",
    "....O465544447ABBCDDEFFGGGHHHHHHHHHHHHHGGGFFEEDCBAA9756899CEFFDB7.",
    "......OPPPOO469ABBCDDEFFFGGGHHHHHHHHGGGGFFFEEDCCBAA9756789BCDDC9Q.",
    "............P69ABBCCDDEFFFFGGGGGGGGGGGFFFEEEDCCBAA997456789BBB97O.",
    "............O69ABBBCCDDEEFFFFFFGGGFFFFFEEEDDCCBAAA9964555789997P..",
    ".............59ABBBCCCDDDEEEFFFFFFFFFEEEDDCCBBAAAA9864Q4456776P...",
    ".............Q8ABBCCCCCCDDDEEEEEEEEEEEDDDCCBBAAAAA986QNNPQQQPN....",
    ".............P89BBCCCCBBCCCDDDDDDDDDDDDCCBBAAAAAAA986P............",
    ".............O79BCCCCCCBBBCCCCCCDDDCCCCBBBAAAAAAA9985.............",
    "..............79BCDDDDCCBBBBBBBCCBBBBBBAAAAAAAAA9987P.............",
    "..............Q9BDDEEEDDCBBAAABBBBBAAAAA99AAAAA99986..............",
    "..............P9BDEEFFEEDCBBA99AAAA9999999999999987O..............",
    "..............P8BDEEFFFEEDCBAA98888898999999999887P...............",
    "..............N7ACDEEFEEEDCBA98777777777888888887P................",
    "...............59BCDEEEEDDBA98666655555666778776O.................",
    "...............P7ABCDEEDDCA986655QQPQ345555665P...................",
    "................48ABCCDDBA98665PON....OPQQPON.....................",
    "................O579ABBA987654O...................................",
    ".................O5689987765QO....................................",
    "...................Q6776655QO.....................................",
    "....................NPQ44QP.......................................",
    "..................................................................",
)
BOT_REST = (
    "..................................................................",
    "..................................................................",
    "..................................................................",
    "..................................................................",
    "..................................................................",
    "..................................................................",
    "..................................................................",
    "..................................................................",
    "..................................................................",
    "...............................NOOON..............................",
    "..........................NPQ99AAAAA98QPN.........................",
    "........................OQABCCDDDDDDCCBA9QO.......................",
    "......................OQABCDEEEEEEEEEEDCCB9QO.....................",
    ".....................PABDEEFFGGGGGGGFFFEDDCB9P....................",
    "...................O8BCDEFGGHHHIIIHHGGGFFEDCBA7O..................",
    "..................O9BCEEGGHIIJJJJJJIIHHGGFEDDBA8O.................",
    ".................O9BCEFGHIIJKKKKKKKJJIIHHGFFEDBA8O................",
    "................O9BCEFGHIJKKLLLMMMLLKJJIHHGFFEDBA7O...............",
    "................8BCEFGHIJKLLMMMMMMMMLKKJIHHGFEECB96...............",
    "...............PACDFGHIJKLMMMMMMMMMMMLKKJIHHGFEDCB9P..............",
    "..............O9BDEFGHJKLMMMMMMMMMMMMMLKJJIHGGFEDBA7O.............",
    "..............QACDFGHIJKMMMMMMMMMMMMMMLKKJIIHGFEDCA9Q.............",
    ".............O9BDEFGHIKLMMMMMMMMMMMMMMMLKJJIHGFFEDBA7O............",
    ".............QABDEGHIJKLMMMMMMMMMMMMMMMLKJJIHGGFEDBA8Q............",
    ".............8BCEFGHIJKLMMMMMMMMMMMMMMMLKJJIHHGFEDCB96............",
    "............O9BCEFGHIJKLMMMMMMMMMMMMMMMLKKJIIHGFEDCB97O...........",
    "............P9BCEFGHIJKLMMMMMMMMMMMMMMLLKJJIIHGFEECBA8P...........",
    "............7ABDEFGHIJKLLMMMMMMMMMMMMMLLKJJIHHGFEECBA85...........",
    "............8ABDEFGHIJJKLMMMMMMMMMMMMLLKKJJIHHGFEDCBA86...........",
    "............8ABDEFGHIIJKLLMMMMMMMMMMMLLKJJIIHHGFEDCBA86...........",
    "...........N8ABDEFGHIIJKLLMMMMMMMMMMMLLKKJIIHHGFEDDBA86N..........",
    "...........O8ABDEFGHHIJKKLLMMMMMMMMMLLKKJJIIHHGFEDCBA86O..........",
    "...........O7ABDEFGHHIJKKLLMMMMMMMMMLLKKJJIIHHGFEDCBA86O..........",
    "...........O7ABDEFGHHIJKKLLMMMMMMMMMLLKKJJIIHHGFEDDBA86O..........",
    "...........P69CDEFGHIIJKKLLMMMMMMMMMLLKKJJIIHHGFEDDBA85P..........",
    "...........P69CDEFGHIIJKKLLMMMMMMMMMLLKKJJIIHHGFEDDBA75P..........",
    "..........NQ58CDEFGHIIJKKLLMMMMMMMMMLLKKJJIIHHGFEEDBA75QN.........",
    ".........OQ658BDEFGHIIJKKLLMMMMMMMMMLLKKJJIIHHGFEEDBA745QO........",
    "........Q77758BDEFGHIIJKKLLMMMMMMMMMLLKKJJIIHHGFEEDCA74776Q.......",
    ".......Q789857BDEFGHIIJKKLLMMMMMMMMMLLKKJJIIHHGFEEDCA658887Q......",
    "......P89AA967BDEFGHIIJKKLLMMMMMMMMMLLKKJJIIHHGFEEDC96589987P.....",
    "......69AABA67BDEFGHIIJKKLLMMMMMMMMMLLKKJJIIHHGFEEDC966999985.....",
    ".....O8AAAB967BDEFGHIIJKKLLMMMMMMMMMLLKKJJIIHHGFFEDC965899997O....",
    ".....P9BBBBA67ADEFGHIIJKKLLMMMMMMMMMLLKKJJIIHHGFFEDC9669A99A8P....",
    ".....6ABBBCA77ADEFGHIIJKKLLMMMMMMMMMLLKKJJIIHHGFFEDC9669AAAA95....",
    "....N9BCCCCA77ADFFGHIIJKKLLMMMMMMMMMLLKKJJIIHHGGFEDC9669BAABA8N...",
    "....PACDDCCB77ADFFGHIIJKKLLMMMMMMMMMLLKKJJIIHHGGFEDC9669BABBB9P...",
    "....QBDEDCCB77ADFFGHIJJKKLLMMMMMMMMMLLKKJJIIHHGGFEDC966ABBCCCAQ...",
    "....9CEFECBB77ADFFGHIJJKKLLMMMMMMMMMLLKKKJIIHHGGFEDC967ABBCDDB8...",
    "...OAEFFECBB77AEFGGHIJJKKLMMMMMMMMMMLLKKKJIIHHGGFEDC967ABBCDDC9O..",
    "...QCFGGEBBB77BEGGHIIJJKKLLMMMMMMMMMLLKKJJIIHHGGFFEDA66ABBDEEDBQ..",
    "...ADGHHEBBB77BEGHIJJJJJKKLLLMMMMLLLLKKKJJIIHHHHGFEDA76ABBDEEEC8..",
    "..OBFHIHEBBB78CFGIJJKJJJJKKLLLLLLLLKKKKJJIIHHIIHHGFDA769BCEFFFEAO.",
    "..PCFHHGEBAB68CFHIKKKKKJJJKKKKKKKKKKKJJJIIIIIIIIHGFEB75ABBDFFFEAP.",
    "..QBFGGFCAAA58DGHJLLLLKJJJJJKKKKKKKJJJJIIIIIIJJJIHGEB759AACEFFDAQ.",
    "..PAEFEDB99959EGIKLMMLLKJIJJJJJJJJJJJJIIIHIIJJJJIIGFC84999BDEDC9P.",
    "..O9CDDCA8885AEGJKLMMLLKJIIIIJJJJJJIIIIHHIIJJKKJJIHFD94888ABCCB8O.",
    "...59BBA87775BEHJKLMMLKKJIIIIIIIIIIIIIHHHIIJJKKKJIHFD947788AAA96..",
    "...O689876666BEHIKLLLLKJJIIHHHIIIIHHHHHGHIIJJKKJJIHFD9566678887O..",
    "....P56655545BEGIJKKKKJJIIHHHHHHHHHHHGGGHHIIJJJJIHGFC955555676P...",
    ".....OQ5444Q4ADFHIIJJJIIIHHGGGGGGGGGGGGGGHHIIIIIHHFEB84Q4455QO....",
    "............P9CEGHHIIIHHHGGGFFFFFFFFFFFFGGHHHHHHGGEDA8P...........",
    "............O7ACEFGGGGGGGGFFEEEDDDDDDDDEFFGGGGGGFEDB97O...........",
    ".............Q8ACDEFFFFFFFEDDCCCCCCCCCCDEEFFFFEEDDB98Q............",
    ".............O58ABCDDDDDDCBCBBBBBBBBBBBBBCDDDDDCCA986O............",
    "..............O579AABBBBBBA9999999999999AABBBBAA9986O.............",
    "...............O5678999A998888777777778889999998876O..............",
    "................N466778777777777777777776777887766N...............",
    ".................NQ56666666656554445665666666766QN................",
    "...................P5555555548ABCCCCB9455555666P..................",
    "....................O555455568ABCCCCA964555566O...................",
    "......................P44455689ABCCBA9755555P.....................",
    "........................PQ456799AAA997554QP.......................",
    "..........................NPQ455555554QPN.........................",
    "................................NNN...............................",
)

EYE_NORMAL = (
    "......RRRRR...........RRRRR.....",
    ".....RSTTTSRR.......RRSTTTSR....",
    "....RSTUUUTSR.......RSTUUUTSR...",
    "....RTUXXXUTSR.....RSTUXXXUTR...",
    "....RTXXXXXUSR.....RSUXXXXXTR...",
    "....RTXXXXXUSR.....RSUXXXXXTR...",
    "....RTXXXXXUSR.....RSUXXXXXTR...",
    "....RTWWWWWUSR.....RSUWWWWWTR...",
    "....RTWWWWWUSR.....RSUWWWWWTR...",
    "....RTVVVVVUSR.....RSUVVVVVTR...",
    "....RTVVVVVUSR.....RSUVVVVVTR...",
    "....RTVVVVVUSR.....RSUVVVVVTR...",
    "....RTVVVVVUSR.....RSUVVVVVTR...",
    "....RTVVVVVUSR.....RSUVVVVVTR...",
    "....RTVVVVVUSR.....RSUVVVVVTR...",
    "....RTVVVVVUSR.....RSUVVVVVTR...",
    "....RTVVVVVUSR.....RSUVVVVVTR...",
    "....RTUVVVUTSR.....RSTUVVVUTR...",
    "....RSTUUUTSR.......RSTUUUTSR...",
    ".....RSTTTSRR.......RRSTTTSR....",
)
EYE_HALF = (
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "......RRSRRR.........RRRSRR.....",
    ".....RSTTTTRR.......RRTTTTSR....",
    "....RSTUXUUTR.......RTUUXUTSR...",
    "....RTUXXXXTSR.....RSTXXXXUTR...",
    "....RTXXXXXUSR.....RSUXXXXXTR...",
    "....RTXXXXXUSR.....RSUXXXXXTR...",
    "....RTXXXXXUSR.....RSUXXXXXTR...",
    "....RTWWWWWUSR.....RSUWWWWWTR...",
    "....RTUWWWWUSR.....RSUWWWWUTR...",
    "....RTUVVVUTSR.....RSTUVVVUTR...",
    "....RSTUUUTSR.......RSTUUUTSR...",
    ".....RSSTTSR.........RSTTSSR....",
    "......RRRRR...........RRRRR.....",
    "................................",
    "................................",
)
EYE_BLINK = (
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "....SSSSSSSSS.......SSSSSSSSS...",
    "...STVVVVVVVTS.....STVVVVVVVTS..",
    "...STVVVVVVVTS.....STVVVVVVVTS..",
    "....STTTTTTTSS.....SSTTTTTTTS...",
    ".....SSSSSSSS.......SSSSSSSS....",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
)
EYE_HAPPY = (
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    ".......SSS.............SSS......",
    ".....SSTTTSS.........SSTTTSS....",
    "....STTVVVVTS.......STVVVVTTS...",
    "...SSVVVTTVVTS.....STVVTTVVVSS..",
    "...STVTSSSTVVS.....SVVTSSSTVTS..",
    "...STVTS..SVVTS...STVVS..STVTS..",
    "..YYYY.....................YYYY.",
    ".YYYYYY...................YYYYYY",
    ".YYYYYYY.................YYYYYYY",
    ".YYYYYYY.................YYYYYYY",
    "..YYYYY...................YYYYY.",
    "...YYY.....................YYY..",
    "................................",
)
EYE_THINK = (
    "......RRRRR.....................",
    ".....RSTTTSRR...................",
    "....RSTUUUTSR...................",
    "....RTUXXXUTSR..................",
    "....RTXXXXXUSR........RRRRR.....",
    "....RTXXXXXUSR.......RSSTSRR....",
    "....RTXXXXXUSR......RSTUUUTSR...",
    "....RTWWWWWUSR......STUWWWUTR...",
    "....RTWWWWWUSR.....RSUWWWWUTR...",
    "....RTVVVVVUSR.....RSUVVVVVTR...",
    "....RTVVVVVUSR.....RSUVVVVVTR...",
    "....RTVVVVVUSR.....RSUVVVVVTR...",
    "....RTVVVVVUSR.....RSUVVVVVTR...",
    "....RTVVVVVUSR.....RSUVVVVVTR...",
    "....RTVVVVVUSR.....RSUVVVVVTR...",
    "....RTVVVVVUSR.....RSTUVVVUTR...",
    "....RTVVVVVUSR......RSTUUUTSR...",
    "....RTUVVVUTSR.......RSTTTSR....",
    "....RSTUUUTSR.........RRRRR.....",
    ".....RSTTTSRR...................",
)
EYE_SLEEP = (
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "...STVTS..SVVS.....SVVS..STVTS..",
    "...STVTSSSTVTS.....STVTSSSTVTS..",
    "...SSVVTTTVVTS.....STVVTTTVVSS..",
    "....STVVVVVTS.......STVVVVVTS...",
    ".....SSTTTSS.........SSTTTSS....",
    ".......SSSS...........SSSS......",
    "................................",
    "................................",
    "................................",
    "................................",
)
EYE_PARTY = (
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
    "..VVVVVVVVVVVVVVVVVVVVVVVVVVVVV.",
    "VVVUUUUUUUUUUUUUUUUUUUUUUUUUUUVV",
    "VUUUUUUrrrrrrrrrttttttttttUUUUUU",
    "VUUUUUUrrrrrrrrrttttttttttUUUUUU",
    "VUUUUUUrrrrrrrrrttttttttttUUUUUU",
    "VUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUU",
    "VUUUUUUUUUUUUUUUUUUUUUUUUUUUUUUU",
    "VVUUUUUUUUUUUUUUUUUUUUUUUUUUUUUV",
    ".VVVUUUUUUUUUUUUUUUUUUUUUUUUUVVV",
    "..VVVVVVVVVVVVVVVVVVVVVVVVVVVVV.",
    "................................",
    "................................",
    "................................",
    "................................",
    "................................",
)

PROP_COFFEE_0 = (
    "................................",
    "............zzz.................",
    "............!!!.................",
    "...........zz.zz................",
    "..........!!...!!...............",
    ".........zz.....zz..............",
    ".........!!.....!!..............",
    "......BGHJcdddddcDB84...........",
    "......BGddeeeeeeedd84...........",
    "......BGcddeeeeeddc84...........",
    "......BGHJKLLKJIGDBIIBB.........",
    "......BGHJKLLKJIGDIIIIIB........",
    "....GIHGHJKLLKJIGDBBBBIIB.......",
    "...JKLKJHDhhhhhhggBff.BIB.......",
    "..IKLMLKIGBhhhhhggfff.BII.......",
    ".EJLLMLKIGChhhhhggfff.BII.......",
    ".EIKLLKJIFChhhhhggBffBBIB.......",
    ".BGIJJJIGEALLKJIGDIIBIIIB.......",
    "..DGHHGFEB6LLKJIGDIIIIBB........",
    "...CDEDCA6KLLKJIGDBBBB..........",
    "....6886HJKLLKJIGDB84...........",
    "........HJKLLKJIGDB.............",
    "................................",
    "................................",
)
PROP_COFFEE_1 = (
    "................................",
    "...........zz.zz................",
    "..........!!...!!...............",
    ".........zz.....zz..............",
    ".........!!.....!!..............",
    "..........zz...zz...............",
    "...........!!.!!................",
    "......BGHJcdddddcDB84...........",
    "......BGddeeeeeeedd84...........",
    "......BGcddeeeeeddc84...........",
    "......BGHJKLLKJIGDBIIBB.........",
    "......BGHJKLLKJIGDIIIIIB........",
    "....GIHGHJKLLKJIGDBBBBIIB.......",
    "...JKLKJHDhhhhhhggBff.BIB.......",
    "..IKLMLKIGBhhhhhggfff.BII.......",
    ".EJLLMLKIGChhhhhggfff.BII.......",
    ".EIKLLKJIFChhhhhggBffBBIB.......",
    ".BGIJJJIGEALLKJIGDIIBIIIB.......",
    "..DGHHGFEB6LLKJIGDIIIIBB........",
    "...CDEDCA6KLLKJIGDBBBB..........",
    "....6886HJKLLKJIGDB84...........",
    "........HJKLLKJIGDB.............",
    "................................",
    "................................",
)
PROP_LAPTOP_0 = (
    "..............o......o..........",
    ".............o......o......o....",
    "............o......o......o.....",
    "...........o......o......o......",
    "..............llllllllllllllllll",
    ".............kkmmmmmmmmmmmmmmmmm",
    ".............kmmonmnonmnonmnommk",
    ".............kmmmmmmmmmmmmmmmmmk",
    "............kkmmmmmmmmmmmmmmmmmk",
    "............kmmmonomonomonommmkk",
    "............kmmmmmmmmmmmmmmmmmk.",
    "...........kkmmmmmmmmmmmmmmmmmk.",
    "...........kmmonmnonmnonmnmmmk..",
    ".........HIHFmmmmmmmmmmmmmmmmk..",
    "..GJJIHFIJJIHEmmmmmmmmmmmmmmkk..",
    "..IJJJIGCJJIHFBnomonomonommmk...",
    ".GIJJIHFCIIHGEBkkkkkkkkkkkkkk...",
    ".FHIHHGEBHHGEC9llllllllllllll...",
    ".CFGGFEC9FEECA6jjjjjjjjjjjjjj...",
    "..BDDCB96BBA96iiiiiiiiiiiiiii...",
    "...89876..66....................",
    "................................",
    "................................",
    "................................",
)
PROP_LAPTOP_1 = (
    ".............o......o......o....",
    "............o......o......o.....",
    "...........o......o......o......",
    "..........o......o......o.......",
    "..............llllllllllllllllll",
    ".............kkmonomonomonomommm",
    ".............kmmmmmmmmmmmmmmmmmk",
    ".............kmmmmmmmmmmmmmmmmmk",
    "............kkmnmnonmnonmnonmmmk",
    "............kmmmmmmmmmmmmmmmmmkk",
    "............kmmmmmmmmmmmmmmmmmk.",
    "...GIHF....kkmonomonomonomommmk.",
    "..IJJJHFB..kmmmmmmmmmmmmmmmmmk..",
    ".FIJJJHGD..kmmmmmmmmmmmmmmmmmk..",
    ".GIIIIHFC.kkmnmnonmnonmnonmmkk..",
    ".EGHHGFDA.kmmmmmmmmmmmmmmmmmk...",
    ".9EFFEDB8JJIGDkkkkkkkkkkkkkkk...",
    "..9BBB97JJJIHFBllllllllllllll...",
    "...j666HJJJIGEBjjjjjjjjjjjjjj...",
    "...iiiiGHIHHFDAiiiiiiiiiiiiii...",
    ".......DFGFFDB8.................",
    "........CDDCA8..................",
    ".........8986...................",
    "................................",
)
PROP_BULB = (
    "................................",
    ".....................r.r.r.r....",
    "....................r.qqqq..r...",
    "...................rqqrrrrqq.r..",
    "..................rqqssrrrrqq.r.",
    ".................r.qsssssrrrq...",
    "..................qrssssssrrrqr.",
    ".................rqrrssssssrrq..",
    "..................qrrssssssrrqr.",
    ".................rqrrrssssrrrq..",
    "...................qrrrssrrrq.r.",
    ".................r.qqrrrrrrqqr..",
    "..................r.qqrrrrqqr...",
    "...................r.kqqqqkr....",
    "....................rkkkkkk.....",
    "...GIIGD..............jjjj......",
    "..IJJJIGD.............jjjj......",
    ".FIJJJIGE9......................",
    ".GIJIIHFD9......................",
    ".EGHHHGEC8......................",
    ".BEFFFDC96......................",
    "..ACCCB96.......................",
    "...68866........................",
    "................................",
)

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
FONT_6X8_BOLD = {
    "A": ('011110', '110011', '110011', '110011', '111111', '110011', '110011', '110011'),
    "B": ('111110', '110011', '110011', '111110', '110011', '110011', '110011', '111110'),
    "C": ('011111', '110000', '110000', '110000', '110000', '110000', '110000', '011111'),
    "D": ('111110', '110011', '110011', '110011', '110011', '110011', '110011', '111110'),
    "E": ('111111', '110000', '110000', '111110', '110000', '110000', '110000', '111111'),
    "F": ('111111', '110000', '110000', '111110', '110000', '110000', '110000', '110000'),
    "G": ('011111', '110000', '110000', '110111', '110011', '110011', '110011', '011111'),
    "H": ('110011', '110011', '110011', '111111', '110011', '110011', '110011', '110011'),
    "I": ('011110', '001100', '001100', '001100', '001100', '001100', '001100', '011110'),
    "J": ('001111', '000110', '000110', '000110', '000110', '110110', '110110', '011100'),
    "K": ('110011', '110110', '111100', '111000', '111100', '110110', '110011', '110011'),
    "L": ('110000', '110000', '110000', '110000', '110000', '110000', '110000', '111111'),
    "M": ('100001', '110011', '111111', '101101', '100001', '100001', '100001', '100001'),
    "N": ('110001', '111001', '111101', '110111', '110011', '110001', '110001', '110001'),
    "O": ('011110', '110011', '110011', '110011', '110011', '110011', '110011', '011110'),
    "P": ('111110', '110011', '110011', '111110', '110000', '110000', '110000', '110000'),
    "Q": ('011110', '110011', '110011', '110011', '110011', '110111', '110011', '011111'),
    "R": ('111110', '110011', '110011', '111110', '111100', '110110', '110011', '110011'),
    "S": ('011111', '110000', '110000', '011110', '000011', '000011', '110011', '011110'),
    "T": ('111111', '001100', '001100', '001100', '001100', '001100', '001100', '001100'),
    "U": ('110011', '110011', '110011', '110011', '110011', '110011', '110011', '011110'),
    "V": ('110011', '110011', '110011', '110011', '110011', '011110', '001100', '001100'),
    "W": ('100001', '100001', '100001', '100001', '101101', '111111', '110011', '100001'),
    "X": ('110011', '110011', '011110', '001100', '001100', '011110', '110011', '110011'),
    "Y": ('110011', '110011', '011110', '001100', '001100', '001100', '001100', '001100'),
    "Z": ('111111', '000011', '000110', '001100', '011000', '110000', '110000', '111111'),
    "0": ('011110', '110011', '110111', '110111', '111011', '111011', '110011', '011110'),
    "1": ('001100', '011100', '111100', '001100', '001100', '001100', '001100', '011110'),
    "2": ('011110', '110011', '000011', '000110', '001100', '011000', '110000', '111111'),
    "3": ('111110', '000011', '000011', '011110', '000011', '000011', '110011', '011110'),
    "4": ('110011', '110011', '110011', '111111', '000011', '000011', '000011', '000011'),
    "5": ('111111', '110000', '110000', '111110', '000011', '000011', '110011', '011110'),
    "6": ('011110', '110000', '110000', '111110', '110011', '110011', '110011', '011110'),
    "7": ('111111', '110011', '000011', '000110', '001100', '001100', '001100', '001100'),
    "8": ('011110', '110011', '110011', '011110', '110011', '110011', '110011', '011110'),
    "9": ('011110', '110011', '110011', '011111', '000011', '000011', '110011', '011110'),
    "!": ('001100', '001100', '001100', '001100', '001100', '000000', '001100', '001100'),
    "?": ('011110', '110011', '000011', '000110', '001100', '000000', '001100', '001100'),
    ".": ('000000', '000000', '000000', '000000', '000000', '000000', '011100', '011100'),
    ",": ('000000', '000000', '000000', '000000', '000000', '001100', '001100', '011000'),
    "-": ('000000', '000000', '000000', '111111', '000000', '000000', '000000', '000000'),
    "+": ('000000', '001100', '001100', '111111', '001100', '001100', '000000', '000000'),
    "/": ('000011', '000110', '001100', '001100', '011000', '011000', '110000', '000000'),
    ":": ('000000', '001100', '001100', '000000', '000000', '001100', '001100', '000000'),
    "~": ('000000', '000000', '011101', '110111', '100010', '000000', '000000', '000000'),
    "%": ('110011', '110110', '001100', '001100', '011000', '011011', '110011', '000000'),
    "#": ('010100', '111110', '010100', '010100', '111110', '010100', '000000', '000000'),
    ">": ('110000', '011000', '001100', '000110', '001100', '011000', '110000', '000000'),
    "<": ('000011', '000110', '001100', '011000', '001100', '000110', '000011', '000000'),
    "_": ('000000', '000000', '000000', '000000', '000000', '000000', '000000', '111111'),
    " ": ('000000', '000000', '000000', '000000', '000000', '000000', '000000', '000000'),
}

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
DEFAULT_PHRASES = {
    "CODING":   ("DEEP WORK", "LGTM!", "SHIP IT!", "TYPING...", "0 BUGS?", "CLEAN CODE"),
    "COFFEE":   ("NEED COFFEE", "SIPPING~", "CAFFEINE+", "BRB COFFEE", "HOT BREW!"),
    "THINKING": ("HMM...", "WAIT WTF?", "BIG BRAIN", "OTF MODE", "LET ME SEE", "WHY THO?"),
    "CHILL":    ("VIBING~", "CHILL MODE", "COZY AF", "LOFI BEAT", "RESTING"),
    "SLEEP":    ("ZZZ...", "SLEEP MODE", "DREAMING~", "AFK ZZZ"),
    "OVERLOAD": ("WTF?!", "CPU 99%!", "SEGFAULT!", "PANIC!!", "HOT CPU!"),
    "PARTY":    ("HELL YEAH!", "DEPLOYED!", "GG EZ!", "10X VIBE!"),
}

STATE_TO_THEME = {
    "CODING":   "CYBER",
    "COFFEE":   "TEAL",
    "THINKING": "VIOLET",
    "CHILL":    "EMERALD",
    "SLEEP":    "INDIGO",
    "OVERLOAD": "CRIMSON",
    "PARTY":    "GOLD",
}

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

    if "\n" in serial_buf:
        lines = serial_buf.split("\n")
        serial_buf = lines[-1]
        for line in lines[:-1]:
            line = line.strip()
            if not line:
                continue
            kv = {}
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
