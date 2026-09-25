"""อัปเดตโปรแกรมจาก GitHub ด้วย git (ใช้ในแอป gui.py)"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
BRANCH = "main"


def _git(*args, timeout=30):
    env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GCM_INTERACTIVE="never")
    r = subprocess.run(["git", *args], cwd=HERE, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout, env=env,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout).strip().splitlines()[-1] if (r.stderr or r.stdout) else "git error")
    return r.stdout.strip()


def current_version():
    try:
        return _git("log", "-1", "--format=%h %ad", "--date=format:%Y-%m-%d")
    except Exception:
        return "ไม่ทราบ"


def check():
    """คืน (จำนวนอัปเดตใหม่, รายการข้อความ commit ใหม่) — โยน RuntimeError ถ้าเช็คไม่ได้"""
    if not os.path.isdir(os.path.join(HERE, ".git")):
        raise RuntimeError("โฟลเดอร์นี้ไม่ได้ติดตั้งด้วย git")
    _git("fetch", "--quiet", "origin", BRANCH, timeout=60)
    behind = int(_git("rev-list", "--count", f"HEAD..origin/{BRANCH}") or 0)
    msgs = _git("log", "--format=%s", f"HEAD..origin/{BRANCH}").splitlines() if behind else []
    return behind, msgs


def apply():
    """ดึงอัปเดต (fast-forward เท่านั้น) + ลงไลบรารีใหม่ถ้า requirements.txt เปลี่ยน คืนข้อความสรุป"""
    changed = _git("diff", "--name-only", f"HEAD..origin/{BRANCH}").splitlines()
    try:
        _git("merge", "--ff-only", f"origin/{BRANCH}", timeout=60)
    except RuntimeError as e:
        raise RuntimeError(f"อัปเดตไม่ได้ (มีไฟล์ที่แก้เองค้างอยู่?): {e}")
    if "requirements.txt" in changed:
        py = sys.executable.replace("pythonw.exe", "python.exe")
        subprocess.run([py, "-m", "pip", "install", "-q", "-r", "requirements.txt"], cwd=HERE,
                       timeout=600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return f"อัปเดตแล้ว {len(changed)} ไฟล์"


def restart():
    """เปิดแอปใหม่ (ปิดตัวเก่าเอง)"""
    subprocess.Popen([sys.executable, os.path.join(HERE, "gui.py")], cwd=HERE,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
