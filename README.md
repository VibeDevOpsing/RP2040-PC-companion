# 🐾 RP2040-Zero 3D Grok Bot Desk Companion

An expressive, **3D volumetric raymarched desk companion** powered by a **Waveshare RP2040-Zero** and a **0.96" ST7735R IPS display (160×80)**, communicating via USB serial with a cross-platform companion daemon for macOS, Linux, and Windows.

Featuring smooth **Signed Distance Field (SDF) 3D raymarched porcelain-pearl rendering**, sub-pixel anti-aliasing, hardware-composited `displayio.TileGrid` layers (~40 FPS), animated interactive props (3D Coffee Mug, Aluminum Laptop, Idea Lightbulb), and a **high-contrast 6×8 bold comic callout bubble**, Grok Bot acts as an expressive desktop companion reacting in real time to your active workflows, CPU load, Pomodoro stamina, and idle states.

---

## ✨ Features & Architecture

```mermaid
flowchart LR
    subgraph Host ["🖥️ Cross-Platform Host Companion (host_companion.py)"]
        Sensors["Fast Native Sensors (1.5s)<br/>• Frontmost App & Window Title<br/>• CoreGraphics / xprintidle / win32 Idle Detection<br/>• CPU Load & Pomodoro Stamina<br/>• Active Terminal & Dev Process Context"]
        Timeline["Activity Timeline<br/>• Window switches & dwell tracking<br/>• Recent status & thought rotation"]
        Reflex["⚡ Reflex Engine<br/>Instant state & safety classification"]
    end

    subgraph RP2040 ["👾 RP2040-Zero + ST7735R (code.py)"]
        Backdrop["🌌 3D Studio Velvet Backdrop<br/>Matte horizon & concentric contact shadow"]
        Bot["🤖 66x75 3D Raymarched Grok Bot<br/>• 20 porcelain shading steps<br/>• 4 walking / sitting / idle poses<br/>• 7 anti-aliased 3D eye expressions"]
        Props["☕ 3D Volumetric Props<br/>Coffee mug + steam, laptop, idea bulb"]
        Bubble["💬 6x8 Bold Comic Callout Bubble<br/>Ultra-crisp 2px stems, rock-steady layout,<br/>rotates live contextual thoughts every 4.2s"]
        LED["🌈 Onboard NeoPixel (GP16)<br/>State-synced organic pulsing"]
    end

    Sensors --> Timeline
    Sensors --> Reflex
    Timeline --> Reflex
    Reflex -->|Serial 115200 (STATE:..|MSG:..)| RP2040
```

### States, Props & Lighting Themes

Grok Bot moves freely across the screen, adapting its body pose, lighting tint, interactive props, and callout bubble:

| State | Action & Props | Eye Expression | Studio Lighting Theme | Context / Trigger |
| :--- | :--- | :--- | :--- | :--- |
| `CODING` | Typing on 3D Aluminum Laptop with neon code | Focused capsule eyes (`NORMAL`) | `CYBER` (Cool Studio White-Blue) | Active coding in IDEs, editors, or terminal work |
| `COFFEE` | Walking & pausing to sip 3D Ceramic Mug with steam | Happy arches (`HAPPY ^ ^`) + Rosy Blush | `TEAL` (Aqua Studio Pearl) | Light browsing, coffee break, or long work streak |
| `THINKING` | Pacing with chin-hand & floating glowing lightbulb | Inquisitive squint (`THINK`) | `VIOLET` (Lavender-Pearl) | Reading docs, planning, research, or short pauses |
| `CHILL` | Sitting cozily on the floor with warm mug nearby | Relaxed blinking / happy eyes | `EMERALD` (Mint Studio Pearl) | Listening to music, watching video, or resting |
| `SLEEP` | Sitting melted on the floor resting | Closed sleep arcs (`SLEEP u u`) | `INDIGO` (Starlight Sleep Pearl) | System idle (`> 3 min`), user AFK |
| `OVERLOAD` | Jittering panic animation + alert outline | High-alert expression | `CRIMSON` (Alert Rose-Pearl) | Heavy CPU load (`> 85%`), compiler errors, crashes |
| `PARTY` | Energetic bouncing across the floor | Sleek 3D Cyber-Visor shades | `GOLD` (Warm Solar Cream-Pearl) | Deploying, merging PRs, build successes |

