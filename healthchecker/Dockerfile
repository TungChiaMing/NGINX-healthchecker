# syntax=docker/dockerfile:1
FROM python:3.12-alpine

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /opt

# Runtime deps only. --only-binary: use prebuilt wheels, never compile (fail fast instead).
# The pip cache survives failed builds, so a retry doesn't download everything again.
COPY requirements-docker.txt /tmp/requirements-docker.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --timeout 120 --retries 10 --only-binary=:all: -r /tmp/requirements-docker.txt

# build context is ./healthchecker -> /opt/healthchecker (run as: python3 -m healthchecker.main)
COPY . healthchecker

EXPOSE 8082
