"""
Auto fishing (วนลูป):
  เหวี่ยงเบ็ด -> รอมินิเกม -> ไล่ตัวขาวให้อยู่ในโซนเขียว (กดค้าง=ขึ้น, ปล่อย=ลง)
  -> มินิเกมจบ -> รอ 1 วิ -> เห็นปุ่ม T -> กด T ค้าง 6.5 วิ -> วนใหม่
  (เหวี่ยงแล้วมินิเกมไม่ขึ้นใน 30 วิ -> เก็บสายแล้วเหวี่ยงใหม่)

ติดตั้ง:   pip install mss numpy scipy
รัน:       python fishing_bot.py

บอทหาหน้าต่าง Roblox เอง (จอไหนก็ได้) และหาตำแหน่งแถบเองตอนมินิเกมขึ้นครั้งแรก
(จำไว้ใน bar.json). ถ้าหาเองไม่เจอ: ตอนแถบขึ้นเอาเมาส์ชี้ที่แถบแล้วกด F8

ปุ่มลัด:
  F6  = เปิด/ปิดบอท
  F8  = ตั้งตำแหน่งแถบเอง (เมาส์ชี้ที่แถบตอนมินิเกมขึ้น)
  F10 = เซฟภาพหน้าต่างเกมเป็น debug.png + บอกว่าจับอะไรได้
  F7  = ออก
"""
import ctypes
import json
import os
import time

import mss
import mss.tools
import numpy as np
from scipy import ndimage

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(2)
except Exception:
    ctypes.windll.user32.SetProcessDPIAware()
user32 = ctypes.windll.user32

VK_F6, VK_F7, VK_F8, VK_F10 = 0x75, 0x76, 0x77, 0x79
BAR_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bar.json")

# ---- ปรับจูนได้ ----
INVERT = False      # กดค้าง = ตัวขาวขึ้น, ปล่อย = ลง (True ถ้ากลับกัน)
LEAD = 0.05         # วินาทีที่ทำนายตำแหน่งโซนล่วงหน้า (เพราะโซนขยับ)
GAIN = 8.0          # ยิ่งมาก ยิ่งไล่เข้าหาโซนแรง (แกว่งมากให้ลดลง, ตามไม่ทันให้เพิ่ม)
LOOP_HZ = 120
LOST_TIMEOUT = 1.0  # หาแถบไม่เจอเกินกี่วินาที ถือว่ามินิเกมจบ

AUTO_CAST = True    # เหวี่ยงเบ็ดเองอัตโนมัติ (วนลูป)
CAST_HOLD = 0.1     # กดค้างกี่วินาทีตอนเหวี่ยงเบ็ด (ถ้าเกมต้องกดค้างชาร์จ ให้เพิ่ม)
CAST_TIMEOUT = 30   # เหวี่ยงแล้วรอมินิเกมนานสุดกี่วินาที ไม่ขึ้นก็เหวี่ยงใหม่
RECAST_CLICKS = 2   # ตอนเหวี่ยงใหม่คลิกกี่ครั้ง (2 = คลิกแรกเก็บสาย คลิกสองเหวี่ยง, ถ้าคลิกเดียวพอให้ใส่ 1)
RECAST_GAP = 1.0    # เว้นระหว่างคลิกเก็บสายกับคลิกเหวี่ยงใหม่ (วินาที)
COLLECT_WAIT = 6.0  # มินิเกมจบแล้วรอปุ่ม T ขึ้นนานสุดกี่วินาที (ไม่ขึ้น = ข้ามไปเหวี่ยงใหม่)
COLLECT_KEY = 0x14  # scan code ปุ่ม T
AFTER_MINIGAME = 1.0  # มินิเกมจบแล้วรอกี่วินาที ก่อนเริ่มหาปุ่ม T
COLLECT_HOLD = 6.5  # กด T ค้างกี่วินาที
ADAPTIVE_HOLD = False  # True = ปล่อยทันทีที่ T หาย แล้วค่อยๆ ลดเวลากดลงเอง
                       # (ปิดไว้: ตอนกด T ปุ่มเปลี่ยนหน้าตา บอทเลยเข้าใจผิดว่า T หายตั้งแต่ ~0.2 วิ)