---

## 🔌 Hardware & Wiring

- **Microcontroller:** Waveshare RP2040-Zero (with onboard WS2812 RGB NeoPixel on `GP16`)
- **Display:** 0.96" ST7735R IPS LCD (`160×80`, SPI interface)

| Display Pin | RP2040-Zero Pin | Function |
| :--- | :--- | :--- |
| `VCC` | `3V3` | 3.3V Power |
| `GND` | `GND` | Ground |
| `SCL` / `SCK` | `GP2` | SPI Clock |
| `SDA` / `MOSI` | `GP3` | SPI Data (MOSI) |
| `RES` / `RST` | `GP4` | Display Reset |
| `DC` | `GP1` | Data / Command Select |
| `CS` | `GP0` | Chip Select |
| `BLK` / `BL` | `GP5` | Backlight Control |
| *(Onboard LED)* | `GP16` | WS2812 RGB NeoPixel Mood Light |

---

## 🖥️ Multi-OS Native Support (macOS, Linux, Windows)

`host_companion.py` runs natively across **macOS**, **Linux**, and **Windows** with automatic OS detection:

| Feature | 🍎 macOS (`darwin`) | 🐧 Linux (`linux`) | 🪟 Windows (`win32`) |
| :--- | :--- | :--- | :--- |
| **USB Serial Port** | USB VID `0x2E8A` / `/dev/cu.usbmodem*` | USB VID `0x2E8A` / `/dev/ttyACM*` | USB VID `0x2E8A` / `COM*` |
| **Active Window & App** | `osascript` (`System Events`) | `hyprctl` (Hyprland), `swaymsg` (Sway), `xdotool`/`xprop` (X11) | `ctypes.windll.user32` (`GetForegroundWindow`) |
| **Idle Time Sensor** | `CoreGraphics` ctypes / `IOHIDSystem` | `xprintidle` (X11) / `gdbus` (`Mutter.IdleMonitor`) | `ctypes.windll.user32.GetLastInputInfo` |
| **CPU Usage** | `psutil` / `os.getloadavg()` | `psutil` / `os.getloadavg()` | `psutil` |

---

## 🚀 Quick Start

### 1. Flash the RP2040-Zero Firmware
1. Install **CircuitPython 9.x** for **Waveshare RP2040-Zero** (e.g. `adafruit-circuitpython-waveshare_rp2040_zero-en_US-9.2.4.uf2`).
2. Make sure `adafruit_st7735r` is in `CIRCUITPY/lib/`.
3. Copy [`code.py`](file:///Users/booo/projects/embeded/esp32-activity-pet/code.py) to the root of your `CIRCUITPY` drive.

### 2. Run the Host Daemon

**Running from Python source (macOS / Linux / Windows):**
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
python host_companion.py
```

**Install as an Automatic Background Service (macOS `launchd` / Linux `systemd`):**
```bash
# Starts automatically on login and restarts if unplugged/replugged:
python3 host_companion.py --install-service

# To remove the background service later:
python3 host_companion.py --uninstall-service
```

**Running in Docker (`Dockerfile` + `docker-compose.yml`):**
```bash
docker compose up -d --build
```

#### Useful CLI Flags:
- `--port /dev/ttyACM0` (or `--port COM3`) — Override automatic serial port detection.
- `--once` — Run a single sensor cycle and exit (great for testing).
- `--no-vision` — Disable screenshot capture in background.

---

## 🛠️ Offline Assets & Firmware Generation

To regenerate the 3D raymarched tiles, palette, and firmware:

```bash
python3 tools/generate_3d_firmware.py -o code.py
```

This runs the analytical Signed Distance Field (SDF) raymarcher and builds `code.py` with pre-computed sprite matrices and font lookups.

---

## ⚙️ Testing

Run the test suite covering protocol encoding, thought formatting, bubble layout, and asset integrity:

```bash
python3 -m unittest discover -s tests
```

---

## 🤝 Contributing

Contributions of all kinds are welcome! Feel free to open an issue or pull request for new poses, animations, sensors, or hardware platform ports.
