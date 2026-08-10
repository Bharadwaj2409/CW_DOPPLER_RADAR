#!/usr/bin/env python3
"""
=========================================================================
 45-Degree (Custom) Sector Radar Scanner GUI
 Target platform : Raspberry Pi 4 Model B (PyQt5)
=========================================================================

WHAT IT DOES
------------
- Listens for UDP packets on a configurable IP:Port.
- Parses lines of the form:
    Signal Level = -51.38 dBFS | Doppler = -9.18 Hz | Velocity = -0.250 m/s
- Draws an animated radar sector (custom start/end angle, 0-360 deg) with
  a continuously sweeping beam.
- Nothing is shown on the scope until the received Signal Level (dBFS)
  is GREATER than the user-set threshold.
- When a detection crosses the threshold, a blinking red triangular
  "blip" is drawn at the current sweep angle.
- The blip's distance from the origin (radar centre) is driven by the
  Velocity value:
       velocity < 0  -> blip sits CLOSER to the origin (approaching)
       velocity > 0  -> blip sits FARTHER from the origin (receding)
- A collapsible settings panel (gear button) lets you set:
       * Listen IP / Port (UDP "dial" + Connect/Disconnect)
       * Detection threshold (dBFS)
       * Sector start / end angle (0-360 deg, custom)
       * Max range (m) / Velocity scale (m/s for full-scale deflection)
       * Sweep speed, blip lifetime / blink speed

INSTALL (Raspberry Pi OS / Debian)
-----------------------------------
    sudo apt update
    sudo apt install python3-pyqt5
    python3 radar_gui.py

    (or)  pip3 install PyQt5   then   python3 radar_gui.py
=========================================================================
"""

import sys
import math
import time
import socket
import struct

from PyQt5.QtCore import Qt, QThread, pyqtSignal, QTimer, QPointF, QRectF
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QPolygonF, QFont, QRadialGradient
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QToolButton, QFrame, QLineEdit, QSpinBox,
    QDoubleSpinBox, QSlider, QFormLayout, QSizePolicy, QGroupBox
)


# ------------------------------------------------------------------ #
#  UDP receiver thread
# ------------------------------------------------------------------ #
#  The upstream GNU Radio block sends RAW BINARY datagrams, not text.
#  Each "vector" is 12 bytes = 3 little-endian float32s, in the order:
#       out0 = Doppler (Hz), out1 = Velocity (m/s), out2 = Signal (dBFS)
#  A single UDP packet can contain many repeated vectors (the block
#  emits ~48,000/sec holding the last computed value); we only need
#  the LAST vector in each packet, same as your working reference
#  script.
# ------------------------------------------------------------------ #
class UdpReceiver(QThread):
    data_received = pyqtSignal(float, float, float)   # signal_dbfs, doppler_hz, velocity_ms
    status_changed = pyqtSignal(str, bool)             # message, is_error

    VECTOR_SIZE = 12          # 3 x float32
    BUFFER_SIZE = 65536
    RCVBUF_BYTES = 8 * 1024 * 1024

    def __init__(self, ip="0.0.0.0", port=5005, parent=None):
        super().__init__(parent)
        self.ip = ip
        self.port = port
        self._running = False
        self.sock = None
        # throttle how often we push a value into the GUI - the block
        # can emit tens of thousands of packets/sec, far more than the
        # GUI (or the human eye) needs. Default 10 Hz.
        self.emit_interval = 0.1

    def update_address(self, ip, port):
        self.ip = ip
        self.port = port

    def set_emit_rate_hz(self, hz):
        hz = max(0.2, min(60.0, hz))
        self.emit_interval = 1.0 / hz

    def run(self):
        self._running = True
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Bigger OS receive buffer so bursts of ~48k pps don't
            # overflow it while Python is busy doing anything else.
            self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, self.RCVBUF_BYTES)
            self.sock.bind((self.ip, self.port))
            self.sock.settimeout(0.5)
            self.status_changed.emit(f"Listening on {self.ip}:{self.port}", False)
        except OSError as e:
            self.status_changed.emit(f"Bind failed: {e}", True)
            self._running = False
            return

        last_emit = 0.0
        packet_count = 0

        while self._running:
            try:
                data, addr = self.sock.recvfrom(self.BUFFER_SIZE)
            except socket.timeout:
                continue
            except OSError:
                break

            if len(data) < self.VECTOR_SIZE:
                continue

            num_vectors = len(data) // self.VECTOR_SIZE
            start = (num_vectors - 1) * self.VECTOR_SIZE

            try:
                doppler_hz, velocity_ms, signal_dbfs = struct.unpack(
                    "<fff", data[start:start + self.VECTOR_SIZE]
                )
            except struct.error:
                continue

            packet_count += 1
            now = time.time()
            if now - last_emit >= self.emit_interval:
                self.data_received.emit(signal_dbfs, doppler_hz, velocity_ms)
                last_emit = now

        if self.sock:
            self.sock.close()
        self.status_changed.emit("Listener stopped", False)

    def stop(self):
        self._running = False
        self.wait(1500)