COLLECT_MAX = 12.0  # กด T ค้างนานสุดจริงๆ (กันค้างตลอด)
HOLD_MIN = 1.0      # เวลากดสูงสุดจะไม่ลดต่ำกว่านี้
HOLD_STEP = 0.5     # ลดเวลากดสูงสุดลงรอบละกี่วินาที
HOLD_MARGIN = 0.5   # เผื่อเวลาจากครั้งที่ T หายช้าสุด (5 ครั้งล่าสุด)
T_GONE_CONFIRM = 0.3  # ไม่เห็น T ต่อเนื่องกี่วินาที ถึงนับว่า T หายจริง
HOLD_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hold.json")
AFTER_COLLECT = 1.0 # เก็บของแล้วรอกี่วินาทีก่อนเหวี่ยงใหม่


# ================= input =================
_prev_keys = {}


def key_pressed(vk):
    down = bool(user32.GetAsyncKeyState(vk) & 0x8000)
    was = _prev_keys.get(vk, False)
    _prev_keys[vk] = down
    return down and not was


_mouse_down = False


def mouse(down):
    global _mouse_down
    if down != _mouse_down:
        user32.mouse_event(0x0002 if down else 0x0004, 0, 0, 0, 0)
        _mouse_down = down


def key(scan, down):
    # ส่งทั้ง virtual-key และ scan code (บางเกมรับแค่แบบใดแบบหนึ่ง)
    vk = user32.MapVirtualKeyW(scan, 1)  # MAPVK_VSC_TO_VK
    user32.keybd_event(vk, scan, 0 if down else 0x0002, 0)


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]


def cursor():
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))
    return p.x, p.y


def game_window():
    """หาหน้าต่าง Roblox (จอไหนก็ได้) คืน (hwnd, พื้นที่เกมบนจอ) หรือ (None, None)"""
    hwnd = user32.FindWindowW(None, "Roblox")
    if not hwnd or user32.IsIconic(hwnd):
        return None, None
    rc = RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rc))
    p = POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(p))
    if rc.right < 100 or rc.bottom < 100:
        return None, None
    return hwnd, {"left": p.x, "top": p.y, "width": rc.right, "height": rc.bottom}


# ================= vision =================
def to_rgb(shot):
    return np.asarray(shot)[..., 2::-1].astype(np.int16)  # BGRA -> RGB


def masks(img):
    r, g, b = img[..., 0], img[..., 1], img[..., 2]
    mx, mn = img.max(-1), img.min(-1)
    # ตัวขาว: สว่าง สีไม่จัด (ขาว / ขาวเทา / ขาวอมเขียว มีเงาไล่สี เช่น 150,184,123)
    # ฟองน้ำออกฟ้า (b > g) เลยไม่โดน
    white = (mn > 70) & (mx - mn < mx * 0.45) & (img.mean(-1) > 115) & (b <= g + 10)
    # โซน: โปร่งแสง สีเปลี่ยนตามพื้นหลัง และบางทีเป็นเขียว บางทีเป็นเหลือง
    # (เขียวมะกอก 75,85,43 / เขียวอมฟ้า 63,149,109 / เขียวเข้ม 45,77,18 / เหลือง)
    green = (g >= r - 10) & (g - b >= 15) & (g >= 60) & ~white
    return white, green


def blobs(mask):
    lab, _ = ndimage.label(mask)
    return [(sl, lab[sl] == i + 1) for i, sl in enumerate(ndimage.find_objects(lab))]


