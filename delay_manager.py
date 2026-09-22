import json
import random
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

CONFIG_PATH = Path("PVT/delay_config.json")

def load_config() -> dict:
    if not CONFIG_PATH.exists():
        return {
            "macro_delay": {"type": "lognormal", "mu": 0.8, "sigma": 0.7, "min_seconds": 1.5, "max_seconds": 15.0},
            "micro_delay": {"type": "uniform", "min_seconds": 0.4, "max_seconds": 1.5}
        }
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        logger.error("Errore lettura %s: %s", CONFIG_PATH, e)
        return {
            "macro_delay": {"type": "lognormal", "mu": 0.8, "sigma": 0.7, "min_seconds": 1.5, "max_seconds": 15.0},
            "micro_delay": {"type": "uniform", "min_seconds": 0.4, "max_seconds": 1.5}
        }

def _calculate_delay(config: dict) -> float:
    dtype = config.get("type", "uniform")
    if dtype == "lognormal":
        mu = config.get("mu", 0.8)
        sigma = config.get("sigma", 0.7)
        val = random.lognormvariate(mu, sigma)
    else:
        min_val = config.get("min_seconds", 0.5)
        max_val = config.get("max_seconds", 2.0)
        val = random.uniform(min_val, max_val)
        
    min_sec = config.get("min_seconds", 0.1)
    max_sec = config.get("max_seconds", 30.0)
    
    return max(min_sec, min(val, max_sec))

def get_macro_delay() -> float:
    cfg = load_config()
    return _calculate_delay(cfg.get("macro_delay", {}))

def get_micro_delay() -> float:
    cfg = load_config()
    return _calculate_delay(cfg.get("micro_delay", {}))

def wait_macro(page=None) -> float:
    delay = get_macro_delay()
    logger.info("Attesa macro (simulazione umana tra aziende): %.2f secondi...", delay)
    if page:
        page.wait_for_timeout(delay * 1000)
    else:
        import time
        time.sleep(delay)
    return delay

def wait_micro(page=None) -> float:
    delay = get_micro_delay()
    logger.debug("Attesa micro (simulazione azione): %.2f s", delay)
    if page:
        page.wait_for_timeout(delay * 1000)
    else:
        import time
        time.sleep(delay)
    return delay
