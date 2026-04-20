"""
jarvis_gui.py  —  Jarvis AI Desktop Application
================================================
Auto-Listen state machine (simple sequential loop):

  IDLE
    └─(toggle ON)──► LISTENING FOR WAKE WORD
                          │
                     hears "Jarvis"
                          │
                          ▼
                    LISTENING FOR COMMAND
                          │
                     hears command
                          │
                          ▼
                      PROCESSING
                    (speak + action)
                          │
                       finished
                          │
                          ▼
                  back to LISTENING FOR WAKE WORD
                          │
                     (toggle OFF)
                          │
                          ▼
                        IDLE

One single background thread drives the whole loop.
It never runs two mic captures or two audio operations at the same time.
"""

import sys, traceback

# ── Global exception hook (must be first) ────────────────────────────────────
def _crash_hook(exc_type, exc_value, exc_tb):
    msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    print("UNCAUGHT EXCEPTION:\n", msg, flush=True)
    try:
        from PyQt5.QtWidgets import QApplication, QMessageBox
        app = QApplication.instance() or QApplication(sys.argv)
        dlg = QMessageBox()
        dlg.setIcon(QMessageBox.Critical)
        dlg.setWindowTitle("Jarvis — Error")
        dlg.setText(str(exc_value))
        dlg.setDetailedText(msg)
        dlg.exec_()
    except Exception:
        pass
    sys.__excepthook__(exc_type, exc_value, exc_tb)

sys.excepthook = _crash_hook

# ── Standard imports ─────────────────────────────────────────────────────────
import os, time, threading, uuid, requests
import speech_recognition as sr
import pygame
from gtts import gTTS

from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QScrollArea, QFrame, QLineEdit,
    QListWidget, QListWidgetItem,
)
from PyQt5.QtCore  import Qt, QThread, pyqtSignal, QTimer, QObject
from PyQt5.QtGui   import (
    QColor, QPainter, QPen, QBrush, QFont, QRadialGradient, QPalette
)

# ── Patch pyttsx3 BEFORE importing main.py ───────────────────────────────────
# main.py runs  engine = pyttsx3.init()  at module level.
# Without eSpeak this raises RuntimeError and kills the process instantly.
import pyttsx3 as _pyttsx3

class _StubEngine:
    def say(self, text):   pass
    def runAndWait(self):  pass
    def stop(self):        pass

_real_pyttsx3_init = _pyttsx3.init
def _safe_pyttsx3_init(*a, **kw):
    try:
        return _real_pyttsx3_init(*a, **kw)
    except Exception as e:
        print(f"[Jarvis] pyttsx3 unavailable ({e}) — using silent stub.", flush=True)
        return _StubEngine()

_pyttsx3.init = _safe_pyttsx3_init

# ── Import backend (main.py) ─────────────────────────────────────────────────
import main as _backend

# ── Initialise pygame audio (once, at startup) ───────────────────────────────
try:
    pygame.init()
    pygame.mixer.init()
except Exception as e:
    print(f"[Jarvis] pygame init warning: {e}", flush=True)

# ── Thread-safe bridge (created after QApplication) ─────────────────────────
class Bridge(QObject):
    add_message = pyqtSignal(str, bool)   # (text, is_user)
    set_status  = pyqtSignal(str)

bridge: Bridge = None   # assigned in __main__ after QApplication exists


# ═══════════════════════════════════════════════════════════════════════════════
#  SPEAK  (replaces main.py's speak — runs in whatever thread calls it)
# ═══════════════════════════════════════════════════════════════════════════════

_audio_lock = threading.Lock()   # only one audio operation at a time

def _speak(text: str):
    """
    Thread-safe gTTS + pygame speak.
    Also emits the text to the GUI chat bubble via bridge.
    """
    print(f"[speak] {text}", flush=True)
    if bridge is not None:
        try:
            bridge.add_message.emit(str(text), False)
        except RuntimeError:
            pass

    fname = f"temp_{uuid.uuid4().hex}.mp3"
    try:
        gTTS(text).save(fname)
        with _audio_lock:
            if pygame.mixer.get_init():
                pygame.mixer.music.load(fname)
                pygame.mixer.music.play()
                while pygame.mixer.music.get_busy():
                    time.sleep(0.1)
                pygame.mixer.music.unload()
    except Exception as e:
        print(f"[speak] audio error: {e}", flush=True)
    finally:
        try:
            if os.path.exists(fname):
                os.remove(fname)
        except Exception:
            pass