def find_bar(img, S):
    """หา "สี่เหลี่ยมโซน" ที่มี "ก้อนขาว" อยู่แนวเดียวกัน (ใบบัวรูปทรงไม่เหลี่ยม เลยไม่ผ่าน)
    S = สเกลจอ (สูง/1080). คืน (x1, x2) ในภาพ หรือ None"""
    white, green = masks(img)
    whites = []
    for sl, comp in blobs(white):
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if 10 * S <= w <= 50 * S and 10 * S <= h <= 50 * S and 0.6 <= w / h <= 1.6 \
                and comp.mean() > 0.6:
            whites.append(((sl[1].start + sl[1].stop) / 2, w))
    best = None
    # หาจากสีโซนอย่างเดียว (ไม่รวมสีขาว กันไปติดกับเส้นขอบแถบ) ตัวขาวที่อยู่ในโซนจะเป็นรู -> fill_holes
    for sl, comp in blobs(green):
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if not (25 * S <= w <= 130 * S and 12 * S <= h <= 100 * S and w >= h * 0.7):
            continue
        fill = ndimage.binary_fill_holes(comp).mean()
        if fill < 0.75:                   # ต้องเป็นสี่เหลี่ยมทึบ
            continue
        zx1, zx2 = sl[1].start, sl[1].stop
        if not any(zx1 < cx < zx2 and ww < w * 0.8 for cx, ww in whites):
            continue
        if detect(img[:, zx1:zx2], S) is None:  # แนวนี้ต้องจับตัวขาว+โซนได้จริง
            continue
        if best is None or fill > best[0]:
            best = (fill, (zx1, zx2))
    return best[1] if best else None


def groups_of(rows):
    return np.split(rows, np.where(np.diff(rows) > 3)[0] + 1)


