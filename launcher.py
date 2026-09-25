"""ตัวเปิดแอป (เรียกจาก "เปิดบอทตกปลา.bat" ด้วย Python ของ .venv)
เช็ค tkinter + ไลบรารี (ติดตั้งลง .venv ให้ถ้าขาด) แล้วเปิด gui.py
ไลบรารีทั้งหมดอยู่ใน .venv ของโฟลเดอร์นี้ ไม่แตะ Python หลักของเครื่อง"""
import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
LIBS = {"mss": "mss", "numpy": "numpy", "scipy": "scipy", "PIL": "pillow"}


def missing():
    return [pkg for mod, pkg in LIBS.items() if importlib.util.find_spec(mod) is None]


def main():
    print(f"Python {sys.version.split()[0]}  ({sys.executable})")
    if sys.prefix == sys.base_prefix:
        print("\n[X] ต้องเปิดผ่าน \"เปิดบอทตกปลา.bat\" (จะสร้าง .venv แยกให้ ไม่ลงไลบรารีใส่ Python หลักของเครื่อง)")
        return 1

    if sys.version_info < (3, 11):
        print(f"\n[X] Python {sys.version.split()[0]} เก่าเกินไป — ต้องใช้ 3.11 ขึ้นไป (ไลบรารีเวอร์ชันที่ล็อกไว้ไม่รองรับ)")
        print("    ติดตั้ง Python ใหม่จาก python.org แล้วลบโฟลเดอร์ .venv ทิ้ง จากนั้นเปิดไฟล์ .bat ใหม่")
        return 1

    if importlib.util.find_spec("tkinter") is None:
        print("\n[X] Python ในเครื่องนี้ไม่มี tkinter (ใช้สร้างหน้าต่าง)")
        print("    ติดตั้ง Python ใหม่จาก python.org และติ๊ก \"tcl/tk and IDLE\" ด้วย")
        return 1

    need = missing()
    if need:
        print(f"\nกำลังติดตั้งไลบรารีที่ต้องใช้: {', '.join(need)} (ครั้งแรกเท่านั้น อาจใช้เวลา 1-2 นาที)...\n")
        r = subprocess.run([sys.executable, "-m", "pip", "install", "-r",
                            os.path.join(HERE, "requirements.txt")])
        importlib.invalidate_caches()
        if r.returncode != 0 or missing():
            print(f"\n[X] ติดตั้งไลบรารีไม่สำเร็จ: {', '.join(missing()) or '-'}")
            print("    ดูข้อความด้านบน หรือแคปหน้าจอนี้ส่งมา")
            return 1
        print("\nติดตั้งเสร็จแล้ว")

    # เปิดแอปแบบไม่มีหน้าต่างดำ (pythonw) ถ้ามี
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen([exe, os.path.join(HERE, "gui.py")], cwd=HERE, creationflags=flags)
    print("กำลังเปิดแอป...")
    return 0


if __name__ == "__main__":
    sys.exit(main())
