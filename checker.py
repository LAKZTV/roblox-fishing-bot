"""
ทดสอบการจับภาพ (แยกจากบอท) — ดูหน้าจออย่างเดียว ไม่คลิก ไม่กดปุ่มใดๆ
ให้ผู้เล่นตกปลาเองตามปกติ แล้วโปรแกรมจะวัดว่าระบบจับภาพแต่ละช่วงได้แม่นแค่ไหน:
  1) รอปลากิน   : ต้องไม่จับแถบผิดทั้งที่ยังไม่มีมินิเกม
  2) มินิเกม    : จับตัวขาว + โซนได้กี่ % ของเฟรม และตัวขาวนิ่งแค่ไหน
  3) ปุ่ม T      : หลังมินิเกมจบ เจอปุ่ม T ไหม ใช้เวลากี่วิ และจับได้สม่ำเสมอไหม
พร้อมแคปภาพแต่ละช่วง (วาดกรอบสิ่งที่จับได้) ไว้ในโฟลเดอร์ check/

รัน: ดับเบิลคลิก "ทดสอบการจับภาพ.bat"  หรือ  pythonw checker.py
"""
import json
import os
import queue
import threading
import time
import tkinter as tk

import mss
import numpy as np
from PIL import Image, ImageDraw, ImageTk

import fishing_bot as fb

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK_DIR = os.path.join(HERE, "check")
T_WAIT = 8.0          # มินิเกมจบแล้วรอดูปุ่ม T นานสุดกี่วินาที
FPS = 30

BG, CARD, FG, MUTED = "#1e1f24", "#2a2c33", "#eceef2", "#9aa0ab"
GREEN, YELLOW, RED, BLUE = "#3fb96b", "#e3b341", "#e0564f", "#4c8dff"


# ================= ตัววัดผล =================
class Stats:
    def __init__(self):
        self.idle_frames = self.idle_false = 0
        self.game_frames = self.game_hits = 0
        self.white_h = []
        self.rounds = 0
        self.t_rounds = self.t_found = 0
        self.t_checks = self.t_hits = 0
        self.t_waits = []

    @staticmethod
    def pct(a, b):
        return round(100 * a / b, 1) if b else None

    def summary(self):
        stable = None
        if len(self.white_h) > 5:
            m = float(np.mean(self.white_h))
            stable = round(max(0.0, 100 * (1 - float(np.std(self.white_h)) / max(m, 1))), 1)
        t_acc = None
        if self.t_rounds:
            found = self.t_found / self.t_rounds
            steady = self.t_hits / self.t_checks if self.t_checks else 0
            t_acc = round(100 * found * steady, 1)
        rep = {
            "rounds": self.rounds,
            "idle": {"frames": self.idle_frames, "false": self.idle_false,
                     "acc": self.pct(self.idle_frames - self.idle_false, self.idle_frames)},
            "minigame": {"frames": self.game_frames, "hits": self.game_hits,
                         "acc": self.pct(self.game_hits, self.game_frames), "stable": stable},
            "T": {"rounds": self.t_rounds, "found": self.t_found,
                  "steady": self.pct(self.t_hits, self.t_checks), "acc": t_acc,
                  "wait": round(float(np.mean(self.t_waits)), 1) if self.t_waits else None},
        }
        accs = [v["acc"] for v in (rep["idle"], rep["minigame"], rep["T"]) if v["acc"] is not None]
        rep["overall"] = round(min(accs), 1) if accs else None   # ใช้ช่วงที่แย่สุดเป็นตัวตัดสิน
        return rep


def verdict(rep):
    o = rep["overall"]
    if rep["rounds"] == 0 or o is None:
        return MUTED, "ยังไม่มีข้อมูล — ตกปลาเองให้ครบอย่างน้อย 1 รอบ"
    if o >= 95:
        return GREEN, "ดีมาก — ระบบจับภาพได้แม่น ใช้บอทได้เลย"
    if o >= 85:
        return GREEN, "ดี — ใช้บอทได้ อาจพลาดบ้างเล็กน้อย"
    if o >= 70:
        return YELLOW, "พอใช้ — ใช้ได้แต่อาจพลาดบ่อย ลองดูภาพใน check/"
    return RED, "ควรปรับก่อนใช้ — ส่งภาพใน check/ มาให้ช่วยดู"


