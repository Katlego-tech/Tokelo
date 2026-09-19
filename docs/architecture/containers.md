# `tokelo` — Containers (C4 level 2)

<!-- The deployable pieces inside the system box, and how they talk: each app, service and data
     store, with its technology. Required, like the context diagram. A non-trivial service also
     gets a component diagram (level 3): copy docs/architecture/component.template.md. -->

```mermaid
C4Container
    title Containers: tokelo
    Person(tenant, "Tenant")
    System_Boundary(tokelo, "Tokelo, AWS eu-west-1") {
        Container(web, "Web app", "React, shadcn/ui; served by the api function (ADR-0010)", "The tenant's interface")
        Container(auth, "User pool", "Amazon Cognito", "Accounts, MFA, tokens")
        Container(gw, "API", "API Gateway (HTTP API), JWT authorizer", "One entry point for the app and /api/: TLS, throttling")
        Container(api, "api", "Python 3.14 on Lambda, container image", "Upload URLs, leases, evidence, dossiers, the rights navigator")
        ContainerDb(files, "Documents bucket", "Amazon S3, SSE-KMS, private", "Uploads as received, job requests, generated dossiers")
        ContainerQueue(queues, "Job queues", "EventBridge to SQS standard queues, each with a dead-letter queue (ADR-0007)", "Lease, evidence and dossier jobs")
        Container(ocr, "ocr", "Python 3.14 on Lambda; pypdf, Tesseract 5", "Page text, clause rules, explanations")
        Container(evidence, "evidence", "Python 3.14 on Lambda", "SHA-256 digests, EXIF metadata")
        Container(dossier, "dossier", "Python 3.14 on Lambda", "The indexed dispute PDF")
        ContainerDb(db, "Database", "Aurora PostgreSQL Serverless v2, private subnets", "Tenants, leases, clauses, flags, evidence, digests, the audit log")
    }
    Rel(tenant, web, "Uses", "HTTPS")
    Rel(web, auth, "Signs in", "HTTPS")
    Rel(web, gw, "Calls, with the tenant's token", "JSON/HTTPS")
    Rel(web, files, "Uploads files directly", "HTTPS PUT, pre-signed URL")
    Rel(gw, api, "Invokes")
    Rel(api, db, "Reads and writes", "PostgreSQL, IAM authentication")
    Rel(api, files, "Signs URLs; writes job requests", "S3 gateway endpoint")
    Rel(files, queues, "Object created", "EventBridge")
    Rel(queues, ocr, "Lease jobs")
    Rel(queues, evidence, "Evidence jobs")
    Rel(queues, dossier, "Dossier jobs")
    Rel(ocr, db, "Writes pages, clauses, flags")
    Rel(evidence, db, "Writes digests, metadata")
    Rel(dossier, db, "Reads the selected records")
    Rel(dossier, files, "Writes the PDF", "S3 gateway endpoint")
```

**How the pieces fit together:**

| Rule | Why | Where it's decided |
|---|---|---|
| **Every job starts as an object in S3.** An upload, or a job request the `api` writes (such as "build this dossier"), creates an object. EventBridge sends it to the job's queue | functions inside the VPC can't call SQS or EventBridge, because there's no way out of the subnets. S3 is reachable through the free gateway endpoint | ADR-0003 |
| **File bytes never pass through the API** | pre-signed URLs offload the I/O (competency 1) | REQ-002 |
| **A job that fails three times goes to its dead-letter queue** | at-least-once processing, with nothing silently lost (competency 2) | REQ-017 |
| **The functions and the database are in private subnets, with no way to or from the internet**; the database takes connections only from the functions | strict network isolation (competency 3) | ADR-0003, REQ-018 |
| **Each evidence file's SHA-256 is recorded when it's stored**, and the audit log is append-only | cryptographic integrity (competency 4) | REQ-008, REQ-011 |
| **Every service is a Lambda function from a container image,** deployed by digest by the release pipeline | $0 while idle | ADR-0002 |
| **The database pauses at 0 ACU when idle,** and connections use IAM tokens signed locally | nearly $0 while idle; no secrets endpoint needed | ADR-0004 |
