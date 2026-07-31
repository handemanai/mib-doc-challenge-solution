# Reviewer guide — verify the claims in 15 minutes

Everything in `MEMO.md` is backed by an artifact in this repository. This page
maps each claim to the fastest way to check it.

## 1. Reproduce one packet in 60 seconds

```bash
docker build -t mib-submission .
mkdir -p /tmp/one && cp <train_dir>/MIB-000001.pdf /tmp/one/
docker run --rm --network none --cpus 4 --memory 8g --read-only --tmpfs /tmp \
  --mount type=bind,src=/tmp/one,dst=/input,readonly \
  --mount type=bind,src=/tmp/out,dst=/output \
  mib-submission /input /output/predictions.jsonl
```

Two runs produce byte-identical output; the full 5,000-case validation run is
one uninterrupted invocation of the same entrypoint.

## 2. The trap suite proves itself

`tests/redteam_corpus/` contains a self-authored corpus of every injection
vector the field manual names but the public PDFs omit — white-on-white and
render-mode-3 answer keys, off-crop text, zero-opacity fills, hidden OCG
layers, QR instructions, under-image text, microtext — each paired with a
clean twin. The pytest suite (`tests/test_redteam.py`) asserts each
trapped packet produces output identical to its twin: the injections are not
merely resisted, they are provably invisible to the decision path. The
runtime contains no component that follows instructions (no LLM/VLM), so the
instruction-injection surface this dataset targets does not exist.

The injections are not hypothetical: about a quarter of the validation
packets carry a hidden answer key, and a cross-submission census shows most
public entries follow it on 10%+ of those cases, versus 2.6% incidental
agreement for this pipeline. On MIB-102051 a 76% majority of public entries
deny — the hidden key's verdict — while the visibly printed registry line
reads `Registry Status: CLEAR`.

## 3. The one false approval is proven irreducible, not excused

`experiments/CFA-MIB-000865-visible-forensic.md` documents the audit of every
channel the true visa class could occupy on MIB-000865 — text layer,
native-resolution OCR, hidden/off-crop text, annotations, optional-content
groups, embedded files, cross-field consistency, near-white wash reveal — and
its absence from all of them, plus the control packet showing that
"find the washed clue" is itself a planted trap on approval-side packets.

## 4. Safety architecture is structural, not statistical

- Deny-direction ROI readers cannot emit approval-moving values by
  construction (`mib/flagread.py`, `mib/worldread.py`).
- Approval-adjacent reads face positive-evidence bars
  (`mib/feeread.py`: "paid" requires the "un" region provably clean).
- Every APPROVED row is re-adjudicated against the exact fields it emits
  before it is written (`mib/two_ledger.py`,
  `enforce_post_fusion_consistency`) — the submission cannot print an
  approval whose own evidence demands denial or review.
- `NEEDS_REVIEW` on evidence-withheld packets is the designed-correct output,
  confirmed by the organizers (challenge issue #5).

## 5. Honest measurement

Tuning used a fixed 799-case split; the 201-case holdout was read only at
milestones. Negative results are retained rather than discarded:
approaches measured and rejected include an ML hedge-resolution gate (−4
OOF), a +90-raw-EV approval expansion declined for manufacturing systematic
false approvals, and a trained OCR-correction transducer that ships disabled
after losing on the sealed holdout under its pre-registered gate.

`docs/PERFORMANCE_OPPORTUNITY_REGISTER_2026-07-26.md` is the register of
every remaining opportunity with its measured ceiling — including the ones we
chose not to take and why. `experiments/CFA-MIB-000865-visible-forensic.md`
is the full irreducibility forensic behind section 3.
