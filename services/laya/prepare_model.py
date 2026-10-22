"""Bake one pinned checkpoint and encoder configuration into the service image."""

import json
import os
from pathlib import Path

from huggingface_hub import snapshot_download
from transformers import AutoConfig

MODEL = "convaiinnovations/laya-multilingual"
REVISION = "e4e9ddf21a7b1903b7acffd8814ad4307bf63a67"


if __name__ == "__main__":
    target = snapshot_download(
        MODEL,
        revision=REVISION,
        local_dir=os.environ["LAYA_MODEL_DIR"],
        allow_patterns=["*.json", "*.safetensors", "tokenizer/*", "LICENSE*", "README.md"],
    )
    config = json.loads((Path(target) / "rl_agent_config.json").read_text())
    AutoConfig.from_pretrained(config["encoder"], trust_remote_code=False)
    print(f"Prepared {MODEL} at {REVISION}")