# Patch backend so processCommand() uses our GUI-aware speak
_backend.speak = _speak


# ═══════════════════════════════════════════════════════════════════════════════
#  AUTO-LISTEN LOOP THREAD
#  Single sequential thread:  wake → command → process → repeat
# ═══════════════════════════════════════════════════════════════════════════════

class AutoListenThread(QThread):
    """
    Runs the full listen → command → process cycle in one sequential thread.
    Never overlaps mic capture with audio playback.
    Stops cleanly when stop() is called.
    """
    sig_status  = pyqtSignal(str)
    sig_message = pyqtSignal(str, bool)   # (text, is_user)
    sig_mic_lit = pyqtSignal(bool)
    sig_pulse   = pyqtSignal(bool)        # start/stop pulse animation

    def __init__(self):
        super().__init__()
        self._stop_flag = threading.Event()

    def stop(self):
        self._stop_flag.set()

    # ── helpers ──────────────────────────────────────────────────────────────

    def _stopped(self):
        return self._stop_flag.is_set()

    def _listen(self, timeout: int, phrase_limit: int) -> str | None:
        """
        Open mic, listen, return recognised text or None.
        All exceptions are caught — never crashes the thread.
        """
        try:
            r = sr.Recognizer()
            with sr.Microphone() as src:
                audio = r.listen(src, timeout=timeout,
                                 phrase_time_limit=phrase_limit)
            return r.recognize_google(audio)
        except sr.WaitTimeoutError:
            return None
        except sr.UnknownValueError:
            return None
        except Exception as e:
            print(f"[listen] {type(e).__name__}: {e}", flush=True)
            return None

    # ── main loop ─────────────────────────────────────────────────────────────

    def run(self):
        self.sig_status.emit("Auto-Listen: ON — say 'Jarvis'")

        while not self._stopped():

            # ── STAGE 1: listen for wake word ────────────────────────────────
            self.sig_mic_lit.emit(True)
            self.sig_pulse.emit(True)
            self.sig_status.emit("🎙  Listening for 'Jarvis'…")

            word = self._listen(timeout=5, phrase_limit=3)

            self.sig_mic_lit.emit(False)
            self.sig_pulse.emit(False)

            if self._stopped():
                break

            if not word or "jarvis" not in word.lower():
                # Nothing heard or wrong word — loop back quietly
                continue

            # ── STAGE 2: acknowledge ─────────────────────────────────────────
            self.sig_message.emit("[ Wake word detected ]", False)
            self.sig_status.emit("⚡  Wake word heard!")
            _speak("Yaa!")          # blocks until audio finishes — that's fine,
                                    # mic is not open at this point

            if self._stopped():
                break

            # ── STAGE 3: listen for command ──────────────────────────────────
            self.sig_mic_lit.emit(True)
            self.sig_pulse.emit(True)
            self.sig_status.emit("🎙  Listening for command…")

            command = self._listen(timeout=6, phrase_limit=10)

            self.sig_mic_lit.emit(False)
            self.sig_pulse.emit(False)

            if self._stopped():
                break

            if not command:
                self.sig_message.emit("⚠  Didn't catch that — say 'Jarvis' to try again.", False)
                continue

            # ── STAGE 4: process & respond ───────────────────────────────────
            self.sig_message.emit(command, True)
            self.sig_status.emit("⚙  Processing…")

            try:
                _backend.processCommand(command)   # may call _speak() internally
            except Exception as e:
                print(f"[processCommand] {e}", flush=True)
                self.sig_message.emit(f"[Error] {e}", False)

            if self._stopped():
                break

            # ── back to top of loop ──────────────────────────────────────────
            self.sig_status.emit("✓  Ready — say 'Jarvis' again")
            time.sleep(0.3)   # tiny pause so the OS fully releases the audio device

        # ── thread exit ──────────────────────────────────────────────────────
        self.sig_mic_lit.emit(False)
        self.sig_pulse.emit(False)
        self.sig_status.emit("Idle — click 🎙 or enable Auto-Listen")


# ═══════════════════════════════════════════════════════════════════════════════
#  ONE-SHOT COMMAND THREAD  (used by the manual mic button)
# ═══════════════════════════════════════════════════════════════════════════════