# ================= ตัวดูหน้าจอ (ไม่ส่ง input ใดๆ) =================
class Watcher:
    def __init__(self, log):
        self.log = log
        self.stats = Stats()
        self.phase = "รอ"
        self.active = False
        self.quit = False
        self.shots = {}
        self.new_shot = None

    def snapshot(self, sct, game, cfg, kind, res=None, t_origin=None):
        shot = sct.grab(game)
        img = Image.frombytes("RGB", shot.size, shot.rgb)
        d = ImageDraw.Draw(img)
        if cfg:
            b = fb.bar_region(cfg, game)
            bx, bw = b["left"] - game["left"], b["width"]
            d.rectangle([bx, 0, bx + bw, game["height"] - 1], outline=(76, 141, 255), width=2)
            if res:
                wy, zt, zb = res
                d.rectangle([bx - 4, zt, bx + bw + 4, zb], outline=(63, 220, 107), width=3)
                w0, w1 = int(wy) - 10, int(wy) + 10
                d.rectangle([bx + bw // 4, w0, bx + bw * 3 // 4, w1], outline=(255, 80, 80), width=3)
        if t_origin and fb_T_box[0]:
            x, y, w, h = fb_T_box[0]
            ox, oy = t_origin
            d.rectangle([ox + x - 4, oy + y - 4, ox + x + w + 4, oy + y + h + 4],
                        outline=(255, 80, 80), width=3)
        os.makedirs(CHECK_DIR, exist_ok=True)
        path = os.path.join(CHECK_DIR, f"{kind}.png")
        img.save(path)
        self.shots[kind] = path
        self.new_shot = kind

    def run(self):
        st = self.stats
        cfg = None
        if os.path.exists(fb.BAR_FILE):
            with open(fb.BAR_FILE) as f:
                data = json.load(f)
            if "x1" in data:
                cfg = data
        cand, cand_n, last_scan = None, 0, 0.0
        playing, hits, streak, last_seen = False, 0, 0, 0.0
        idle_shot_at = 0

        with mss.mss() as sct:
            while not self.quit:
                if not self.active:
                    self.phase = "หยุดอยู่"
                    time.sleep(0.1)
                    continue
                _, game = fb.game_window()
                if game is None:
                    self.phase = "หาหน้าต่าง Roblox ไม่เจอ"
                    time.sleep(0.3)
                    continue
                S = game["height"] / 1080
                now = time.perf_counter()

                # ---- ยังไม่รู้ตำแหน่งแถบ ----
                if cfg is None:
                    self.phase = "รอแถบมินิเกมขึ้นครั้งแรก (เพื่อหาตำแหน่งแถบ)"
                    if now - last_scan > 0.3:
                        last_scan = now
                        c = fb.calibrate(sct, game)
                        if c and cand and abs(c["x1"] - cand["x1"]) < 0.01:
                            cand_n += 1
                        else:
                            cand_n = 1 if c else 0
                        cand = c
                        if cand_n >= 3:
                            cfg = cand
                            fb.save_cfg(cfg)
                            self.log("เจอตำแหน่งแถบแล้ว เริ่มวัดผล")
                    time.sleep(0.02)
                    continue

                res = fb.detect(fb.to_rgb(sct.grab(fb.bar_region(cfg, game))), S)

                if not playing:
                    self.phase = "รอปลากิน (ตรวจว่าไม่จับผิด)"
                    st.idle_frames += 1
                    idle_shot_at += 1
                    if res:
                        streak += 1
                    else:
                        if streak == 1:            # เจอเฟรมเดียวแล้วหาย = จับผิด
                            st.idle_false += 1
                            self.log("⚠ จับแถบผิด 1 เฟรม ตอนยังไม่มีมินิเกม")
                        streak = 0
                    if idle_shot_at == FPS * 3:
                        self.snapshot(sct, game, cfg, "1_รอปลากิน")
                    if streak >= 2:
                        playing, streak, hits, last_seen = True, 0, 0, now
                        st.idle_frames -= 2            # 2 เฟรมนี้คือมินิเกมจริง
                        st.game_frames += 2
                        st.game_hits += 2
                        self.log("มินิเกมขึ้น — กำลังวัดการจับตัวขาว/โซน")
                else:
                    self.phase = "มินิเกม (วัดการจับตัวขาว/โซน)"
                    if res:
                        st.game_frames += hits + 1     # นับเฟรมที่พลาดกลางเกมด้วย
                        st.game_hits += 1
                        hits = 0
                        last_seen = now
                        st.white_h.append(white_height(sct, game, cfg, S))
                        if st.game_hits % 60 == 20:
                            self.snapshot(sct, game, cfg, "2_มินิเกม", res)
                    else:
                        hits += 1                      # พลาดติดกัน (ถ้าจบเกมจะไม่นับ)
                        if now - last_seen > fb.LOST_TIMEOUT:
                            playing = False
                            st.rounds += 1
                            self.log(f"มินิเกมจบ (รอบที่ {st.rounds}) — รอดูปุ่ม T")
                            self.watch_T(sct, game, S)
                            idle_shot_at = 0
                time.sleep(1 / FPS)

    def watch_T(self, sct, game, S):
        st = self.stats
        self.phase = "รอปุ่ม T (หลังมินิเกม)"
        center = {"left": game["left"] + int(game["width"] * 0.3),
                  "top": game["top"] + int(game["height"] * 0.2),
                  "width": int(game["width"] * 0.4), "height": int(game["height"] * 0.6)}
        origin = (int(game["width"] * 0.3), int(game["height"] * 0.2))
        seen = lambda: find_T_box(fb.to_rgb(sct.grab(center)), S)
        st.t_rounds += 1
        t0 = time.perf_counter()
        while not seen():
            if self.quit or not self.active:
                return
            if time.perf_counter() - t0 > T_WAIT:
                self.log(f"⚠ ไม่เห็นปุ่ม T ภายใน {T_WAIT:g} วิ")
                self.snapshot(sct, game, None, "3_ปุ่ม_T")
                return
            time.sleep(0.05)
        wait = time.perf_counter() - t0
        st.t_found += 1
        st.t_waits.append(wait)
        self.snapshot(sct, game, None, "3_ปุ่ม_T", t_origin=origin)
        n = 0
        for _ in range(10):                 # เช็คซ้ำ 10 เฟรม (0.5 วิ) ว่าจับได้สม่ำเสมอไหม
            n += bool(seen())
            time.sleep(0.05)
        st.t_checks += 10
        st.t_hits += n
        self.log(f"เจอปุ่ม T หลังมินิเกมจบ {wait:.1f} วิ (จับซ้ำได้ {n}/10)")
        # รอให้ผู้เล่นเก็บของจนปุ่มหาย ก่อนกลับไปวัดช่วงรอปลากิน
        t1 = time.perf_counter()
        while seen() and time.perf_counter() - t1 < 15 and self.active and not self.quit:
            time.sleep(0.2)


fb_T_box = [None]


def find_T_box(img, S):
    """เหมือน fb.find_T แต่จำตำแหน่งปุ่มไว้วาดกรอบ"""
    for sl, comp in fb.blobs(img.min(-1) > 200):
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if not (8 * S <= w <= 60 * S and 8 * S <= h <= 60 * S and 0.75 <= w / h <= 1.33):
            continue
        filled = fb.ndimage.binary_fill_holes(comp)
        fill = filled.mean()
        holes = (filled & ~comp).sum() / filled.sum()
        if 0.65 <= fill <= 0.88 and holes >= 0.03:
            fb_T_box[0] = (sl[1].start, sl[0].start, w, h)
            return True
    return False


def white_height(sct, game, cfg, S):
    """ความสูงตัวขาว (ใช้วัดว่าจับตัวขาวได้นิ่งไหม)"""
    strip = fb.to_rgb(sct.grab(fb.bar_region(cfg, game)))
    w = strip.shape[1]
    q = max(w // 4, 2)
    white, _ = fb.masks(strip)
    rows = np.where(white[:, q:w - q].mean(1) > 0.3)[0]
    if len(rows) == 0:
        return 0
    return len(max(fb.groups_of(rows), key=len))


# ================= หน้าต่าง =================
class App:
    def __init__(self, root):
        self.root = root
        self.logs = queue.Queue()
        self.w = Watcher(lambda t: self.logs.put(time.strftime("%H:%M:%S ") + t))
        fb._log_fn = lambda t: None

        root.title("ทดสอบการจับภาพ")
        root.configure(bg=BG)
        root.resizable(False, False)
        root.attributes("-topmost", True)
        root.protocol("WM_DELETE_WINDOW", self.close)
        pad = {"padx": 12}

        tk.Label(root, text="ทดสอบการจับภาพ", fg=FG, bg=BG, font=("Segoe UI", 14, "bold"),
                 anchor="w").pack(fill="x", pady=(12, 0), **pad)
        tk.Label(root, text="ดูหน้าจออย่างเดียว ไม่คลิก/ไม่กดปุ่ม — ตกปลาเองตามปกติ 2-3 รอบ",
                 fg=MUTED, bg=BG, font=("Segoe UI", 9), anchor="w").pack(fill="x", **pad)

        self.btn = tk.Button(root, text="▶  เริ่มทดสอบ", command=self.toggle, bg=BLUE, fg="white",
                             activebackground=BLUE, activeforeground="white", relief="flat",
                             font=("Segoe UI", 13, "bold"), cursor="hand2")
        self.btn.pack(fill="x", pady=10, ipady=5, **pad)
        self.phase = tk.Label(root, text="", fg=FG, bg=BG, font=("Segoe UI", 10), anchor="w")
        self.phase.pack(fill="x", **pad)

        # ---- แถบผลแต่ละช่วง ----
        self.rows = {}
        box = tk.Frame(root, bg=BG)
        box.pack(fill="x", pady=6, **pad)
        for key, name in [("idle", "1. รอปลากิน (ไม่จับผิด)"), ("minigame", "2. มินิเกม (ตัวขาว/โซน)"),
                          ("stable", "   ตัวขาวนิ่ง"), ("T", "3. ปุ่ม T")]:
            f = tk.Frame(box, bg=BG)
            f.pack(fill="x", pady=2)
            tk.Label(f, text=name, fg=FG if key != "stable" else MUTED, bg=BG, width=22, anchor="w",
                     font=("Segoe UI", 10)).pack(side="left")
            c = tk.Canvas(f, width=120, height=12, bg=CARD, highlightthickness=0)
            c.pack(side="left", padx=6)
            v = tk.Label(f, text="-", fg=FG, bg=BG, width=7, anchor="e", font=("Segoe UI", 10, "bold"))
            v.pack(side="left")
            d = tk.Label(f, text="", fg=MUTED, bg=BG, anchor="w", font=("Segoe UI", 8))
            d.pack(side="left", padx=4)
            self.rows[key] = (c, v, d)

        self.overall = tk.Label(root, text="", fg=FG, bg=CARD, font=("Segoe UI", 11, "bold"),
                                anchor="w", justify="left", wraplength=400)
        self.overall.pack(fill="x", pady=(6, 4), ipady=8, ipadx=8, **pad)

        # ---- ภาพล่าสุด ----
        self.preview = tk.Label(root, bg=CARD)
        self.preview.pack(pady=4, **pad)
        self.preview_cap = tk.Label(root, text="", fg=MUTED, bg=BG, font=("Segoe UI", 8))
        self.preview_cap.pack(**pad)

        row = tk.Frame(root, bg=BG)
        row.pack(fill="x", pady=4, **pad)
        for text, cmd in [("เปิดโฟลเดอร์ภาพ", self.open_dir), ("ล้างผล", self.reset),
                          ("ลืมตำแหน่งแถบ", self.forget_bar)]:
            tk.Button(row, text=text, command=cmd, bg=CARD, fg=FG, activebackground=CARD,
                      activeforeground=FG, relief="flat", font=("Segoe UI", 9), cursor="hand2") \
                .pack(side="left", expand=True, fill="x", padx=2)

        self.log = tk.Text(root, height=7, width=58, bg=CARD, fg=FG, relief="flat",
                           font=("Consolas", 9), state="disabled", wrap="word")
        self.log.pack(fill="both", pady=(4, 12), **pad)

        self.thread = threading.Thread(target=self.w.run, daemon=True)
        self.thread.start()
        self.tick()

    def toggle(self):
        self.w.active = not self.w.active
        self.logs.put(time.strftime("%H:%M:%S ") + ("เริ่มทดสอบ" if self.w.active else "หยุดทดสอบ"))

    def reset(self):
        self.w.stats = Stats()
        self.logs.put(time.strftime("%H:%M:%S ") + "ล้างผลแล้ว")

    def forget_bar(self):
        if os.path.exists(fb.BAR_FILE):
            os.remove(fb.BAR_FILE)
        self.logs.put(time.strftime("%H:%M:%S ") + "ลืมตำแหน่งแถบแล้ว (เริ่มทดสอบใหม่เพื่อหาอีกครั้ง)")

    def open_dir(self):
        os.makedirs(CHECK_DIR, exist_ok=True)
        os.startfile(CHECK_DIR)

    def close(self):
        self.w.quit = True
        self.save_report()
        self.root.after(150, self.root.destroy)

    def save_report(self):
        rep = self.w.stats.summary()
        rep["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        rep["verdict"] = verdict(rep)[1]
        os.makedirs(CHECK_DIR, exist_ok=True)
        with open(os.path.join(CHECK_DIR, "report.json"), "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)

    def set_row(self, key, acc, detail):
        c, v, d = self.rows[key]
        c.delete("all")
        if acc is None:
            v.configure(text="-", fg=MUTED)
        else:
            col = GREEN if acc >= 90 else YELLOW if acc >= 70 else RED
            c.create_rectangle(0, 0, 120 * acc / 100, 12, fill=col, width=0)
            v.configure(text=f"{acc:.0f}%", fg=col)
        d.configure(text=detail)

    def tick(self):
        while not self.logs.empty():
            self.log.configure(state="normal")
            self.log.insert("end", self.logs.get() + "\n")
            self.log.see("end")
            self.log.configure(state="disabled")

        a = self.w.active
        self.btn.configure(text="■  หยุดทดสอบ" if a else "▶  เริ่มทดสอบ",
                           bg=RED if a else BLUE, activebackground=RED if a else BLUE)
        self.phase.configure(text="ตอนนี้: " + self.w.phase)

        rep = self.w.stats.summary()
        i, m, t = rep["idle"], rep["minigame"], rep["T"]
        self.set_row("idle", i["acc"], f"จับผิด {i['false']}/{i['frames']} เฟรม")
        self.set_row("minigame", m["acc"], f"{m['hits']}/{m['frames']} เฟรม")
        self.set_row("stable", m["stable"], "")
        self.set_row("T", t["acc"], f"เจอ {t['found']}/{t['rounds']} รอบ"
                     + (f" · ~{t['wait']} วิ" if t["wait"] is not None else ""))
        col, text = verdict(rep)
        o = "-" if rep["overall"] is None else f"{rep['overall']:.0f}%"
        self.overall.configure(text=f"ผลรวม {o}  ({rep['rounds']} รอบ)\n{text}", fg=col)

        if self.w.new_shot:
            kind, self.w.new_shot = self.w.new_shot, None
            try:
                img = Image.open(self.w.shots[kind])
                img.thumbnail((400, 225))
                self.photo = ImageTk.PhotoImage(img)
                self.preview.configure(image=self.photo)
                self.preview_cap.configure(text=f"ภาพล่าสุด: {kind}.png  (กรอบแดง=ตัวขาว/ปุ่ม T, เขียว=โซน, ฟ้า=แถบ)")
            except Exception:
                pass
        self.root.after(200, self.tick)


if __name__ == "__main__":
    root = tk.Tk()
    App(root)
    root.mainloop()
