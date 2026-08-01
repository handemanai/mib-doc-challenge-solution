#!/usr/bin/env python3
"""Stage-1 worker: extract state for a slice of PDFs (sequential; plain OS
processes — multiprocessing pools deadlock with RapidOCR under macOS spawn).
Decisions happen later in decide_batch.py once the batch epoch is known.

Hang protection, layer 1: each case runs under a SIGALRM deadline; a hung
extraction degrades to a conservative empty state and the worker moves on.
Hangs inside C extensions don't surface Python signals, so the worker also
touches a heartbeat file before each PDF — predict.py watches it and
kills/respawns a worker whose heartbeat goes stale (layer 2).
"""
import json
import os
import signal
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from mib.pipeline import extract_state  # noqa: E402

CASE_TIMEOUT = int(os.environ.get("MIB_CASE_TIMEOUT", "120"))
EXTRACTION_ATTEMPT = int(os.environ.get("MIB_EXTRACTION_ATTEMPT", "1"))
MAX_CASES_PER_WORKER = int(os.environ.get("MIB_WORKER_MAX_CASES", "48"))
RECYCLE_EXIT_CODE = 75

# --- Batch-deadline governor (hang protection layer 3) -----------------------
# predict.py projects the batch finish time and publishes a degradation level
# to a file beside the state files; each case reads the level as it starts.
# Levels shed the least valuable OCR work first, only for cases not yet
# started, and recover automatically when the projection improves. Level 0 is
# byte-identical to an ungoverned run, so on hardware that meets the batch
# budget the governor never changes an output. The ladder exists so that slow
# evaluation hardware produces a measured, bounded quality cost on the tail
# instead of a batch-limit kill that loses the run.
# MIB_GOVERNOR_FORCE_LEVEL is an internal seam (the retry pass pins level 0;
# pinned-level measurement runs use it); receipt-producing supervisors reject
# it from the environment, so official runs cannot be quietly pinned.
GOVERNOR_LEVEL_FILE = "governor_level"
GOVERNOR_LEVELS = {
    0: {},
    1: {"MIB_NATIVE_MAX_PAGES": "2", "MIB_NATIVE_MAX_HQ": "1"},
    2: {"MIB_NATIVE_SCAN_OCR": "0"},
    3: {"MIB_NATIVE_SCAN_OCR": "0"},
    4: {"MIB_NATIVE_SCAN_OCR": "0"},
}
GOVERNOR_CASE_TIMEOUT = {3: 60, 4: 20}
GOVERNOR_MAX_LEVEL = max(GOVERNOR_LEVELS)
_GOVERNED_KEYS = ("MIB_NATIVE_SCAN_OCR", "MIB_NATIVE_MAX_PAGES",
                  "MIB_NATIVE_MAX_HQ")
_BASELINE_ENV = {key: os.environ.get(key) for key in _GOVERNED_KEYS}


def _governor_level(state_out):
    forced = os.environ.get("MIB_GOVERNOR_FORCE_LEVEL")
    raw = forced
    if raw is None:
        try:
            raw = (Path(state_out).parent / GOVERNOR_LEVEL_FILE).read_text()
        except OSError:
            return 0
    try:
        return max(0, min(GOVERNOR_MAX_LEVEL, int(raw.strip())))
    except ValueError:
        return 0


def _apply_governor_env(level):
    """Stateless per-case application: overrides for the level, the operator's
    original values for everything else, so a recovered level leaves no
    residue."""
    overrides = GOVERNOR_LEVELS.get(level, {})
    for key in _GOVERNED_KEYS:
        value = overrides.get(key, _BASELINE_ENV[key])
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = value


class CaseTimeout(BaseException):
    """Deadline control flow; broad best-effort observers must not swallow it."""
    pass


def _on_alarm(signum, frame):
    raise CaseTimeout()


def _failure_category(err):
    low = err.lower()
    if any(s in low for s in ("per_case_timeout", "casetimeout", "case timeout")):
        return "per_case_timeout"
    if any(s in low for s in ("onnx", "inferencesession", "session_failure")):
        return "recognizer_session_error"
    if "recognizable_stub" in low:
        return "recognizable_stub"
    return "extraction_exception"


def _error_summary(exc, limit=400):
    """Keep the exception class and root/tail message, not traceback prefixes.

    ONNXRuntimeError embeds a full traceback in str(exc); the actionable runtime
    message is the last non-empty line.  Newlines are collapsed and the result
    is bounded so ledgers do not grow without limit or retain incidental paths.
    """
    lines = [" ".join(line.split()) for line in str(exc).splitlines()
             if line.strip()]
    tail = lines[-1] if lines else "no_message"
    summary = f"{type(exc).__name__}: {tail}"
    if len(summary) <= limit:
        return summary
    prefix = f"{type(exc).__name__}: "
    return prefix + tail[-max(1, limit - len(prefix)):]


def _provenance(status, category=None, error=None):
    attempt = {"attempt": EXTRACTION_ATTEMPT, "status": status}
    if category:
        attempt["failure_category"] = category
    if error:
        attempt["error"] = error[:400]
    return {"attempt_count": 1, "recovered": False, "attempts": [attempt]}


def _empty_state(pdf, err, category=None):
    category = category or _failure_category(err)
    return {"case_id": Path(pdf).stem, "pools": {}, "doc_notes": {},
            "mean_ocr_conf": 0.0, "injection": {}, "error": err[:400],
            "extraction": _provenance("failed", category, err)}


