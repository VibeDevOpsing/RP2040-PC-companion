#!/usr/bin/env python3
"""
Cross-Platform Host Companion Daemon (macOS, Linux, Windows)
for the Waveshare RP2040-Zero 3D Grok Bot desk companion (ST7735R 160x80).

Architecture:
  - The RP2040 renders a raymarched 3D bot with props (coffee, laptop, lightbulb) and a
    side comic callout bubble. This daemon decides WHAT the bot does and THINKS.
  - Multi-OS Native Sensors (macOS, Linux X11/Wayland, Windows):
      * Auto-detects RP2040 USB Serial (`0x2E8A` VID or `/dev/cu.usbmodem*`, `/dev/ttyACM*`, `COM*`)
      * Frontmost application & window title
      * System user idle time (keyboard/mouse inactivity)
      * CPU load & Pomodoro stamina energy
      * Optional downscaled screenshot for Vision LLMs
  - Hybrid Brain:
      * Tier 1 (Reflexes, every 1.5s): instant state from app switches, CPU spikes, idle sleep.
      * Tier 2 (Thought Engine, background thread): a local LLM in LM Studio
        (e.g. `google/gemma-4-e2b`) reads the current context + recent activity timeline
        and writes up to 3 short live "thoughts" (e.g. "CURSOR AGAIN?", "TESTS RED?!").
        It runs periodically AND immediately on meaningful events (app switch, CPU panic,
        returning from AFK), without ever blocking the reflex loop.

Serial protocol (one line per update, `\\n` terminated):
  STATE:<STATE>|THEME:<THEME>|MSG:<T1~T2~T3>|MOOD:..|ACT:..|NRG:..|CPU:..|EVT:..|POSTER:..|HOUR:..
  `MSG` holds `~`-separated thoughts that the firmware rotates in the bubble.
  An empty `MSG:` tells the firmware to fall back to its built-in phrase pool.
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
import threading
import time
from collections import deque
from typing import Optional, Dict, Any, List, Sequence, Tuple

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
VALID_STATES = {
    "CODING", "COFFEE", "THINKING", "CHILL", "SLEEP", "OVERLOAD", "PARTY"
}
VALID_THEMES = {
    "CYBER", "VIOLET", "TEAL", "EMERALD", "INDIGO", "CRIMSON", "GOLD"
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

# ─── THOUGHT BUBBLE CONSTRAINTS (must mirror firmware `split_callout_lines`) ─
BUBBLE_LINE_CHARS = 10          # 6x8 bold font, 7px advance, 80px max bubble width
BUBBLE_MAX_LINES = 2
MAX_THOUGHTS = 3
THOUGHT_TTL_SEC = 75.0          # How long LLM thoughts stay valid without refresh
THOUGHT_MIN_GAP_SEC = 8.0       # Never call the LLM more often than this
SERIAL_HEARTBEAT_SEC = 10.0     # Resend unchanged state at most this often
_ALLOWED_BUBBLE_CHARS = re.compile(r"[^A-Z0-9!?.,+\-/:%#><_ ]")


def layout_bubble_lines(text: str, width: int = BUBBLE_LINE_CHARS) -> Optional[List[str]]:
    """Greedy word-wrap identical to the firmware. Returns None if text doesn't fit in 2 lines."""
    words = text.split()
    if not words:
        return None
    lines: List[str] = []
    cur = ""
    for w in words:
        if len(w) > width:
            return None
        if not cur:
            cur = w
        elif len(cur) + 1 + len(w) <= width:
            cur += " " + w
        else:
            lines.append(cur)
            cur = w
    lines.append(cur)
    return lines if len(lines) <= BUBBLE_MAX_LINES else None


def sanitize_thought(text: Any) -> str:
    """Uppercases, strips unsupported glyphs and shortens a thought until it fits the bubble."""
    if not isinstance(text, str):
        return ""
    t = text.upper().replace("~", "-")
    t = t.replace("’", "'").replace("'", "")
    t = _ALLOWED_BUBBLE_CHARS.sub(" ", t)
    words = [w[:BUBBLE_LINE_CHARS] for w in t.split()]
    while words and layout_bubble_lines(" ".join(words)) is None:
        words.pop()
    return " ".join(words)