class ManualCommandThread(QThread):
    sig_ready  = pyqtSignal(str)
    sig_error  = pyqtSignal(str)
    sig_status = pyqtSignal(str)

    def run(self):
        self.sig_status.emit("🎙  Listening…")
        try:
            r = sr.Recognizer()
            with sr.Microphone() as src:
                audio = r.listen(src, timeout=6, phrase_time_limit=10)
            cmd = r.recognize_google(audio)
            self.sig_ready.emit(cmd)
        except sr.WaitTimeoutError:
            self.sig_error.emit("Timed out — try again.")
        except sr.UnknownValueError:
            self.sig_error.emit("Couldn't understand that — try again.")
        except Exception as e:
            self.sig_error.emit(str(e))


# ═══════════════════════════════════════════════════════════════════════════════
#  PROCESS THREAD  (runs processCommand in background for manual input)
# ═══════════════════════════════════════════════════════════════════════════════

class ProcessThread(QThread):
    sig_done   = pyqtSignal()
    sig_status = pyqtSignal(str)

    def __init__(self, command: str):
        super().__init__()
        self.command = command

    def run(self):
        self.sig_status.emit("⚙  Processing…")
        try:
            _backend.processCommand(self.command)
        except Exception as e:
            print(f"[ProcessThread] {e}", flush=True)
            if bridge:
                bridge.add_message.emit(f"[Error] {e}", False)
        self.sig_done.emit()


# ═══════════════════════════════════════════════════════════════════════════════
#  NEWS THREAD
# ═══════════════════════════════════════════════════════════════════════════════

class NewsThread(QThread):
    sig_done  = pyqtSignal(list)
    sig_error = pyqtSignal(str)

    def run(self):
        try:
            r = requests.get(
                f"https://newsapi.org/v2/top-headlines?country=us"
                f"&apiKey={_backend.newsapi}",
                timeout=8,
            )
            if r.status_code == 200:
                arts = r.json().get("articles", [])
                self.sig_done.emit([a["title"] for a in arts if a.get("title")])
            else:
                self.sig_error.emit(f"API error {r.status_code}")
        except Exception as e:
            self.sig_error.emit(str(e))


# ═══════════════════════════════════════════════════════════════════════════════
#  ANIMATED WIDGETS
# ═══════════════════════════════════════════════════════════════════════════════

class PulseRings(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(240, 240)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._rings = []
        self._tick  = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)
        self._timer.setInterval(25)

    def start(self):
        self._rings = []
        self._tick  = 0
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self._rings = []
        self.update()

    def _step(self):
        self._tick += 1
        if self._tick % 18 == 0:
            self._rings.append([0.0, 255])
        self._rings = [[r + 1.8, max(0, a - 5)] for r, a in self._rings]
        self._rings = [x for x in self._rings if x[1] > 0]
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy = self.width() // 2, self.height() // 2
        for r, a in self._rings:
            p.setPen(QPen(QColor(0, 200, 255, int(a)), 2))
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(int(cx - r), int(cy - r), int(r * 2), int(r * 2))


class MicBtn(QPushButton):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(80, 80)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet("background: transparent; border: none;")
        self._lit = False

    def set_lit(self, val: bool):
        self._lit = val
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx = cy = 40
        r = 36
        if self._lit:
            halo = QRadialGradient(cx, cy, r + 16)
            halo.setColorAt(0, QColor(0, 200, 255, 130))
            halo.setColorAt(1, QColor(0, 0, 0, 0))
            p.setPen(Qt.NoPen)
            p.setBrush(halo)
            p.drawEllipse(cx - r - 16, cy - r - 16, (r + 16) * 2, (r + 16) * 2)
        bg = QRadialGradient(cx, cy, r)
        if self._lit:
            bg.setColorAt(0, QColor(0, 170, 245))
            bg.setColorAt(1, QColor(0, 65, 140))
        else:
            bg.setColorAt(0, QColor(10, 65, 108))
            bg.setColorAt(1, QColor(2, 17, 38))
        p.setBrush(bg)
        p.setPen(QPen(QColor(0, 220, 255) if self._lit else QColor(0, 95, 150), 2))
        p.drawEllipse(cx - r, cy - r, r * 2, r * 2)
        p.setPen(QPen(Qt.white, 2))
        p.setBrush(QBrush(Qt.white))
        p.drawRoundedRect(cx - 7, cy - 16, 14, 20, 7, 7)
        p.setBrush(Qt.NoBrush)
        p.drawArc(cx - 12, cy + 2, 24, 14, 0, -180 * 16)
        p.drawLine(cx, cy + 16, cx, cy + 23)
        p.drawLine(cx - 7, cy + 23, cx + 7, cy + 23)


