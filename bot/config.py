"""Membaca config.yaml dan .env.

Struktur config (tiap market punya robot & setelan sendiri):

    model:  {...}            # otak AI, dipakai kedua market
    paper:  {slippage_pct}
    loop:   {...}
    db_path: data/trader.db
    crypto: {mode, exchange, quote, symbols, watchlist, timeframe, strategy, risk, paper_balance}
    forex:  {mode, source, symbols, watchlist, timeframe, strategy, risk, paper_balance}

Config versi lama (satu robot gabungan) otomatis diubah ke struktur ini.
venue_cfg(cfg, venue) membuat tampilan "datar" untuk satu market yang dipakai mesin robot.
"""
import copy
import logging
import os
import sys
from pathlib import Path

import yaml
from dotenv import load_dotenv

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # Mac: operasi yang belum didukung GPU jatuh ke CPU

ROOT = Path(__file__).resolve().parent.parent
KRONOS_DIR = ROOT / "Kronos"
VENUES = ("crypto", "forex")

CRYPTO_WATCH = ["BTC/USDT", "ETH/USDT", "SOL/USDT", "BNB/USDT", "XRP/USDT", "DOGE/USDT"]
FOREX_WATCH = ["EURUSD", "GBPUSD", "USDJPY", "AUDUSD", "USDCAD", "XAUUSD"]

DEFAULTS = {
    "model": {"name": "NeoQuasar/Kronos-small", "tokenizer": "NeoQuasar/Kronos-Tokenizer-base", "device": "auto",
              "lookback": 400, "pred_len": 12, "n_paths": 10, "temperature": 1.0, "top_p": 0.9},
    "paper": {"slippage_pct": 0.05},
    "loop": {"price_check_sec": 60, "delay_after_close_sec": 15},
    "db_path": "data/trader.db",
    "crypto": {"mode": "paper", "exchange": "tokocrypto", "quote": "USDT", "symbols": ["BTC/USDT", "ETH/USDT"],
               "watchlist": CRYPTO_WATCH, "timeframe": "1h", "strategy": {}, "paper_balance": 1000.0,
               "risk": {"order_size_quote": 15.0, "max_order_size_quote": 50.0, "max_open_positions": 3,
                        "max_daily_loss_quote": 20.0}},
    "forex": {"mode": "paper", "source": "auto", "symbols": ["EURUSD", "XAUUSD"], "watchlist": FOREX_WATCH,
              "timeframe": "1h", "strategy": {}, "paper_balance": 1000.0,
              "risk": {"risk_pct": 1.0, "max_lots": 1.0, "leverage": 100, "max_open_positions": 3,
                       "max_daily_loss_quote": 20.0}},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


def normalize(cfg: dict) -> dict:
    """Ubah config lama (satu robot) ke struktur per market, lalu lengkapi nilai default."""
    cfg = cfg or {}
    if not isinstance(cfg.get("crypto"), dict) or "symbols" not in cfg.get("crypto", {}):
        old_syms = cfg.get("symbols") or []
        risk = cfg.get("risk") or {}
        fx = cfg.get("forex") or {}
        bal = (cfg.get("paper") or {}).get("starting_balance", 1000.0)
        mode = str(cfg.get("mode", "paper")).lower()
        cfg = {
            "model": cfg.get("model", {}), "paper": {"slippage_pct": (cfg.get("paper") or {}).get("slippage_pct", 0.05)},
            "loop": cfg.get("loop", {}), "db_path": cfg.get("db_path", "data/trader.db"),
            "crypto": {"mode": mode if any("/" in s for s in old_syms) else "paper",
                       "exchange": cfg.get("exchange", "tokocrypto"), "quote": cfg.get("quote", "USDT"),
                       "symbols": [s for s in old_syms if "/" in s] or DEFAULTS["crypto"]["symbols"],
                       "timeframe": cfg.get("timeframe", "1h"), "strategy": cfg.get("strategy", {}),
                       "paper_balance": bal,
                       "risk": {k: risk[k] for k in ("order_size_quote", "max_order_size_quote", "max_open_positions",
                                                     "max_daily_loss_quote") if k in risk}},
            "forex": {"mode": "paper", "source": fx.get("source", "auto"),
                      "symbols": [s for s in old_syms if "/" not in s] or DEFAULTS["forex"]["symbols"],
                      "timeframe": cfg.get("timeframe", "1h"), "strategy": cfg.get("strategy_forex", {}),
                      "paper_balance": bal,
                      "risk": {**{k: fx[k] for k in ("risk_pct", "max_lots", "leverage") if k in fx},
                               **{k: risk[k] for k in ("max_open_positions", "max_daily_loss_quote") if k in risk}}},
        }
    cfg = _merge(DEFAULTS, cfg)
    for v in VENUES:
        cfg[v]["mode"] = "live" if str(cfg[v].get("mode", "paper")).lower() == "live" else "paper"
        cfg[v]["watchlist"] = list(dict.fromkeys(list(cfg[v].get("watchlist") or []) + list(cfg[v]["symbols"])))
    return cfg


def load_config(path: str | None = None) -> dict:
    load_dotenv(ROOT / ".env", override=True)
    p = Path(path) if path else ROOT / "config.yaml"
    raw = {}
    if p.exists():
        with open(p, encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
    return normalize(raw)


def venue_cfg(cfg: dict, venue: str) -> dict:
    """Config datar untuk satu market (bentuk yang dipakai mesin robot & uji strategi)."""
    v, c, f = cfg[venue], cfg["crypto"], cfg["forex"]
    risk = dict(v["risk"])
    risk.setdefault("order_size_quote", c["risk"].get("order_size_quote", 15.0))
    risk.setdefault("max_order_size_quote", c["risk"].get("max_order_size_quote", 50.0))
    return {
        "venue": venue, "mode": v["mode"], "exchange": c["exchange"], "quote": c["quote"],
        "symbols": list(v["symbols"]), "timeframe": v["timeframe"], "model": cfg["model"], "loop": cfg["loop"],
        "db_path": cfg["db_path"],
        "paper": {"starting_balance": float(v["paper_balance"]), "slippage_pct": cfg["paper"]["slippage_pct"]},
        "risk": risk,
        "strategy": c["strategy"] if venue == "crypto" else {},
        "strategy_forex": f["strategy"] if venue == "forex" else {},
        "forex": {"source": f.get("source", "auto"), "leverage": f["risk"].get("leverage", 100),
                  "risk_pct": f["risk"].get("risk_pct", 1.0), "max_lots": f["risk"].get("max_lots", 1.0)},
    }


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
    for noisy in ("urllib3", "ccxt", "httpx", "huggingface_hub", "yfinance", "peewee"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return logging.getLogger(name)


def api_keys() -> tuple[str | None, str | None]:
    return os.getenv("TOKOCRYPTO_API_KEY") or None, os.getenv("TOKOCRYPTO_API_SECRET") or None


def live_unlocked(venue: str = "crypto") -> bool:
    key = "LIVE_CRYPTO" if venue == "crypto" else "LIVE_FOREX"
    if os.getenv(key) is None and venue == "crypto":   # kompatibel .env lama
        return os.getenv("LIVE_TRADING", "").strip().upper() == "YA"
    return os.getenv(key, "").strip().upper() == "YA"
