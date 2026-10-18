#!/usr/bin/env python3
"""
Cross-Platform Host Companion Daemon (macOS, Linux, Windows)
for Waveshare RP2040-Zero 8-Bit Snow Bear / Yeti Desk-Buddy.

Architecture:
  - Purely visual 8-bit display (zero text clutter): thoughts and context are rendered
    as animated pixel art inside the Dynamic Wall Painting (`POSTER`) + Time-of-Day Mountain Landscape.
  - Multi-OS Native Sensors (macOS, Linux X11/Wayland, Windows):
    * Auto-detects RP2040 USB Serial (`0x2E8A` VID or `/dev/cu.usbmodem*`, `/dev/ttyACM*`, `COM*`)
    * Frontmost application & window title
    * System user idle time (keyboard/mouse inactivity)
    * CPU load & Pomodoro stamina energy
    * Silent downscaled screenshot capture for Vision LLMs
  - Hybrid Brain:
    * Tier 1 (Reflexes, every 1.5s): Instant reaction to app switches, CPU spikes, idle sleep.
    * Tier 2 (LM Studio Subconscious, every 25s): Queries local 1B-2B VLM/LLM (e.g. `google/gemma-4-e2b`).
"""

import argparse
import base64
import ctypes
import glob
import io
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Optional, Dict, Any, Tuple

try:
    import serial
    import serial.tools.list_ports
except ImportError:
    print("Please install pyserial: pip install -r requirements.txt")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("Please install requests: pip install -r requirements.txt")
    sys.exit(1)

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    from PIL import Image, ImageGrab
    HAS_PIL = True
except ImportError:
    HAS_PIL = False


# ─── PLATFORM & CONFIGURATION ───────────────────────────────────────────────
OS_SYSTEM = platform.system().lower()  # 'darwin', 'linux', 'windows'
IN_DOCKER = os.path.exists("/.dockerenv") or os.environ.get("IN_DOCKER") == "1"
DEFAULT_LMSTUDIO_URL = os.environ.get(
    "LMSTUDIO_URL",
    "http://host.docker.internal:1234/v1" if IN_DOCKER else "http://127.0.0.1:1234/v1",
)
DEFAULT_SERIAL_PORT = os.environ.get("DESK_BUDDY_PORT", None)
REFLEX_INTERVAL_SEC = float(os.environ.get("REFLEX_INTERVAL_SEC", "1.5"))
LLM_INTERVAL_SEC = float(os.environ.get("LLM_INTERVAL_SEC", "25.0"))
IDLE_SLEEP_THRESHOLD_SEC = 180.0   # 3 min idle -> sleeping
IDLE_REST_THRESHOLD_SEC = 60.0     # 1 min idle -> resting/recharging energy

# RP2040 / CircuitPython USB Vendor IDs (Raspberry Pi = 0x2E8A, Adafruit = 0x239A)
RP2040_USB_VIDS = {0x2E8A, 0x239A}

VALID_MOODS = {
    "focused", "happy", "curious", "vibing", "bored", "tired", "sleepy", "stressed", "panicking"
}
VALID_POSTERS = {
    "code_matrix",    # Falling green matrix code + </> (coding / terminal)
    "bug_alert",      # Crawling pixel beetle + ! (debugging / errors / stackoverflow)
    "coffee_need",    # Steaming coffee cup (tired / needs break / long streak)
    "brain_idea",     # Glowing lightbulb with sparks (research / docs / AI chat / planning)
    "fire_panic",     # Roaring flames (high CPU / heavy build / deadline stress)
    "music_eq",       # Neon equalizer bars (music / audio / vibing)
    "chill_play",     # Play button screen (YouTube / video / social media / gaming)
    "rocket_launch",  # Launching pixel rocket (shipping / git commit / high flow)
    "heart_love",     # Beating pixel heart with sparkles (happy / positive / chill)
    "zzz_dream",      # Moon & drifting clouds (sleeping / AFK)
    "zen_mountain",   # Mt. Fuji sunset landscape (calm browsing / reading)
}

