# Runtime for agent commands: Python and the bench service's dependencies, baked in because the sandbox has no network.
FROM python:3.12-slim

RUN pip install --no-cache-dir \
        "fastapi==0.115.*" "pydantic==2.*" "httpx==0.27.*" \
        "pytest==8.*" "ruff==0.7.*" \
    && useradd --create-home --uid 1000 agent

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER agent
WORKDIR /work
