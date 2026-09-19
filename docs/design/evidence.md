# Design — the `evidence` lane

**Status:** draft · **Owner:** Katlego · **Tasks:** T007, then T037–T040, T041 (the timeline
entries) · **Spec:** [SPEC.md](../../SPEC.md) US2, US3

---

## 1. What this covers

The `evidence` worker, for every photo, notice and WhatsApp export a tenant uploads. It:
- records the file's SHA-256 digest and when it was stored
- reads a photo's capture metadata
- creates the file's timeline entries

It also sets how a file is verified later.

It doesn't cover:
- leases: [ocr.md](ocr.md)
- the verify endpoint's shape: [api.md](api.md) §6
- how the timeline is laid out in a dossier: [dossier.md](dossier.md)

## 2. Reference material

| Kind | Where |
| --- | --- |
| Requirements | REQ-008 to REQ-012 |
| Decisions | ADR-0007 (idempotent workers) |
| The tables | [domain-model.md](domain-model.md): `Document`, `CaptureMetadata`, `TimelineEntry`, `AuditEntry` |
| Standards | SHA-256 (FIPS 180-4), through Python's `hashlib`; EXIF 2.3 tags `DateTimeOriginal`, `OffsetTimeOriginal`, `Make`, `Model` and the GPS tags, read with Pillow |
| WhatsApp exports | the two line formats in §6 |

## 3. Domain model

The worker writes `Document.sha256`, `stored_at` and `s3_version_id`, and `CaptureMetadata` and
`TimelineEntry` ([domain-model.md](domain-model.md)). Nothing new.

## 4. Flow

```mermaid
sequenceDiagram
    participant Q as evidence queue
    participant E as evidence
    participant S as S3
    participant D as Database
    Q->>E: Object Created: uploads/{tenant}/{photo|notice|chat}/{doc}
    E->>D: the Document by key; stop if it already has its sha256 (ADR-0007)
    E->>S: HEAD the object, by version: its LastModified and real size
    E->>S: GET it, by version, streamed through SHA-256
    E->>D: Document stored: sha256, s3_version_id, stored_at = LastModified
    alt photo
        E->>E: read EXIF: capture time, device, GPS
        E->>D: INSERT CaptureMetadata (NULL where absent); a TimelineEntry at the capture time, if there is one
    else notice
        E->>D: a TimelineEntry at the notice's date (§6)
    else chat
        E->>E: parse the export into messages (§6)
        E->>D: a TimelineEntry per message
    end
    E->>D: Document processed; AuditEntry upload
```

**Verifying a file later** is done by the `api` ([api.md](api.md), T039). It reads the stored
object **by the recorded version ID**, streams it through SHA-256, compares the result with the
recorded digest, and writes an audit entry. It never hashes something the client sends.

**Failure paths:**
- **The object's real size is over the kind's limit** (a client got around the policy):
  `failed`, with the reason.
- **EXIF can't be read, or isn't there:** the capture fields stay NULL, shown as "not recorded"
  (REQ-009). That isn't a failure.
