# `tokelo` — System context (C4 level 1)

<!-- The system as one box: who uses it, and which other systems it depends on. Required in every
     Secret Realm project (scripts/realm/realm design-check), and free of placeholders once any
     requirement is approved. Keep it true as the system changes: it's the first thing a new
     person, human or AI, reads. -->

```mermaid
C4Context
    title System context: tokelo
    Person(tenant, "Tenant", "A residential tenant in South Africa, on a phone or a laptop")
    Person(operator, "Operator", "Releases, the budget and incidents")
    System(tokelo, "Tokelo", "Checks leases against the curated statutes, keeps tamper-evident evidence, compiles dispute dossiers, answers rights questions. AWS eu-west-1")
    System_Ext(github, "GitHub", "The code, CI, and the release and promote workflows")
    System_Ext(tribunal, "Rental Housing Tribunal or Small Claims Court", "Receives the dossier, from the tenant")
    Rel(tenant, tokelo, "Uploads leases and evidence, builds dossiers, asks questions", "HTTPS")
    Rel(operator, github, "Merges changes, tags releases")
    Rel(github, tokelo, "Deploys a release's signed images", "AWS APIs, OIDC roles")
    Rel(tokelo, operator, "Budget alerts", "email")
    Rel(tenant, tribunal, "Files the dossier")
```

- **The tenant files the dossier themselves.** Tokelo has no connection to the Tribunal or the
  courts, and it doesn't speak for the tenant.
- **Everything Tokelo runs is in one AWS account,** in `eu-west-1` (ADR-0001). The services it
  uses from AWS appear inside the box on the [containers](containers.md) diagram.
- **No language model** is called in phases 1–5 (ADR-0006), and no other outside service
  receives tenant data.