def _terminal_failure_category(state):
    attempts = state.get("extraction", {}).get("attempts", [])
    if not attempts or attempts[-1].get("status") != "failed":
        return None
    return attempts[-1].get("failure_category")


def _test_hang(mode):
    """Test-only seam (tests/test_watchdog.py): simulate a hang that is either
    interruptible by SIGALRM ("py") or opaque to it like a spinning C call
    ("c"). Never active unless MIB_TEST_HANG_CASE is set in the environment."""
    if mode == "c":
        signal.pthread_sigmask(signal.SIG_BLOCK, {signal.SIGALRM})
    while True:
        time.sleep(0.05)


def _read_pdf_list(list_file):
    """Read the supervisor's lossless path list, with legacy compatibility.

    JSON is used by current callers because whitespace is legal in a path and
    a newline-delimited transport cannot represent a filename containing a
    newline.  Older newline-delimited lists remain accepted, but each line is
    treated as one path instead of being split on arbitrary whitespace.
    """
    raw = Path(list_file).read_text()
    try:
        paths = json.loads(raw)
    except json.JSONDecodeError:
        return [line for line in raw.splitlines() if line]
    if not isinstance(paths, list) or not all(isinstance(path, str)
                                               for path in paths):
        raise ValueError("PDF list must be a JSON array of paths")
    return paths


def main(list_file, state_out, heartbeat=None):
    pdfs = _read_pdf_list(list_file)
    hb = Path(heartbeat) if heartbeat else None
    signal.signal(signal.SIGALRM, _on_alarm)

    with open(state_out, "w") as f:
        for i, pdf in enumerate(pdfs):
            if hb:
                # JSON preserves every legal path character for the parent
                # watchdog, including leading/trailing spaces and newlines.
                hb.write_text(json.dumps(pdf))
            level = _governor_level(state_out)
            _apply_governor_env(level)
            case_timeout = GOVERNOR_CASE_TIMEOUT.get(level, CASE_TIMEOUT)
            signal.alarm(case_timeout)
            os.environ["MIB_ACTIVE_CASE"] = Path(pdf).stem
            case_started = time.monotonic()
            try:
                if os.environ.get("MIB_TEST_HANG_CASE") == Path(pdf).stem:
                    _test_hang(os.environ.get("MIB_TEST_HANG_MODE", "py"))
                crash_attempt = os.environ.get("MIB_TEST_CRASH_ATTEMPT", "all")
                if (os.environ.get("MIB_TEST_CRASH_CASE") == Path(pdf).stem
                        and crash_attempt in ("all", str(EXTRACTION_ATTEMPT))):
                    os.kill(os.getpid(), signal.SIGKILL)  # segfault stand-in
                exception_attempt = os.environ.get(
                    "MIB_TEST_EXTRACT_EXCEPTION_ATTEMPT", "1")
                if (os.environ.get("MIB_TEST_EXTRACT_EXCEPTION_CASE")
                        == Path(pdf).stem
                        and exception_attempt == str(EXTRACTION_ATTEMPT)):
                    raise RuntimeError("injected_python_extraction_failure")
                state = extract_state(pdf)
                if (os.environ.get("MIB_TEST_STUB_CASE") == Path(pdf).stem
                        and EXTRACTION_ATTEMPT == 1):
                    state = _empty_state(pdf, "recognizable_stub_injected",
                                         "recognizable_stub")
                else:
                    state["extraction"] = _provenance("success")
            except CaseTimeout:
                state = _empty_state(pdf, f"per_case_timeout({case_timeout}s)")
            except Exception as exc:
                state = _empty_state(pdf, _error_summary(exc))
            finally:
                signal.alarm(0)
                os.environ.pop("MIB_ACTIVE_CASE", None)
            if level:
                state["governor_level"] = level
            timing_log = os.environ.get("MIB_TIMING_LOG")
            if timing_log:
                # Opt-in per-case wall-time telemetry (off by default; no
                # production effect). One append-only line per case.
                try:
                    with open(timing_log, "a") as tf:
                        tf.write(f"{Path(pdf).stem}\t"
                                 f"{time.monotonic() - case_started:.3f}\n")
                except OSError:
                    pass
            f.write(json.dumps(state) + "\n")
            f.flush()
            os.fsync(f.fileno())
            if i % 25 == 0:
                print(f"{Path(state_out).stem}: {i}/{len(pdfs)}", flush=True)
            # A recognizer/session exception may poison process-global ONNX
            # state. The failed row is already durable; ask the parent to
            # resume only the unfinished tail in a fresh worker.
            if _terminal_failure_category(state) == "recognizer_session_error":
                return RECYCLE_EXIT_CODE
            # PyMuPDF and OCR dependencies keep process-global native state.
            # Long validation runs showed repeatable C-extension aborts after
            # roughly 78 cases per worker, while every fresh-process retry
            # succeeded. Recycle with a wide safety margin before that observed
            # cliff. The just-finished row is fsync'd above, so the parent
            # resumes only the durable tail.
            if i + 1 >= MAX_CASES_PER_WORKER and i + 1 < len(pdfs):
                return RECYCLE_EXIT_CODE
    return 0


if __name__ == "__main__":
    raise SystemExit(main(*sys.argv[1:4]))