CODING_APPS = {
    "code", "cursor", "windsurf", "zed", "xcode", "pycharm", "intellij",
    "webstorm", "clion", "goland", "sublimetext", "neovide", "nvim", "vim",
    "emacs", "android studio", "devenv", "rider", "fleet"
}
TERMINAL_APPS = {
    "terminal", "iterm2", "warp", "alacritty", "kitty", "ghostty", "wezterm",
    "konsole", "gnome-terminal", "xfce4-terminal", "foot", "tilix",
    "windowsterminal", "powershell", "cmd", "wt"
}
MUSIC_APPS = {
    "spotify", "music", "podcasts", "vlc", "iina", "rhythmbox", "elisa",
    "clementine", "strawberry", "audacious", "foobar2000", "aimp"
}
DISTRACTION_KEYWORDS = {
    "youtube", "netflix", "reddit", "twitter", "x.com", "tiktok", "instagram",
    "twitch", "facebook", "9gag", "steam"
}
DEBUG_KEYWORDS = {
    "error", "exception", "traceback", "failed", "panic", "segfault",
    "bug", "issue", "stack overflow", "debugger", "crash"
}
IDEA_KEYWORDS = {
    "claude", "gemini", "chatgpt", "lm studio", "docs", "documentation",
    "notion", "obsidian", "figma", "github", "readme", "architecture"
}
ROCKET_KEYWORDS = {
    "pull request", "deploy", "release", "build succeeded", "passed", "merged"
}


# ─── MULTI-OS SERIAL PORT MANAGER ───────────────────────────────────────────
class BoardSerial:
    def __init__(self, port_override: Optional[str] = None, baudrate: int = 115200):
        self.port_override = port_override or DEFAULT_SERIAL_PORT
        self.baudrate = baudrate
        self.ser: Optional[serial.Serial] = None
        self.port_name: Optional[str] = None
        self.last_packet: str = ""

    def find_port(self) -> Optional[str]:
        if self.port_override:
            return self.port_override

        # 1. Cross-platform USB VID/description scan via pyserial (sorted ascending so Console port *01 comes first!)
        try:
            ports = sorted(serial.tools.list_ports.comports(), key=lambda x: x.device)
            for p in ports:
                desc = f"{p.description or ''} {p.manufacturer or ''} {p.product or ''}".lower()
                if (p.vid in RP2040_USB_VIDS) or any(
                    k in desc for k in ("rp2040", "circuitpython", "pico", "waveshare")
                ):
                    return p.device
        except Exception:
            pass

        # 2. OS-specific device path fallbacks (sorted ascending)
        if OS_SYSTEM == "darwin":
            for pattern in ("/dev/cu.usbmodem*", "/dev/tty.usbmodem*"):
                matches = sorted(glob.glob(pattern))
                if matches:
                    return matches[0]
        elif OS_SYSTEM == "linux":
            for pattern in ("/dev/ttyACM*", "/dev/ttyUSB*"):
                matches = sorted(glob.glob(pattern))
                if matches:
                    return matches[0]
        elif OS_SYSTEM == "windows":
            try:
                ports = sorted(serial.tools.list_ports.comports(), key=lambda x: x.device)
                if ports:
                    return ports[0].device
            except Exception:
                pass
        return None

    def ensure_connected(self) -> bool:
        if self.ser and self.ser.is_open:
            return True
        port = self.find_port()
        if not port:
            return False
        try:
            if "://" in port:
                # Supports socket://host.docker.internal:7777 or rfc2217:// for Docker on macOS/Windows!
                self.ser = serial.serial_for_url(port, baudrate=self.baudrate, timeout=0.5)
            else:
                self.ser = serial.Serial(port, self.baudrate, timeout=0.5)
            self.port_name = port
            print(f"[Serial] Connected to RP2040-Zero on {port} ({OS_SYSTEM}{'/docker' if IN_DOCKER else ''})")
            return True
        except Exception as e:
            print(f"[Serial] Connect error on {port}: {e}")
            self.ser = None
            return False

    def send_state(
        self,
        mood: str,
        act: str,
        nrg: int,
        cpu: int,
        evt: str,
        poster: str,
        force: bool = False,
    ) -> bool:
        cur_hour = time.localtime().tm_hour
        packet = f"MOOD:{mood}|ACT:{act}|NRG:{nrg}|CPU:{cpu}|EVT:{evt}|POSTER:{poster}|HOUR:{cur_hour}\n"
        if not force and packet == self.last_packet:
            return True

        if not self.ensure_connected():
            return False

        try:
            self.ser.write(packet.encode("utf-8", errors="ignore"))
            self.ser.flush()
            self.last_packet = packet
            print(f">>> [RP2040] {packet.strip()}")
            return True
        except Exception as e:
            print(f"[Serial] Write lost ({e}), will reconnect...")
            try:
                self.ser.close()
            except Exception:
                pass
            self.ser = None
            return False


