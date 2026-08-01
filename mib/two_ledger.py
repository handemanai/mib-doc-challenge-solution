"""Two-ledger fusion: evdom-v1 field selection + monotone decision reconcile.

Two independent *results* are produced first — a complete baseline ledger and a
complete native-pixel ledger, each decided by the same pure `pipeline.decide` —
and only then are they combined:

* Emitted fields are chosen by the frozen ``evdom-v1`` rule (`choose_native` /
  `select_fields`), ported byte-equivalent from the frozen analysis tool. It
  preserves every baseline risk token, requires a native evidence record, and
  replaces a baseline field only when it is weak/fallback or strictly dominated
  by a stronger, no-worse native read. Field fills never feed the decision.
* The adjudication is reconciled by `reconcile` under an explicit monotone
  policy (never relax a baseline denial; never let benign native evidence open
  an approval; a stricter NEEDS_REVIEW->DENIED only with explicit causal adverse
  native evidence).

Ablations (config ``MIB_TWO_LEDGER``):

* ``fields`` (Ablation 1): field selection only; adjudication/reasons/confidence
  byte-frozen to baseline (= evdom-v1 exactly).
* ``full``   (Ablation 2): fields + adverse-only decision flips.
"""
from __future__ import annotations

import copy
import os

from .vocab import (DISQUALIFYING_FLAGS, FEES, FLAGS, PURPOSES, SPECIES,
                    VISAS, WORLDS)

# Closed vocabularies a native winner must already belong to before it may be
# selected (the native decode snaps to these; the gate asserts it). risk_flags
# is a pipe-joined subset of FLAGS plus "none".
_LEGAL_VALUES = {
    "species_code": frozenset(SPECIES),
    "home_world": frozenset(WORLDS),
    "visa_class": frozenset(VISAS),
    "declared_purpose": frozenset(PURPOSES),
    "fee_status": frozenset(FEES),
}
_LEGAL_FLAGS = frozenset(FLAGS) | {"none"}


def ablation_from_env():
    """Resolve the active fusion mode from the environment.

    Returns ``None`` when the native ledger is off (baseline behavior), else
    ``"fields"`` (Ablation 1) or ``"full"`` (Ablation 2). ``MIB_TWO_LEDGER``
    selects the ablation; when the native ledger is on but the mode is unset,
    the production mode (``full``) is used.
    """
    if os.environ.get("MIB_NATIVE_SCAN_OCR", "1") != "1":
        return None
    mode = os.environ.get("MIB_TWO_LEDGER", "full").strip().lower()
    return "fields" if mode == "fields" else "full"

RULE_ID = "evdom-v1"
FIELDS = (
    "applicant_name",
    "species_code",
    "home_world",
    "visa_class",
    "sponsor_id",
    "arrival_date",
    "declared_purpose",
    "risk_flags",
    "fee_status",
)

POST_FUSION_REVIEW_CONFIDENCE = 0.55


def enforce_final_consistency(pred, detail, receipt):
    """Reconcile a final APPROVED row with the exact fields it will emit.

    Selection and fusion pick fields after the decision is made, so a row can
    otherwise ship APPROVED while its own printed evidence demands denial —
    the one pattern a reviewer can refute from the submission file alone.

    Semantics (can only preserve or narrow an approval, never create or deny):
    - Emitted fields adjudicate APPROVED: unchanged.
    - Approval rests on a rank-1 adjudicator-note finding (the manual's
      highest evidence rank): the finding stays authoritative for the
      decision, but it does not invent field values. An emitted unpaid fee is
      changed only when the same rank-1 payload explicitly corrects fee_status
      to paid or waived. Other contradictions keep their fields and the
      approval stands, with the conflict recorded for audit.
    - Any other approval whose emitted fields adjudicate DENIED or
      NEEDS_REVIEW narrows to NEEDS_REVIEW at capped confidence.
    """
    from . import rules

    if pred.get("adjudication") != "APPROVED":
        return pred, detail
    fields = {f: pred.get(f) for f in FIELDS}
    policy, policy_reasons = rules.adjudicate(fields, receipt_date=receipt)
    if policy == "APPROVED":
        return pred, detail
    note_authority = (detail.get("reasons") == ["adjudicator_note"])
    audit = {
        "final_before": "APPROVED",
        "ordinary_policy_decision": policy,
        "ordinary_policy_reasons": list(policy_reasons),
        "note_authority": note_authority,
    }
    if note_authority:
        if policy == "DENIED" and policy_reasons == ["unpaid_fee"]:
            rank1_fee = ((detail.get("rank1_payload") or {}).get("fields")
                         or {}).get("fee_status")
            if rank1_fee in {"paid", "waived"}:
                pred = dict(pred)
                pred["fee_status"] = rank1_fee
                audit["action"] = \
                    "fee_reconciled_to_explicit_rank1_correction"
            else:
                audit["action"] = "preserved_rank1_finding_approval"
        else:
            audit["action"] = "preserved_rank1_finding_approval"
        detail = dict(detail)
        detail["post_fusion_consistency"] = audit
        return pred, detail
    pred = dict(pred)
    pred["adjudication"] = "NEEDS_REVIEW"
    pred["confidence"] = min(
        float(pred.get("confidence", 1.0)), POST_FUSION_REVIEW_CONFIDENCE)
    detail = dict(detail)
    detail["reasons"] = ["post_fusion_field_conflict"]
    audit["action"] = "review_field_conflict"
    audit["final_after"] = "NEEDS_REVIEW"
    detail["post_fusion_consistency"] = audit
    return pred, detail


