# The `evidence` worker (docs/design/evidence.md §7): Lambda's Python 3.14 base image, pinned by
# the digest of its multi-architecture index; the release builds it for linux/amd64 (ADR-0002).
# Built from the repository's root: `docker buildx build -f services/evidence/Dockerfile .`
FROM ghcr.io/astral-sh/uv:0.11.32@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c AS uv
FROM public.ecr.aws/lambda/python:3.14@sha256:3f0bbbb2fd963ec4bdb2ec30e587464c91b0775ce7712167efdf17d5a12a7705

# Pillow and pypdf, exactly as uv.lock pins them, every file checked against its hash, into the
# function's own directory (the base image ships boto3 and nothing else this worker needs). uv is
# only used here, and doesn't stay in the image.
# --no-cache: uv's cache is named at random each run, and left in the image it made every build's
# digest different (T056).
COPY pyproject.toml uv.lock /tmp/build/
RUN --mount=from=uv,source=/uv,target=/usr/local/bin/uv \
    uv export --project /tmp/build --frozen --only-group evidence-image --no-emit-project \
        --format requirements-txt --output-file /tmp/build/requirements.txt \
    && uv pip install --python /var/lang/bin/python --target "${LAMBDA_TASK_ROOT}" --no-cache \
        --require-hashes --no-deps -r /tmp/build/requirements.txt \
    && rm -rf /tmp/build

COPY src/tokelo ${LAMBDA_TASK_ROOT}/tokelo

# No USER: Lambda runs a container image as its own least-privileged user, whatever the image
# says ("Create a Lambda function using a container image", AWS Lambda docs).
# nosemgrep: dockerfile.security.missing-user.missing-user
CMD ["tokelo.evidence.handler.handler"]
