# ADR-0005 — Leases are read from their text layer first, and OCR'd with Tesseract only where there's none

- Status: superseded by ADR-0009
- Date: 2026-09-19 · Deciders: Katlego

## Context

Module A reads uploaded leases: digital PDFs, scanned PDFs, and phone photos of printed pages.
The specification named Amazon Textract. Textract refuses this account while it's on the free
plan (`SubscriptionRequiredException`, 2026-09-18), and staying on the free plan is decided. So
OCR is open source (the user, 2026-09-18). This ADR picks the engine and where it runs.

What matters here:

- **Accuracy on real inputs:** clean digital PDFs, scans, and skewed, unevenly lit phone photos.
  South African leases are mostly in English, some in Afrikaans.
- **Where it runs:** a Lambda function from a container image (ADR-0002): at most 10 GB per
  image, 15 minutes per invocation, and 10,240 MB of memory, on CPU only.
- **Cost:** Lambda's always-free allowance is 400,000 GB-seconds a month. Heavier engines use it
  up faster.
- **The rules engine needs clause text,** not layout. The key-value and table extraction Textract
  offered isn't something module A depends on.

| Engine | Licence | Footprint | Strength | Weakness |
|---|---|---|---|---|
| Tesseract 5 | Apache-2.0 | small: a C++ library and a model per language (`eng`, `afr`) | mature, fast on CPU, good on clean printed text | weaker on skewed or unevenly lit photos without preprocessing |
| PaddleOCR | Apache-2.0 | large: the PaddlePaddle framework and models | better on photos and difficult layouts | a much bigger image, more memory, slower cold starts |
| docTR | Apache-2.0 | large: PyTorch or TensorFlow | good accuracy, modern models | a much bigger image, more memory |

## Options considered

1. **Do nothing: OCR every page with one engine.** This wastes time and accuracy on digital PDFs,
   whose text is already in the file.
2. **Text layer first, then Tesseract for pages without one, with preprocessing** (deskew,
   threshold and denoise, with Pillow or OpenCV) (chosen).
3. **Text layer first, then PaddleOCR.** It's more accurate on photos, but at several times the
   size and memory.
4. **Textract, by upgrading to the paid plan.** That's rejected by the free-plan decision.

## Decision

**The `ocr` worker reads each page's text layer first (`pypdf`), and runs Tesseract 5
(`eng` and `afr`), after preprocessing, only on pages without one.** PaddleOCR is the fallback,
through a new ADR, if Tesseract misses the accuracy NFR on the photo samples.

A measurement confirms the choice before the `ocr` worker is built on it:

- **The samples:** synthetic leases only, in the four forms. Real tenant documents never go into
  the repository.
- **What's measured:** the character error rate against the known text, and the time per page, in
  the `ocr` image on Lambda.

## Consequences

- The `ocr` image carries Tesseract and its two language models, `pypdf`, and Pillow or OpenCV. It
  stays small, which keeps cold starts short and the always-free allowance long.
- Each page is its own SQS message (ADR-0002), so a long lease never comes near Lambda's
  15-minute limit.
- `REQUIREMENTS.md` states the accuracy and time-per-page NFRs, and the measurement's samples
  become test fixtures.
- Digital PDFs, the common case, skip OCR entirely, and their text is exact.
