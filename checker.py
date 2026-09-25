"""
ระบบทดสอบการจับภาพ (ใช้ในแท็บ "ทดสอบ" ของแอป gui.py)
วัดว่าระบบจับภาพแต่ละช่วงแม่นแค่ไหน + แคปภาพพร้อมกรอบไว้ในโฟลเดอร์ check/
  1) รอปลากิน : ต้องไม่จับแถบผิดทั้งที่ยังไม่มีมินิเกม
  2) มินิเกม  : จับตัวขาว + โซนได้กี่ % ของเฟรม และตัวขาวนิ่งแค่ไหน
  3) ปุ่ม T    : หลังมินิเกมจบ เจอปุ่ม T ไหม ใช้เวลากี่วิ และจับได้สม่ำเสมอไหม

มี 2 แบบ:
  - อัตโนมัติ (AutoObserver): บอทเล่นเองตามจำนวนรอบ แล้ววัดผลไปพร้อมกัน
  - เล่นเอง   (Watcher)     : ดูหน้าจออย่างเดียว ไม่คลิก/ไม่กดปุ่ม ผู้เล่นตกปลาเอง
"""
import json
import os
import time

import mss
import numpy as np
from PIL import Image, ImageDraw

import fishing_bot as fb

HERE = os.path.dirname(os.path.abspath(__file__))
CHECK_DIR = os.path.join(HERE, "check")
T_WAIT = 8.0   # (แบบเล่นเอง) มินิเกมจบแล้วรอดูปุ่ม T นานสุดกี่วินาที
FPS = 30       # (แบบเล่นเอง) จับภาพกี่เฟรมต่อวินาที


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
            steady = self.t_hits / self.t_checks if self.t_checks else 0
            t_acc = round(100 * self.t_found / self.t_rounds * steady, 1)
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
        rep["overall"] = round(min(accs), 1) if accs else None   # ช่วงที่แย่สุดเป็นตัวตัดสิน
        return rep


def verdict(rep):
    """คืน (ระดับ, ข้อความ) ระดับ = good / ok / bad / none"""
    o = rep["overall"]
    if rep["rounds"] == 0 or o is None:
        return "none", "ยังไม่มีข้อมูล — ต้องครบอย่างน้อย 1 รอบ"
    if o >= 95:
        return "good", "ดีมาก — ระบบจับภาพได้แม่น ใช้บอทได้เลย"
    if o >= 85:
        return "good", "ดี — ใช้บอทได้ อาจพลาดบ้างเล็กน้อย"
    if o >= 70:
        return "ok", "พอใช้ — ใช้ได้แต่อาจพลาดบ่อย ลองดูภาพใน check/"
    return "bad", "ควรปรับก่อนใช้ — ส่งภาพใน check/ มาให้ช่วยดู"


def t_region(game):
    return {"left": game["left"] + int(game["width"] * 0.3),
            "top": game["top"] + int(game["height"] * 0.2),
            "width": int(game["width"] * 0.4), "height": int(game["height"] * 0.6)}