# ------------------------------------------------------------------ #
#  Radar Widget  (custom paint - sector scope, sweep, blips)
# ------------------------------------------------------------------ #
class RadarWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(420, 420)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # ---- configurable parameters -------------------------------------------------
        self.start_angle = 45.0        # degrees, math convention (0 = +X axis, CCW)
        self.end_angle = 135.0
        self.max_range_m = 50.0        # full-scale range in meters (label only)
        self.velocity_scale = 5.0      # m/s that maps to full-scale radial deflection
        self.sweep_speed = 60.0        # deg / second
        self.blink_hz = 3.0            # blink frequency of a live target
        self.blip_lifetime = 3.0       # seconds a blip stays on screen after last hit

        # ---- runtime state --------------------------------------------------------
        self.sweep_angle = self.start_angle
        self.sweep_dir = 1             # +1 / -1  (ping-pong across the sector)
        self.trail = []                # list of past sweep angles for fading trail
        # single tracked target -- None when nothing is above threshold.
        # dict: angle, radius_frac, velocity, signal, t0 (first seen), t_last (last update)
        self.target = None

        self.threshold_dbfs = -50.0

        self.last_signal = None
        self.last_doppler = None
        self.last_velocity = None
        self.connected = False

        # ---- animation timer --------------------------------------------------------
        self._last_tick = time.monotonic()
        self.timer = QTimer(self)
        self.timer.timeout.connect(self._tick)
        self.timer.start(30)   # ~33 FPS

    # ---------------------------------------------------------------- public API
    def set_sector(self, start_deg, end_deg):
        start_deg = start_deg % 360
        end_deg = end_deg % 360
        if end_deg <= start_deg:
            end_deg += 360
        self.start_angle = start_deg
        self.end_angle = end_deg
        self.sweep_angle = start_deg
        self.sweep_dir = 1
        self.trail.clear()

    def set_threshold(self, value):
        self.threshold_dbfs = value

    def set_max_range(self, value):
        self.max_range_m = max(1.0, value)

    def set_velocity_scale(self, value):
        self.velocity_scale = max(0.1, value)

    def set_sweep_speed(self, deg_per_sec):
        self.sweep_speed = max(1.0, deg_per_sec)

    def set_blink_hz(self, hz):
        self.blink_hz = max(0.2, hz)

    def set_blip_lifetime(self, seconds):
        self.blip_lifetime = max(0.3, seconds)

    def set_connected(self, is_connected):
        self.connected = is_connected

    def feed_data(self, signal_dbfs, doppler_hz, velocity_ms):
        """Called whenever a new UDP sample arrives.

        Only ONE target is ever tracked. As long as consecutive samples
        stay above the threshold, the SAME triangle is updated in place
        (its angle follows the sweep, its radius follows velocity) --
        it does not spawn a new blip per packet. If the signal drops
        below threshold the target starts fading and is cleared after
        `blip_lifetime` seconds with no further detections.
        """
        self.last_signal = signal_dbfs
        self.last_doppler = doppler_hz
        self.last_velocity = velocity_ms

        if signal_dbfs > self.threshold_dbfs:
            frac = self._velocity_to_radius_frac(velocity_ms)
            now = time.monotonic()
            if self.target is None:
                self.target = {"t0": now}
            self.target.update({
                "angle": self.sweep_angle,
                "radius_frac": frac,
                "velocity": velocity_ms,
                "signal": signal_dbfs,
                "t_last": now,
            })

    # ---------------------------------------------------------------- internals
    def _velocity_to_radius_frac(self, velocity_ms):
        """Negative velocity -> near centre, positive velocity -> near edge."""
        mid = 0.5
        frac = mid + (velocity_ms / (2.0 * self.velocity_scale))
        return max(0.06, min(0.98, frac))

    def _tick(self):
        now = time.monotonic()
        dt = now - self._last_tick
        self._last_tick = now

        # advance sweep (ping-pong across the sector)
        span = self.end_angle - self.start_angle
        if span <= 0:
            span = 360
        step = self.sweep_speed * dt
        self.sweep_angle += self.sweep_dir * step
        if self.sweep_angle >= self.end_angle:
            self.sweep_angle = self.end_angle
            self.sweep_dir = -1
        elif self.sweep_angle <= self.start_angle:
            self.sweep_angle = self.start_angle
            self.sweep_dir = 1

        self.trail.append(self.sweep_angle)
        if len(self.trail) > 14:
            self.trail.pop(0)

        # expire the target if it hasn't been refreshed in a while
        if self.target and (now - self.target["t_last"]) > self.blip_lifetime:
            self.target = None

        self.update()

    # ---------------------------------------------------------------- painting
    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        painter.fillRect(0, 0, w, h, QColor(6, 12, 10))

        margin = 24
        avail = min(w, h) - 2 * margin
        radius_px = max(40, avail / 2)

        # origin placed so the whole sector (whatever angles chosen) fits nicely
        cx = w / 2.0
        cy = h / 2.0 + radius_px * 0.25
        origin = QPointF(cx, cy)

        self._draw_sector_background(painter, origin, radius_px)
        self._draw_range_rings(painter, origin, radius_px)
        self._draw_angle_spokes(painter, origin, radius_px)
        self._draw_sweep(painter, origin, radius_px)
        self._draw_target(painter, origin, radius_px)
        self._draw_origin_marker(painter, origin)
        self._draw_hud(painter)

    def _to_point(self, origin, radius_px, angle_deg):
        rad = math.radians(angle_deg)
        x = origin.x() + radius_px * math.cos(rad)
        y = origin.y() - radius_px * math.sin(rad)
        return QPointF(x, y)

    def _draw_sector_background(self, painter, origin, radius_px):
        rect = QRectF(origin.x() - radius_px, origin.y() - radius_px,
                       radius_px * 2, radius_px * 2)
        span = self.end_angle - self.start_angle

        grad = QRadialGradient(origin, radius_px)
        grad.setColorAt(0.0, QColor(10, 45, 30, 220))
        grad.setColorAt(1.0, QColor(4, 14, 10, 230))
        painter.setBrush(QBrush(grad))
        painter.setPen(QPen(QColor(0, 255, 120, 160), 2))
        # QPainter angles: 0 = 3 o'clock, positive = counter-clockwise, in 1/16 deg
        painter.drawPie(rect, int(self.start_angle * 16), int(span * 16))

    def _draw_range_rings(self, painter, origin, radius_px):
        rings = 4
        painter.setPen(QPen(QColor(0, 255, 120, 90), 1, Qt.DashLine))
        font = QFont("Consolas", 8)
        painter.setFont(font)
        for i in range(1, rings + 1):
            r = radius_px * i / rings
            rect = QRectF(origin.x() - r, origin.y() - r, r * 2, r * 2)
            span = self.end_angle - self.start_angle
            painter.drawArc(rect, int(self.start_angle * 16), int(span * 16))

            label_angle = self.start_angle
            p = self._to_point(origin, r, label_angle)
            range_val = self.max_range_m * i / rings
            painter.setPen(QPen(QColor(0, 255, 150, 180)))
            painter.drawText(p + QPointF(4, -4), f"{range_val:.0f}m")
            painter.setPen(QPen(QColor(0, 255, 120, 90), 1, Qt.DashLine))

    def _draw_angle_spokes(self, painter, origin, radius_px):
        span = self.end_angle - self.start_angle
        step = 15 if span > 60 else 5
        painter.setPen(QPen(QColor(0, 255, 120, 60), 1))
        a = self.start_angle
        while a <= self.end_angle + 0.001:
            p = self._to_point(origin, radius_px, a)
            painter.drawLine(origin, p)
            a += step
        # boundary edges brighter
        painter.setPen(QPen(QColor(0, 255, 160, 200), 2))
        painter.drawLine(origin, self._to_point(origin, radius_px, self.start_angle))
        painter.drawLine(origin, self._to_point(origin, radius_px, self.end_angle))

    def _draw_sweep(self, painter, origin, radius_px):
        n = len(self.trail)
        for i, ang in enumerate(self.trail):
            alpha = int(200 * (i + 1) / max(1, n))
            pen = QPen(QColor(0, 255, 90, alpha), 3 if i == n - 1 else 1.5)
            painter.setPen(pen)
            p = self._to_point(origin, radius_px, ang)
            painter.drawLine(origin, p)

    def _draw_origin_marker(self, painter, origin):
        painter.setPen(QPen(QColor(0, 255, 150), 1))
        painter.setBrush(QBrush(QColor(0, 255, 150)))
        painter.drawEllipse(origin, 4, 4)

    def _draw_target(self, painter, origin, radius_px):
        """Draw the single tracked target (if any). It blinks continuously
        while live and fades out if not refreshed within blip_lifetime."""
        b = self.target
        if b is None:
            return

        now = time.monotonic()
        age_since_update = now - b["t_last"]
        life_frac = max(0.0, 1.0 - age_since_update / self.blip_lifetime)
        if life_frac <= 0:
            self.target = None
            return

        blink_phase = now - b["t0"]
        blink = 0.5 + 0.5 * math.sin(2 * math.pi * self.blink_hz * blink_phase)
        alpha = int(255 * life_frac * (0.35 + 0.65 * blink))
        alpha = max(0, min(255, alpha))

        r = radius_px * b["radius_frac"]
        center = self._to_point(origin, r, b["angle"])

        size = 12 + 4 * life_frac
        tri = self._triangle(center, size, b["angle"])

        painter.setPen(QPen(QColor(255, 40, 40, alpha), 1))
        painter.setBrush(QBrush(QColor(255, 30, 30, alpha)))
        painter.drawPolygon(tri)

        # small readout next to the blip
        painter.setPen(QPen(QColor(255, 120, 120, alpha)))
        f = QFont("Consolas", 8)
        painter.setFont(f)
        txt = f'{b["signal"]:.1f}dB {b["velocity"]:+.2f}m/s'
        painter.drawText(center + QPointF(10, -6), txt)

    def _triangle(self, center, size, pointing_angle_deg):
        """An upward pointing (radially outward) triangle centred at `center`."""
        rad = math.radians(pointing_angle_deg)
        # local axes: 'out' points away from origin, 'perp' is perpendicular
        out = QPointF(math.cos(rad), -math.sin(rad))
        perp = QPointF(-math.sin(rad), -math.cos(rad))

        tip = QPointF(center.x() + out.x() * size, center.y() + out.y() * size)
        base1 = QPointF(center.x() - out.x() * size * 0.6 + perp.x() * size * 0.6,
                         center.y() - out.y() * size * 0.6 + perp.y() * size * 0.6)
        base2 = QPointF(center.x() - out.x() * size * 0.6 - perp.x() * size * 0.6,
                         center.y() - out.y() * size * 0.6 - perp.y() * size * 0.6)
        return QPolygonF([tip, base1, base2])

    def _draw_hud(self, painter):
        painter.setPen(QPen(QColor(0, 255, 150, 220)))
        painter.setFont(QFont("Consolas", 9, QFont.Bold))
        status = "LINK: CONNECTED" if self.connected else "LINK: IDLE"
        painter.drawText(10, 18, status)
        painter.drawText(10, 34, f"Sector: {self.start_angle:.0f}\u00b0 - {self.end_angle:.0f}\u00b0")
        painter.drawText(10, 50, f"Threshold: {self.threshold_dbfs:.1f} dBFS")

        if self.last_signal is not None:
            det = self.last_signal > self.threshold_dbfs
            color = QColor(255, 60, 60) if det else QColor(0, 255, 150)
            painter.setPen(QPen(color))
            txt = "** TARGET **" if det else "no target"
            painter.drawText(self.width() - 150, 18, txt)
            painter.drawText(self.width() - 220, 34,
                              f"Sig:{self.last_signal:7.2f}dBFS")
            painter.drawText(self.width() - 220, 50,
                              f"Dop:{self.last_doppler:7.2f}Hz")
            painter.drawText(self.width() - 220, 66,
                              f"Vel:{self.last_velocity:7.3f}m/s")