# ─── MULTI-OS SENSORS (MACOS, LINUX, WINDOWS) ───────────────────────────────
def get_active_window_info() -> Tuple[str, str]:
    """Returns (app_name, window_title) of the frontmost window across macOS, Linux, and Windows."""
    if OS_SYSTEM == "darwin":
        script = '''
        global frontApp, frontAppName, windowTitle
        set windowTitle to ""
        tell application "System Events"
            set frontApp to first application process whose frontmost is true
            set frontAppName to name of frontApp
            tell process frontAppName
                try
                    set windowTitle to name of front window
                end try
            end tell
        end tell
        return frontAppName & "|||" & windowTitle
        '''
        try:
            res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=1.5)
            if res.returncode == 0 and "|||" in res.stdout:
                app, title = res.stdout.strip().split("|||", 1)
                return app.strip(), title.strip()
        except Exception:
            pass

    elif OS_SYSTEM == "linux":
        # 1. Hyprland (Wayland)
        if os.environ.get("HYPRLAND_INSTANCE_SIGNATURE") and shutil.which("hyprctl"):
            try:
                res = subprocess.run(["hyprctl", "activewindow", "-j"], capture_output=True, text=True, timeout=1.0)
                if res.returncode == 0:
                    data = json.loads(res.stdout)
                    return str(data.get("class") or "LinuxApp"), str(data.get("title") or "")
            except Exception:
                pass

        # 2. Sway (Wayland)
        if os.environ.get("SWAYSOCK") and shutil.which("swaymsg"):
            try:
                res = subprocess.run(["swaymsg", "-t", "get_tree"], capture_output=True, text=True, timeout=1.0)
                if res.returncode == 0 and '"focused": true' in res.stdout:
                    m_app = re.search(r'"focused":\s*true.*?"app_id":\s*"([^"]+)"', res.stdout, re.DOTALL)
                    m_title = re.search(r'"focused":\s*true.*?"name":\s*"([^"]+)"', res.stdout, re.DOTALL)
                    return (m_app.group(1) if m_app else "SwayApp"), (m_title.group(1) if m_title else "")
            except Exception:
                pass

        # 3. X11 / XWayland via xdotool + xprop
        if shutil.which("xdotool"):
            try:
                wid = subprocess.run(
                    ["xdotool", "getactivewindow"], capture_output=True, text=True, timeout=1.0
                ).stdout.strip()
                if wid:
                    title = subprocess.run(
                        ["xdotool", "getwindowname", wid], capture_output=True, text=True, timeout=1.0
                    ).stdout.strip()
                    app = "X11App"
                    if shutil.which("xprop"):
                        xp = subprocess.run(
                            ["xprop", "-id", wid, "WM_CLASS"], capture_output=True, text=True, timeout=1.0
                        ).stdout
                        m = re.findall(r'"([^"]+)"', xp)
                        if m:
                            app = m[-1]
                    return app, title
            except Exception:
                pass

    elif OS_SYSTEM == "windows":
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            if hwnd:
                length = user32.GetWindowTextLengthW(hwnd)
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                title = buf.value.strip()

                pid = ctypes.c_ulong()
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                app = "WindowsApp"
                if HAS_PSUTIL and pid.value:
                    try:
                        app = psutil.Process(pid.value).name().replace(".exe", "")
                    except Exception:
                        pass
                return app, title
        except Exception:
            pass

    return "Unknown", ""