class Recorder:
    """เก็บสถิติ + แคปภาพ (ถูกเรียกจากบอท หรือจาก Watcher)"""

    def __init__(self, log, target_rounds=None, on_done=None):
        self.log = log
        self.target = target_rounds
        self.on_done = on_done
        self.stats = Stats()
        self.shots = {}
        self.new_shot = None
        self.streak = 0
        self.miss_run = 0
        self.idle_since = 0
        self.was_playing = False
        self.done = False

    # ---------- เรียกทุกเฟรม ----------
    def frame(self, playing, res, sct, game, cfg):
        st = self.stats
        if not playing:
            self.was_playing = False
            st.idle_frames += 1
            self.idle_since += 1
            if res:
                self.streak += 1
            else:
                if self.streak == 1:              # เจอแค่เฟรมเดียวแล้วหาย = จับผิด
                    st.idle_false += 1
                    self.log("⚠ จับแถบผิด 1 เฟรม ตอนยังไม่มีมินิเกม")
                self.streak = 0
            if self.idle_since == FPS * 3:
                self.snapshot(sct, game, cfg, "1_รอปลากิน")
            return
        if not self.was_playing:                  # เฟรมที่ยืนยันมินิเกม ย้ายไปนับเป็นมินิเกม
            self.was_playing = True
            st.idle_frames -= self.streak
            st.game_frames += self.streak
            st.game_hits += self.streak
            self.streak = 0
        if res:
            st.game_frames += self.miss_run + 1   # พลาดกลางเกมนับด้วย (พลาดตอนจบไม่นับ)
            st.game_hits += 1
            self.miss_run = 0
            w0, w1 = fb._diag.get("white", (0, 0))
            st.white_h.append(w1 - w0)
            if st.game_hits % 90 == 30:
                self.snapshot(sct, game, cfg, "2_มินิเกม", res)
        else:
            self.miss_run += 1

    def game_end(self):
        self.miss_run = 0
        self.log(f"มินิเกมจบ (รอบที่ {self.stats.rounds + 1}) — ตรวจปุ่ม T")

    def t_found(self, seen, sct, game, wait):
        st = self.stats
        st.t_rounds += 1
        st.t_found += 1
        st.t_waits.append(wait)
        self.snapshot(sct, game, None, "3_ปุ่ม_T", t_game=game)
        n = 0
        for _ in range(10):                       # เช็คซ้ำ 10 เฟรม (0.5 วิ)
            n += bool(seen())
            time.sleep(0.05)
        st.t_checks += 10
        st.t_hits += n
        self.log(f"เจอปุ่ม T หลังมินิเกมจบ {wait:.1f} วิ (จับซ้ำได้ {n}/10)")

    def t_missed(self, sct, game):
        self.stats.t_rounds += 1
        self.snapshot(sct, game, None, "3_ปุ่ม_T")
        self.log("⚠ ไม่เห็นปุ่ม T")

    def round_done(self):
        self.stats.rounds += 1
        self.idle_since = 0
        rep = self.save()
        o = "-" if rep["overall"] is None else f"{rep['overall']:.0f}%"
        self.log(f"จบรอบที่ {rep['rounds']} — ผลรวมตอนนี้ {o}")
        if self.target and self.stats.rounds >= self.target and not self.done:
            self.done = True
            self.log(f"ทดสอบครบ {self.target} รอบแล้ว: {verdict(rep)[1]}")
            if self.on_done:
                self.on_done()

    # ---------- ภาพ / รายงาน ----------
    def snapshot(self, sct, game, cfg, kind, res=None, t_game=None):
        try:
            shot = sct.grab(game)
            img = Image.frombytes("RGB", shot.size, shot.rgb)
            d = ImageDraw.Draw(img)
            if cfg:
                b = fb.bar_region(cfg, game)
                bx, bw = b["left"] - game["left"], b["width"]
                d.rectangle([bx, 0, bx + bw, game["height"] - 1], outline=(76, 141, 255), width=2)
                if res:
                    _, zt, zb = res
                    d.rectangle([bx - 4, zt, bx + bw + 4, zb], outline=(63, 220, 107), width=3)
                    w0, w1 = fb._diag.get("white", (0, 0))
                    d.rectangle([bx + bw // 4, w0, bx + bw * 3 // 4, w1], outline=(255, 80, 80), width=3)
            if t_game and "T" in fb._diag:
                x, y, w, h = fb._diag["T"]
                ox, oy = int(t_game["width"] * 0.3), int(t_game["height"] * 0.2)
                d.rectangle([ox + x - 4, oy + y - 4, ox + x + w + 4, oy + y + h + 4],
                            outline=(255, 80, 80), width=3)
            os.makedirs(CHECK_DIR, exist_ok=True)
            path = os.path.join(CHECK_DIR, f"{kind}.png")
            img.save(path)
            self.shots[kind] = path
            self.new_shot = kind
        except Exception as e:
            self.log(f"แคปภาพ {kind} ไม่ได้: {e}")

    def save(self):
        rep = self.stats.summary()
        rep["time"] = time.strftime("%Y-%m-%d %H:%M:%S")
        rep["verdict"] = verdict(rep)[1]
        os.makedirs(CHECK_DIR, exist_ok=True)
        with open(os.path.join(CHECK_DIR, "report.json"), "w", encoding="utf-8") as f:
            json.dump(rep, f, ensure_ascii=False, indent=2)
        return rep


class Watcher:
    """แบบเล่นเอง: ดูหน้าจออย่างเดียว (ไม่ส่ง input ใดๆ) แล้วป้อนข้อมูลให้ Recorder"""

    def __init__(self, rec):
        self.rec = rec
        self.stop = False
        self.phase = "เตรียม"

    def run(self):
        cfg = None
        if os.path.exists(fb.BAR_FILE):
            with open(fb.BAR_FILE) as f:
                data = json.load(f)
            if "x1" in data:
                cfg = data
        cand, cand_n, last_scan = None, 0, 0.0
        playing, hits, last_seen = False, 0, 0.0

        with mss.mss() as sct:
            while not self.stop:
                _, game = fb.game_window()
                if game is None:
                    self.phase = "หาหน้าต่าง Roblox ไม่เจอ"
                    time.sleep(0.3)
                    continue
                S = game["height"] / 1080
                now = time.perf_counter()

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
                            self.rec.log("เจอตำแหน่งแถบแล้ว เริ่มวัดผล")
                    time.sleep(0.02)
                    continue

                res = fb.detect(fb.to_rgb(sct.grab(fb.bar_region(cfg, game))), S)
                self.rec.frame(playing, res, sct, game, cfg)
                if not playing:
                    self.phase = "รอปลากิน (ตรวจว่าไม่จับผิด)"
                    hits = hits + 1 if res else 0
                    if hits >= 2:
                        playing, hits, last_seen = True, 0, now
                        self.rec.log("มินิเกมขึ้น — วัดการจับตัวขาว/โซน")
                else:
                    self.phase = "มินิเกม (วัดการจับตัวขาว/โซน)"
                    if res:
                        last_seen = now
                    elif now - last_seen > fb.LOST_TIMEOUT:
                        playing = False
                        self.rec.game_end()
                        self.watch_T(sct, game, S)
                        self.rec.round_done()
                time.sleep(1 / FPS)

    def watch_T(self, sct, game, S):
        self.phase = "รอปุ่ม T (หลังมินิเกม)"
        region = t_region(game)
        seen = lambda: fb.find_T(fb.to_rgb(sct.grab(region)), S)
        t0 = time.perf_counter()
        while not seen():
            if self.stop:
                return
            if time.perf_counter() - t0 > T_WAIT:
                self.rec.t_missed(sct, game)
                return
            time.sleep(0.05)
        self.rec.t_found(seen, sct, game, time.perf_counter() - t0)
        self.phase = "รอผู้เล่นเก็บของ..."
        t1 = time.perf_counter()
        while seen() and time.perf_counter() - t1 < 15 and not self.stop:
            time.sleep(0.2)