# ------------------------------------------------------------------ #
#  Collapsible settings panel
# ------------------------------------------------------------------ #
class SettingsPanel(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        self.setStyleSheet("""
            QFrame { background-color: #0c1512; border: 1px solid #0f3d28; border-radius: 6px; }
            QLabel { color: #a9ffcf; }
            QGroupBox { color: #6dffb0; border: 1px solid #14513a; margin-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }
            QLineEdit, QSpinBox, QDoubleSpinBox {
                background-color: #061109; color: #d8ffe9; border: 1px solid #14513a;
                padding: 3px; border-radius: 3px;
            }
            QPushButton {
                background-color: #0f3d28; color: #d8ffe9; border: 1px solid #1f8a56;
                border-radius: 4px; padding: 5px 10px;
            }
            QPushButton:hover { background-color: #17603d; }
            QSlider::groove:horizontal { background: #14513a; height: 4px; }
            QSlider::handle:horizontal { background: #2ecf7a; width: 12px; margin: -5px 0; border-radius: 6px; }
        """)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 10)
        outer.setSpacing(8)

        # ---- network group ----------------------------------------------------
        net_box = QGroupBox("UDP Connection")
        net_form = QFormLayout()
        self.ip_edit = QLineEdit("0.0.0.0")
        self.ip_edit.setPlaceholderText("Listen IP (0.0.0.0 = any)")
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1, 65535)
        self.port_spin.setValue(5005)
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.2, 60.0)
        self.rate_spin.setValue(10.0)
        self.rate_spin.setSuffix(" Hz")
        self.rate_spin.setToolTip("How often to pull the latest sample into the GUI")
        self.connect_btn = QPushButton("Connect / Listen")
        self.connect_btn.setCheckable(True)
        net_form.addRow("IP Address:", self.ip_edit)
        net_form.addRow("Port:", self.port_spin)
        net_form.addRow("GUI update rate:", self.rate_spin)
        net_form.addRow(self.connect_btn)
        net_box.setLayout(net_form)

        # ---- detection group ----------------------------------------------------
        det_box = QGroupBox("Detection")
        det_form = QFormLayout()
        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(-150.0, 0.0)
        self.threshold_spin.setDecimals(2)
        self.threshold_spin.setSingleStep(0.5)
        self.threshold_spin.setValue(-50.0)
        det_form.addRow("Threshold (dBFS):", self.threshold_spin)
        det_box.setLayout(det_form)

        # ---- sector group ----------------------------------------------------
        sec_box = QGroupBox("Scan Sector")
        sec_form = QFormLayout()
        self.start_spin = QSpinBox()
        self.start_spin.setRange(0, 360)
        self.start_spin.setValue(45)
        self.end_spin = QSpinBox()
        self.end_spin.setRange(0, 360)
        self.end_spin.setValue(135)
        sec_form.addRow("Start angle (deg):", self.start_spin)
        sec_form.addRow("End angle (deg):", self.end_spin)
        sec_box.setLayout(sec_form)

        # ---- scale / animation group ----------------------------------------------------
        scale_box = QGroupBox("Scaling / Animation")
        scale_form = QFormLayout()
        self.range_spin = QDoubleSpinBox()
        self.range_spin.setRange(1, 10000)
        self.range_spin.setValue(50)
        self.range_spin.setSuffix(" m")

        self.vel_scale_spin = QDoubleSpinBox()
        self.vel_scale_spin.setRange(0.1, 1000)
        self.vel_scale_spin.setValue(5.0)
        self.vel_scale_spin.setSuffix(" m/s")

        self.sweep_speed_slider = QSlider(Qt.Horizontal)
        self.sweep_speed_slider.setRange(5, 300)
        self.sweep_speed_slider.setValue(60)

        self.blink_slider = QSlider(Qt.Horizontal)
        self.blink_slider.setRange(1, 10)
        self.blink_slider.setValue(3)

        self.lifetime_spin = QDoubleSpinBox()
        self.lifetime_spin.setRange(0.5, 30.0)
        self.lifetime_spin.setValue(3.0)
        self.lifetime_spin.setSuffix(" s")

        scale_form.addRow("Max range:", self.range_spin)
        scale_form.addRow("Velocity full-scale:", self.vel_scale_spin)
        scale_form.addRow("Sweep speed (deg/s):", self.sweep_speed_slider)
        scale_form.addRow("Blink rate (Hz):", self.blink_slider)
        scale_form.addRow("Blip hold time:", self.lifetime_spin)
        scale_box.setLayout(scale_form)

        self.apply_btn = QPushButton("Apply Settings")

        outer.addWidget(net_box)
        outer.addWidget(det_box)
        outer.addWidget(sec_box)
        outer.addWidget(scale_box)
        outer.addWidget(self.apply_btn)
        outer.addStretch(1)

        self.setMaximumWidth(300)