def get_system_idle_seconds() -> float:
    """Returns seconds since last keyboard/mouse input across macOS, Linux, and Windows."""
    if OS_SYSTEM == "darwin":
        try:
            res = subprocess.run(["ioreg", "-c", "IOHIDSystem"], capture_output=True, text=True, timeout=1.0)
            m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', res.stdout)
            if m:
                return int(m.group(1)) / 1_000_000_000.0
        except Exception:
            pass

    elif OS_SYSTEM == "linux":
        if shutil.which("xprintidle"):
            try:
                res = subprocess.run(["xprintidle"], capture_output=True, text=True, timeout=1.0)
                if res.returncode == 0 and res.stdout.strip().isdigit():
                    return int(res.stdout.strip()) / 1000.0
            except Exception:
                pass
        if shutil.which("gdbus"):
            try:
                res = subprocess.run(
                    [
                        "gdbus", "call", "--session",
                        "--dest", "org.gnome.Mutter.IdleMonitor",
                        "--object-path", "/org/gnome/Mutter/IdleMonitor/Core",
                        "--method", "org.gnome.Mutter.IdleMonitor.GetIdletime"
                    ],
                    capture_output=True, text=True, timeout=1.0
                )
                m = re.search(r"uint64\s+(\d+)", res.stdout)
                if m:
                    return int(m.group(1)) / 1000.0
            except Exception:
                pass

    elif OS_SYSTEM == "windows":
        try:
            class LASTINPUTINFO(ctypes.Structure):
                _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

            lii = LASTINPUTINFO()
            lii.cbSize = ctypes.sizeof(LASTINPUTINFO)
            if ctypes.windll.user32.GetLastInputInfo(ctypes.byref(lii)):
                millis = ctypes.windll.kernel32.GetTickCount() - lii.dwTime
                return max(0.0, millis / 1000.0)
        except Exception:
            pass

    return 0.0


def get_cpu_usage() -> int:
    """Returns total CPU load percentage (0..100) across macOS, Linux, and Windows."""
    if HAS_PSUTIL:
        try:
            return int(psutil.cpu_percent(interval=None))
        except Exception:
            pass
    if OS_SYSTEM in ("darwin", "linux"):
        try:
            load1, _, _ = os.getloadavg()
            cores = os.cpu_count() or 8
            return max(0, min(100, int((load1 / cores) * 100)))
        except Exception:
            pass
    return 15


def capture_downscaled_screenshot_b64(max_dim: int = 512) -> Optional[str]:
    """Captures the main screen silently and resizes to tiny JPEG for fast VLM inference on any OS."""
    # 1. Cross-platform Pillow ImageGrab (works on macOS, Windows, and Linux X11)
    if HAS_PIL:
        try:
            img = ImageGrab.grab()
            img.thumbnail((max_dim, max_dim))
            if img.mode != "RGB":
                img = img.convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=75)
            return base64.b64encode(buf.getvalue()).decode("ascii")
        except Exception:
            pass

    # 2. Native OS CLI fallbacks (zero Python imaging library required)
    tmp_jpg = os.path.join(tempfile.gettempdir(), "desk_buddy_screen.jpg")
    try:
        if OS_SYSTEM == "darwin":
            res = subprocess.run(
                ["screencapture", "-x", "-m", "-t", "jpg", tmp_jpg],
                capture_output=True, timeout=2.0
            )
            if res.returncode == 0 and os.path.exists(tmp_jpg):
                subprocess.run(["sips", "-Z", str(max_dim), tmp_jpg], capture_output=True, timeout=2.0)
                with open(tmp_jpg, "rb") as f:
                    return base64.b64encode(f.read()).decode("ascii")

        elif OS_SYSTEM == "linux":
            for cmd in (
                ["grim", "-t", "jpeg", "-q", "75", tmp_jpg],
                ["scrot", "-o", tmp_jpg],
                ["gnome-screenshot", "-f", tmp_jpg],
            ):
                if shutil.which(cmd[0]):
                    res = subprocess.run(cmd, capture_output=True, timeout=2.5)
                    if res.returncode == 0 and os.path.exists(tmp_jpg):
                        with open(tmp_jpg, "rb") as f:
                            return base64.b64encode(f.read()).decode("ascii")
    except Exception:
        return None
    finally:
        if os.path.exists(tmp_jpg):
            try:
                os.remove(tmp_jpg)
            except Exception:
                pass
    return None