def sanitize_thoughts(items: Any, limit: int = MAX_THOUGHTS) -> List[str]:
    """Normalizes an LLM `thoughts` value (list or string) into <= `limit` unique bubble-safe strings."""
    if isinstance(items, str):
        items = re.split(r"[~\n|]", items)
    if not isinstance(items, (list, tuple)):
        return []
    out: List[str] = []
    for it in items:
        s = sanitize_thought(it)
        if s and s not in out:
            out.append(s)
        if len(out) >= limit:
            break
    return out


def build_packet(
    state: str, theme: str, thoughts: Sequence[str], mood: str, act: str,
    nrg: int, cpu: int, evt: str, poster: str, hour: int,
) -> str:
    """Builds one serial protocol line. `thoughts` are sanitized and `~`-joined into MSG."""
    msg = "~".join(sanitize_thoughts(list(thoughts)))
    return (
        f"STATE:{state}|THEME:{theme}|MSG:{msg}|"
        f"MOOD:{mood}|ACT:{act}|NRG:{nrg}|CPU:{cpu}|EVT:{evt}|POSTER:{poster}|HOUR:{hour}\n"
    )


class ActivityTimeline:
    """Remembers recent app/window switches so the LLM can react to what *changed*."""

    def __init__(self, maxlen: int = 8):
        self.events: deque = deque(maxlen=maxlen)
        self.current_since: float = time.time()

    def update(self, app: str, title: str, now: Optional[float] = None) -> bool:
        """Records a switch. Returns True if the frontmost app changed."""
        now = time.time() if now is None else now
        if app == "Unknown":
            return False
        if self.events and self.events[-1][1] == app:
            if self.events[-1][2] != title:
                ts, a, _ = self.events[-1]
                self.events[-1] = (ts, a, title)
            return False
        self.events.append((now, app, title))
        self.current_since = now
        return True

    def dwell_minutes(self, now: Optional[float] = None) -> float:
        now = time.time() if now is None else now
        return max(0.0, (now - self.current_since) / 60.0)

    def summary(self, now: Optional[float] = None) -> str:
        now = time.time() if now is None else now
        lines = []
        for ts, app, title in list(self.events)[-6:]:
            ago = int(max(0, now - ts) // 60)
            short_title = (title or "")[:48]
            lines.append(f"- {ago}m ago: {app}" + (f" — {short_title}" if short_title else ""))
        return "\n".join(lines) if lines else "- (no history yet)"


# ─── MULTI-OS SERIAL PORT MANAGER ───────────────────────────────────────────
class BoardSerial:
    def __init__(self, port_override: Optional[str] = None, baudrate: int = 115200):
        self.port_override = port_override or DEFAULT_SERIAL_PORT
        self.baudrate = baudrate
        self.ser: Optional[serial.Serial] = None
        self.port_name: Optional[str] = None
        self.last_packet: str = ""
        self.last_key: Optional[tuple] = None
        self.last_send_ts: float = 0.0

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
        state: str = "COFFEE",
        theme: str = "CYBER",
        thoughts: Sequence[str] = (),
        force: bool = False,
    ) -> bool:
        """Sends a state line to the board.

        Packets are only written when the *semantic* content (state/theme/thoughts/mood/
        activity/event) changes, or every SERIAL_HEARTBEAT_SEC as a keep-alive. CPU/energy
        jitter alone does not trigger a write, which keeps the RP2040 from re-parsing
        (and allocating strings for) identical lines every 1.5s.
        """
        now = time.time()
        clean = tuple(sanitize_thoughts(list(thoughts)))
        key = (state, theme, clean, mood, act, evt, poster)
        if not force and key == self.last_key and (now - self.last_send_ts) < SERIAL_HEARTBEAT_SEC:
            return True

        packet = build_packet(
            state, theme, clean, mood, act, nrg, cpu, evt, poster, time.localtime().tm_hour
        )

        if not self.ensure_connected():
            return False

        try:
            self.ser.write(packet.encode("utf-8", errors="ignore"))
            self.ser.flush()
            if key != self.last_key:
                print(f">>> [RP2040] {packet.strip()}")
            self.last_packet = packet
            self.last_key = key
            self.last_send_ts = now
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


_MAC_IDLE_FN: Any = None
_MAC_IDLE_LOADED = False