- **A chat line doesn't match either format:** it's added to the message before it, as WhatsApp
  does with multi-line messages. An export with no parsable line is `failed` ("not a WhatsApp
  export").
- **A job is delivered twice:** the document already has its digest, so the worker stops.

## 5. State

The document's states are [domain-model.md](domain-model.md) §5's. This worker moves it
`stored` → `processed`, or `failed`.

## 6. Contracts

### What's recorded for a photo

| Field | From | When absent |
|---|---|---|
| `captured_at` | `DateTimeOriginal`, with `OffsetTimeOriginal` if present. Without an offset, taken as SAST (UTC+2), and the view says so | NULL: "not recorded" |
| `device` | `Make` and `Model` | NULL: "not recorded" |
| `latitude`, `longitude` | the GPS IFD, converted to decimal degrees | NULL: "not recorded" |

Nothing is inferred. The upload time is **not** used as a capture time.

### A notice's date

In this order, and the entry's summary says which it is:
1. the photo's capture time, for a notice that was photographed
2. the PDF's creation date, if the file has one
3. otherwise, the upload time, labelled "uploaded on"

### WhatsApp export lines

A message starts at a line in either format:
- Android: `DD/MM/YYYY, HH:MM - Name: message`
- iOS: `[DD/MM/YYYY, HH:MM:SS] Name: message`

The export has no time zone, so the time is taken as SAST (UTC+2). Each message becomes one
`TimelineEntry` (`chat_message`), whose summary is the sender and the message, cut to 500
characters. The export itself stays whole, with its own digest.

## 7. Structure

| Path | New? | Responsibility |
| --- | --- | --- |
| `src/tokelo/evidence/handler.py` | new | the entry point, and the health answer |
| `src/tokelo/evidence/digest.py` | new | streaming SHA-256 by version; `stored_at` from `LastModified` (T037) |
| `src/tokelo/evidence/exif.py` | new | §6's photo fields (T038) |
| `src/tokelo/dossier/timeline.py` | new | notice dates and WhatsApp parsing (T041). It belongs to the dossier lane, and this worker calls it at upload |
| `services/evidence/Dockerfile` | new | Lambda's Python 3.14 base, pinned by digest |
| `tests/evidence/`, `tests/fixtures/photos/`, `tests/fixtures/timeline/` | new | synthetic photos (with and without EXIF) and exports |

## 8. Decisions & alternatives

| Decision | Chosen | Rejected, and why |
| --- | --- | --- |
| What the digest is of | **the stored object, by its version ID,** read back from S3 | a digest sent by the browser: the tenant's own claim isn't evidence |
| When "stored" is | **S3's `LastModified` for that version** | the event's arrival time: later, and less exact |
| A photo with no capture time | **"not recorded"**, and no timeline entry from it | the upload time as a stand-in: it would put the photo on the wrong day (REQ-009) |
| Where the timeline entries are made | **here, at upload** | at dossier time: the timeline page would be empty until a dossier is built |
| Keeping files tamper-evident | **the digest, versioning and the append-only audit log** | S3 Object Lock: see [infrastructure.md](infrastructure.md) §8 |

Deviations from [docs/architecture-defaults.md](../architecture-defaults.md): none.

## 9. How this is verified

- `tests/evidence/test_digest.py`:
  - the recorded digest equals `sha256sum` of the fixture
  - a second delivery changes nothing (REQ-008)
- `tests/evidence/test_exif.py`: a photo with full EXIF, one with no GPS, one with no EXIF at all
  (REQ-009).
- `tests/api/test_verify.py`:
  - an unchanged file matches
  - a new version of the object doesn't, because the recorded version is what's read (REQ-010)
- `tests/dossier/test_timeline.py`: both WhatsApp formats, a multi-line message, and a file that
  isn't an export (REQ-012).

## 10. Open questions

- [ ] **HEIC photos from iPhones** ([api.md](api.md) §10): if tenants' photos arrive as HEIC,
  reading their EXIF needs a library decision first.

## Threats (STRIDE)

| Threat | STRIDE | Where | Mitigation | Proven by |
|---|---|---|---|---|
| A tenant supplies a digest of their own | Spoofing | the digest | the worker computes it from the stored object; nothing from the client is used | tests/evidence/test_digest.py (T037) |
| A stored file is overwritten after it was fingerprinted | Tampering | the documents bucket | versioning keeps the original, and verification reads the recorded version, so a later write can't pass as the original | tests/api/test_verify.py (T039) |
| A digest is changed in the database | Tampering | `Document.sha256` | the trigger refuses any change once it's set ([domain-model.md](domain-model.md)) | tests/integration/test_schema.py (T023) |
| A tenant denies having uploaded or verified a file | Repudiation | uploads, verifications | an audit entry for each, which the application can't edit | tests/integration/test_schema.py (T023) |
| A photo's GPS reveals where the tenant lives to someone else | Information disclosure | `CaptureMetadata` | only the tenant's own requests return it; it enters a dossier only when the tenant selects that photo | tests/api/test_authz.py (T024) |
| A crafted image exhausts memory | Denial of service | `exif.py` | only the EXIF block is read, never the pixels; 20 MB at most | tests/evidence/test_exif.py (T038) |
| A crafted export floods the timeline | Denial of service | `timeline.py` | 5 MB at most; each summary cut to 500 characters | tests/dossier/test_timeline.py (T041) |
