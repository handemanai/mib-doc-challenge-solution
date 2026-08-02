# CFA-MIB-000865 visible-evidence forensic result

## Decision

`MIB-000865` is not recoverable from legitimate judge-visible evidence.
The public truth is `visa_class=TRANSIT-7` and `adjudication=DENIED`, but the
only visible visa field in the four-page packet cleanly says
`Visa Class: XW-2`.

This is not an OCR failure. No visible correction, cross-out, signed finding,
adverse stamp, or second document supplies `TRANSIT-7`. A reader or ROI change
cannot recover a token that is absent from the visible pixels.

The disposition is:

- `REJECT` the broad review-only attestation gate;
- `PARK` the narrow exact-pattern observation as an unsupported post-hoc
  singleton;
- do not add a production rule, field rewrite, case lookup, generator prior,
  or non-visible signal.

## Frozen evidence boundary

The forensic design allowed ordinary rendered pixels, visible printed text,
signatures, stamps, checkbox state, cross-outs, and case-bound visible
authority. It excluded hidden or optional-content text, answer keys, barcode
instructions, filenames, case IDs, document hashes, generator signatures, and
truth as an input to reading or rule construction.

The target PDF is bound by SHA-256
`f197d4be25fb96ebb6b69ca9c040f6340887405471b238219ba13a3cf2195fbc`.
The frozen source commit is
`e392ce99b134e75887a3a0950446760ed83ee114` (a pre-publication working-tree
commit in the private experiment tree). The final public runtime preserves the
same fields and decision for this packet.

The exact-pattern cohort was selected from visible cached state before opening
its comparator labels. The target's already-known error motivated the
investigation; its truth was not treated as candidate evidence.

## What is visible

| Page | Visible evidence | Decision boundary |
| --- | --- | --- |
| 1, biometric | Zaquell Miramora; TRIANGULAN; flags none | No visa or adverse authority |
| 2, registry | name; Gliese-581g; TRIANGULAN; CLEAR; 2026-06-15 | `CLEAR` is not a visa correction |
| 3, fee | waived; $0.00; `DIP-WAIVER` | Fee evidence, not visa or adjudication evidence |
| 4, intake | `Visa Class: XW-2`; SPN-4146; 2026-06-15; reactor maintenance | No correction, signature, or adverse finding |

The visible red page-4 stamps read `COPY`, `FILED`, and `ARCHIVE`. Raster OCR
at 200 and 400 DPI reads `XW-2` and never `TRANSIT-7`.

The PDF contains four pages and no annotations, links, optional-content
groups, embedded files, form, or JavaScript. Pages 1 and 4 are raster pages
apart from footer text. This container inventory supports absence only; no
non-visible channel is treated as positive evidence.

Rendered-page SHA-256 bindings:

| Render | SHA-256 |
| --- | --- |
| page 1, 200 DPI | `bfd4d4d941b1e01752c31261cb2ff5d442a7dca9c6c6dcc586f1aa1b3b3254fe` |
| page 2, 200 DPI | `2f26d21d970c260cb86a4c2361c5c7be3d6b89940106da69ad4354b91f336b6e` |
| page 3, 200 DPI | `d8dc5efcd92887de17f6544051040935b9fde18ffa5819d9fbc8abde769661ac` |
| page 4, 200 DPI | `acf36769aad591871753c2b623764f844fc5a8b1820d0c2d200e40664d757817` |
| page 4, 400 DPI | `b3d4f1b51867609abed6c96be6f5c4ec90f3804bba647fa2a019772f7ca1de4d` |

## Current pipeline behavior

The frozen state accurately emits visa `XW-2` from `intake`, with snap score
`100`, evidence agreement `1`, fee `waived`, risk flags `none`, action
`APPROVED`, and reason `clean`. It has no rank-1 finding, rank-1 conflict,
native ledger, or image-view registry error.

Another reader over the intake would add another observation of the same
physical source, not independent authority.

## Cohort and group support