# ─── LM STUDIO BRAIN (VISUAL POSTER SELECTOR) ───────────────────────────────
class LMStudioBrain:
    def __init__(self, base_url: str = DEFAULT_LMSTUDIO_URL, use_vision: bool = True):
        self.base_url = base_url.rstrip("/")
        self.use_vision = use_vision
        self.vision_supported = use_vision
        self.model_id = self._detect_model()

    def _detect_model(self) -> str:
        try:
            r = requests.get(f"{self.base_url}/models", timeout=2.0)
            if r.status_code == 200:
                models = r.json().get("data", [])
                for m in models:
                    if "gemma-4-e2b" in m.get("id", "").lower():
                        print(f"[LM Studio] Connected to model: {m['id']}")
                        return m["id"]
                if models:
                    mid = models[0]["id"]
                    print(f"[LM Studio] Detected loaded model: {mid}")
                    return mid
        except Exception:
            pass
        return "google/gemma-4-e2b"

    def analyze_context(
        self,
        app_name: str,
        window_title: str,
        activity: str,
        energy: int,
        cpu: int,
        idle_sec: float,
        work_streak_min: float,
    ) -> Optional[Dict[str, Any]]:
        """Calls local 1B-2B LLM in LM Studio to pick the Dynamic Wall Painting (`poster`), `mood`, and `event`."""
        system_prompt = (
            "You are the subconscious brain of a cozy pixel-art companion sitting in a room with a Dynamic Wall Painting. "
            "There is NO text on the display: you express all thoughts by changing the animated painting (`poster`) on the wall! "
            "Choose the best `poster` from this exact list:\n"
            "- code_matrix (writing code, terminal work, deep programming)\n"
            "- bug_alert (debugging errors, stack traces, fixing bugs, warnings)\n"
            "- coffee_need (user working too long, low energy, needs a break)\n"
            "- brain_idea (reading docs, AI brainstorming, learning, designing)\n"
            "- fire_panic (high CPU load, intense stress, heavy compilation)\n"
            "- music_eq (listening to music, Spotify, audio vibes)\n"
            "- chill_play (watching YouTube/video, gaming, social media, relaxing)\n"
            "- rocket_launch (shipping code, git push, great productive flow)\n"
            "- heart_love (happy mood, balanced energy, positive vibe)\n"
            "- zzz_dream (user is idle/AFK or sleeping)\n"
            "- zen_mountain (calm web browsing, peaceful reading)\n\n"
            "Respond ONLY with a single valid JSON object (no markdown fences):\n"
            '{"poster": "one_of_the_posters_above", '
            '"mood": "focused|happy|curious|vibing|bored|tired|stressed|panicking", '
            '"event": "none|sip_coffee|cheer", '
            '"energy_delta": 0}'
        )

        user_context = (
            f"Current System Context ({OS_SYSTEM}):\n"
            f"- Active App: {app_name}\n"
            f"- Window Title: {window_title or 'N/A'}\n"
            f"- Activity: {activity}\n"
            f"- Work Streak: {work_streak_min:.0f} mins\n"
            f"- Companion Energy: {energy}%\n"
            f"- CPU Load: {cpu}%\n"
            f"- Idle Seconds: {idle_sec:.0f}s\n"
            "Return JSON now:"
        )

        messages = [{"role": "system", "content": system_prompt}]

        img_b64 = None
        if self.use_vision and self.vision_supported and idle_sec < IDLE_SLEEP_THRESHOLD_SEC:
            img_b64 = capture_downscaled_screenshot_b64(max_dim=512)

        if img_b64:
            messages.append({
                "role": "user",
                "content": [
                    {"type": "text", "text": user_context},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}}
                ]
            })
        else:
            messages.append({"role": "user", "content": user_context})

        payload = {
            "model": self.model_id,
            "messages": messages,
            "temperature": 0.4,
            "max_tokens": 500,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "companion_reaction",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "poster": {
                                "type": "string",
                                "enum": sorted(list(VALID_POSTERS)),
                            },
                            "mood": {
                                "type": "string",
                                "enum": sorted(list(VALID_MOODS)),
                            },
                            "event": {
                                "type": "string",
                                "enum": ["none", "sip_coffee", "cheer"],
                            },
                            "energy_delta": {
                                "type": "integer",
                            },
                        },
                        "required": ["poster", "mood", "event", "energy_delta"],
                        "additionalProperties": False,
                    },
                },
            },
        }

        try:
            r = requests.post(f"{self.base_url}/chat/completions", json=payload, timeout=25.0)
            if r.status_code != 200 and img_b64:
                print(f"[LM Studio] Vision call returned {r.status_code}, falling back to fast Text-mode.")
                self.vision_supported = False
                payload["messages"] = [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_context},
                ]
                r = requests.post(f"{self.base_url}/chat/completions", json=payload, timeout=20.0)

            if r.status_code == 200:
                msg_obj = r.json()["choices"][0]["message"]
                content = (msg_obj.get("content") or "").strip()
                reasoning = (msg_obj.get("reasoning_content") or "").strip()
                content = re.sub(r"<think>.*?</think>", "", content, flags=re.DOTALL).strip()
                content = re.sub(r"<\|thought\|>.*?<\|thought\|>", "", content, flags=re.DOTALL).strip()
                m = re.search(r"\{.*?\}", content, flags=re.DOTALL)
                if not m and reasoning:
                    m = re.search(r"\{.*?\}", reasoning, flags=re.DOTALL)
                if m:
                    return json.loads(m.group(0))
                else:
                    print(f"[LM Studio] Raw output (no JSON): content={content[:80]!r}")
            else:
                print(f"[LM Studio] HTTP {r.status_code}: {r.text[:150]}")
        except Exception as e:
            print(f"[LM Studio] Warning: {e}")
        return None


