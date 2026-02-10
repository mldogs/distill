#!/bin/bash
set -e

# =============================================================================
# Docker entrypoint script for Python services
# Handles: api, celery-worker, celery-beat, migrate
# =============================================================================

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# -----------------------------------------------------------------------------
# Wait for PostgreSQL to be ready
# -----------------------------------------------------------------------------
wait_for_postgres() {
    if [ -z "$DB_HOST" ]; then
        log_warn "DB_HOST not set, skipping PostgreSQL check"
        return 0
    fi

    log_info "Waiting for PostgreSQL at $DB_HOST:${DB_PORT:-5432}..."

    local max_attempts=30
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if pg_isready -h "$DB_HOST" -p "${DB_PORT:-5432}" -U "${DB_USER:-postgres}" > /dev/null 2>&1; then
            log_info "PostgreSQL is ready!"
            return 0
        fi

        log_info "Attempt $attempt/$max_attempts - PostgreSQL not ready, waiting..."
        sleep 2
        attempt=$((attempt + 1))
    done

    log_error "PostgreSQL did not become ready in time"
    return 1
}

# -----------------------------------------------------------------------------
# Wait for Redis to be ready
# -----------------------------------------------------------------------------
wait_for_redis() {
    if [ -z "$REDIS_URL" ]; then
        log_warn "REDIS_URL not set, skipping Redis check"
        return 0
    fi

    # Extract host and port from REDIS_URL (redis://host:port/db)
    local redis_host=$(echo "$REDIS_URL" | sed -E 's|redis://([^:]+):.*|\1|')
    local redis_port=$(echo "$REDIS_URL" | sed -E 's|redis://[^:]+:([0-9]+).*|\1|')

    log_info "Waiting for Redis at $redis_host:$redis_port..."

    local max_attempts=30
    local attempt=1

    while [ $attempt -le $max_attempts ]; do
        if python -c "import redis; r = redis.from_url('$REDIS_URL'); r.ping()" 2>/dev/null; then
            log_info "Redis is ready!"
            return 0
        fi

        log_info "Attempt $attempt/$max_attempts - Redis not ready, waiting..."
        sleep 2
        attempt=$((attempt + 1))
    done

    log_error "Redis did not become ready in time"
    return 1
}

# -----------------------------------------------------------------------------
# Run database migrations
# -----------------------------------------------------------------------------
run_migrations() {
    log_info "Running database migrations..."
    cd /app/storage && alembic upgrade head
    log_info "Migrations completed!"
}

# -----------------------------------------------------------------------------
# Main entrypoint logic
# -----------------------------------------------------------------------------
main() {
    local command="${1:-api}"

    case "$command" in
        api)
            wait_for_postgres

            # Run migrations if AUTO_MIGRATE is set
            if [ "${AUTO_MIGRATE:-false}" = "true" ]; then
                run_migrations
            fi

            log_info "Starting API server..."
            exec uvicorn api.main:app --host 0.0.0.0 --port "${API_PORT:-8000}"
            ;;

        celery-worker)
            wait_for_postgres
            wait_for_redis

            log_info "Starting Celery worker..."
            exec celery -A jobs.celery_app worker \
                --loglevel="${CELERY_LOG_LEVEL:-info}" \
                --concurrency="${CELERY_CONCURRENCY:-4}"
            ;;

        celery-beat)
            wait_for_redis

            log_info "Starting Celery beat scheduler..."
            exec celery -A jobs.celery_app beat \
                --loglevel="${CELERY_LOG_LEVEL:-info}"
            ;;

        migrate)
            wait_for_postgres
            run_migrations
            ;;

        shell)
            log_info "Starting interactive shell..."
            exec /bin/bash
            ;;

        *)
            # Pass through any other command
            log_info "Executing: $@"
            exec "$@"
            ;;
    esac
}

main "$@"
