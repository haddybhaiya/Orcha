"""Application configuration and settings for Orcha"""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AppConfig:
    """Runtime configuration passed to CLI and core engine."""

    dataset_dir: Path = Path("dataset")
    output_path: Path = Path("output.csv")
    validate_only: bool = False
    smoke: bool = False
    audit_data: bool = False
    audit_evidence: bool = False
    resolve_user: str | None = None
    forecast_request_id: str | None = None
    check_baselines: bool = False
    check_samples: bool = False
    decision_request_id: str | None = None
    generate_output: bool = False
    validate_output: bool = False
    audit_safe_amounts: bool = False
    audit_earliest_dates: bool = False
    log_level: str = "INFO"

    @classmethod
    def from_env_or_args(
        cls,
        dataset: Path | str | None = None,
        output: Path | str | None = None,
        validate_only: bool = False,
        smoke: bool = False,
        audit_data: bool = False,
        audit_evidence: bool = False,
        resolve_user: str | None = None,
        forecast_request_id: str | None = None,
        check_baselines: bool = False,
        check_samples: bool = False,
        decision_request_id: str | None = None,
        generate_output: bool = False,
        validate_output: bool = False,
        audit_safe_amounts: bool = False,
        audit_earliest_dates: bool = False,
    ) -> "AppConfig":
        raw_dataset: Path | str
        if dataset is not None:
            raw_dataset = dataset
        elif env_ds := os.getenv("DATASET_DIR"):
            raw_dataset = env_ds
        elif Path("dataset").is_dir():
            raw_dataset = "dataset"
        elif Path("../dataset").is_dir():
            raw_dataset = "../dataset"
        else:
            raw_dataset = "dataset"

        raw_output = output or os.getenv("OUTPUT_CSV") or "output.csv"
        log_level = os.getenv("LOG_LEVEL", "INFO").upper()

        return cls(
            dataset_dir=Path(raw_dataset),
            output_path=Path(raw_output),
            validate_only=validate_only,
            smoke=smoke,
            audit_data=audit_data,
            audit_evidence=audit_evidence,
            resolve_user=resolve_user,
            forecast_request_id=forecast_request_id,
            check_baselines=check_baselines,
            check_samples=check_samples,
            decision_request_id=decision_request_id,
            generate_output=generate_output,
            validate_output=validate_output,
            audit_safe_amounts=audit_safe_amounts,
            audit_earliest_dates=audit_earliest_dates,
            log_level=log_level,
        )
