# Telegram Post Exchange - Python Services
# Used for: api, celery-worker, celery-beat

# =============================================================================
# Stage 1: Base image with system dependencies
# =============================================================================
FROM python:3.11-slim as base

# Prevent Python from writing .pyc files and buffering stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app

# Install system dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    # PostgreSQL client (for pg_isready)
    postgresql-client \
    # Build dependencies for some Python packages
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# =============================================================================
# Stage 2: Build dependencies
# =============================================================================
FROM base as builder

# Install Python dependencies
COPY requirements.txt .
COPY jobs/requirements.txt ./jobs/

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt && \
    pip install --no-cache-dir -r jobs/requirements.txt

# =============================================================================
# Stage 3: Runtime image
# =============================================================================
FROM base as runtime

# Copy installed packages from builder
COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin

# Create non-root user for security
RUN groupadd --gid 1000 appuser && \
    useradd --uid 1000 --gid 1000 --shell /bin/bash appuser

# Copy application code
COPY --chown=appuser:appuser . .

# Copy and set entrypoint
COPY --chown=appuser:appuser scripts/docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

# Switch to non-root user
USER appuser

# Default port for API
EXPOSE 8000

# Health check for API
HEALTHCHECK --interval=10s --timeout=5s --start-period=15s --retries=5 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=5)" || exit 1

# Default command (can be overridden in docker-compose)
ENTRYPOINT ["/docker-entrypoint.sh"]
CMD ["api"]
