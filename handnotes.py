#!/usr/bin/env python3

import configparser
import glob
import os
import shutil
import subprocess
import sys
from datetime import datetime

from PIL import Image, ImageDraw
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QPainter, QImage, QPixmap, QPen, QColor
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel
)

MAX_NOTES = 50
CONFIG_DIR = os.path.join(os.environ.get("HOME", ""), ".config", "handnotes")
DEFAULTS = {
    "ratio": "3", "x": "999", "y": "999", "width": "600", "height": "400",
    "bg_color": "#dd6", "control_bg": "#000", "button_bg": "#000",
    "button_fg": "#fff", "line_color": "black", "line_width": "3",
    "workspace": "1", "time_res": "50"
}


class ListManipulator:
    def __init__(self, maxsize):
        self._list, self._index, self.maxsize = [], -1, maxsize

    def add(self, item):
        self._list.append(item)
        if len(self._list) > self.maxsize:
            self._list.pop(0)
        self._index = len(self._list) - 1

    def previous(self):
        if self._index > 0:
            self._index -= 1
            return self._list[self._index]

    def next(self):
        if self._index < len(self._list) - 1:
            self._index += 1
            return self._list[self._index]


class Canvas(QLabel):
    def __init__(self, parent, cfg):
        super().__init__(parent)
        self.parent_app = parent
        self.cfg = cfg
        self.canvas_w, self.canvas_h = cfg["width"], cfg["height"]
        self.image = Image.new(
            "RGB",
            (self.canvas_w * cfg["ratio"], self.canvas_h * cfg["ratio"]),
            cfg["bg_color"]
        )
        self.draw = ImageDraw.Draw(self.image, "RGBA")
        self.last_x = self.last_y = None
        self.erasing = False
        self.setFixedSize(self.canvas_w, self.canvas_h)
        self.setMouseTracking(True)
        self._base_pixmap = None
        self._pending_lines = []
        self._update_timer = QTimer()
        self._update_timer.setInterval(cfg["time_res"])
        self._update_timer.timeout.connect(self._flush_and_continue)
        self._overlay_pen = self._create_overlay_pen()
        self._rebuild_base_pixmap()

    def _create_overlay_pen(self):
        pen = QPen(QColor(self.cfg["line_color"]))
        pen.setWidth(max(1, self.cfg["line_width"] // self.cfg["ratio"]))
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        return pen

    def _rebuild_base_pixmap(self):
        img = self.image.resize(
            (self.canvas_w, self.canvas_h), resample=Image.BILINEAR
        )
        data = img.convert("RGBA").tobytes("raw", "RGBA")
        qimg = QImage(data, self.canvas_w, self.canvas_h,
                      QImage.Format_RGBA8888)
        self._base_pixmap = QPixmap.fromImage(qimg)
        self._pending_lines.clear()
        self.setPixmap(self._base_pixmap)

    def _flush_to_image(self):
        if not self._pending_lines:
            return
        r = self.cfg["ratio"]
        for x1, y1, x2, y2 in self._pending_lines:
            self.draw.line(
                [x1 * r, y1 * r, x2 * r, y2 * r],
                fill=self.cfg["line_color"],
                width=self.cfg["line_width"],
                joint="curve"
            )
        self._rebuild_base_pixmap()

    def _flush_and_continue(self):
        self._flush_to_image()
        self._sample_mouse_position()

    def _sample_mouse_position(self):
        pos = self.mapFromGlobal(self.cursor().pos())
        x, y = pos.x(), pos.y()
        if not (0 <= x < self.canvas_w and 0 <= y < self.canvas_h):
            return
        if self.last_x is not None:
            if self.erasing:
                self._erase_at(x * self.cfg["ratio"], y * self.cfg["ratio"])
                self._rebuild_base_pixmap()
            else:
                self._pending_lines.append((self.last_x, self.last_y, x, y))
                self._draw_overlay()
        self.last_x, self.last_y = x, y

    def mouseMoveEvent(self, event):
        pass

    def _draw_overlay(self):
        if self._base_pixmap is None:
            return
        pixmap = self._base_pixmap.copy()
        painter = QPainter(pixmap)
        painter.setPen(self._overlay_pen)
        painter.setRenderHint(QPainter.Antialiasing)
        for x1, y1, x2, y2 in self._pending_lines:
            painter.drawLine(x1, y1, x2, y2)
        painter.end()
        self.setPixmap(pixmap)

    def mouseReleaseEvent(self, event):
        self._update_timer.stop()
        self._flush_to_image()
        self.last_x = self.last_y = None
        if event.button() == Qt.RightButton:
            self.erasing = False
        self.parent_app.save_note()

    def mousePressEvent(self, event):
        if event.button() == Qt.RightButton:
            self.erasing = True
        self.last_x, self.last_y = event.x(), event.y()
        if not self._update_timer.isActive():
            self._update_timer.start()

    def _erase_at(self, x, y):
        r = self.cfg["line_width"] * 10
        self.draw.ellipse(
            [(x - r, y - r), (x + r, y + r)], fill=self.cfg["bg_color"]
        )

    def set_image(self, img):
        self.image = img
        self.draw = ImageDraw.Draw(self.image, "RGBA")
        self._rebuild_base_pixmap()


class NoteApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.cfg = self._load_config()
        self._setup_window()
        self.notes = ListManipulator(maxsize=MAX_NOTES)
        self._initialize_notes()
        self._load_last_note()
        QTimer.singleShot(2000, self._set_workspace)

    def _load_config(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        config_path = os.path.join(CONFIG_DIR, "handnotes.conf")
        config = configparser.ConfigParser()
        if os.path.exists(config_path):
            config.read(config_path)
            p = config["DEFAULT"]
        else:
            config["DEFAULT"] = DEFAULTS
            with open(config_path, "w") as f:
                config.write(f)
            p = DEFAULTS
        return {
            "ratio": int(p.get("ratio", 3)),
            "width": int(p.get("width", 600)),
            "height": int(p.get("height", 400)),
            "x": int(p.get("x", 999)),
            "y": int(p.get("y", 999)),
            "bg_color": p.get("bg_color", "#dd6"),
            "control_bg": p.get("control_bg", "#000"),
            "button_bg": p.get("button_bg", "#000"),
            "button_fg": p.get("button_fg", "#fff"),
            "line_color": p.get("line_color", "black"),
            "line_width": int(p.get("line_width", 3)),
            "workspace": int(p.get("workspace", 1)),
            "time_res": int(p.get("time_res", 50)),
        }

    def _setup_window(self):
        self.setWindowTitle("HandNotes")
        self.setWindowFlags(Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint)
        self.setWindowOpacity(0.5)
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self.canvas = Canvas(self, self.cfg)
        layout.addWidget(self.canvas)
        layout.addWidget(self._create_controls())
        self.setGeometry(
            self.cfg["x"], self.cfg["y"],
            self.cfg["width"], self.cfg["height"] + 20
        )

    def _create_controls(self):
        ctrl = QWidget()
        ctrl.setStyleSheet(f"background-color: {self.cfg['control_bg']};")
        layout = QHBoxLayout(ctrl)
        layout.setContentsMargins(1, 1, 1, 1)
        layout.setSpacing(1)
        buttons = [
            ("Save", self.save_note), ("Clear", self._clear_note),
            ("<", self._previous_note), (">", self._next_note),
            (None, None), ("Exit", self.close)
        ]
        style = (f"background-color:{self.cfg['button_bg']};"
                 f"color:{self.cfg['button_fg']};border:none;font-size:8px;")
        for text, cmd in buttons:
            if text is None:
                layout.addStretch()
                continue
            btn = QPushButton(text)
            btn.setFixedSize(35, 15)
            btn.setStyleSheet(style)
            btn.clicked.connect(cmd)
            layout.addWidget(btn)
        return ctrl

    def _initialize_notes(self):
        pattern = os.path.join(CONFIG_DIR, "note_*.png")
        for f in sorted(glob.glob(pattern), key=os.path.getmtime):
            try:
                self.notes.add(Image.open(f))
            except Exception as e:
                print(f"Error loading {f}: {e}")

    def _set_workspace(self):
        if shutil.which("wmctrl"):
            subprocess.run(
                ["wmctrl", "-r", "HandNotes", "-t", str(self.cfg["workspace"])]
            )

    def save_note(self):
        try:
            img = self.canvas.image.copy()
            self.notes.add(img)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            img.save(os.path.join(CONFIG_DIR, f"note_{ts}.png"))
            files = sorted(
                [f for f in os.listdir(CONFIG_DIR) if f.endswith(".png")],
                key=lambda x: os.path.getmtime(os.path.join(CONFIG_DIR, x))
            )
            for old in files[:-MAX_NOTES]:
                os.remove(os.path.join(CONFIG_DIR, old))
        except Exception as e:
            print(f"Error saving: {e}")

    def _clear_note(self):
        c = self.cfg
        self.canvas.image = Image.new(
            "RGB", (c["width"] * c["ratio"], c["height"] * c["ratio"]),
            c["bg_color"]
        )
        self.canvas.draw = ImageDraw.Draw(self.canvas.image, "RGBA")
        self.canvas._rebuild_base_pixmap()
        self.save_note()

    def _load_last_note(self):
        files = glob.glob(os.path.join(CONFIG_DIR, "note_*.png"))
        if files:
            try:
                self.canvas.set_image(
                    Image.open(max(files, key=os.path.getmtime))
                )
            except Exception as e:
                print(f"Error loading: {e}")

    def _previous_note(self):
        if img := self.notes.previous():
            self.canvas.set_image(img.copy())

    def _next_note(self):
        if img := self.notes.next():
            self.canvas.set_image(img.copy())


def main():
    app = QApplication(sys.argv)
    window = NoteApp()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
