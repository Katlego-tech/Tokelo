# The `ocr` worker (docs/design/ocr.md §2, §7). Debian's slim Python 3.14, not Lambda's own
# image: Amazon Linux 2023 packages no Tesseract, which T029 adds from apt. AWS's runtime client
# (awslambdaric) makes it a Lambda image. Both bases are pinned by the digest of their
# multi-architecture index; the release builds it for linux/amd64 (ADR-0002).
# Built from the repository's root: `docker buildx build -f services/ocr/Dockerfile .`
FROM ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c AS uv

FROM python:3.14-slim-trixie@sha256:caaf356f40667c496d405780745b9ac25771c189a51dfcc42430d531ea09f8a2

# Tesseract 5 and its English model, which is the whole reason this image is Debian's Python and
# not Lambda's: Amazon Linux 2023 packages no Tesseract (ADR-0009, docs/design/ocr.md §2). English
# only — no other language model is installed, and none is wanted (ADR-0009).
RUN apt-get update \
    && apt-get install --no-install-recommends --yes tesseract-ocr tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

# The runtime client and its dependencies, exactly as uv.lock pins them, every file checked
# against its hash. uv is only used here, and doesn't stay in the image.
COPY pyproject.toml uv.lock /tmp/build/
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv export --project /tmp/build --frozen --only-group ocr-image --no-emit-project \
        --format requirements-txt --output-file /tmp/build/requirements.txt \
    && uv pip install --system --require-hashes --no-deps -r /tmp/build/requirements.txt \
    && rm -rf /tmp/build

WORKDIR /function
COPY src/tokelo /function/tokelo

# No USER: Lambda runs a container image as its own least-privileged user, whatever the image
# says ("Create a Lambda function using a container image", AWS Lambda docs).
# nosemgrep: dockerfile.security.missing-user-entrypoint.missing-user-entrypoint
ENTRYPOINT ["/usr/local/bin/python", "-m", "awslambdaric"]
# nosemgrep: dockerfile.security.missing-user.missing-user
CMD ["tokelo.ocr.handler.handler"]
