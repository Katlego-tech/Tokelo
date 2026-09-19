# Design documents

One per non-trivial lane, named after it, so `feat/<lane>` <-> `docs/design/<lane>.md`.
Start from [DESIGN-DOC.template.md](../../DESIGN-DOC.template.md); rules and the
which-diagram-when table are in [../design-documentation.md](../design-documentation.md).

Diagrams are **Mermaid in fenced code blocks**, never images -- they diff in a PR and every
assistant can read and write them.

| Lane | Doc | Status | Covers |
| --- | --- | --- | --- |
| domain model | [domain-model.md](domain-model.md) | agreed | the entities and their rules (class, sequence, state) |
| `api` | [api.md](api.md) | agreed | the endpoints, identity, pre-signed uploads, the key layout, job requests (sequence, contracts) |
| infrastructure | [infrastructure.md](infrastructure.md) | agreed | the VPC, database, buckets, events, queues, functions, identity, hosting, alarms, costs (deployment, contracts) |
| `ocr` | [ocr.md](ocr.md) | draft | text layer, OCR, clauses, the rule catalogue |
| `evidence` | [evidence.md](evidence.md) | draft | digests, EXIF, verification |
| `dossier` | [dossier.md](dossier.md) | draft | the PDF, the timeline |
| navigator | navigator.md | to be written (T009) | the curated topics |
| web | web.md | to be written (T010) | screens, flows, the reference images |
