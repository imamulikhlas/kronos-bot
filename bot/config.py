"""Membaca config.yaml dan .env."""
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
KRONOS_DIR = ROOT / "Kronos"


def load_config(path: str | None = None) -> dict:
    load_dotenv(ROOT / ".env", override=True)
    p = Path(path) if path else ROOT / "config.yaml"
    with open(p, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg["mode"] = str(cfg.get("mode", "paper")).lower().strip()
    if cfg["mode"] not in ("paper", "live"):
        raise SystemExit("config.yaml: mode harus 'paper' atau 'live'.")
    return cfg


def path_in_root(rel: str) -> Path:
    p = Path(rel)
    p = p if p.is_absolute() else ROOT / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def setup_logging(name: str = "bot") -> logging.Logger:
    log_path = path_in_root(f"logs/{name}.log")
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(message)s", "%Y-%m-%d %H:%M:%S")
    root = logging.getLogger()
    root.setLevel(logging.INFO)
    if not root.handlers:
        sh = logging.StreamHandler(sys.stdout)
        sh.setFormatter(fmt)
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setFormatter(fmt)
        root.addHandler(sh)
        root.addHandler(fh)
    for noisy in ("urllib3", "ccxt", "httpx", "huggingface_hub"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return logging.getLogger(name)


def api_keys() -> tuple[str | None, str | None]:
    return os.getenv("TOKOCRYPTO_API_KEY") or None, os.getenv("TOKOCRYPTO_API_SECRET") or None


def live_unlocked() -> bool:
    return os.getenv("LIVE_TRADING", "").strip().upper() == "YA"
