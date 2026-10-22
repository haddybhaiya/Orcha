"""Test application configuration and path resolution."""

import os
from pathlib import Path

from orcha.config import AppConfig


def test_default_config() -> None:
    config = AppConfig.from_env_or_args()
    assert config.dataset_dir in (Path("dataset"), Path("../dataset"))
    assert config.output_path == Path("output.csv")
    assert config.validate_only is False
    assert config.smoke is False


def test_explicit_args_override() -> None:
    config = AppConfig.from_env_or_args(
        dataset="custom/dataset",
        output="custom/out.csv",
        validate_only=True,
        smoke=True,
    )
    assert config.dataset_dir == Path("custom/dataset")
    assert config.output_path == Path("custom/out.csv")
    assert config.validate_only is True
    assert config.smoke is True


def test_env_var_fallback(monkeypatch: object) -> None:
    os.environ["DATASET_DIR"] = "env_data"
    os.environ["OUTPUT_CSV"] = "env_output.csv"
    try:
        config = AppConfig.from_env_or_args()
        assert config.dataset_dir == Path("env_data")
        assert config.output_path == Path("env_output.csv")
    finally:
        del os.environ["DATASET_DIR"]
        del os.environ["OUTPUT_CSV"]
