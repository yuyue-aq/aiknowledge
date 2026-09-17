FROM python:3.14.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:${PATH}"

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

# Keep the resolver version aligned with the lockfile-producing development
# environment so container builds remain reproducible.
RUN python -m pip install --no-cache-dir "uv==0.12.3"

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --extra local-embeddings --no-install-project

COPY app ./app
COPY alembic.ini ./
COPY migrations ./migrations

# The dependency environment contains the optional local BGE runtime and can
# be several gigabytes.  It is intentionally read-only at runtime, so only
# application-owned sources need changing to the non-root user.  Avoiding a
# recursive chown of .venv keeps rebuilds fast without weakening isolation.
RUN chown -R app:app /app/app /app/migrations && chown app:app /app/alembic.ini /app/pyproject.toml /app/uv.lock
USER app

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