def _mac_idle_fn():
    """Loads CoreGraphics' CGEventSourceSecondsSinceLastEventType once (no subprocess per tick)."""
    global _MAC_IDLE_FN, _MAC_IDLE_LOADED
    if not _MAC_IDLE_LOADED:
        _MAC_IDLE_LOADED = True
        try:
            lib = ctypes.cdll.LoadLibrary(
                "/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices"
            )
            fn = lib.CGEventSourceSecondsSinceLastEventType
            fn.restype = ctypes.c_double
            fn.argtypes = [ctypes.c_uint32, ctypes.c_uint32]
            _MAC_IDLE_FN = fn
        except Exception:
            _MAC_IDLE_FN = None
    return _MAC_IDLE_FN


def get_system_idle_seconds() -> float:
    """Returns seconds since last keyboard/mouse input across macOS, Linux, and Windows."""
    if OS_SYSTEM == "darwin":
        fn = _mac_idle_fn()
        if fn is not None:
            try:
                return max(0.0, float(fn(1, 0xFFFFFFFF)))  # HIDSystemState, kCGAnyInputEventType
            except Exception:
                pass
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
        timeline: str = "",
        dwell_min: float = 0.0,
        recent_thoughts: Sequence[str] = (),
        reflex_state: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Asks the local LLM for the bot's action/theme and up to 3 live thoughts.

        Returns the parsed JSON dict with a normalized `thoughts` list (bubble-safe), or None.
        """
        system_prompt = (
            "You are Grok Bot, a tiny 3D ghost-robot living on a 160x80 desk display next to a developer. "
            "You watch what the developer is doing RIGHT NOW and react with short inner thoughts shown in a "
            "comic bubble beside you.\n"
            "Pick your `state` (physical action + prop):\n"
            "- CODING: typing on a laptop (developer is coding / in terminal)\n"
            "- COFFEE: walking around sipping coffee (light browsing, long streak, tired)\n"
            "- THINKING: pondering with a lightbulb (docs, AI chats, reading, planning, short pauses)\n"
            "- CHILL: sitting cozily (music, videos, social media, resting)\n"
            "- SLEEP: sleeping (developer AFK)\n"
            "- OVERLOAD: panicking (errors, crashes, failing tests, CPU on fire)\n"
            "- PARTY: celebrating (deploy, merged PR, tests passed, release)\n"
            "Pick a `theme` tint: CYBER, VIOLET, TEAL, EMERALD, INDIGO, CRIMSON or GOLD.\n\n"
            "Write `thoughts`: 1 to 3 DIFFERENT reactions to the CURRENT situation, like inner monologue.\n"
            "Rules for every thought:\n"
            "- max 3 words and max 16 characters, ENGLISH, UPPERCASE, ASCII only, no emoji, no quotes\n"
            "- be specific: mention the app, file, site or what changed (short names like VSCODE, PR, TESTS, YT)\n"
            "- witty dev slang allowed: WTF?!, LGTM!, OTF, BRB, 10X, NGL, SUS, GG\n"
            "- never repeat any of the recent thoughts you are given\n"
            "Good examples: 'CURSOR AGAIN?', 'TESTS RED?!', 'YT BREAK~', 'PR MERGED!', '2H IN VIM', "
            "'READ DOCS', 'CPU ON FIRE', 'BACK FROM AFK', 'NEED COFFEE', 'SHIP IT!'.\n\n"
            "Respond ONLY with one JSON object:\n"
            '{"state": "...", "theme": "...", "thoughts": ["...", "..."], '
            '"mood": "focused|happy|curious|vibing|bored|tired|sleepy|stressed|panicking", '
            '"event": "none|sip_coffee|cheer", "energy_delta": 0}'
        )

        recent = ", ".join(recent_thoughts) if recent_thoughts else "none"
        local_time = time.strftime("%H:%M")
        user_context = (
            f"Now ({OS_SYSTEM}, local time {local_time}):\n"
            f"- Active app: {app_name} (for {dwell_min:.0f} min)\n"
            f"- Window title: {window_title or 'N/A'}\n"
            f"- Detected activity: {activity} (reflex suggests {reflex_state or 'n/a'})\n"
            f"- Work streak: {work_streak_min:.0f} min | Energy: {energy}% | CPU: {cpu}% | Idle: {idle_sec:.0f}s\n"
            f"Recent activity timeline (oldest first):\n{timeline or '- (none)'}\n"
            f"Recent thoughts (do NOT repeat): {recent}\n"
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
            "temperature": 0.8,
            "max_tokens": 300,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "grok_bot_thoughts",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "state": {"type": "string", "enum": sorted(VALID_STATES)},
                            "theme": {"type": "string", "enum": sorted(VALID_THEMES)},
                            "thoughts": {
                                "type": "array",
                                "items": {"type": "string"},
                                "minItems": 1,
                                "maxItems": MAX_THOUGHTS,
                            },
                            "mood": {"type": "string", "enum": sorted(VALID_MOODS)},
                            "event": {"type": "string", "enum": ["none", "sip_coffee", "cheer"]},
                            "energy_delta": {"type": "integer"},
                        },
                        "required": ["state", "theme", "thoughts", "mood", "event", "energy_delta"],
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
                data = parse_llm_json(msg_obj.get("content") or "", msg_obj.get("reasoning_content") or "")
                if data is None:
                    print(f"[LM Studio] Raw output (no JSON): {str(msg_obj.get('content'))[:80]!r}")
                    return None
                data["thoughts"] = sanitize_thoughts(data.get("thoughts") or data.get("speech") or [])
                return data
            print(f"[LM Studio] HTTP {r.status_code}: {r.text[:150]}")
        except Exception as e:
            print(f"[LM Studio] Warning: {e}")
        return None


def parse_llm_json(content: str, reasoning: str = "") -> Optional[Dict[str, Any]]:
    """Extracts the first JSON object from model output (handles <think> blocks and code fences)."""
    for text in (content, reasoning):
        if not text:
            continue
        text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
        text = re.sub(r"<\|thought\|>.*?<\|thought\|>", "", text, flags=re.DOTALL)
        text = text.replace("```json", "").replace("```", "").strip()
        try:
            obj = json.loads(text)
            if isinstance(obj, dict):
                return obj
        except ValueError:
            pass
        start = text.find("{")
        end = text.rfind("}")
        if start != -1 and end > start:
            try:
                obj = json.loads(text[start:end + 1])
                if isinstance(obj, dict):
                    return obj
            except ValueError:
                pass
    return None


class ThoughtEngine:
    """Runs LLM inference on a background thread.

    The reflex loop calls `update_context()` every tick (cheap) and `trigger()` on meaningful
    events. The worker wakes up either on a trigger or every `interval` seconds, enforces
    `min_gap` between calls, and publishes the latest result for `poll()` to pick up.
    """

    def __init__(self, brain: "LMStudioBrain", interval: float, min_gap: float = THOUGHT_MIN_GAP_SEC):
        self.brain = brain
        self.interval = interval
        self.min_gap = min_gap
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._ctx: Optional[Dict[str, Any]] = None
        self._result: Optional[Dict[str, Any]] = None
        self._last_call = 0.0
        self.busy = False
        self._thread = threading.Thread(target=self._run, name="thought-engine", daemon=True)

    def start(self) -> "ThoughtEngine":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    def update_context(self, ctx: Dict[str, Any]) -> None:
        with self._lock:
            self._ctx = dict(ctx)

    def trigger(self, reason: str = "") -> None:
        if reason:
            print(f"[Thoughts] Trigger: {reason}")
        self._wake.set()

    def poll(self) -> Optional[Dict[str, Any]]:
        with self._lock:
            res, self._result = self._result, None
        return res

    def _run(self) -> None:
        # Small delay so the first context snapshot exists before the first call.
        self._wake.wait(timeout=2.0)
        while not self._stop.is_set():
            self._wake.clear()
            wait = self.min_gap - (time.time() - self._last_call)
            if wait > 0:
                time.sleep(wait)
            with self._lock:
                ctx = dict(self._ctx) if self._ctx else None
            if ctx is not None:
                self.busy = True
                self._last_call = time.time()
                t0 = time.time()
                res = self.brain.analyze_context(**ctx)
                self.busy = False
                if res is not None:
                    res["_latency"] = time.time() - t0
                    with self._lock:
                        self._result = res
            self._wake.wait(timeout=self.interval)


# ─── TIER 1: INSTANT REFLEX CLASSIFIER ──────────────────────────────────────
def classify_reflex(
    app_name: str, window_title: str, idle_sec: float, cpu: int, energy: int
) -> Tuple[str, str, str, str, str, str]:
    """
    Instant (<5ms) mapping from OS sensors to (activity, mood, poster, state, theme, default_speech).
    """
    app_low = app_name.lower()
    title_low = window_title.lower()
    combined = f"{app_low} {title_low}"
    now_sec = int(time.time())

    # 1. User is AFK / inactive -> Cyber-Slime melts into a puddle and sleeps
    if idle_sec >= IDLE_SLEEP_THRESHOLD_SEC:
        return "sleeping", "sleepy", "zzz_dream", "SLEEP", "INDIGO", "ZZZ..."

    # 2. User is resting (45s..180s idle) -> Cyber-Slime lies down & chills
    if idle_sec >= 45.0:
        return "idle", "vibing", "chill_play", "CHILL", "EMERALD", "RESTING~"

    # 3. High CPU spike -> Glitch overload!
    if cpu >= 85:
        return "debugging", "panicking", "fire_panic", "OVERLOAD", "CRIMSON", "CPU 99%!"

    # 4. Debugging errors / crash keywords
    if any(k in combined for k in DEBUG_KEYWORDS):
        return "debugging", "stressed", "bug_alert", "OVERLOAD", "CRIMSON", "WTF?!"

    # 5. Celebrating deploy / PR / build success
    if any(k in combined for k in ROCKET_KEYWORDS):
        return "coding", "happy", "rocket_launch", "PARTY", "GOLD", "SHIP IT!"

    # 6. Listening to music or watching video -> Lying down chilling
    if any(a in app_low for a in MUSIC_APPS) or any(k in combined for k in DISTRACTION_KEYWORDS):
        return "music", "vibing", "music_eq", "CHILL", "EMERALD", "VIBING~"

    # 7. Short pause (15s..45s) or reading AI/Docs -> Standing/pacing & thinking with lightbulb!
    if idle_sec >= 15.0 or any(k in combined for k in IDEA_KEYWORDS):
        act = "coding" if any(a in app_low for a in CODING_APPS) else "browsing"
        return act, "curious", "brain_idea", "THINKING", "VIOLET", "HMM..."

    # 8. Low energy or periodic coffee stroll during work (every ~60s takes a 15s coffee walk!)
    if energy < 35 or (now_sec % 60) < 15:
        act = "coding" if any(a in app_low for a in CODING_APPS | TERMINAL_APPS) else "browsing"
        return act, "focused", "coffee_need", "COFFEE", "TEAL", "NEED COFFEE"

    # 9. Active coding or terminal work -> Typing on holographic laptop
    if any(a in app_low for a in CODING_APPS | TERMINAL_APPS):
        return "coding", "focused", "code_matrix", "CODING", "CYBER", "DEEP WORK"

    return "browsing", "curious", "zen_mountain", "COFFEE", "TEAL", "SIPPING~"


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
    parser = argparse.ArgumentParser(description="RP2040-Zero 3D Cyber-Slime Companion Daemon")
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
    print(f"  👾 RP2040-ZERO 3D GROK BOT DAEMON ({OS_SYSTEM.upper()})")
    print(f"  LM Studio API : {args.lm_url}")
    print(f"  Vision Mode   : {'Disabled (Text-only)' if args.no_vision else 'Enabled (Auto-fallback)'}")
    print(f"  Thoughts      : every {args.llm_interval:.0f}s + on events (min gap {THOUGHT_MIN_GAP_SEC:.0f}s)")
    print("=" * 64)

    board = BoardSerial(port_override=args.port)
    brain = LMStudioBrain(base_url=args.lm_url, use_vision=not args.no_vision)
    timeline = ActivityTimeline()
    engine: Optional[ThoughtEngine] = None
    if not args.once:
        engine = ThoughtEngine(brain, interval=args.llm_interval).start()

    energy = 95.0
    work_start_ts = time.time()
    last_energy_ts = time.time()
    last_title = ""
    last_reflex_state = ""

    current_evt = "none"
    llm_mood: Optional[str] = None
    llm_state: Optional[str] = None
    llm_theme: Optional[str] = None
    llm_thoughts: List[str] = []
    llm_until: float = 0.0
    recent_thoughts: deque = deque(maxlen=9)

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
            r_act, r_mood, r_poster, r_state, r_theme, r_speech = classify_reflex(
                app_name, win_title, idle_sec, cpu, int(energy)
            )

            # 4. Detect meaningful events -> invalidate stale thoughts & wake the LLM immediately
            trigger_reason = ""
            if timeline.update(app_name, win_title, now):
                trigger_reason = f"switched to {app_name}"
                llm_until = 0.0
            elif win_title != last_title and r_state in ("OVERLOAD", "PARTY"):
                trigger_reason = f"title hints {r_state}"
            if r_state != last_reflex_state:
                if r_state in ("OVERLOAD", "PARTY", "SLEEP"):
                    trigger_reason = trigger_reason or f"reflex -> {r_state}"
                    llm_until = 0.0
                elif last_reflex_state in ("SLEEP", "CHILL") and idle_sec < 5:
                    trigger_reason = trigger_reason or "user is back"
                    llm_until = 0.0
            if win_title != last_title or r_state != last_reflex_state:
                print(
                    f"[Reflex] App='{app_name}' Title='{win_title[:35]}' -> "
                    f"State={r_state} | Theme={r_theme} | CPU={cpu}% | Idle={idle_sec:.0f}s"
                )
            last_title = win_title
            last_reflex_state = r_state

            ctx = dict(
                app_name=app_name,
                window_title=win_title,
                activity=r_act,
                energy=int(energy),
                cpu=cpu,
                idle_sec=idle_sec,
                work_streak_min=work_streak_min,
                timeline=timeline.summary(now),
                dwell_min=timeline.dwell_minutes(now),
                recent_thoughts=list(recent_thoughts),
                reflex_state=r_state,
            )

            # 5. Tier 2: Thought Engine (async in daemon mode, sync in --once mode)
            if engine is not None:
                engine.update_context(ctx)
                if trigger_reason:
                    engine.trigger(trigger_reason)
                res = engine.poll()
            else:
                t0 = time.time()
                res = brain.analyze_context(**ctx)
                if res is not None:
                    res["_latency"] = time.time() - t0

            if res:
                new_state = str(res.get("state", "")).upper().strip()
                llm_state = new_state if new_state in VALID_STATES else None
                new_theme = str(res.get("theme", "")).upper().strip()
                llm_theme = new_theme if new_theme in VALID_THEMES else None
                new_mood = str(res.get("mood", "")).lower().strip()
                llm_mood = new_mood if new_mood in VALID_MOODS else None
                llm_thoughts = list(res.get("thoughts") or [])
                recent_thoughts.extend(llm_thoughts)
                llm_until = now + THOUGHT_TTL_SEC

                new_evt = str(res.get("event", "none")).lower().strip()
                if new_evt in {"none", "sip_coffee", "cheer"}:
                    current_evt = new_evt
                try:
                    edelta = int(res.get("energy_delta", 0))
                    energy = max(5.0, min(100.0, energy + max(-5, min(5, edelta))))
                except Exception:
                    pass
                print(
                    f"[Thoughts] {llm_thoughts} | State={llm_state} | Theme={llm_theme} | "
                    f"Mood={llm_mood} | {res.get('_latency', 0):.1f}s"
                )

            # 6. Merge: reflex safety states (SLEEP/OVERLOAD) always win over the LLM
            llm_active = now < llm_until
            if llm_active and r_state not in ("SLEEP", "OVERLOAD"):
                current_state = llm_state or r_state
                current_theme = llm_theme or r_theme
                current_mood = llm_mood or r_mood
            else:
                current_state, current_theme, current_mood = r_state, r_theme, r_mood
            # Empty thoughts -> firmware rotates its built-in phrase pool for the state.
            thoughts_out = llm_thoughts if llm_active else []

            # 7. Send state packet to RP2040-Zero
            board.send_state(
                mood=current_mood,
                act=r_act,
                nrg=int(energy),
                cpu=cpu,
                evt=current_evt,
                poster=r_poster,
                state=current_state,
                theme=current_theme,
                thoughts=thoughts_out,
            )
            current_evt = "none"

            if args.once:
                print("[Desk-Buddy] Single test cycle completed.")
                break

            time.sleep(REFLEX_INTERVAL_SEC)

    except KeyboardInterrupt:
        print("\n[Desk-Buddy] Daemon stopped. See you soon!")
    finally:
        if engine is not None:
            engine.stop()


if __name__ == "__main__":
    main()
