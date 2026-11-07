"""
Model AI panel di PROSES TERPISAH.

Kenapa: di Windows, PyTorch tidak mengembalikan memori ke sistem walaupun model sudah dilepas di dalam
program. Dengan proses terpisah, "Free memory", Cancel, dan pelepasan otomatis cukup menutup proses itu,
dan sistem operasi pasti mengambil kembali semua memorinya. Cancel juga bisa langsung berhenti, tanpa
menunggu potongan hitungan selesai.

Proses ini dijalankan sebagai `python -m bot.ai_worker <port>` (bukan multiprocessing), supaya server
tidak ikut dimuat ulang di dalamnya.
"""
import json
import logging
import os
import subprocess
import sys
import threading
import time
from multiprocessing.connection import Client, Listener

from .config import ROOT

log = logging.getLogger("kronos")
NO_WINDOW = 0x08000000 if os.name == "nt" else 0          # Windows: jangan buka jendela konsol baru


class WorkerGone(RuntimeError):
    """Proses AI berhenti (dibatalkan, dilepas, atau crash)."""


class RemoteForecaster:
    """Antarmuka sama dengan KronosForecaster (paths, paths_many, cfg, device, device_name, kind)."""

    def __init__(self, mcfg: dict, device: str | None = None, timeout: float = 3600):
        self.cfg = dict(mcfg)
        key = os.urandom(16)
        listener = Listener(("127.0.0.1", 0), authkey=key)
        logs = ROOT / "logs"
        logs.mkdir(exist_ok=True)
        env = {**os.environ, "KRONOS_AI_KEY": key.hex(), "PYTHONUTF8": "1"}
        self._log = open(logs / "ai_worker.log", "ab")
        self.proc = subprocess.Popen([sys.executable, "-m", "bot.ai_worker", str(listener.address[1])], cwd=str(ROOT),
                                     env=env, stdout=self._log, stderr=self._log, creationflags=NO_WINDOW)
        self.pid = self.proc.pid
        box = {}
        th = threading.Thread(target=lambda: box.setdefault("conn", listener.accept()), daemon=True)
        th.start()
        t0 = time.time()
        while th.is_alive() and time.time() - t0 < 60:
            if self.proc.poll() is not None:
                break
            th.join(0.2)
        listener.close()
        self._conn = box.get("conn")
        if self._conn is None:
            self.close()
            raise RuntimeError("Proses AI gagal dimulai. Lihat logs/ai_worker.log.")
        self._conn.send(("init", dict(mcfg), device or mcfg.get("device", "auto")))
        msg = self._wait(timeout)                       # memuat model (pertama kali bisa mengunduh)
        if msg[0] != "ready":
            self.close()
            raise RuntimeError(msg[1])
        self._info(msg[1])

    def _info(self, info):
        self.device, self.device_name, self.kind = info["device"], info["device_name"], info["kind"]
        self.batch = int(info.get("batch") or 2)

    def _wait(self, timeout):
        t0 = time.time()
        try:
            while not self._conn.poll(0.3):
                if self.proc.poll() is not None:
                    raise WorkerGone("Proses AI berhenti.")
                if time.time() - t0 > timeout:
                    raise RuntimeError("Proses AI tidak menjawab.")
            return self._conn.recv()
        except (EOFError, BrokenPipeError, ConnectionResetError, OSError) as e:
            raise WorkerGone("Proses AI berhenti.") from e

    def paths_many(self, items: list) -> list:
        if not self.alive():
            raise WorkerGone("Proses AI berhenti.")
        try:
            self._conn.send(("paths", items, {k: self.cfg.get(k) for k in ("temperature", "top_p", "ensemble", "n_paths")}))
        except (BrokenPipeError, ConnectionResetError, OSError) as e:
            raise WorkerGone("Proses AI berhenti.") from e
        msg = self._wait(3600)
        if msg[0] == "error":
            raise RuntimeError(msg[1])
        self._info(msg[2])
        return msg[1]

    def paths(self, hist, y_ts):
        return self.paths_many([(hist, y_ts)])[0]

    def alive(self) -> bool:
        return self.proc.poll() is None

    def close(self):
        """Tutup proses AI. Semua memorinya kembali ke sistem."""
        try:
            if self._conn is not None and self.alive():
                self._conn.send(("stop",))
        except Exception:  # noqa: BLE001
            pass
        try:
            self.proc.wait(3)
        except Exception:  # noqa: BLE001
            self.proc.kill()
            try:
                self.proc.wait(5)
            except Exception:  # noqa: BLE001
                pass
        try:
            self._log.close()
        except Exception:  # noqa: BLE001
            pass

    def kill(self):
        """Hentikan seketika (Cancel)."""
        try:
            self.proc.kill()
            self.proc.wait(5)
        except Exception:  # noqa: BLE001
            pass

    _conn = None


def system_info_subprocess() -> dict:
    """Info GPU/CPU dibaca di proses sementara, supaya server sendiri tidak perlu memuat PyTorch."""
    code = "import json; from bot.forecast import system_info; print(json.dumps(system_info()))"
    r = subprocess.run([sys.executable, "-c", code], cwd=str(ROOT), capture_output=True, text=True, timeout=180,
                       creationflags=NO_WINDOW)
    lines = [ln for ln in r.stdout.splitlines() if ln.startswith("{")]
    if not lines:
        raise RuntimeError((r.stderr or "gagal membaca info perangkat").strip().splitlines()[-1][:300])
    return json.loads(lines[-1])


def _main(port: int):
    conn = Client(("127.0.0.1", port), authkey=bytes.fromhex(os.environ["KRONOS_AI_KEY"]))
    _, mcfg, device = conn.recv()
    slow = float(os.environ.get("SLOW", "0"))
    try:
        if os.environ.get("KRONOS_FAKE_AI"):              # untuk pengujian tanpa model
            from .forecast import DummyForecaster
            fc = DummyForecaster(mcfg, seed=11)
            fc.kind = "cpu"
        else:
            from .forecast import KronosForecaster
            fc = KronosForecaster(mcfg, device)
        from .forecast import default_batch
        info = lambda: {"device": str(fc.device), "device_name": fc.device_name, "kind": getattr(fc, "kind", "cpu"),  # noqa: E731
                        "batch": default_batch(fc.device)}
        conn.send(("ready", info()))
    except BaseException as e:  # noqa: BLE001
        conn.send(("error", f"{type(e).__name__}: {e}"))
        return
    base = dict(fc.cfg)
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            return
        if msg[0] == "stop":
            return
        if msg[0] == "paths":
            _, items, over = msg
            try:
                fc.cfg = {**base, **{k: v for k, v in over.items() if v is not None}}
                if slow:
                    time.sleep(slow * len(items))
                conn.send(("ok", fc.paths_many(items), info()))
            except BaseException as e:  # noqa: BLE001
                conn.send(("error", f"{type(e).__name__}: {e}"))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s | ai_worker | %(message)s")
    _main(int(sys.argv[1]))
