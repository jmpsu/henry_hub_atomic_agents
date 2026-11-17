Work autonomously; ask nothing. Repo: ~/Projects/henry_hub_atomic_agents. Run `source .venv/bin/activate` first. Follow every rule in CLAUDE.md.

STEP 1 — CONSISTENCY GATE (do this before touching any code)
1. Read docs/GOAL_CHECKLIST.md and goal_checklist.txt in full.
2. Print a table: every row ID (S, G, G1-*, E, F, M, A, B, N, R, V, X, O, AD, D, P, O12-R, O13-R, O14-R) with its I/T/P or Status marks, from docs/GOAL_CHECKLIST.md.
3. Compare against goal_checklist.txt: list any ID present in one file but not the other, and any row whose marks differ.
4. Confirm these exist and match the checklist: ~/Downloads/0002-lng-forward-knowledge-library-ollama.patch (sha256 23b703139c45f43b605c3217d629b835eee1ad79c3ed8301a869ebe732b1125d), markets_complete.txt, ~/emi_alignment.tsv.
5. If goal_checklist.txt has rows that docs/GOAL_CHECKLIST.md lacks, copy those rows into docs/GOAL_CHECKLIST.md (additive only, never delete a row).
6. Print exactly one line: "CHECKLIST CONSISTENT: docs/GOAL_CHECKLIST.md is the single source of truth" — or, if anything cannot be reconciled, print "CHECKLIST INCONSISTENT:" with the exact differences and STOP.

STEP 2 — IMPLEMENT (only after the CONSISTENT line)
Work through docs/GOAL_CHECKLIST.md in this order, updating I/T/P marks in place after each row is verified:
 a. P1/O15: keep the fuller uncommitted G1 implementation in the working tree; port the knowledge-library parameter sourcing from the 0002 patch (lng_evidence.py logic) onto it, obeying O13-R (adopted). Do not apply 0001.
 b. G1 and all G1-* rows, then AD6.
 c. G5: M1-M7, Module B (B1-B4, AD2 Waha, AD3 T&F as labelled constant), Module A (A1-A4, F0-F13): build every part that has an available feed; for each feed that does not exist, record BLOCKED with the exact blocker and the command that activates it.
 d. G2/E1-E8, AD1, N1-N3.
 e. G6: R1.1-R3.5, V1-V6 (chat bar per R3.1).
 f. AD7: drill-down D-rows.
 g. AD8 using ~/emi_alignment.tsv.
Rules: never use port 8095 for test runs (O1) — use 127.0.0.1:8096; run the targeted pytest file after each module, the full suite at the end; no fabricated values; PIT cutoff everywhere; provenance on every new figure; checkpoint the DB before any state-changing run.

STEP 3 — FINISH
Commit on feat/lng-forward (separate commits per section), push, run the full suite, take the headless-Chrome screenshots named in the checklist, update section 10 (final gate) marks, and print a final report: every row ID with I/T/P, BLOCKED rows with exact blockers, test tail, screenshot paths.
