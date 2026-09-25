"""แอปบอทตกปลา (แท็บ บอท + ทดสอบ) — ดับเบิลคลิก "เปิดบอทตกปลา.bat" หรือรัน: pythonw gui.py"""
import json
import os
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk

from PIL import Image, ImageTk

import checker
import updater
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
GREEN, YELLOW, RED, BLUE = "#3fb96b", "#e3b341", "#e0564f", "#4c8dff"
LEVEL_COLOR = {"good": GREEN, "ok": YELLOW, "bad": RED, "none": MUTED}
FONT = "Segoe UI"
UPDATE_EVERY_MS = 30 * 60 * 1000   # เช็คอัปเดตซ้ำทุก 30 นาที


def button(parent, text, cmd, bg=CARD, size=9, bold=False):
    return tk.Button(parent, text=text, command=cmd, bg=bg, fg="white" if bg != CARD else FG,
                     activebackground=bg, activeforeground="white" if bg != CARD else FG,
                     relief="flat", cursor="hand2", font=(FONT, size, "bold" if bold else "normal"))


class App:
    def __init__(self, root):
        self.root = root
        self.logs = queue.Queue()
        self.log_line = lambda text: self.logs.put(time.strftime("%H:%M:%S ") + text)
        fb._log_fn = self.log_line
        self.auto_update = tk.BooleanVar(master=root, value=True)
        self.load_settings()
        self.closing = False
        self.update_ready = 0
        self.rec = None          # checker.Recorder ของการทดสอบล่าสุด
        self.test_mode = None    # None / "auto" / "manual"
        self.watcher = None

        root.title("บอทตกปลา")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self.on_close)

        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TNotebook", background=BG, borderwidth=0)
        style.configure("TNotebook.Tab", background=CARD, foreground=MUTED, padding=(18, 6),
                        font=(FONT, 10, "bold"), borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", BG)], foreground=[("selected", FG)])
        style.configure("TSpinbox", fieldbackground=CARD, background=CARD, foreground=FG,
                        arrowcolor=FG, bordercolor=CARD)

        # ---- ส่วนบน (ใช้ร่วม) ----
        top = tk.Frame(root, bg=BG)
        top.pack(fill="x", padx=12, pady=(12, 0))
        self.dot = tk.Label(top, text="●", fg=MUTED, bg=BG, font=(FONT, 16))
        self.dot.pack(side="left")
        self.status = tk.Label(top, text="หยุดอยู่", fg=FG, bg=BG, font=(FONT, 13, "bold"), anchor="w")
        self.status.pack(side="left", padx=6, fill="x", expand=True)
        self.info = tk.Label(root, text="", fg=MUTED, bg=BG, font=(FONT, 9), anchor="w")
        self.info.pack(fill="x", padx=12)
        self.update_bar = button(root, "", self.do_update, BLUE, 9, True)   # โชว์เมื่อมีอัปเดต

        nb = ttk.Notebook(root)
        nb.pack(fill="both", padx=8, pady=(8, 0))
        self.tab_bot = tk.Frame(nb, bg=BG)
        self.tab_test = tk.Frame(nb, bg=BG)
        nb.add(self.tab_bot, text="บอท")
        nb.add(self.tab_test, text="ทดสอบ")
        self.build_bot_tab(self.tab_bot)
        self.build_test_tab(self.tab_test)

        # ---- บันทึก (ใช้ร่วม) ----
        self.log = tk.Text(root, height=7, width=52, bg=CARD, fg=FG, relief="flat",
                           font=("Consolas", 9), state="disabled", wrap="word")
        self.log.pack(fill="both", padx=12, pady=(8, 4))
        bottom = tk.Frame(root, bg=BG)
        bottom.pack(fill="x", padx=12, pady=(0, 2))
        self.topmost = tk.BooleanVar(value=True)
        tk.Checkbutton(bottom, text="อยู่บนสุดเสมอ", variable=self.topmost, command=self.set_topmost,
                       fg=MUTED, bg=BG, selectcolor=CARD, activebackground=BG,
                       activeforeground=FG, font=(FONT, 8)).pack(side="left")
        tk.Label(bottom, text="F6 เริ่ม/หยุด · F8 ตั้งแถบ · F7 ปิด", fg=MUTED, bg=BG,
                 font=(FONT, 8)).pack(side="right")
        upd = tk.Frame(root, bg=BG)
        upd.pack(fill="x", padx=12, pady=(0, 10))
        self.version = tk.Label(upd, text="เวอร์ชัน " + updater.current_version(), fg=MUTED, bg=BG,
                                font=(FONT, 8))
        self.version.pack(side="left")
        tk.Checkbutton(upd, text="อัปเดตอัตโนมัติ", variable=self.auto_update, command=self.save_settings,
                       fg=MUTED, bg=BG, selectcolor=CARD, activebackground=BG,
                       activeforeground=FG, font=(FONT, 8)).pack(side="right")
        button(upd, "เช็คอัปเดต", lambda: self.check_update(manual=True), size=8).pack(side="right", padx=6)

        self.started_at = None
        self.worker = threading.Thread(target=fb.main, daemon=True)
        self.worker.start()
        self.tick()
        self.root.after(1500, self.check_update)

    # ================= แท็บบอท =================
    def build_bot_tab(self, t):
        pad = {"padx": 8}
        self.btn = button(t, "▶  เริ่ม  (F6)", self.toggle, GREEN, 14, True)
        self.btn.pack(fill="x", pady=10, ipady=6, **pad)

        stats = tk.Frame(t, bg=BG)
        stats.pack(fill="x", **pad)
        self.stat_labels = {}
        for i, (key, name) in enumerate([("catches", "ได้ของ"), ("games", "มินิเกม"),
                                         ("casts", "เหวี่ยง"), ("misses", "พลาด")]):
            box = tk.Frame(stats, bg=CARD)
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0))
            stats.columnconfigure(i, weight=1)
            val = tk.Label(box, text="0", fg=FG, bg=CARD, font=(FONT, 16, "bold"))
            val.pack(pady=(6, 0))
            tk.Label(box, text=name, fg=MUTED, bg=CARD, font=(FONT, 9)).pack(pady=(0, 6))
            self.stat_labels[key] = val
        self.elapsed = tk.Label(t, text="", fg=MUTED, bg=BG, font=(FONT, 9), anchor="w")
        self.elapsed.pack(fill="x", pady=(4, 0), **pad)

        sett = tk.LabelFrame(t, text=" ตั้งค่า ", fg=MUTED, bg=BG, bd=1, relief="groove", font=(FONT, 9))
        sett.pack(fill="x", pady=8, **pad)
        self.vars = {}
        for r, (name, label, lo, hi, step) in enumerate(SETTINGS):
            tk.Label(sett, text=label, fg=FG, bg=BG, font=(FONT, 10), anchor="w") \
                .grid(row=r, column=0, sticky="w", padx=8, pady=3)
            var = tk.StringVar(value=f"{getattr(fb, name):g}")
            sp = ttk.Spinbox(sett, from_=lo, to=hi, increment=step, textvariable=var, width=7,
                             command=lambda n=name: self.apply(n))
            sp.grid(row=r, column=1, padx=8, pady=3, sticky="e")
            sp.bind("<FocusOut>", lambda e, n=name: self.apply(n))
            sp.bind("<Return>", lambda e, n=name: self.apply(n))
            self.vars[name] = var
        sett.columnconfigure(0, weight=1)

        row = tk.Frame(t, bg=BG)
        row.pack(fill="x", pady=(0, 8), **pad)
        button(row, "หาแถบใหม่", self.find_bar).pack(side="left", expand=True, fill="x", padx=(0, 6))
        button(row, "ลืมตำแหน่งแถบ", self.reset_bar).pack(side="left", expand=True, fill="x")

    # ================= แท็บทดสอบ =================
    def build_test_tab(self, t):
        pad = {"padx": 8}
        tk.Label(t, text="เช็คว่าระบบจับภาพเกมของคุณได้แม่นแค่ไหน ก่อนใช้บอทจริง",
                 fg=MUTED, bg=BG, font=(FONT, 9), anchor="w").pack(fill="x", pady=(8, 4), **pad)

        r = tk.Frame(t, bg=BG)
        r.pack(fill="x", **pad)
        tk.Label(r, text="จำนวนรอบ", fg=FG, bg=BG, font=(FONT, 10)).pack(side="left")
        self.rounds_var = tk.StringVar(value="3")
        ttk.Spinbox(r, from_=1, to=20, increment=1, textvariable=self.rounds_var, width=4) \
            .pack(side="left", padx=6)

        self.btn_auto = button(t, "▶  ทดสอบอัตโนมัติ  (บอทเล่นเอง)", self.test_auto, BLUE, 11, True)
        self.btn_auto.pack(fill="x", pady=(8, 4), ipady=4, **pad)
        self.btn_manual = button(t, "👁  ทดสอบแบบเล่นเอง  (ดูจออย่างเดียว)", self.test_manual)
        self.btn_manual.pack(fill="x", ipady=3, **pad)
        self.test_phase = tk.Label(t, text="", fg=MUTED, bg=BG, font=(FONT, 9), anchor="w")
        self.test_phase.pack(fill="x", pady=(6, 0), **pad)

        self.rows = {}
        box = tk.Frame(t, bg=BG)
        box.pack(fill="x", pady=4, **pad)
        for key, name in [("idle", "1. รอปลากิน (ไม่จับผิด)"), ("minigame", "2. มินิเกม (ตัวขาว/โซน)"),
                          ("stable", "    ตัวขาวนิ่ง"), ("T", "3. ปุ่ม T")]:
            f = tk.Frame(box, bg=BG)
            f.pack(fill="x", pady=2)
            tk.Label(f, text=name, fg=FG if key != "stable" else MUTED, bg=BG, width=20, anchor="w",
                     font=(FONT, 10)).pack(side="left")
            c = tk.Canvas(f, width=100, height=12, bg=CARD, highlightthickness=0)
            c.pack(side="left", padx=6)
            v = tk.Label(f, text="-", fg=MUTED, bg=BG, width=5, anchor="e", font=(FONT, 10, "bold"))
            v.pack(side="left")
            d = tk.Label(f, text="", fg=MUTED, bg=BG, anchor="w", font=(FONT, 8))
            d.pack(side="left", padx=4)
            self.rows[key] = (c, v, d)

        self.overall = tk.Label(t, text="", fg=MUTED, bg=CARD, font=(FONT, 11, "bold"),
                                anchor="w", justify="left", wraplength=380)
        self.overall.pack(fill="x", pady=(6, 4), ipady=6, ipadx=8, **pad)
        self.preview = tk.Label(t, bg=CARD)
        self.preview.pack(pady=2, **pad)
        self.preview_cap = tk.Label(t, text="", fg=MUTED, bg=BG, font=(FONT, 8))
        self.preview_cap.pack(**pad)
        button(t, "เปิดโฟลเดอร์ภาพ (check/)", self.open_dir).pack(fill="x", pady=(4, 8), **pad)

    # ================= settings =================
    def load_settings(self):
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                for k, v in json.load(f).items():
                    if k == "AUTO_UPDATE":
                        self.auto_update.set(bool(v))
                    elif hasattr(fb, k):
                        setattr(fb, k, float(v))
        except Exception:
            pass

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
                data = {n: getattr(fb, n) for n, *_ in SETTINGS}
                data["AUTO_UPDATE"] = self.auto_update.get()
                json.dump(data, f, indent=2)
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

    # ================= actions: บอท =================
    def toggle(self):
        if self.test_mode == "manual":
            self.log_line("กำลังทดสอบแบบเล่นเองอยู่ — หยุดทดสอบก่อน")
            return
        if self.test_mode == "auto" and fb.ctrl.running:
            self.stop_test()
            return
        fb.ctrl.toggle = True

    def find_bar(self):
        fb.ctrl.calibrate = True
        self.log_line("กำลังหาแถบ... (ต้องมีแถบมินิเกมขึ้นอยู่)")

    def reset_bar(self):
        fb.ctrl.reset_bar = True

    # ================= actions: ทดสอบ =================
    def new_recorder(self, auto):
        try:
            n = max(1, int(float(self.rounds_var.get())))
        except ValueError:
            n = 3
        return checker.Recorder(self.log_line, target_rounds=n,
                                on_done=self.finish_auto if auto else self.finish_manual)

    def test_auto(self):
        if self.test_mode:
            self.stop_test()
            return
        if fb.ctrl.running:
            self.log_line("บอททำงานอยู่ — หยุดบอทก่อนแล้วค่อยเริ่มทดสอบ")
            return
        self.rec = self.new_recorder(auto=True)
        self.test_mode = "auto"
        fb.observer = self.rec
        self.log_line(f"เริ่มทดสอบอัตโนมัติ {self.rec.target} รอบ (บอทเล่นเอง)")
        fb.ctrl.toggle = True

    def finish_auto(self):          # เรียกจากเธรดบอทตอนครบรอบ
        fb.observer = None
        self.test_mode = None
        if fb.ctrl.running:
            fb.ctrl.toggle = True

    def test_manual(self):
        if self.test_mode:
            self.stop_test()
            return
        if fb.ctrl.running:
            self.log_line("บอททำงานอยู่ — หยุดบอทก่อนแล้วค่อยเริ่มทดสอบ")
            return
        self.rec = self.new_recorder(auto=False)
        self.test_mode = "manual"
        self.watcher = checker.Watcher(self.rec)
        threading.Thread(target=self.watcher.run, daemon=True).start()
        self.log_line(f"เริ่มทดสอบแบบเล่นเอง {self.rec.target} รอบ — ตกปลาเองได้เลย (โปรแกรมไม่กดอะไร)")

    def finish_manual(self):
        if self.watcher:
            self.watcher.stop = True
        self.test_mode = None

    def stop_test(self):
        mode, self.test_mode = self.test_mode, None
        if mode == "auto":
            fb.observer = None
            if fb.ctrl.running:
                fb.ctrl.toggle = True
        elif mode == "manual" and self.watcher:
            self.watcher.stop = True
        if self.rec:
            self.rec.save()
        self.log_line("หยุดทดสอบ")

    def open_dir(self):
        os.makedirs(checker.CHECK_DIR, exist_ok=True)
        os.startfile(checker.CHECK_DIR)

    def set_topmost(self):
        self.root.attributes("-topmost", self.topmost.get())

    def on_close(self):
        if self.test_mode:
            self.stop_test()
        fb.ctrl.quit = True
        self.save_settings()
        self.closing = True
        self.root.after(200, self.root.destroy)

    # ================= อัปเดต =================
    def check_update(self, manual=False):
        def work():
            try:
                n, msgs = updater.check()
            except Exception as e:
                if manual:
                    self.log_line(f"เช็คอัปเดตไม่ได้: {e}")
                return
            self.root.after(0, lambda: self.on_update_checked(n, msgs, manual))
        threading.Thread(target=work, daemon=True).start()
        if not manual:
            self.root.after(UPDATE_EVERY_MS, self.check_update)

    def on_update_checked(self, n, msgs, manual):
        if n == 0:
            if manual:
                self.log_line("เป็นเวอร์ชันล่าสุดแล้ว")
            return
        self.update_ready = n
        self.log_line(f"มีอัปเดตใหม่ {n} รายการ: " + " / ".join(msgs[:3]))
        idle = not fb.ctrl.running and self.test_mode is None
        if self.auto_update.get() and idle:
            self.do_update()
        else:
            self.update_bar.configure(text=f"⬇  มีอัปเดตใหม่ {n} รายการ — กดเพื่ออัปเดต")
            self.update_bar.pack(fill="x", padx=12, pady=(6, 0), ipady=3, after=self.info)

    def do_update(self):
        if fb.ctrl.running or self.test_mode:
            self.log_line("หยุดบอท/การทดสอบก่อน แล้วค่อยอัปเดต")
            return
        self.update_bar.configure(text="กำลังอัปเดต...", state="disabled")
        self.log_line("กำลังอัปเดต...")

        def work():
            try:
                msg = updater.apply()
            except Exception as e:
                self.root.after(0, lambda: (self.log_line(str(e)),
                                            self.update_bar.configure(state="normal",
                                                                      text="⬇  อัปเดตไม่สำเร็จ — กดลองใหม่")))
                return
            self.root.after(0, lambda: self.finish_update(msg))
        threading.Thread(target=work, daemon=True).start()

    def finish_update(self, msg):
        self.log_line(msg + " — กำลังเปิดแอปใหม่...")
        self.save_settings()
        fb.ctrl.quit = True
        self.closing = True
        self.root.after(800, lambda: (updater.restart(), self.root.destroy()))

    # ================= refresh =================
    def set_row(self, key, acc, detail):
        c, v, d = self.rows[key]
        c.delete("all")
        if acc is None:
            v.configure(text="-", fg=MUTED)
        else:
            col = GREEN if acc >= 90 else YELLOW if acc >= 70 else RED
            c.create_rectangle(0, 0, 100 * acc / 100, 12, fill=col, width=0)
            v.configure(text=f"{acc:.0f}%", fg=col)
        d.configure(text=detail)

    def tick(self):
        c = fb.ctrl
        while not self.logs.empty():
            self.log.configure(state="normal")
            self.log.insert("end", self.logs.get() + "\n")
            if int(self.log.index("end-1c").split(".")[0]) > 300:
                self.log.delete("1.0", "50.0")
            self.log.see("end")
            self.log.configure(state="disabled")

        # ---- ส่วนบน ----
        if self.test_mode == "manual":
            self.status.configure(text="ทดสอบแบบเล่นเอง")
            self.dot.configure(fg=BLUE)
        else:
            self.status.configure(text=("[ทดสอบ] " if self.test_mode == "auto" else "") + c.status)
            self.dot.configure(fg=(BLUE if self.test_mode else GREEN) if c.running else MUTED)
        self.info.configure(text=("เกม: เจอ Roblox" if c.game_found else "เกม: ไม่เจอหน้าต่าง Roblox")
                            + ("  ·  แถบ: จำตำแหน่งแล้ว" if c.has_bar or os.path.exists(fb.BAR_FILE)
                               else "  ·  แถบ: ยังไม่รู้ตำแหน่ง"))

        # ---- แท็บบอท ----
        if c.running:
            self.btn.configure(text="■  หยุด  (F6)", bg=RED, activebackground=RED)
            self.started_at = self.started_at or time.time()
        else:
            self.btn.configure(text="▶  เริ่ม  (F6)", bg=GREEN, activebackground=GREEN)
            self.started_at = None
        for key, lbl in self.stat_labels.items():
            lbl.configure(text=str(getattr(c, key)))
        if self.started_at:
            s = int(time.time() - self.started_at)
            self.elapsed.configure(text=f"ทำงานมาแล้ว {s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}")
        else:
            self.elapsed.configure(text="")

        # ---- แท็บทดสอบ ----
        if self.test_mode == "auto":          # ผู้เล่นกด F6 หยุดบอทกลางคัน -> หยุดทดสอบด้วย
            if c.running:
                self.auto_ran = True
            elif getattr(self, "auto_ran", False):
                self.stop_test()
        else:
            self.auto_ran = False
        busy = self.test_mode is not None
        self.btn_auto.configure(text="■  หยุดทดสอบ" if self.test_mode == "auto"
                                else "▶  ทดสอบอัตโนมัติ  (บอทเล่นเอง)",
                                bg=RED if self.test_mode == "auto" else BLUE,
                                activebackground=RED if self.test_mode == "auto" else BLUE,
                                state="disabled" if self.test_mode == "manual" else "normal")
        self.btn_manual.configure(text="■  หยุดทดสอบ" if self.test_mode == "manual"
                                  else "👁  ทดสอบแบบเล่นเอง  (ดูจออย่างเดียว)",
                                  state="disabled" if self.test_mode == "auto" else "normal")
        if self.rec:
            rep = self.rec.stats.summary()
            i, m, t = rep["idle"], rep["minigame"], rep["T"]
            self.set_row("idle", i["acc"], f"ผิด {i['false']}/{i['frames']} เฟรม")
            self.set_row("minigame", m["acc"], f"{m['hits']}/{m['frames']} เฟรม")
            self.set_row("stable", m["stable"], "")
            self.set_row("T", t["acc"], f"เจอ {t['found']}/{t['rounds']}"
                         + (f" · ~{t['wait']} วิ" if t["wait"] is not None else ""))
            level, text = checker.verdict(rep)
            o = "-" if rep["overall"] is None else f"{rep['overall']:.0f}%"
            self.overall.configure(text=f"ผลรวม {o}  ({rep['rounds']}/{self.rec.target} รอบ)\n{text}",
                                   fg=LEVEL_COLOR[level])
            if busy:
                phase = self.watcher.phase if self.test_mode == "manual" and self.watcher else c.status
                self.test_phase.configure(text=f"ตอนนี้: {phase}")
            else:
                self.test_phase.configure(text="ทดสอบเสร็จ/หยุดแล้ว — ผลอยู่ด้านล่าง")
            if self.rec.new_shot:
                kind, self.rec.new_shot = self.rec.new_shot, None
                try:
                    img = Image.open(self.rec.shots[kind])
                    img.thumbnail((380, 214))
                    self.photo = ImageTk.PhotoImage(img)
                    self.preview.configure(image=self.photo)
                    self.preview_cap.configure(text=f"{kind}.png — แดง=ตัวขาว/ปุ่ม T · เขียว=โซน · ฟ้า=แถบ")
                except Exception:
                    pass
        else:
            self.overall.configure(text="ยังไม่ได้ทดสอบ\nกด \"ทดสอบอัตโนมัติ\" แล้วรอให้บอทเล่นครบรอบ",
                                   fg=MUTED)

        if self.closing:
            return
        if not self.worker.is_alive():   # กด F7 -> ปิดหน้าต่างด้วย
            self.on_close()
            return
        self.root.after(200, self.tick)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
