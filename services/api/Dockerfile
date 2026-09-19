# The `api` function (docs/design/api.md §7), which also serves the web app (ADR-0010).
# Built from the repository's root: `docker buildx build -f services/api/Dockerfile .`
# Both bases are pinned by the digest of their multi-architecture index; the release builds
# for linux/amd64 (ADR-0002).

# 1. The web app: installed exactly as web/package-lock.json pins it, with install scripts off,
#    type-checked and built by `npm run build` into /web/dist.
FROM node:24.21.0-trixie-slim@sha256:8ec5d7557396cfe32d21c3f9c13072355ceab22b584578ca4bb28af31120cffe AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --ignore-scripts --no-audit --no-fund
COPY web/ ./
RUN npm run build

# 2. The function: Lambda's Python 3.14 base, the code, and the built app beside it.
FROM public.ecr.aws/lambda/python:3.14@sha256:3f0bbbb2fd963ec4bdb2ec30e587464c91b0775ce7712167efdf17d5a12a7705

COPY src/tokelo ${LAMBDA_TASK_ROOT}/tokelo
COPY --from=web /web/dist ${LAMBDA_TASK_ROOT}/web

# No USER: Lambda runs a container image as its own least-privileged user, whatever the image
# says ("Create a Lambda function using a container image", AWS Lambda docs).
# nosemgrep: dockerfile.security.missing-user.missing-user
CMD ["tokelo.api.handler.handler"]