# ─── TIER 1: INSTANT REFLEX CLASSIFIER ──────────────────────────────────────
def classify_reflex(app_name: str, window_title: str, idle_sec: float, cpu: int, energy: int) -> Tuple[str, str, str]:
    """
    Instant (<5ms) mapping from OS sensors to (activity, mood, wall_poster).
    """
    app_low = app_name.lower()
    title_low = window_title.lower()
    combined = f"{app_low} {title_low}"

    if idle_sec >= IDLE_SLEEP_THRESHOLD_SEC:
        return "sleeping", "sleepy", "zzz_dream"

    if cpu >= 85:
        return "debugging", "panicking", "fire_panic"

    if any(k in combined for k in DEBUG_KEYWORDS):
        return "debugging", "stressed", "bug_alert"

    if energy < 28:
        act = "coding" if any(a in app_low for a in CODING_APPS | TERMINAL_APPS) else "idle"
        return act, "tired", "coffee_need"

    if any(k in combined for k in ROCKET_KEYWORDS):
        return "coding", "happy", "rocket_launch"

    if any(a in app_low for a in MUSIC_APPS):
        return "music", "vibing", "music_eq"

    if any(k in combined for k in DISTRACTION_KEYWORDS):
        return "browsing", "bored", "chill_play"

    if any(k in combined for k in IDEA_KEYWORDS):
        act = "coding" if any(a in app_low for a in CODING_APPS) else "browsing"
        return act, "curious", "brain_idea"

    if any(a in app_low for a in CODING_APPS):
        return "coding", "focused", "code_matrix"

    if any(a in app_low for a in TERMINAL_APPS):
        return "terminal", "focused", "code_matrix"

    return "browsing", "curious", "zen_mountain"