# --- evdom-v1 selector (ported verbatim from field_view_selector_frozen.py) ---

def norm(value):
    return " ".join(str(value or "").strip().casefold().split())


def flag_set(value):
    raw = norm(value)
    if raw in {"", "none", "null", "unknown"}:
        return set()
    return {part.strip() for part in raw.split("|")
            if part.strip() and part.strip() != "none"}


def field_equal(field, left, right):
    if field == "risk_flags":
        return flag_set(left) == flag_set(right)
    return norm(left) == norm(right)


def finite_number(value, fallback):
    try:
        result = float(value)
    except (TypeError, ValueError):
        return fallback
    return result if result == result and abs(result) != float("inf") else fallback


def choose_native(field, base_value, native_value, base_evidence,
                  native_evidence):
    """Apply the frozen, deterministic ``evdom-v1`` selector."""
    if field_equal(field, base_value, native_value):
        return False, "agreement"
    if not native_evidence:
        return False, "native_without_evidence"
    if field == "risk_flags" and not flag_set(native_value).issuperset(
            flag_set(base_value)):
        return False, "preserve_baseline_risk_tokens"

    base_rank = finite_number(base_evidence.get("rank"), 99.0)
    native_rank = finite_number(native_evidence.get("rank"), 99.0)
    base_snap = finite_number(base_evidence.get("snap_score"), -1.0)
    native_snap = finite_number(native_evidence.get("snap_score"), -1.0)

    if base_rank >= 6.0:
        return True, "replace_weak_baseline_evidence"
    if native_rank < base_rank and native_snap >= base_snap:
        return True, "native_evidence_dominates"
    return False, "baseline_evidence_not_dominated"


def select_fields(base_fields, base_evidence, native_fields, native_evidence):
    """Return (fused_fields, audit) applying evdom-v1 over the nine fields.

    ``*_evidence`` map field -> {"rank", "snap_score", ...} as emitted by the
    runtime ledger (`scripts/predict.py::_ledger_row`). Baseline values are
    preserved unless the frozen rule selects the native read.
    """
    fused = copy.deepcopy(dict(base_fields))
    audit = []
    for field in FIELDS:
        base_value = base_fields.get(field)
        native_value = native_fields.get(field)
        use_native, reason = choose_native(
            field, base_value, native_value,
            base_evidence.get(field) or {}, native_evidence.get(field) or {})
        if use_native:
            fused[field] = native_value
            audit.append({
                "field": field, "base": base_value, "native": native_value,
                "reason": reason,
            })
    return fused, audit


# --- adverse-evidence detection for the monotone decision reconcile ---

def native_adverse_record(native_pred, native_detail):
    """Explicit causal adverse native evidence, or ``None``.

    Exactly two adverse causes are recognised (both pre-registered):

    1. A native-evidenced deny-trigger risk token: the native read carries a
       disqualifying flag that was actually extracted and drove a native denial
       (e.g. MIB-000672 ``active_warrant``).
    2. A body-``Case ID:``-bound native rank-1 ``DENIED`` finding. The native
       ledger only grants finding authority through that binding, so a native
       ``finding_note == "DENIED"`` is by construction body-ID-bound.
    """
    if native_pred.get("adjudication") != "DENIED":
        return None
    reasons = native_detail.get("reasons") or []
    extracted = set(native_detail.get("extracted_fields") or [])

    tokens = flag_set(native_pred.get("risk_flags"))
    deny_tokens = sorted(tokens & DISQUALIFYING_FLAGS)
    if deny_tokens and "risk_flags" in extracted and "disqualifying_flag" in reasons:
        return {
            "cause": "native_deny_trigger_risk_token",
            "tokens": deny_tokens,
            "reasons": list(reasons),
        }

    origin = native_detail.get("finding_authority_origin") or {}
    if (native_detail.get("finding_note") == "DENIED"
            and origin.get("view") == "native_full_page_image"):
        return {
            "cause": "body_id_bound_native_denied_finding",
            "origin": origin,
            "reasons": list(reasons),
        }
    return None


