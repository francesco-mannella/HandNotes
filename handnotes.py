#!/usr/bin/env python3

import configparser
import glob
import os
import threading
import tkinter as tk
from datetime import datetime

from PIL import Image, ImageDraw, ImageTk


def clip(x, mn, mx):
    return max(mn, min(mx, x))


class NoteApp:
    def __init__(self, root):
        self.root = root
        self.load_params()
        self.root.title("Draw Note")
        self.root.geometry(f"{self.width}x{self.height}+{self.x}+{self.y}")
        self.root.attributes("-topmost", 0)
        self.root.attributes("-alpha", 0.5)
        self.root.wm_attributes("-type", "splash")
        self.canvas = tk.Canvas(
            root,
            bg=self.bg_color,
            highlightthickness=0,
            width=self.width // self.ratio,
            height=self.height // self.ratio,
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        self.image = Image.new(
            "RGB",
            (self.width * self.ratio, self.height * self.ratio),
            self.bg_color,
        )
        self.draw = ImageDraw.Draw(self.image, "RGBA")
        self.last_x = self.last_y = None
        self.space_pressed = False
        self.canvas.bind("<B1-Motion>", self.draw_note)
        self.canvas.bind("<ButtonRelease-1>", self.reset_last_coords)
        self.canvas.bind("<ButtonPress-3>", self.on_start_erase)
        self.canvas.bind("<ButtonRelease-3>", self.on_end_erase)
        self.control_frame = tk.Frame(root, bg=self.control_bg)
        self.control_frame.pack(side=tk.BOTTOM, fill=tk.X)
        self.create_buttons()
        self.tk_img = None
        self.note_on = False
        self.load_last_note()
        self.update_canvas()

    def load_params(self):
        config_dir = os.path.join(
            os.environ.get("HOME", ""), ".config", "handnotes"
        )
        os.makedirs(config_dir, exist_ok=True)
        config_path = os.path.join(config_dir, "handnotes.conf")
        config = configparser.ConfigParser()
        defaults = {
            "ratio": "3",
            "x": "999",
            "y": "999",
            "width": "600",
            "height": "400",
            "bg_color": "#dd6",
            "control_bg": "#000",
            "button_bg": "#000",
            "button_fg": "#fff",
            "line_color": "black",
            "line_width": "3",
        }
        if os.path.exists(config_path):
            config.read(config_path)
            params = config["DEFAULT"]
        else:
            config["DEFAULT"] = defaults
            with open(config_path, "w") as f:
                config.write(f)
            params = defaults
        self.ratio = int(params.get("ratio", defaults["ratio"]))
        self.width = int(params.get("width", defaults["width"]))
        self.height = int(params.get("height", defaults["height"]))
        self.x = int(params.get("x", defaults["x"]))
        self.y = int(params.get("y", defaults["y"]))
        self.bg_color = params.get("bg_color", defaults["bg_color"])
        self.control_bg = params.get("control_bg", defaults["control_bg"])
        self.button_bg = params.get("button_bg", defaults["button_bg"])
        self.button_fg = params.get("button_fg", defaults["button_fg"])
        self.line_color = params.get("line_color", defaults["line_color"])
        self.line_width = int(params.get("line_width", defaults["line_width"]))
        ws, hs = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.x = clip(self.x, 1, ws - self.width)
        self.y = clip(self.y, 1, hs - self.height)
        self.notes_dir = config_dir

    def create_buttons(self):
        buttons = [
            ("Save", self.save_note, tk.LEFT),
            ("Clear", self.clear_note, tk.LEFT),
            ("Exit", self.root.quit, tk.RIGHT),
        ]
        for text, cmd, side in buttons:
            tk.Button(
                self.control_frame,
                text=text,
                borderwidth=0,
                command=cmd,
                bg=self.button_bg,
                fg=self.button_fg,
                relief=tk.FLAT,
                width=5,
                height=1,
                font=("TkDefaultFont", 6),
            ).pack(side=side, padx=1, pady=1)

    def draw_note(self, event):
        x, y = event.x * self.ratio, event.y * self.ratio
        if self.space_pressed:
            self.erase(x, y)
        else:
            if self.last_x is not None and self.last_y is not None:
                self.draw.line(
                    [self.last_x, self.last_y, x, y],
                    fill=self.line_color,
                    width=self.line_width,
                    joint="curve",
                )
        self.last_x, self.last_y = x, y
        self.update_canvas()

        if self.note_on is False:
            self.note_on = True
            self.timer = threading.Timer(10, self.timer_callback).start()

    def erase(self, x, y):
        erase_radius = self.line_width * 10
        left_up = (x - erase_radius, y - erase_radius)
        right_down = (x + erase_radius, y + erase_radius)
        self.draw.ellipse(
            [left_up, right_down], fill=self.bg_color, outline=None
        )

    def timer_callback(self):
        self.save_note()
        self.note_on = False

    def load_last_note(self):
        pattern = os.path.join(self.notes_dir, "note_*.png")
        files = glob.glob(pattern)
        if not files:
            print("No saved notes found.")
            return False
        last_file = max(files, key=os.path.getmtime)
        try:
            loaded_img = Image.open(last_file)
            self.image = loaded_img.copy()
            self.draw = ImageDraw.Draw(self.image, "RGBA")
            self.update_canvas()
            print(f"Loaded note: {last_file}")
            return True
        except Exception as e:
            print(f"Error loading last note: {e}")
            return False

    def save_note(self):
        try:
            img = self.image.resize(
                (self.width * self.ratio, self.height * self.ratio),
                resample=Image.LANCZOS,
            )
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = os.path.join(self.notes_dir, f"note_{timestamp}.png")
            img.save(filename)
            print(f"Note saved as {filename}")
            images = sorted(
                [f for f in os.listdir(self.notes_dir) if f.endswith(".png")],
                key=lambda x: os.path.getmtime(
                    os.path.join(self.notes_dir, x)
                ),
            )
            for old_img in images[:-50]:
                os.remove(os.path.join(self.notes_dir, old_img))

        except Exception as e:
            print(f"Error saving note: {e}")

    def clear_note(self):
        self.image = Image.new(
            "RGB",
            (self.width * self.ratio, self.height * self.ratio),
            self.bg_color,
        )
        self.draw = ImageDraw.Draw(self.image, "RGBA")
        self.update_canvas()
        print("Note cleared")

    def update_canvas(self):
        img = self.image.resize(
            (self.width, self.height), resample=Image.LANCZOS
        )
        self.tk_img = ImageTk.PhotoImage(img)
        self.canvas.create_image(0, 0, anchor=tk.NW, image=self.tk_img)

    def reset_last_coords(self, event):
        self.last_x = self.last_y = None

    def on_start_erase(self, event):
        self.space_pressed = True

    def on_end_erase(self, event):
        self.space_pressed = False


def main():
    root = tk.Tk()
    app = NoteApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
