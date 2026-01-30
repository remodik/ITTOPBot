# ===========================================
# CollegeSite Backend Dockerfile
# ===========================================
# Multi-stage build for optimized production image
#
# Build: docker build -t college-reports-api .
# Run:   docker run -p 8000:8000 college-reports-api

# Stage 1: Builder
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt


# Stage 2: Production
FROM python:3.11-slim as production

WORKDIR /app

# Install runtime dependencies only
RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq5 \
    curl \
    && rm -rf /var/lib/apt/lists/* \
    && apt-get clean

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Create non-root user for security
RUN useradd --create-home --shell /bin/bash appuser \
    && mkdir -p /app/data \
    && chown -R appuser:appuser /app

# Copy application code
COPY --chown=appuser:appuser . .

# Switch to non-root user
USER appuser

# Environment defaults
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HOST=0.0.0.0 \
    PORT=8000

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT}/api/health || exit 1

# Run with gunicorn for production
CMD ["sh", "-c", "gunicorn server:app --workers 2 --worker-class uvicorn.workers.UvicornWorker --bind ${HOST}:${PORT}"]


# Stage 3: Development (optional)
FROM production as development

USER root

# Install development dependencies
RUN pip install --no-cache-dir \
    pytest \
    black \
    flake8 \
    mypy

USER appuser

# Run with uvicorn reload for development
CMD ["sh", "-c", "uvicorn server:app --host ${HOST} --port ${PORT} --reload"]