def detect(strip, S, prev_center=None):
    """strip = ภาพแถบ คืน (white_y, zone_top, zone_bottom) หรือ None"""
    w = strip.shape[1]
    q = max(w // 4, 2)
    white, green = masks(strip)
    mid_white = white[:, q:w - q].mean(1)
    side_white = np.concatenate([white[:, :q // 2], white[:, w - q // 2:]], 1).mean(1)
    # แถวตัวขาว: ตรงกลางขาว แต่ขอบข้างไม่ขาว
    wrows = np.where((mid_white > 0.3) & (side_white < 0.2))[0]
    # แถวโซน: ขอบข้างเป็นสีโซน และตรงกลางเป็นสีโซนหรือตัวขาว
    sides = np.concatenate([green[:, :q], green[:, w - q:]], 1)
    mid_gw = (green | white)[:, q:w - q]
    zrows = np.where((sides.mean(1) > 0.7) & (mid_gw.mean(1) > 0.7))[0]
    if len(wrows) < 3 or len(zrows) < 12 * S:
        return None
    wg = [g for g in groups_of(wrows) if 8 * S <= len(g) <= 60 * S]
    zg = [g for g in groups_of(zrows) if len(g) >= 12 * S]
    if not wg or not zg:
        return None
    wrow = max(wg, key=len)
    if prev_center is not None:   # โซนขยับต่อเนื่อง เลือกกลุ่มที่ใกล้ตำแหน่งเดิม
        zrow = min(zg, key=lambda g: abs(g.mean() - prev_center))
    else:
        zrow = max(zg, key=len)
    return wrow.mean(), zrow.min(), zrow.max()


def find_T(img, S):
    """หาปุ่ม T (วงกลมขาว มีตัว T สีดำตรงกลาง)"""
    for sl, comp in blobs(img.min(-1) > 200):
        h, w = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
        if not (8 * S <= w <= 60 * S and 8 * S <= h <= 60 * S and 0.75 <= w / h <= 1.33):
            continue
        filled = ndimage.binary_fill_holes(comp)
        fill = filled.mean()                              # วงกลม ~0.78
        holes = (filled & ~comp).sum() / filled.sum()     # รูตัว T ~0.09
        if 0.65 <= fill <= 0.88 and holes >= 0.03:
            return True
    return False


# ================= helpers =================
def bar_region(cfg, game):
    """ตำแหน่งแถบ (เก็บเป็นสัดส่วนของหน้าต่างเกม) -> พิกัดจอ"""
    return {"left": game["left"] + int(cfg["x1"] * game["width"]),
            "top": game["top"],
            "width": max(int((cfg["x2"] - cfg["x1"]) * game["width"]), 4),
            "height": game["height"]}


def calibrate(sct, game, x_hint=None):
    """หาแถบในหน้าต่างเกม (ถ้ามี x_hint = หาเฉพาะรอบๆ เมาส์)"""
    S = game["height"] / 1080
    left, width = game["left"], game["width"]
    if x_hint is not None:
        half = int(150 * S)
        left = max(x_hint - half, game["left"])
        width = min(x_hint + half, game["left"] + game["width"]) - left
        if width < 20:
            return None
    img = to_rgb(sct.grab({"left": left, "top": game["top"], "width": width, "height": game["height"]}))
    fb = find_bar(img, S)
    if not fb:
        return None
    x1, x2 = fb
    return {"x1": (left + x1 - game["left"]) / game["width"],
            "x2": (left + x2 - game["left"]) / game["width"]}


def save_cfg(cfg):
    with open(BAR_FILE, "w") as f:
        json.dump(cfg, f)


def cast(game, quiet=False):
    """ย้ายเมาส์เข้าหน้าต่างเกม (ถ้าอยู่นอกเกม) แล้วคลิกเหวี่ยงเบ็ด"""
    x, y = cursor()
    inside = (game["left"] <= x < game["left"] + game["width"]
              and game["top"] <= y < game["top"] + game["height"])
    if not inside:
        user32.SetCursorPos(game["left"] + game["width"] // 2,
                            game["top"] + int(game["height"] * 0.6))
        time.sleep(0.05)
    if not quiet:
        print("เหวี่ยงเบ็ด... รอมินิเกม")
    mouse(True)
    time.sleep(CAST_HOLD)
    mouse(False)


def load_hold():
    """เวลากด T ที่เรียนรู้ไว้ (จำข้ามการเปิดบอท)"""
    try:
        with open(HOLD_FILE) as f:
            d = json.load(f)
        return float(d["hold"]), list(d.get("history", []))
    except Exception:
        return COLLECT_HOLD, []


def save_hold(hold, history):
    with open(HOLD_FILE, "w") as f:
        json.dump({"hold": round(hold, 2), "history": history[-20:]}, f)


_hold, _history = None, None


def collect(sct, game, S):
    """รอปุ่ม T ขึ้น -> กด T ค้าง พร้อมนับว่ากดกี่วิแล้ว T หาย
    แล้วค่อยๆ ลดเวลากดสูงสุดลงมาให้ใกล้เวลาจริง (ถ้าไม่พอก็เพิ่มกลับ)"""
    global _hold, _history
    if _hold is None:
        _hold, _history = load_hold() if ADAPTIVE_HOLD else (COLLECT_HOLD, [])

    center = {"left": game["left"] + int(game["width"] * 0.3),
              "top": game["top"] + int(game["height"] * 0.2),
              "width": int(game["width"] * 0.4), "height": int(game["height"] * 0.6)}
    seen = lambda: find_T(to_rgb(sct.grab(center)), S)

    t0 = time.perf_counter()
    while not seen():
        if time.perf_counter() - t0 > COLLECT_WAIT:
            print("ไม่เห็นปุ่ม T ข้ามไป")
            return
        time.sleep(0.1)

    print(f"เห็นปุ่ม T -> กด T ค้าง (สูงสุด {_hold:.1f} วิ)")
    t0 = time.perf_counter()
    gone_since = None   # เวลาที่เริ่มไม่เห็น T
    gone_at = None      # กดไปกี่วิแล้ว T หาย
    last_print = 0
    try:
        while True:
            el = time.perf_counter() - t0
            key(COLLECT_KEY, True)  # ส่งซ้ำเหมือนกดค้างจริง (auto-repeat)
            if seen():
                gone_since = None
            elif gone_since is None:
                gone_since = el
            if gone_at is None and gone_since is not None and el - gone_since >= T_GONE_CONFIRM:
                gone_at = gone_since          # T หายจริง (ไม่เห็นต่อเนื่อง)
                print(f"  (มองไม่เห็นปุ่ม T ตั้งแต่ {gone_at:.1f} วิ)")
                if ADAPTIVE_HOLD:
                    break                     # โหมดปรับเวลาเอง: ปล่อยทันที
            if int(el) > last_print:
                last_print = int(el)
                print(f"  กด T ... {last_print} วิ")
            if el >= _hold:     # ครบเวลากดสูงสุดแล้ว T ยังไม่หาย
                break
            time.sleep(0.05)
    finally:
        key(COLLECT_KEY, False)

    if not ADAPTIVE_HOLD:
        print(f"กด T ครบ {_hold:g} วิ เก็บของเสร็จ")
        return

    old = _hold
    if gone_at is not None:
        _history.append(round(gone_at, 2))
        recent = _history[-5:]
        target = max(recent) + HOLD_MARGIN          # เวลาที่ควรพอ (ยึดครั้งที่นานสุดล่าสุด)
        _hold = max(target, _hold - HOLD_STEP, HOLD_MIN)   # ค่อยๆ ลดทีละ HOLD_STEP
        print(f"T หายหลังกด {gone_at:.1f} วิ | เฉลี่ย {sum(recent) / len(recent):.1f} วิ"
              f" ({len(_history)} ครั้ง) | เวลากดสูงสุด {old:.1f} -> {_hold:.1f} วิ")
    else:
        _hold = min(_hold + 1.0, COLLECT_MAX)
        print(f"กดครบแล้ว T ยังไม่หาย | เพิ่มเวลากดสูงสุด {old:.1f} -> {_hold:.1f} วิ")
    save_hold(_hold, _history)


def recast(game):
    """เหวี่ยงไปนานแล้วมินิเกมไม่ขึ้น: คลิกเก็บสายก่อน แล้วค่อยเหวี่ยงใหม่"""
    print(f"รอเกิน {CAST_TIMEOUT} วิ มินิเกมไม่ขึ้น -> เก็บสายแล้วเหวี่ยงใหม่")
    for _ in range(RECAST_CLICKS - 1):
        cast(game, quiet=True)
        time.sleep(RECAST_GAP)
    cast(game)


# ================= main =================
def main():
    cfg = None
    if os.path.exists(BAR_FILE):
        with open(BAR_FILE) as f:
            data = json.load(f)
        if "x1" in data:
            cfg = data
            print("ใช้ตำแหน่งแถบที่จำไว้ (กด F8 ตอนแถบขึ้นเพื่อตั้งใหม่)")

    running = False
    playing = False
    last_seen = 0.0
    last_y = last_z = last_t = None
    vel = zvel = 0.0
    next_cast = 0.0
    hits = 0
    line_out = False          # เหวี่ยงเบ็ดออกไปแล้ว รอมินิเกมอยู่
    auto_cand, auto_count, last_auto = None, 0, 0.0
    warned = 0.0
    print("F6 = เปิด/ปิด | F8 = ตั้งตำแหน่งแถบเอง | F10 = debug.png | F7 = ออก")

    with mss.mss() as sct:
        while True:
            hwnd, game = game_window()
            now = time.perf_counter()

            if key_pressed(VK_F7):
                break
            if key_pressed(VK_F6):
                running = not running
                mouse(False)
                playing, next_cast, line_out = False, now + 1.0, False
                if running and hwnd:
                    user32.SetForegroundWindow(hwnd)
                print("บอท:", "ON" if running else "OFF",
                      "| หน้าต่างเกม:", game if game else "ไม่เจอ Roblox")
            if key_pressed(VK_F8):
                c = calibrate(sct, game, cursor()[0]) if game else None
                if c:
                    cfg = c
                    save_cfg(cfg)
                    print("ตั้งตำแหน่งแถบแล้ว:", bar_region(cfg, game))
                else:
                    print("หาแถบไม่เจอรอบๆ เมาส์ (กดตอนแถบขึ้น และเมาส์ชี้ที่แถบ)")
            if key_pressed(VK_F10):
                if game:
                    shot = sct.grab(game)
                    mss.tools.to_png(shot.rgb, shot.size, output="debug.png")
                    S = game["height"] / 1080
                    d = detect(to_rgb(sct.grab(bar_region(cfg, game))), S) if cfg else "ยังไม่มีตำแหน่งแถบ"
                    print("เซฟ debug.png แล้ว | เกม:", game, "| แถบ:", d,
                          "| ปุ่ม T:", find_T(to_rgb(shot), S))
                else:
                    print("ไม่เจอหน้าต่าง Roblox")

            if not running:
                time.sleep(0.03)
                continue
            if game is None:
                mouse(False)
                playing = False
                if now - warned > 3:
                    print("หาหน้าต่าง Roblox ไม่เจอ (เปิดเกมไว้ อย่าย่อหน้าต่าง)")
                    warned = now
                time.sleep(0.2)
                continue

            S = game["height"] / 1080

            # ---- ยังไม่รู้ตำแหน่งแถบ: สแกนทั้งหน้าต่างเกมหาเอง ----
            if cfg is None:
                if now - last_auto > 0.3:
                    last_auto = now
                    c = calibrate(sct, game)
                    # ต้องเจอที่เดิม 3 ครั้งติด กันจับผิด
                    if c and auto_cand and abs(c["x1"] - auto_cand["x1"]) < 0.01:
                        auto_count += 1
                    else:
                        auto_count = 1 if c else 0
                    auto_cand = c
                    if auto_count >= 3:
                        cfg = auto_cand
                        save_cfg(cfg)
                        playing, hits = False, 0
                        print("เจอแถบเอง จำตำแหน่งไว้แล้ว:", bar_region(cfg, game))
                        continue
                if auto_count == 0 and AUTO_CAST and now >= next_cast:
                    recast(game) if line_out else cast(game)
                    line_out = True
                    next_cast = time.perf_counter() + CAST_TIMEOUT
                if now - warned > 10:
                    print("กำลังหาแถบ... (หรือกด F8 ตอนแถบขึ้น เมาส์ชี้ที่แถบ)")
                    warned = now
                time.sleep(0.02)
                continue

            res = detect(to_rgb(sct.grab(bar_region(cfg, game))), S, last_z if playing else None)

            # ---- ยังไม่อยู่ในมินิเกม ----
            if not playing:
                hits = hits + 1 if res else 0
                if hits >= 2:              # เจอ 2 เฟรมติดกัน กันจับผิด
                    playing, hits, line_out = True, 0, False
                    last_seen = now
                    last_y = last_z = None
                    print("มินิเกมขึ้น -> เล่นมินิเกม")
                elif AUTO_CAST and now >= next_cast:
                    recast(game) if line_out else cast(game)
                    line_out = True
                    next_cast = time.perf_counter() + CAST_TIMEOUT
                else:
                    time.sleep(0.03)
                continue

            # ---- อยู่ในมินิเกม ----
            if res is None:
                mouse(False)
                last_y, vel = None, 0.0
                if now - last_seen > LOST_TIMEOUT:
                    playing = False
                    print(f"มินิเกมจบ รอ {AFTER_MINIGAME:g} วิ แล้วหาปุ่ม T...")
                    time.sleep(AFTER_MINIGAME)
                    collect(sct, game, S)
                    next_cast = time.perf_counter() + AFTER_COLLECT
                time.sleep(0.01)
                continue
            last_seen = now

            wy, ztop, zbot = res
            center = (ztop + zbot) / 2
            if last_y is not None:
                dt = max(now - last_t, 1e-3)
                vel = 0.6 * vel + 0.4 * (wy - last_y) / dt        # ความเร็วตัวขาว
                zvel = 0.7 * zvel + 0.3 * (center - last_z) / dt  # ความเร็วโซน
            last_y, last_z, last_t = wy, center, now

            # y มากขึ้น = ต่ำลง. ไล่ตาม "ตำแหน่งโซนในอนาคต"
            target = center + zvel * LEAD
            err = wy - target                    # + = ตัวขาวอยู่ต่ำกว่าเป้า
            desired_vel = zvel - GAIN * err      # ความเร็วที่อยากให้ตัวขาววิ่ง
            want_up = vel > desired_vel          # ตกเร็วเกิน/ขึ้นช้าเกิน -> กด
            mouse(want_up != INVERT)

            time.sleep(1 / LOOP_HZ)

    mouse(False)
    print("ออกแล้ว")


if __name__ == "__main__":
    main()