All four predeclared exact-pattern cases have visible `DIP-WAIVER`, emitted
`XW-2`, fee `waived`, risk flags `none`, and current reason `clean`.

| Case | Public truth action | Public truth visa |
| --- | --- | --- |
| `MIB-000109` | APPROVED | XW-2 |
| `MIB-000152` | NEEDS_REVIEW | XW-2 |
| `MIB-000821` | APPROVED | XW-2 |
| `MIB-000865` | DENIED | TRANSIT-7 |

Across 106 visible `DIP-WAIVER` cases, 21 emitted `XW-2` values agree with
truth `XW-2`; `MIB-000865` is the only `XW-2 -> TRANSIT-7` mismatch. The
three comparators contain a visible sponsor-attestation page corroborating
`XW-2`; the target does not. Missing attestation is a legitimate difference
in approval provenance, but it is not evidence for `TRANSIT-7` or denial.

Group support is insufficient:

- layout `grp-52ab4ec78f30817a`: target is a singleton;
- damage `grp-d7155af244268d08`: target is the only exact-pattern member;
- topology `grp-2c80b12d27e5b1b9`: target is the only exact-pattern member.

## Frozen review-only gate

After visual discovery, the following broader rule was frozen before opening
the five candidate labels:

> Demote an existing approval to review when visa evidence has agreement one,
> no visible sponsor-letter page exists, and no signed rank-1 approval exists.

The rule could only demote `APPROVED` to `NEEDS_REVIEW`; it could not deny or
rewrite any field. Its frozen candidates were `MIB-000242`, `MIB-000303`,
`MIB-000740`, `MIB-000865`, and `MIB-000913`.

Measured outcome:

- one catastrophic false approval removed;
- four correct approvals demoted;
- zero truth-review cases corrected;
- classification raw delta `-18`;
- classification-section delta `-0.18`, before calibration.

Two harmed approvals, `MIB-000303` and `MIB-000740`, are in the target's
topology group. That group directly rejects generalization of the broad gate.
The narrower target pattern remains a post-hoc isolate without same-layout or
same-pattern support.

## Bound ignored originals

The detailed working evidence remains intentionally ignored and is bound here
so the negative result is auditable without making transient renders part of
the tracked portfolio:

| Ignored artifact | SHA-256 |
| --- | --- |
| `PREDECLARED_FORENSIC_DESIGN.json` | `068a90a70ecef2152219f62fb528623970c26c65f6949f94da36be039706680d` |
| `POSTHOC_ATTESTATION_GATE_DESIGN.json` | `ab463de5b6c4d3c5ac7e47ad5c556d0b7c09db08383d02767c93094af1503223` |
| `POSTHOC_ATTESTATION_GATE_RESULTS.json` | `a7e9df11af176a039508c4b44361b062f465d7f876347b2c200271126e6cd228` |
| `FORENSIC_FINDINGS.md` | `df7ebdf38163f323f8d5dc8e7b995f1d30fe4d12ad5b0d5f20b746a0a56c3513` |

The frozen state, state receipt, terminal evaluation receipt, evidence ledger,
and tracked group manifest are bound in a standardized receipt that lives in
the private experiment tree; this file is the self-contained public summary.

## Rule boundary

No production behavior follows from this case. In particular:

- do not infer `TRANSIT-7` from `DIP-WAIVER` or missing attestation;
- do not infer denial from absence of approval corroboration;
- do not use a case ID, filename, hash, hidden layer, answer key, barcode
  instruction, or generator signature;
- do not promote a reader whose only success is this target;
- do not weaken the rule that independent authority requires distinct physical
  view and source provenance.

A future reconsideration requires a label-blind, repeated, group-supported
failure mechanism; a review-only effect; zero new catastrophic approvals; no
usable-group score regression; and perturbation/provenance validation.

The technical memo (`MEMO.md` in this repository) independently corroborates
the pixel-level absence of `TRANSIT-7`. It was consulted only after this
reproduction and is not an input to the gate or its measured result.