# ------------------------------------------------------------------ #
#  Main Window
# ------------------------------------------------------------------ #
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Radar Sector Scanner - Raspberry Pi 4")
        self.resize(1000, 650)
        self.setStyleSheet("background-color: #05100b;")

        self.udp_thread = None

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(8, 8, 8, 8)

        # ---- top bar ------------------------------------------------------------
        top_bar = QHBoxLayout()
        self.settings_btn = QToolButton()
        self.settings_btn.setText("\u2699  Settings")
        self.settings_btn.setCheckable(True)
        self.settings_btn.setStyleSheet("""
            QToolButton { color: #d8ffe9; background-color: #0f3d28; border: 1px solid #1f8a56;
                          border-radius: 4px; padding: 6px 12px; font-size: 13px; }
            QToolButton:checked { background-color: #17603d; }
        """)
        self.settings_btn.toggled.connect(self._toggle_settings)

        self.status_label = QLabel("Not connected")
        self.status_label.setStyleSheet("color: #6dffb0; font-family: Consolas; padding-left: 12px;")

        top_bar.addWidget(self.settings_btn)
        top_bar.addWidget(self.status_label, 1)
        root.addLayout(top_bar)

        # ---- body: radar + settings ------------------------------------------------------------
        body = QHBoxLayout()
        self.radar = RadarWidget()
        self.settings = SettingsPanel()
        self.settings.setVisible(False)

        body.addWidget(self.radar, 3)
        body.addWidget(self.settings, 1)
        root.addLayout(body, 1)

        # ---- wire up settings ------------------------------------------------------------
        self.settings.connect_btn.clicked.connect(self._toggle_connection)
        self.settings.apply_btn.clicked.connect(self._apply_settings)
        self.settings.threshold_spin.valueChanged.connect(self.radar.set_threshold)
        self.settings.sweep_speed_slider.valueChanged.connect(
            lambda v: self.radar.set_sweep_speed(float(v)))
        self.settings.blink_slider.valueChanged.connect(
            lambda v: self.radar.set_blink_hz(float(v)))
        self.settings.lifetime_spin.valueChanged.connect(self.radar.set_blip_lifetime)

        # push initial values into the radar widget
        self._apply_settings()

    # ---------------------------------------------------------------- UI actions
    def _toggle_settings(self, checked):
        self.settings.setVisible(checked)

    def _apply_settings(self):
        s = self.settings
        self.radar.set_sector(s.start_spin.value(), s.end_spin.value())
        self.radar.set_threshold(s.threshold_spin.value())
        self.radar.set_max_range(s.range_spin.value())
        self.radar.set_velocity_scale(s.vel_scale_spin.value())
        self.radar.set_sweep_speed(float(s.sweep_speed_slider.value()))
        self.radar.set_blink_hz(float(s.blink_slider.value()))
        self.radar.set_blip_lifetime(s.lifetime_spin.value())

    def _toggle_connection(self, checked):
        if checked:
            ip = self.settings.ip_edit.text().strip() or "0.0.0.0"
            port = self.settings.port_spin.value()
            self.udp_thread = UdpReceiver(ip, port)
            self.udp_thread.set_emit_rate_hz(self.settings.rate_spin.value())
            self.udp_thread.data_received.connect(self._on_data)
            self.udp_thread.status_changed.connect(self._on_status)
            self.udp_thread.start()
            self.settings.connect_btn.setText("Disconnect")
            self.settings.ip_edit.setEnabled(False)
            self.settings.port_spin.setEnabled(False)
        else:
            if self.udp_thread:
                self.udp_thread.stop()
                self.udp_thread = None
            self.settings.connect_btn.setText("Connect / Listen")
            self.settings.ip_edit.setEnabled(True)
            self.settings.port_spin.setEnabled(True)
            self.radar.set_connected(False)
            self.status_label.setText("Not connected")

    # ---------------------------------------------------------------- slots
    def _on_data(self, signal_dbfs, doppler_hz, velocity_ms):
        self.radar.feed_data(signal_dbfs, doppler_hz, velocity_ms)
        self.status_label.setText(
            f"Signal Level = {signal_dbfs:.2f} dBFS | "
            f"Doppler = {doppler_hz:.2f} Hz | "
            f"Velocity = {velocity_ms:.3f} m/s"
        )

    def _on_status(self, message, is_error):
        self.radar.set_connected(not is_error and "Listening" in message)
        color = "#ff5555" if is_error else "#6dffb0"
        self.status_label.setStyleSheet(f"color: {color}; font-family: Consolas; padding-left: 12px;")
        self.status_label.setText(message)

    def closeEvent(self, event):
        if self.udp_thread:
            self.udp_thread.stop()
        event.accept()


# ------------------------------------------------------------------ #
#  Entry point
# ------------------------------------------------------------------ #
def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
