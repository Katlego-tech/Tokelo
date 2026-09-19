# The `api` function (docs/design/api.md §7): Lambda's Python 3.14 base image, pinned by the
# digest of its multi-architecture index; the release builds it for linux/amd64 (ADR-0002).
# Built from the repository's root: `docker buildx build -f services/api/Dockerfile .`
# T014 adds a Node stage before this one, to build and serve the web app (ADR-0010).
FROM public.ecr.aws/lambda/python:3.14@sha256:3f0bbbb2fd963ec4bdb2ec30e587464c91b0775ce7712167efdf17d5a12a7705

COPY src/tokelo ${LAMBDA_TASK_ROOT}/tokelo

# No USER: Lambda runs a container image as its own least-privileged user, whatever the image
# says ("Create a Lambda function using a container image", AWS Lambda docs).
# nosemgrep: dockerfile.security.missing-user.missing-user
CMD ["tokelo.api.handler.handler"]
