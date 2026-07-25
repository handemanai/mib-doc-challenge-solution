import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUN_SH = ROOT / "run.sh"


def test_run_sh_forwards_optional_predict_arguments(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$@\"\n")
    fake_python.chmod(0o755)
    env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}")

    result = subprocess.run(
        ["bash", str(RUN_SH), "/in", "/out/predictions.jsonl",
         "--ledger", "/out/ledger.jsonl",
         "--run-receipt", "/out/run-receipt.json"],
        text=True, capture_output=True, env=env)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == [
        "/app/scripts/predict.py",
        "/in",
        "/out/predictions.jsonl",
        "--ledger",
        "/out/ledger.jsonl",
        "--run-receipt",
        "/out/run-receipt.json",
    ]


def test_run_sh_pins_native_math_threads(tmp_path):
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    fake_python = fake_bin / "python3"
    fake_python.write_text(
        "#!/bin/sh\n"
        "printf '%s\\n' \"$OMP_NUM_THREADS\" \"$OPENBLAS_NUM_THREADS\" "
        "\"$MKL_NUM_THREADS\"\n")
    fake_python.chmod(0o755)
    env = dict(os.environ, PATH=f"{fake_bin}:{os.environ['PATH']}",
               OMP_NUM_THREADS="9", OPENBLAS_NUM_THREADS="8",
               MKL_NUM_THREADS="7")

    result = subprocess.run(
        ["bash", str(RUN_SH), "/in", "/out/predictions.jsonl"],
        text=True, capture_output=True, env=env)

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["1", "1", "1"]