def reconcile(base_out, native_out, native_adverse, ablation):
    """Reconcile the two adjudications under the monotone policy.

    Returns (adjudication, reasons, confidence, transition_record). ``base_out``
    / ``native_out`` are dicts with adjudication/reasons/confidence. Precedence:

    1. Ablation 1 (``fields``) or native ledger absent -> baseline tuple, exact.
    2. Baseline DENIED -> baseline tuple (never relax a denial).
    3. Same adjudication both sides -> baseline tuple, exact (incl. confidence).
    4. NEEDS_REVIEW -> DENIED only with an explicit causal adverse native
       record; the flipped row takes the native decide() confidence.
    5. Otherwise baseline tuple; APPROVED is never created by reconciliation.
    """
    base_tuple = (base_out["adjudication"], list(base_out["reasons"]),
                  base_out["confidence"])

    def frozen(reason):
        return (*base_tuple, {
            "decision_source": "baseline",
            "rule": reason,
            "base_adjudication": base_out["adjudication"],
            "native_adjudication": (native_out or {}).get("adjudication"),
            "confidence_source": "baseline",
        })

    if ablation != "full":
        return frozen("ablation_fields_decisions_frozen")
    if native_out is None:
        return frozen("native_absent")
    if base_out["adjudication"] == "DENIED":
        return frozen("baseline_denied_never_relaxed")
    if base_out["adjudication"] == native_out["adjudication"]:
        return frozen("same_adjudication")
    if (base_out["adjudication"] == "NEEDS_REVIEW"
            and native_out["adjudication"] == "DENIED"
            and native_adverse is not None):
        return ("DENIED", list(native_out["reasons"]), native_out["confidence"], {
            "decision_source": "native_adverse_flip",
            "rule": "needs_review_to_denied_adverse",
            "base_adjudication": "NEEDS_REVIEW",
            "native_adjudication": "DENIED",
            "adverse_evidence": native_adverse,
            "confidence_source": "native",
        })
    return frozen("no_authorized_transition")


# --- top-level per-case orchestration -----------------------------------------

def decide_case(state, base_epoch, native_epoch, base_revoked, native_revoked,
                ablation):
    """Decide one case under the two-ledger fusion.

    ``ablation`` is ``None`` (baseline only — no native ledger present),
    ``"fields"`` (Ablation 1) or ``"full"`` (Ablation 2). Returns
    (pred, detail) matching `pipeline.decide`, with two-ledger provenance added
    to the detail (``two_ledger``) for the audit trail.
    """
    from .pipeline import decide

    base_pred, base_detail = decide(state, base_epoch, batch_revoked=base_revoked)
    native = state.get("native_ledger")
    if not ablation or native is None:
        return enforce_final_consistency(base_pred, base_detail, base_epoch)

    native_pred, native_detail = decide(
        native, native_epoch, batch_revoked=native_revoked)

    base_evidence = _evidence_map(base_detail)
    native_evidence = _evidence_map(native_detail)
    # Route each native winner through the baseline's shipped per-field validity
    # gates before the frozen evdom comparison (closes the sanity-gate bypass).
    native_fields, native_rejections = sanitize_native(
        {f: base_pred[f] for f in FIELDS}, base_evidence,
        {f: native_pred.get(f) for f in FIELDS}, native_evidence,
        base_epoch)
    fused_fields, field_audit = select_fields(
        {f: base_pred[f] for f in FIELDS},
        base_evidence,
        native_fields,
        native_evidence)

    # Annotate each accepted native fill with the source page type it came from,
    # for the promotion overlap analysis (a note/receipt/slip page a dedicated
    # reader lane also targets, vs. an ordinary field page unique to two-ledger).
    native_sources = native_detail.get("sources", {}) \
        if isinstance(native_detail, dict) else {}
    for row in field_audit:
        row["native_source"] = native_sources.get(row["field"])

    adverse = native_adverse_record(native_pred, native_detail)
    base_out = {"adjudication": base_pred["adjudication"],
                "reasons": base_detail.get("reasons") or [],
                "confidence": base_pred["confidence"]}
    native_out = {"adjudication": native_pred["adjudication"],
                  "reasons": native_detail.get("reasons") or [],
                  "confidence": native_pred["confidence"]}
    adjudication, reasons, confidence, transition = reconcile(
        base_out, native_out, adverse, ablation)

    pred = dict(base_pred)
    pred.update(fused_fields)
    pred["adjudication"] = adjudication
    pred["confidence"] = confidence

    transition_record = {
        "rule_id": RULE_ID,
        "ablation": ablation,
        "field_selection": field_audit,
        "native_fills": [row["field"] for row in field_audit],
        "baseline_lock": [f for f in FIELDS
                          if f not in {row["field"] for row in field_audit}],
        "decision_transition": transition,
        "confidence_source": transition.get("confidence_source"),
        "native_rejections": native_rejections,
        "native_adverse": adverse,
        "native_adjudication": native_pred["adjudication"],
        "native_confidence": native_pred["confidence"],
        "unbound_note_observations": native.get("unbound_note_observations", []),
    }
    detail = dict(base_detail)
    detail["reasons"] = reasons
    detail["two_ledger"] = transition_record
    return enforce_final_consistency(pred, detail, base_epoch)


