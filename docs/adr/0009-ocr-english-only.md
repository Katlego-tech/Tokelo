# ADR-0009 — Leases are read in English only: text layer first, then Tesseract's English model

- Status: accepted
- Date: 2026-09-19 · Deciders: Katlego

## Context

ADR-0005 chose how leases are read: the PDF's text layer first, then Tesseract 5 on pages without
one, with PaddleOCR as the fallback. It named two Tesseract language models. On 2026-09-19
Katlego decided that **Tokelo reads English only**, and that no other language belongs anywhere
in the project.

Everything else in ADR-0005 still holds:
- the free plan rules out Textract
- Lambda's limits: 10 GB per image, 15 minutes, 10,240 MB, CPU only
- the always-free allowance favours a small engine
- the rules engine needs clause text, not layout

This ADR restates that decision with English only, and supersedes ADR-0005.

## Options considered

1. **Do nothing: keep ADR-0005** and its second language model. Ruled out by Katlego's decision.
2. **English only:** the text layer, then Tesseract 5 with the English model (`eng`), with
   preprocessing (chosen).

## Decision

**The `ocr` worker reads each page's text layer first (`pypdf`), and runs Tesseract 5 with the
English model (`eng`) only, after preprocessing (deskew, threshold, denoise), on pages without
one.** PaddleOCR is the fallback, through a new ADR, if Tesseract misses the accuracy NFR on the
photo samples.

A measurement confirms the choice before the `ocr` worker is built on it:
- **the samples:** synthetic English leases only, in three forms: a digital PDF, a scanned PDF,
  and phone photos. Real tenant documents never go into the repository.
- **what's measured:** the character error rate against the known text, and the time per page,
  in the `ocr` image on Lambda.

## Consequences

- **The `ocr` image carries Tesseract and its English model only,** with `pypdf` and the
  preprocessing libraries.
- **A lease in any other language isn't supported:**
  - its scanned pages read with low confidence, so they're reported as pages that couldn't be
    read (REQ-004)
  - its text-layer pages don't match the English rules, so no clause is flagged
  - the web app says plainly that Tokelo reads English leases
- `SPEC.md`'s non-goals say "English only", and the sample leases (T028) are English.
- Each page is still its own SQS message (ADR-0002), so no invocation comes near 15 minutes.
