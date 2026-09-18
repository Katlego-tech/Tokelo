# Observability: the OpenTelemetry baseline

Every service sends traces, metrics and logs with OpenTelemetry, to whatever OTLP endpoint its
environment names. The kit doesn't choose the backend (DESIGN.md §9); Grafana Cloud's free tier is
a good start (an OTLP endpoint and a token, no servers to run).

## The environment every service reads

| Variable | Value |
|---|---|
| `OTEL_SERVICE_NAME` | the `[[service]]` name in realm.toml |
| `OTEL_RESOURCE_ATTRIBUTES` | `service.version=<release>,deployment.environment=<staging or production>` |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | the backend's OTLP address |
| `OTEL_EXPORTER_OTLP_HEADERS` | its credentials, e.g. `Authorization=Basic …`: a secret, set on the platform, never committed |
| `OTEL_TRACES_SAMPLER` | `parentbased_traceidratio`, with `OTEL_TRACES_SAMPLER_ARG=0.2` once traffic is real |

The `compose` platform sets the first two by itself. On Railway, set them as service variables in
each environment; `service.version` is the release's tag.

## Instrumenting, without code changes

- **Python:** add `opentelemetry-distro` and `opentelemetry-exporter-otlp`, run
  `opentelemetry-bootstrap -a install` once, and start the service through
  `opentelemetry-instrument` (e.g. `opentelemetry-instrument uvicorn app.main:app`).
- **Node:** add `@opentelemetry/api` and `@opentelemetry/auto-instrumentations-node`, and start
  with `node --require @opentelemetry/auto-instrumentations-node/register server.js`.

Then add spans by hand only where the automatic ones don't reach: the core's key steps.

## What to measure

- **The SLIs in `slo.toml`:** each objective's indicator has to be a query on this data, or the
  objective can't be tracked between releases.
- **Error budget burn:** alert when the budget is burning fast enough to run out within the window.
- **Never** personal data in span or log attributes: mask it where it's recorded.