def _agreement_count(evidence):
    """Cross-source corroboration count a ledger recorded for a field, or None."""
    value = (evidence or {}).get("agreement")
    return value if isinstance(value, (int, float)) else None


def _closed_vocab_ok(field, value):
    """True when a native winner is already a legal value for a closed-vocab
    field (risk_flags is a pipe-joined subset of FLAGS plus ``none``)."""
    if field == "risk_flags":
        tokens = {part.strip() for part in str(value).split("|")
                  if part.strip()}
        return bool(tokens) and tokens <= _LEGAL_FLAGS
    legal = _LEGAL_VALUES.get(field)
    return legal is None or value in legal


def sanitize_native(base_pred, base_evidence, native_pred, native_evidence,
                    receipt):
    """Close the native-candidate sanity-gate bypass before evdom compares.

    Each native field winner that disagrees with the baseline is routed through
    the SAME per-field validity gates the baseline already enforces, and a
    rejected native value is set to the baseline value so the frozen evdom
    selector sees agreement and keeps the baseline. The gates:

    * ``arrival_date`` -- the shipped year-garble twin arbitration
      (`pipeline._arbitrate_date_pool`) over {baseline, native}: a native read
      implausibly far past the receipt epoch that shares month-day with the
      plausible baseline is a single-digit year garble and is dropped.
    * ``applicant_name`` -- both tokens must reach the name lexicon
      (`pipeline._name_lexicon_ok`, which also requires two tokens), and a
      native read may not displace a baseline name that is strictly better
      corroborated. Two lexicon-legal names differing by one syllable ("Zarix"
      vs "Zanax") are indistinguishable by validity alone, so this reuses the
      cross-source agreement signal the baseline selector already trusts --
      compared on the GENUINE agreement each ledger independently recorded, not
      a synthetic re-pool that would structurally bias against the native read.
    * closed-vocab fields -- the native winner must already be a legal value.

    evdom's choose_native/select_fields comparison is byte-untouched. Returns
    (sanitized_native_pred, rejections).
    """
    from . import pipeline
    native_pred = dict(native_pred)
    rejections = []
    for field in FIELDS:
        base_value = base_pred.get(field)
        native_value = native_pred.get(field)
        if field_equal(field, base_value, native_value):
            continue

        def _reject(reason):
            rejections.append({"field": field, "native": native_value,
                               "baseline": base_value, "reason": reason})
            native_pred[field] = base_value

        if field == "arrival_date":
            kept, valid = pipeline._arbitrate_date_pool(
                [[base_value], [native_value]], receipt)
            survivors = kept or valid
            if survivors and not any(
                    field_equal(field, c[0], native_value) for c in survivors):
                _reject("date_year_garble")
            continue

        if field == "applicant_name":
            if not pipeline._name_lexicon_ok(native_value):
                _reject("name_off_lexicon")
                continue
            base_agr = _agreement_count(base_evidence.get(field))
            native_agr = _agreement_count(native_evidence.get(field))
            if (base_agr is not None and native_agr is not None
                    and native_agr < base_agr):
                _reject("name_less_corroborated_than_baseline")
            continue

        if not _closed_vocab_ok(field, native_value):
            _reject("off_vocabulary_value")
    return native_pred, rejections


def _evidence_map(detail):
    """{field: {"rank", "snap_score", "agreement"}} from a decide() detail."""
    out = {}
    for field, ev in (detail.get("field_evidence") or {}).items():
        if isinstance(ev, (list, tuple)) and len(ev) >= 2:
            out[field] = {"rank": ev[0], "snap_score": ev[1],
                          "agreement": ev[2] if len(ev) >= 3 else 1}
    return out


def native_batch_inputs(states):
    """(native_states, has_native) for computing a native batch epoch/revoked.

    Returns the list of embedded native ledgers so the native decide can use a
    batch epoch and frequent-sponsor set computed over the native reads, keeping
    each ledger a fully independent result.
    """
    natives = [s["native_ledger"] for s in states
               if isinstance(s, dict) and s.get("native_ledger") is not None]
    return natives, bool(natives)