def manage_background_service(install: bool = True) -> None:
    """Installs or removes a native OS background autostart service (macOS launchd / Linux systemd)."""
    script_path = os.path.abspath(__file__)
    python_bin = sys.executable

    if OS_SYSTEM == "darwin":
        plist_dir = os.path.expanduser("~/Library/LaunchAgents")
        plist_path = os.path.join(plist_dir, "com.deskbuddy.companion.plist")
        if not install:
            subprocess.run(["launchctl", "unload", plist_path], capture_output=True)
            if os.path.exists(plist_path):
                os.remove(plist_path)
            print("[Service] Uninstalled macOS LaunchAgent.")
            return

        os.makedirs(plist_dir, exist_ok=True)
        log_path = os.path.expanduser("~/Library/Logs/desk-buddy.log")
        plist_content = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.deskbuddy.companion</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python_bin}</string>
        <string>{script_path}</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_path}</string>
    <key>StandardErrorPath</key>
    <string>{log_path}</string>
</dict>
</plist>
"""
        with open(plist_path, "w") as f:
            f.write(plist_content)
        subprocess.run(["launchctl", "unload", plist_path], capture_output=True)
        subprocess.run(["launchctl", "load", "-w", plist_path], check=False)
        print(f"[Service] Installed & started macOS LaunchAgent: {plist_path}")
        print(f"[Service] Logs at: {log_path}")

    elif OS_SYSTEM == "linux":
        svc_dir = os.path.expanduser("~/.config/systemd/user")
        svc_path = os.path.join(svc_dir, "desk-buddy.service")
        if not install:
            subprocess.run(["systemctl", "--user", "disable", "--now", "desk-buddy.service"], capture_output=True)
            if os.path.exists(svc_path):
                os.remove(svc_path)
            print("[Service] Uninstalled Linux systemd user service.")
            return

        os.makedirs(svc_dir, exist_ok=True)
        svc_content = f"""[Unit]
Description=RP2040-Zero 8-Bit Desk-Buddy Companion Daemon
After=graphical-session.target

