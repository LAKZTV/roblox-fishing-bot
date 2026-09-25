"""หน้าต่างควบคุมบอทตกปลา — ดับเบิลคลิก "เปิดบอทตกปลา.bat" หรือรัน: pythonw gui.py"""
import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

import fishing_bot as fb

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")

# (ชื่อตัวแปรใน fishing_bot, ป้าย, ค่าต่ำสุด, ค่าสูงสุด, ขั้น)
SETTINGS = [
    ("COLLECT_HOLD", "กด T ค้าง (วิ)", 1, 15, 0.5),
    ("CAST_TIMEOUT", "รอปลากินนานสุด (วิ)", 5, 120, 5),
    ("CAST_HOLD", "กดเหวี่ยงเบ็ด (วิ)", 0.05, 3, 0.05),
    ("GAIN", "ความแรงไล่โซน", 2, 20, 0.5),
]

BG, CARD, FG, MUTED = "#1e1f24", "#2a2c33", "#eceef2", "#9aa0ab"
GREEN, RED, BLUE = "#3fb96b", "#e0564f", "#4c8dff"


class App:
    def __init__(self, root):
        self.root = root
        self.logs = queue.Queue()
        fb._log_fn = lambda text: self.logs.put(time.strftime("%H:%M:%S ") + text)
        self.load_settings()

        root.title("บอทตกปลา")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TSpinbox", fieldbackground=CARD, background=CARD, foreground=FG,
                        arrowcolor=FG, bordercolor=CARD)

        pad = {"padx": 12}

        # ---- สถานะ ----
        top = tk.Frame(root, bg=BG)
        top.pack(fill="x", pady=(12, 4), **pad)
        self.dot = tk.Label(top, text="●", fg=MUTED, bg=BG, font=("Segoe UI", 16))
        self.dot.pack(side="left")
        self.status = tk.Label(top, text="หยุดอยู่", fg=FG, bg=BG, font=("Segoe UI", 13, "bold"),
                               anchor="w")
        self.status.pack(side="left", padx=6, fill="x", expand=True)

        self.info = tk.Label(root, text="", fg=MUTED, bg=BG, font=("Segoe UI", 9), anchor="w")
        self.info.pack(fill="x", **pad)

        # ---- ปุ่มเริ่ม/หยุด ----
        self.btn = tk.Button(root, text="▶  เริ่ม  (F6)", command=self.toggle, bg=GREEN, fg="white",
                             activebackground=GREEN, activeforeground="white", relief="flat",
                             font=("Segoe UI", 14, "bold"), cursor="hand2", height=1)
        self.btn.pack(fill="x", pady=10, ipady=6, **pad)

        # ---- ตัวนับ ----
        stats = tk.Frame(root, bg=BG)
        stats.pack(fill="x", **pad)
        self.stat_labels = {}
        for i, (key, name) in enumerate([("catches", "ได้ของ"), ("games", "มินิเกม"),
                                         ("casts", "เหวี่ยง"), ("misses", "พลาด")]):
            box = tk.Frame(stats, bg=CARD)
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0))
            stats.columnconfigure(i, weight=1)
            val = tk.Label(box, text="0", fg=FG, bg=CARD, font=("Segoe UI", 16, "bold"))
            val.pack(pady=(6, 0))
            tk.Label(box, text=name, fg=MUTED, bg=CARD, font=("Segoe UI", 9)).pack(pady=(0, 6))
            self.stat_labels[key] = val
        self.elapsed = tk.Label(root, text="", fg=MUTED, bg=BG, font=("Segoe UI", 9), anchor="w")
        self.elapsed.pack(fill="x", pady=(4, 0), **pad)

        # ---- ตั้งค่า ----
        sett = tk.LabelFrame(root, text=" ตั้งค่า ", fg=MUTED, bg=BG, bd=1, relief="groove",
                             font=("Segoe UI", 9))
        sett.pack(fill="x", pady=8, **pad)
        self.vars = {}
        for r, (name, label, lo, hi, step) in enumerate(SETTINGS):
            tk.Label(sett, text=label, fg=FG, bg=BG, font=("Segoe UI", 10), anchor="w") \
                .grid(row=r, column=0, sticky="w", padx=8, pady=3)
            var = tk.StringVar(value=f"{getattr(fb, name):g}")
            sp = ttk.Spinbox(sett, from_=lo, to=hi, increment=step, textvariable=var, width=7,
                             command=lambda n=name: self.apply(n))
            sp.grid(row=r, column=1, padx=8, pady=3, sticky="e")
            sp.bind("<FocusOut>", lambda e, n=name: self.apply(n))
            sp.bind("<Return>", lambda e, n=name: self.apply(n))
            self.vars[name] = var
        sett.columnconfigure(0, weight=1)

        # ---- ปุ่มแถบ ----
        row = tk.Frame(root, bg=BG)
        row.pack(fill="x", **pad)
        for text, cmd in [("หาแถบใหม่", self.find_bar), ("ลืมตำแหน่งแถบ", self.reset_bar)]:
            tk.Button(row, text=text, command=cmd, bg=CARD, fg=FG, activebackground=CARD,
                      activeforeground=FG, relief="flat", font=("Segoe UI", 9), cursor="hand2") \
                .pack(side="left", expand=True, fill="x", padx=(0, 6) if text == "หาแถบใหม่" else 0)
        self.topmost = tk.BooleanVar(value=True)
        tk.Checkbutton(root, text="อยู่บนสุดเสมอ", variable=self.topmost, command=self.set_topmost,
                       fg=MUTED, bg=BG, selectcolor=CARD, activebackground=BG,
                       activeforeground=FG, font=("Segoe UI", 9)).pack(anchor="w", pady=(6, 0), **pad)

        # ---- บันทึก ----
        self.log = tk.Text(root, height=9, width=46, bg=CARD, fg=FG, relief="flat",
                           font=("Consolas", 9), state="disabled", wrap="word")
        self.log.pack(fill="both", pady=(6, 4), **pad)
        tk.Label(root, text="F6 เริ่ม/หยุด  ·  F8 ตั้งแถบ (เมาส์ชี้แถบ)  ·  F7 ปิด",
                 fg=MUTED, bg=BG, font=("Segoe UI", 8)).pack(pady=(0, 10))

        self.started_at = None
        self.worker = threading.Thread(target=fb.main, daemon=True)
        self.worker.start()
        self.tick()

    # ---------- settings ----------
    def load_settings(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                for k, v in json.load(f).items():
                    if hasattr(fb, k):
                        setattr(fb, k, float(v))
        except Exception:
            pass

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                json.dump({n: getattr(fb, n) for n, *_ in SETTINGS}, f, indent=2)
        except Exception:
            pass

    def apply(self, name):
        lo, hi = next((lo, hi) for n, _, lo, hi, _ in SETTINGS if n == name)
        try:
            val = min(max(float(self.vars[name].get()), lo), hi)
        except ValueError:
            val = getattr(fb, name)
        setattr(fb, name, val)
        self.vars[name].set(f"{val:g}")
        self.save_settings()

    # ---------- actions ----------
    def toggle(self):
        fb.ctrl.toggle = True

    def find_bar(self):
        fb.ctrl.calibrate = True
        fb.log("กำลังหาแถบ... (ต้องมีแถบมินิเกมขึ้นอยู่)")

    def reset_bar(self):
        fb.ctrl.reset_bar = True

    def set_topmost(self):
        self.root.attributes("-topmost", self.topmost.get())

    def on_close(self):
        fb.ctrl.quit = True
        self.save_settings()
        self.root.after(200, self.root.destroy)

    # ---------- refresh ----------
    def tick(self):
        c = fb.ctrl
        while not self.logs.empty():
            self.log.configure(state="normal")
            self.log.insert("end", self.logs.get() + "\n")
            if int(self.log.index("end-1c").split(".")[0]) > 300:
                self.log.delete("1.0", "50.0")
            self.log.see("end")
            self.log.configure(state="disabled")

        self.status.configure(text=c.status)
        if c.running:
            self.dot.configure(fg=GREEN)
            self.btn.configure(text="■  หยุด  (F6)", bg=RED, activebackground=RED)
            self.started_at = self.started_at or time.time()
        else:
            self.dot.configure(fg=MUTED)
            self.btn.configure(text="▶  เริ่ม  (F6)", bg=GREEN, activebackground=GREEN)
            self.started_at = None
        self.info.configure(text=("เกม: เจอ Roblox" if c.game_found else "เกม: ไม่เจอหน้าต่าง Roblox")
                            + ("  ·  แถบ: จำตำแหน่งแล้ว" if c.has_bar else "  ·  แถบ: ยังไม่รู้ตำแหน่ง"))
        for key, lbl in self.stat_labels.items():
            lbl.configure(text=str(getattr(c, key)))
        if self.started_at:
            s = int(time.time() - self.started_at)
            self.elapsed.configure(text=f"ทำงานมาแล้ว {s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}")
        if not self.worker.is_alive() and not c.quit:
            self.root.destroy()   # กด F7 -> ปิดหน้าต่างด้วย
            return
        self.root.after(200, self.tick)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