# ═══════════════════════════════════════════════════════════════════════════════
#  MAIN WINDOW
# ═══════════════════════════════════════════════════════════════════════════════

class JarvisApp(QMainWindow):

    def __init__(self):
        super().__init__()
        self.setWindowTitle("JARVIS  —  AI Desktop Assistant")
        self.setMinimumSize(960, 660)
        self.resize(1140, 750)

        self._auto_thread   = None   # AutoListenThread
        self._manual_thread = None   # ManualCommandThread
        self._proc_thread   = None   # ProcessThread
        self._news_thread   = None   # NewsThread

        self._build_ui()
        self._apply_palette()
        self._wire_signals()

        # Connect bridge signals to UI slots
        bridge.add_message.connect(self._append_message)
        bridge.set_status.connect(self._set_status)

        self._set_status("Idle — click 🎙 or enable Auto-Listen")
        self._append_message(
            "Hello! I'm Jarvis. Click the mic button, type below, "
            "or enable Auto-Listen and say 'Jarvis'.", False
        )
        QTimer.singleShot(1000, self._fetch_news)

    # ── UI construction ───────────────────────────────────────────────────────

    def _build_ui(self):
        root = QWidget()
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        lay.addWidget(self._make_sidebar())
        sep = QFrame()
        sep.setFrameShape(QFrame.VLine)
        sep.setStyleSheet("QFrame{color:#001e2e;}")
        lay.addWidget(sep)
        lay.addWidget(self._make_centre(), stretch=1)

    def _make_sidebar(self):
        sb = QWidget()
        sb.setFixedWidth(218)
        sb.setStyleSheet("background:#050d19;")
        lay = QVBoxLayout(sb)
        lay.setContentsMargins(14, 18, 14, 12)
        lay.setSpacing(5)

        logo = QLabel("⬡  JARVIS")
        logo.setFont(QFont("Segoe UI", 15, QFont.Bold))
        logo.setStyleSheet("color:#00CCFF;letter-spacing:5px;")
        lay.addWidget(logo)
        tag = QLabel("AI Desktop Assistant")
        tag.setFont(QFont("Segoe UI", 8))
        tag.setStyleSheet("color:#244a58;")
        lay.addWidget(tag)
        lay.addSpacing(8)

        lay.addWidget(self._shdr("QUICK ACTIONS"))
        self._qa = {}
        for key, icon, label in [
            ("google",   "🌐", "Google"),
            ("youtube",  "▶ ", "YouTube"),
            ("facebook", "📘", "Facebook"),
            ("linkedin", "💼", "LinkedIn"),
            ("news",     "📰", "Headlines"),
        ]:
            b = self._sbtn(icon, label)
            self._qa[key] = b
            lay.addWidget(b)

        lay.addWidget(self._shdr("MUSIC LIBRARY"))
        import melodylibrary
        for song in melodylibrary.melody:
            b = self._sbtn("♪", song.capitalize())
            b.clicked.connect(lambda _, s=song: self._run_text_command(f"play {s}"))
            lay.addWidget(b)

        lay.addWidget(self._shdr("NEWS FEED"))
        self._news_list = QListWidget()
        self._news_list.setStyleSheet("""
            QListWidget{background:transparent;border:none;color:#3a5f6f;font-size:9px;}
            QListWidget::item{border-bottom:1px solid #001829;padding:4px 2px;}
            QListWidget::item:hover{color:#00AACC;background:#00111e;}
        """)
        self._news_list.setWordWrap(True)
        self._news_list.setFont(QFont("Segoe UI", 8))
        lay.addWidget(self._news_list, stretch=1)

        self._refresh_btn = self._sbtn("🔄", "Refresh News")
        lay.addWidget(self._refresh_btn)
        return sb

    def _make_centre(self):
        panel = QWidget()
        panel.setStyleSheet("background:#030910;")
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        # header bar
        hdr = QWidget()
        hdr.setFixedHeight(52)
        hdr.setStyleSheet("""background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
            stop:0 #020d18,stop:1 #050e1c);border-bottom:1px solid #002030;""")
        hl = QHBoxLayout(hdr)
        hl.setContentsMargins(22, 0, 22, 0)
        self._dot = QLabel("●")
        self._dot.setStyleSheet("color:#00FF88;font-size:12px;")
        self._stat_lbl = QLabel("…")
        self._stat_lbl.setFont(QFont("Segoe UI", 9))
        self._stat_lbl.setStyleSheet("color:#3d6678;")
        self._auto_btn = QPushButton("Auto-Listen: OFF")
        self._auto_btn.setCheckable(True)
        self._auto_btn.setCursor(Qt.PointingHandCursor)
        self._auto_btn.setFont(QFont("Segoe UI", 9))
        self._auto_btn.setStyleSheet("""
            QPushButton{background:#001424;color:#2d5f70;border:1px solid #002030;
                border-radius:4px;padding:4px 14px;}
            QPushButton:checked{background:#003050;color:#00CCFF;border-color:#005577;}
            QPushButton:hover{border-color:#004060;}
        """)
        hl.addWidget(self._dot)
        hl.addSpacing(6)
        hl.addWidget(self._stat_lbl)
        hl.addStretch()
        hl.addWidget(self._auto_btn)
        lay.addWidget(hdr)

        # mic area
        mic_host = QWidget()
        mic_host.setFixedHeight(258)
        mic_host.setStyleSheet("background:transparent;")
        mh = QVBoxLayout(mic_host)
        mh.setAlignment(Qt.AlignCenter)
        self._mic_container = QWidget()
        self._mic_container.setFixedSize(240, 240)
        self._pulse  = PulseRings(self._mic_container)
        self._pulse.setGeometry(0, 0, 240, 240)
        self._mic_btn = MicBtn(self._mic_container)
        self._mic_btn.setGeometry(80, 80, 80, 80)
        mh.addWidget(self._mic_container)
        lay.addWidget(mic_host)

        self._mode_lbl = QLabel("Click 🎙 or say 'Jarvis'")
        self._mode_lbl.setAlignment(Qt.AlignCenter)
        self._mode_lbl.setFont(QFont("Segoe UI", 10))
        self._mode_lbl.setStyleSheet("color:#1e3d4a;margin-bottom:4px;")
        lay.addWidget(self._mode_lbl)

        div = QFrame()
        div.setFrameShape(QFrame.HLine)
        div.setStyleSheet("QFrame{color:#001829;margin:2px 22px;}")
        lay.addWidget(div)

        chdr = QLabel("CONVERSATION LOG")
        chdr.setFont(QFont("Segoe UI", 8, QFont.Bold))
        chdr.setStyleSheet("color:#1e3a48;padding:6px 22px 2px;letter-spacing:2px;")
        lay.addWidget(chdr)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setStyleSheet("""
            QScrollArea{border:none;background:transparent;}
            QScrollBar:vertical{background:#010a14;width:5px;}
            QScrollBar::handle:vertical{background:#002030;border-radius:2px;min-height:20px;}
            QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{height:0;}
        """)
        self._chat_w = QWidget()
        self._chat_w.setStyleSheet("background:transparent;")
        self._chat_lay = QVBoxLayout(self._chat_w)
        self._chat_lay.setAlignment(Qt.AlignTop)
        self._chat_lay.setSpacing(2)
        self._chat_lay.setContentsMargins(8, 8, 8, 8)
        self._scroll.setWidget(self._chat_w)
        lay.addWidget(self._scroll, stretch=1)

        # input bar
        ibar = QWidget()
        ibar.setStyleSheet("background:#020d1a;border-top:1px solid #001e2e;")
        il = QHBoxLayout(ibar)
        il.setContentsMargins(16, 10, 16, 10)
        il.setSpacing(10)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or question…")
        self._input.setFont(QFont("Segoe UI", 10))
        self._input.setStyleSheet("""
            QLineEdit{background:#001929;color:#88CCEE;border:1px solid #003050;
                border-radius:20px;padding:8px 16px;}
            QLineEdit:focus{border-color:#006088;background:#001d30;}
        """)
        self._send_btn = QPushButton("Send")
        self._send_btn.setCursor(Qt.PointingHandCursor)
        self._send_btn.setFont(QFont("Segoe UI", 10, QFont.Bold))
        self._send_btn.setStyleSheet("""
            QPushButton{background:qlineargradient(x1:0,y1:0,x2:1,y2:0,
                stop:0 #005080,stop:1 #0077AA);color:white;border:none;
                border-radius:20px;padding:8px 24px;}
            QPushButton:hover{background:#0077BB;}
            QPushButton:pressed{background:#004060;}
        """)
        il.addWidget(self._input)
        il.addWidget(self._send_btn)
        lay.addWidget(ibar)
        return panel

    # ── widget helpers ────────────────────────────────────────────────────────

    def _shdr(self, text):
        l = QLabel(text)
        l.setFont(QFont("Segoe UI", 8, QFont.Bold))
        l.setStyleSheet("color:#005066;border-bottom:1px solid #002030;"
                        "padding-bottom:3px;margin-top:10px;")
        return l

    def _sbtn(self, icon, label):
        b = QPushButton(f"  {icon}  {label}")
        b.setCursor(Qt.PointingHandCursor)
        b.setFont(QFont("Segoe UI", 9))
        b.setStyleSheet("""
            QPushButton{background:#001422;color:#4a7080;border:1px solid #002030;
                border-radius:5px;padding:6px 8px;text-align:left;}
            QPushButton:hover{background:#001e30;color:#00CCEE;border-color:#005060;}
            QPushButton:pressed{background:#002840;}
        """)
        return b

    def _make_bubble(self, text, is_user):
        c = QWidget()
        c.setStyleSheet("background:transparent;")
        lay = QHBoxLayout(c)
        lay.setContentsMargins(10, 3, 10, 3)
        lbl = QLabel(text)
        lbl.setWordWrap(True)
        lbl.setMaximumWidth(430)
        lbl.setFont(QFont("Segoe UI", 10))
        if is_user:
            lbl.setStyleSheet("""background:qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 #004070,stop:1 #002244);color:#00DDFF;
                border:1px solid #005588;border-radius:14px 14px 4px 14px;padding:8px 14px;""")
            lay.addStretch()
            lay.addWidget(lbl)
        else:
            lbl.setStyleSheet("""background:qlineargradient(x1:0,y1:0,x2:1,y2:1,
                stop:0 #001830,stop:1 #00202e);color:#77BBDD;
                border:1px solid #003050;border-radius:14px 14px 14px 4px;padding:8px 14px;""")
            lay.addWidget(lbl)
            lay.addStretch()
        return c

    def _apply_palette(self):
        pal = QPalette()
        pal.setColor(QPalette.Window,          QColor(3,   9,  16))
        pal.setColor(QPalette.WindowText,      QColor(100, 180, 220))
        pal.setColor(QPalette.Base,            QColor(5,  14,  26))
        pal.setColor(QPalette.AlternateBase,   QColor(8,  20,  38))
        pal.setColor(QPalette.Text,            QColor(100, 180, 220))
        pal.setColor(QPalette.Button,          QColor(5,  18,  36))
        pal.setColor(QPalette.ButtonText,      QColor(100, 180, 220))
        pal.setColor(QPalette.Highlight,       QColor(0,  80, 130))
        pal.setColor(QPalette.HighlightedText, QColor(255, 255, 255))
        QApplication.instance().setPalette(pal)

    # ── signal wiring ─────────────────────────────────────────────────────────

    def _wire_signals(self):
        self._qa["google"].clicked.connect(   lambda: self._run_text_command("open google"))
        self._qa["youtube"].clicked.connect(  lambda: self._run_text_command("open youtube"))
        self._qa["facebook"].clicked.connect( lambda: self._run_text_command("open facebook"))
        self._qa["linkedin"].clicked.connect( lambda: self._run_text_command("open linkedin"))
        self._qa["news"].clicked.connect(     lambda: self._run_text_command("headlines"))
        self._refresh_btn.clicked.connect(self._fetch_news)
        self._mic_btn.clicked.connect(self._on_mic_click)
        self._auto_btn.toggled.connect(self._on_auto_toggled)
        self._send_btn.clicked.connect(self._on_send)
        self._input.returnPressed.connect(self._on_send)

    # ── UI update slots (always called on main thread via bridge) ─────────────

    def _append_message(self, text: str, is_user: bool):
        self._chat_lay.addWidget(self._make_bubble(text, is_user))
        QTimer.singleShot(40, lambda:
            self._scroll.verticalScrollBar().setValue(
                self._scroll.verticalScrollBar().maximum()))

    def _set_status(self, text: str):
        self._stat_lbl.setText(text)
        self._mode_lbl.setText(text)

    # ── Auto-Listen toggle ────────────────────────────────────────────────────

    def _on_auto_toggled(self, on: bool):
        if on:
            self._auto_btn.setText("Auto-Listen: ON")
            self._dot.setStyleSheet("color:#00FF88;font-size:12px;")
            self._start_auto_loop()
        else:
            self._auto_btn.setText("Auto-Listen: OFF")
            self._dot.setStyleSheet("color:#2a4a55;font-size:12px;")
            self._stop_auto_loop()

    def _start_auto_loop(self):
        if self._auto_thread and self._auto_thread.isRunning():
            return
        t = AutoListenThread()
        t.sig_status.connect(self._set_status)
        t.sig_message.connect(self._append_message)
        t.sig_mic_lit.connect(self._mic_btn.set_lit)
        t.sig_pulse.connect(lambda on: self._pulse.start() if on else self._pulse.stop())
        self._auto_thread = t
        t.start()

    def _stop_auto_loop(self):
        if self._auto_thread:
            self._auto_thread.stop()
            self._auto_thread = None
        self._pulse.stop()
        self._mic_btn.set_lit(False)
        self._set_status("Idle — click 🎙 or enable Auto-Listen")

    # ── Manual mic button ─────────────────────────────────────────────────────

    def _on_mic_click(self):
        # Disable auto-listen while doing a manual capture
        if self._auto_thread and self._auto_thread.isRunning():
            self._append_message("⚠  Turn off Auto-Listen before using manual mic.", False)
            return
        if self._manual_thread and self._manual_thread.isRunning():
            return
        self._pulse.start()
        self._mic_btn.set_lit(True)
        t = ManualCommandThread()
        t.sig_status.connect(self._set_status)
        t.sig_ready.connect(self._on_manual_ready)
        t.sig_error.connect(self._on_manual_error)
        t.finished.connect(lambda: (self._pulse.stop(), self._mic_btn.set_lit(False)))
        self._manual_thread = t
        t.start()

    def _on_manual_ready(self, cmd: str):
        self._run_text_command(cmd)

    def _on_manual_error(self, err: str):
        self._append_message(f"⚠  {err}", False)
        self._set_status("Idle — click 🎙 or enable Auto-Listen")

    # ── Text / button command dispatch ────────────────────────────────────────

    def _on_send(self):
        text = self._input.text().strip()
        if not text:
            return
        self._input.clear()
        self._run_text_command(text)

    def _run_text_command(self, cmd: str):
        """Run a command from text input or sidebar buttons (not from auto-listen)."""
        if self._proc_thread and self._proc_thread.isRunning():
            self._append_message("⚠  Please wait for the current command to finish.", False)
            return
        self._append_message(cmd, True)
        t = ProcessThread(cmd)
        t.sig_status.connect(self._set_status)
        t.sig_done.connect(lambda: self._set_status("Ready ✓"))
        self._proc_thread = t
        t.start()

    # ── News feed ─────────────────────────────────────────────────────────────

    def _fetch_news(self):
        if self._news_thread and self._news_thread.isRunning():
            return
        self._news_list.clear()
        item = QListWidgetItem("Fetching headlines…")
        item.setForeground(QColor("#1e4050"))
        self._news_list.addItem(item)
        t = NewsThread()
        t.sig_done.connect(self._on_news_done)
        t.sig_error.connect(self._on_news_error)
        self._news_thread = t
        t.start()

    def _on_news_done(self, headlines: list):
        self._news_list.clear()
        for h in headlines[:15]:
            item = QListWidgetItem(h)
            item.setForeground(QColor("#365e6e"))
            self._news_list.addItem(item)

    def _on_news_error(self, err: str):
        self._news_list.clear()
        item = QListWidgetItem(f"⚠  {err}")
        item.setForeground(QColor("#883333"))
        self._news_list.addItem(item)

    # ── Window close ─────────────────────────────────────────────────────────

    def closeEvent(self, event):
        self._stop_auto_loop()
        if self._auto_thread:
            self._auto_thread.wait(2000)
        event.accept()


# ═══════════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setApplicationName("Jarvis AI")
    app.setStyle("Fusion")

    # Bridge MUST be created after QApplication
    bridge = Bridge()

    try:
        window = JarvisApp()
        window.show()
    except Exception as e:
        from PyQt5.QtWidgets import QMessageBox
        dlg = QMessageBox()
        dlg.setIcon(QMessageBox.Critical)
        dlg.setWindowTitle("Jarvis — Startup Error")
        dlg.setText(str(e))
        dlg.setDetailedText(traceback.format_exc())
        dlg.exec_()
        sys.exit(1)

    sys.exit(app.exec_())