[Service]
ExecStart={python_bin} {script_path}
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
"""
        with open(svc_path, "w") as f:
            f.write(svc_content)
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        subprocess.run(["systemctl", "--user", "enable", "--now", "desk-buddy.service"], check=False)
        print(f"[Service] Installed & started systemd user service: {svc_path}")
    else:
        print(f"[Service] Automatic service installer is supported on macOS and Linux (current: {OS_SYSTEM}).")


def main():
    parser = argparse.ArgumentParser(description="RP2040-Zero Cross-Platform Desk-Buddy Daemon")
    parser.add_argument("--port", default=None, help="Override serial port (e.g. /dev/ttyACM0, COM3, socket://host.docker.internal:7777)")
    parser.add_argument("--lm-url", default=DEFAULT_LMSTUDIO_URL, help="LM Studio OpenAI API base URL")
    parser.add_argument("--no-vision", action="store_true", help="Use ultra-fast text-only prompts without screenshots")
    parser.add_argument("--llm-interval", type=float, default=LLM_INTERVAL_SEC, help="Seconds between LLM checks")
    parser.add_argument("--once", action="store_true", help="Run a single reflex + LLM cycle and exit")
    parser.add_argument("--install-service", action="store_true", help="Install & start background autostart service (macOS launchd / Linux systemd)")
    parser.add_argument("--uninstall-service", action="store_true", help="Remove background autostart service")
    args = parser.parse_args()

    if args.install_service:
        manage_background_service(install=True)
        return
    if args.uninstall_service:
        manage_background_service(install=False)
        return

    print("=" * 64)
    print(f"  🎨 RP2040-ZERO 8-BIT DESK-BUDDY DAEMON ({OS_SYSTEM.upper()})")
    print(f"  LM Studio API : {args.lm_url}")
    print(f"  Vision Mode   : {'Disabled (Text-only)' if args.no_vision else 'Enabled (Auto-fallback)'}")
    print("=" * 64)

    board = BoardSerial(port_override=args.port)
    brain = LMStudioBrain(base_url=args.lm_url, use_vision=not args.no_vision)

    energy = 95.0
    work_start_ts = time.time()
    last_llm_ts = 0.0
    last_energy_ts = time.time()
    last_app = ""
    last_title = ""

    current_mood = "focused"
    current_act = "coding"
    current_evt = "none"
    current_poster = "code_matrix"

    llm_mood_override: Optional[str] = None
    llm_poster_override: Optional[str] = None
    llm_override_until: float = 0.0

    try:
        while True:
            now = time.time()

            # 1. Read cross-platform OS sensors
            app_name, win_title = get_active_window_info()
            idle_sec = get_system_idle_seconds()
            cpu = get_cpu_usage()

            # 2. Update Pomodoro Energy
            dt = now - last_energy_ts
            last_energy_ts = now
            if idle_sec >= IDLE_REST_THRESHOLD_SEC:
                energy = min(100.0, energy + (dt / 60.0) * 4.0)
                if idle_sec >= IDLE_SLEEP_THRESHOLD_SEC:
                    work_start_ts = now
            else:
                energy = max(5.0, energy - (dt / 60.0) * 1.4)

            work_streak_min = max(0.0, (now - work_start_ts) / 60.0)

            # 3. Tier 1: Fast Reflex classification
            reflex_act, reflex_mood, reflex_poster = classify_reflex(
                app_name, win_title, idle_sec, cpu, int(energy)
            )
            current_act = reflex_act

            if (app_name != last_app or win_title != last_title) and app_name != "Unknown":
                if app_name != last_app:
                    llm_override_until = 0.0
                    if 30 <= energy <= 75 and current_act in ("coding", "terminal"):
                        current_evt = "sip_coffee"
                last_app = app_name
                last_title = win_title
                print(
                    f"[Reflex] App='{app_name}' Title='{win_title[:35]}' -> "
                    f"Act={reflex_act} | Poster={reflex_poster} | CPU={cpu}% | NRG={int(energy)}%"
                )

            if now < llm_override_until and reflex_act != "sleeping" and cpu < 85:
                current_mood = llm_mood_override or reflex_mood
                current_poster = llm_poster_override or reflex_poster
            else:
                current_mood = reflex_mood
                current_poster = reflex_poster

            # 4. Tier 2: LM Studio Subconscious (every N seconds)
            if now - last_llm_ts >= args.llm_interval:
                last_llm_ts = now
                res = brain.analyze_context(
                    app_name=app_name,
                    window_title=win_title,
                    activity=current_act,
                    energy=int(energy),
                    cpu=cpu,
                    idle_sec=idle_sec,
                    work_streak_min=work_streak_min,
                )
                if res:
                    new_mood = str(res.get("mood", "")).lower().strip()
                    if new_mood in VALID_MOODS:
                        llm_mood_override = new_mood
                        current_mood = new_mood

                    new_poster = str(res.get("poster", "")).lower().strip()
                    if new_poster in VALID_POSTERS:
                        llm_poster_override = new_poster
                        current_poster = new_poster

                    llm_override_until = now + 24.0

                    new_evt = str(res.get("event", "none")).lower().strip()
                    if new_evt in {"none", "sip_coffee", "cheer"}:
                        current_evt = new_evt

                    try:
                        edelta = int(res.get("energy_delta", 0))
                        energy = max(5.0, min(100.0, energy + max(-5, min(5, edelta))))
                    except Exception:
                        pass

                    print(
                        f"[LLM Painting] Poster='{current_poster}' | Mood='{current_mood}' | "
                        f"Evt='{current_evt}' | NRG={int(energy)}%"
                    )

            # 5. Send visual state packet to RP2040-Zero
            board.send_state(
                mood=current_mood,
                act=current_act,
                nrg=int(energy),
                cpu=cpu,
                evt=current_evt,
                poster=current_poster,
            )
            current_evt = "none"

            if args.once:
                print("[Desk-Buddy] Single test cycle completed.")
                break

            time.sleep(REFLEX_INTERVAL_SEC)

    except KeyboardInterrupt:
        print("\n[Desk-Buddy] Daemon stopped. See you soon!")


if __name__ == "__main__":
    main()
