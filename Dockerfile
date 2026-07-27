# =============================================================================
# Agent Trading System — Development Container
# =============================================================================
# Purpose: Local development environment with live code reload via volume mount.
# Not intended for production deployment.
# =============================================================================

FROM python:3.14.6-slim

WORKDIR /app

# Copy project definition files first (for Docker layer caching)
COPY pyproject.toml README.md requirements.lock ./

# Copy source code, scripts, and migrations (needed for editable install)
COPY src/ src/
COPY scripts/ scripts/
COPY db/ db/

# Install project with dev dependencies
RUN pip install --no-cache-dir --constraint requirements.lock -e ".[dev]"

# Environment defaults
ENV PYTHONPATH=/app/src
ENV PYTHONUNBUFFERED=1

# Default: keep the container alive for interactive use
CMD ["tail", "-f", "/dev/null"]
