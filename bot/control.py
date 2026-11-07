"""Menyalakan/mematikan proses robot & uji strategi dari Panel Kontrol, plus simpan pengaturan."""
import os
import subprocess
import sys
import time
from pathlib import Path

import psutil
import yaml

from .config import ROOT

DATA = ROOT / "data"
LOGS = ROOT / "logs"
BT_PID = DATA / "backtest.pid"
BT_LOG = LOGS / "backtest_console.log"



def _wib_now():
    import datetime as _dt
    return _dt.datetime.now(_dt.timezone(_dt.timedelta(hours=7))).strftime("%Y-%m-%d %H:%M:%S")

def _env():
    env = os.environ.copy()
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _spawn(args, pid_file: Path, log_file: Path, append=True):
    DATA.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    logf = open(log_file, "a" if append else "w", encoding="utf-8")
    kw = {}
    if os.name == "nt":
        kw["creationflags"] = subprocess.CREATE_NO_WINDOW | subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kw["start_new_session"] = True
    p = subprocess.Popen([sys.executable, "-u", *args], cwd=str(ROOT), stdout=logf, stderr=subprocess.STDOUT,
                         stdin=subprocess.DEVNULL, env=_env(), **kw)
    pid_file.write_text(str(p.pid))
    return p.pid


def _alive(pid_file: Path, script: str) -> bool:
    try:
        pid = int(pid_file.read_text().strip())
        p = psutil.Process(pid)
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE and any(script in c for c in p.cmdline())
    except Exception:  # noqa: BLE001
        return False


def _stop(pid_file: Path):
    try:
        pid = int(pid_file.read_text().strip())
        p = psutil.Process(pid)
        p.terminate()
        try:
            p.wait(timeout=15)
        except psutil.TimeoutExpired:
            p.kill()
    except Exception:  # noqa: BLE001
        pass
    pid_file.unlink(missing_ok=True)


# ---------------- robot (satu proses per market) ----------------
def bot_pid(venue: str) -> Path:
    return DATA / f"bot_{venue}.pid"


def bot_console(venue: str) -> Path:
    return LOGS / f"bot_{venue}_console.log"


def _alive_bot(venue: str) -> bool:
    try:
        pid = int(bot_pid(venue).read_text().strip())
        p = psutil.Process(pid)
        cmd = " ".join(p.cmdline())
        return p.is_running() and p.status() != psutil.STATUS_ZOMBIE and "run_bot.py" in cmd and venue in cmd
    except Exception:  # noqa: BLE001
        return False


def bot_running(venue: str) -> bool:
    return _alive_bot(venue)


def bot_crashed(venue: str) -> bool:
    """PID tercatat tetapi prosesnya sudah mati (bukan dihentikan dari panel)."""
    return bot_pid(venue).exists() and not bot_running(venue)


def start_bot(venue: str):
    if bot_running(venue):
        return
    LOGS.mkdir(parents=True, exist_ok=True)
    with open(bot_console(venue), "a", encoding="utf-8") as f:
        f.write(f"\n===== Robot {venue} dinyalakan {_wib_now()} WIB =====\n")
    _spawn(["run_bot.py", "--venue", venue, "--ya"], bot_pid(venue), bot_console(venue))


def stop_bot(venue: str):
    _stop(bot_pid(venue))


def restart_bot(venue: str):
    stop_bot(venue)
    time.sleep(1)
    start_bot(venue)


def restart_if_running(venue: str) -> bool:
    if bot_running(venue):
        restart_bot(venue)
        return True
    return False


# ---------------- uji strategi ----------------
def backtest_running() -> bool:
    return _alive(BT_PID, "backtest.py")


def start_backtest(symbols, tf: str, candles: int, every: int, optimize: bool = False,
                   device: str = "auto", folds: int = 0, end: str | None = None):
    if backtest_running():
        return
    if isinstance(symbols, str):
        symbols = [symbols]
    args = ["backtest.py", *symbols, "--tf", tf, "--candles", str(candles), "--every", str(every),
            "--device", device]
    if folds:
        args += ["--folds", str(folds)]
    if end:
        args += ["--end", end]
    if optimize:
        args.append("--optimize")
    _spawn(args, BT_PID, BT_LOG, append=False)


def stop_backtest():
    _stop(BT_PID)


def tail(path: Path, n=40) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(lines[-n:])
    except FileNotFoundError:
        return ""


# ---------------- simpan pengaturan ----------------
def save_config(cfg: dict):
    clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
    with open(ROOT / "config.yaml", "w", encoding="utf-8") as f:
        f.write("# Diatur dari Panel Kontrol. Boleh juga diedit manual.\n")
        yaml.safe_dump(clean, f, allow_unicode=True, sort_keys=False)


def read_env() -> dict:
    out = {}
    p = ROOT / ".env"
    if p.exists():
        for line in p.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.strip().startswith("#"):
                k, v = line.split("=", 1)
                out[k.strip()] = v.strip()
    return out


def save_env(values: dict):
    cur = read_env()
    cur.update(values)
    body = ["# Diatur dari Panel Kontrol. JANGAN bagikan file ini ke siapa pun."]
    body += [f"{k}={v}" for k, v in cur.items()]
    (ROOT / ".env").write_text("\n".join(body) + "\n", encoding="utf-8")
    for k, v in values.items():
        os.environ[k] = v
