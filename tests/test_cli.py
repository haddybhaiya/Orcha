"""Test CLI argument parsing, smoke execution, and validation mode."""

from pathlib import Path

from orcha.cli import main


def test_cli_smoke_demo_dataset() -> None:
    """Run CLI smoke test against synthetic demo dataset."""
    ret = main(["--dataset", "demo/dataset", "--smoke"])
    assert ret == 0


def test_cli_validate_only_demo_dataset() -> None:
    """Run CLI validate-only against synthetic demo dataset."""
    ret = main(["--dataset", "demo/dataset", "--validate-only"])
    assert ret == 0


def test_cli_default_mode() -> None:
    """Run CLI in default dataset information mode."""
    ret = main(["--dataset", "demo/dataset"])
    assert ret == 0


def test_cli_missing_dataset_failure(tmp_path: Path) -> None:
    """Run CLI pointing to empty directory; must fail cleanly."""
    empty_dir = tmp_path / "non_existent"
    ret = main(["--dataset", str(empty_dir), "--validate-only"])
    assert ret != 0


def test_cli_audit_data() -> None:
    """Run CLI --audit-data against synthetic demo dataset."""
    ret = main(["--dataset", "demo/dataset", "--audit-data"])
    assert ret == 0
