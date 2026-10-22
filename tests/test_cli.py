"""Test CLI argument parsing, smoke execution, and validation mode."""

from pathlib import Path

from orcha.cli import main


def test_cli_smoke_real_dataset() -> None:
    """Run CLI smoke test against real repository dataset."""
    ret = main(["--smoke"])
    assert ret == 0


def test_cli_validate_only_real_dataset() -> None:
    """Run CLI validate-only against real repository dataset."""
    ret = main(["--validate-only"])
    assert ret == 0


def test_cli_default_mode() -> None:
    """Run CLI in default dataset information mode."""
    ret = main([])
    assert ret == 0


def test_cli_missing_dataset_failure(tmp_path: Path) -> None:
    """Run CLI pointing to empty directory; must fail cleanly."""
    empty_dir = tmp_path / "non_existent"
    ret = main(["--dataset", str(empty_dir), "--validate-only"])
    assert ret != 0


def test_cli_audit_data() -> None:
    """Run CLI --audit-data against real repository dataset."""
    ret = main(["--audit-data"])
    assert ret == 0

