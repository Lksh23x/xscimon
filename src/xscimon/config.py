import os
from functools import lru_cache
from pathlib import Path
import yaml
from dotenv import load_dotenv

load_dotenv()

_CONFIG_PATH = Path(__file__).parents[2] / "config.yaml"


@lru_cache(maxsize=1)
def get_config() -> dict:
    with open(_CONFIG_PATH) as f:
        return yaml.safe_load(f)
