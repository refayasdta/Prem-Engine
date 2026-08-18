#!/bin/sh
set -eu

DATABASE_NAME="${POSTGRES_DB:-prem_engine}"
DATABASE_USER="${POSTGRES_USER:-prem_engine}"
DATABASE_HOST="${POSTGRES_HOST:-postgres}"
BACKUP_ROOT=/backups
MODEL_ROOT=/models
VERIFY_DATABASE=prem_engine_restore_verify

psql_database() {
  database="$1"
  shift
  psql --no-psqlrc --set=ON_ERROR_STOP=1 --host "$DATABASE_HOST" \
    --username "$DATABASE_USER" --dbname "$database" "$@"
}

safe_bundle_name() {
  case "$1" in
    prem-engine-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]T[0-9][0-9][0-9][0-9][0-9][0-9]Z) ;;
    *) echo "Invalid backup bundle name: $1" >&2; exit 2 ;;
  esac
}

summary_query() {
  cat <<'SQL'
SELECT 'schema_revision=' || COALESCE((SELECT version_num FROM alembic_version LIMIT 1), 'missing')
UNION ALL SELECT 'matches=' || count(*) FROM matches
UNION ALL SELECT 'players=' || count(*) FROM players
UNION ALL SELECT 'squad_memberships=' || count(*) FROM squad_memberships
UNION ALL SELECT 'legacy_simulations=' || count(*) FROM stored_simulations
UNION ALL SELECT 'device_simulations=' || count(*) FROM device_simulations
UNION ALL SELECT 'device_played=' || count(*) FROM device_simulations WHERE state = 'played'
UNION ALL SELECT 'device_missed=' || count(*) FROM device_simulations WHERE state = 'missed'
UNION ALL SELECT 'device_void=' || count(*) FROM device_simulations WHERE state = 'void'
UNION ALL SELECT 'model_artifacts=' || count(*) FROM local_model_artifacts
UNION ALL SELECT 'active_models=' || COALESCE(string_agg(model_type || ':' || model_version, ',' ORDER BY model_type), 'none')
  FROM local_model_artifacts WHERE active IS TRUE
ORDER BY 1;
SQL
}

write_summary() {
  database="$1"
  destination="$2"
  summary_query | psql_database "$database" --tuples-only --no-align > "$destination"
}

require_quiescent_database() {
  connections="$(psql_database postgres --tuples-only --no-align --command \
    "SELECT count(*) FROM pg_stat_activity WHERE datname = '$DATABASE_NAME' AND pid <> pg_backend_pid();")"
  if [ "${connections:-0}" -ne 0 ]; then
    echo "Backup/restore refused: stop the api and worker services first." >&2
    echo "Active database connections: $connections" >&2
    exit 3
  fi
}

backup() {
  require_quiescent_database
  timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
  bundle_name="prem-engine-$timestamp"
  bundle="$BACKUP_ROOT/$bundle_name"
  mkdir -p "$bundle"
  umask 077
  pg_dump --host "$DATABASE_HOST" --username "$DATABASE_USER" --dbname "$DATABASE_NAME" \
    --format=custom --no-owner --no-acl --file "$bundle/database.dump"
  tar -C "$MODEL_ROOT" -czf "$bundle/local-models.tar.gz" .
  write_summary "$DATABASE_NAME" "$bundle/database-summary.txt"
  {
    echo "schema_version=1"
    echo "created_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "release=${PREM_ENGINE_RELEASE:-uncommitted}"
    echo "database=$DATABASE_NAME"
    echo "provider_secrets_included=false"
  } > "$bundle/metadata.txt"
  (cd "$bundle" && sha256sum database.dump local-models.tar.gz database-summary.txt metadata.txt > SHA256SUMS)
  echo "$bundle_name"
}

verify_bundle_files() {
  bundle_name="$1"
  safe_bundle_name "$bundle_name"
  bundle="$BACKUP_ROOT/$bundle_name"
  test -d "$bundle" || { echo "Backup bundle not found: $bundle_name" >&2; exit 2; }
  (cd "$bundle" && sha256sum -c SHA256SUMS && tar -tzf local-models.tar.gz >/dev/null)
}

drop_verify_database() {
  psql_database postgres --command \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$VERIFY_DATABASE';" >/dev/null
  psql_database postgres --command "DROP DATABASE IF EXISTS $VERIFY_DATABASE;" >/dev/null
}

verify() {
  bundle_name="${1:-}"
  verify_bundle_files "$bundle_name"
  bundle="$BACKUP_ROOT/$bundle_name"
  trap drop_verify_database EXIT INT TERM
  drop_verify_database
  psql_database postgres --command "CREATE DATABASE $VERIFY_DATABASE;" >/dev/null
  pg_restore --host "$DATABASE_HOST" --username "$DATABASE_USER" --dbname "$VERIFY_DATABASE" \
    --no-owner --no-acl --exit-on-error "$bundle/database.dump"
  write_summary "$VERIFY_DATABASE" /tmp/restored-summary.txt
  if ! cmp -s "$bundle/database-summary.txt" /tmp/restored-summary.txt; then
    echo "Restored database summary differs from the backup manifest." >&2
    diff -u "$bundle/database-summary.txt" /tmp/restored-summary.txt >&2 || true
    exit 4
  fi
  echo "Verified backup: $bundle_name"
}

restore() {
  bundle_name="${1:-}"
  confirmation="${2:-}"
  if [ "$confirmation" != "RESTORE-$DATABASE_NAME" ]; then
    echo "Restore refused. Pass the exact confirmation: RESTORE-$DATABASE_NAME" >&2
    exit 5
  fi
  require_quiescent_database
  verify_bundle_files "$bundle_name"
  bundle="$BACKUP_ROOT/$bundle_name"
  psql_database postgres --command \
    "ALTER DATABASE $DATABASE_NAME WITH ALLOW_CONNECTIONS false;" >/dev/null
  psql_database postgres --command \
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = '$DATABASE_NAME';" >/dev/null
  psql_database postgres --command "DROP DATABASE $DATABASE_NAME;" >/dev/null
  psql_database postgres --command "CREATE DATABASE $DATABASE_NAME;" >/dev/null
  pg_restore --host "$DATABASE_HOST" --username "$DATABASE_USER" --dbname "$DATABASE_NAME" \
    --no-owner --no-acl --exit-on-error "$bundle/database.dump"
  find "$MODEL_ROOT" -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
  tar -C "$MODEL_ROOT" -xzf "$bundle/local-models.tar.gz"
  write_summary "$DATABASE_NAME" /tmp/restored-summary.txt
  cmp "$bundle/database-summary.txt" /tmp/restored-summary.txt
  echo "Restored backup: $bundle_name"
}

diagnostics() {
  echo "Prem Engine local diagnostics"
  echo "generated_at_utc=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "database_ready=$(pg_isready --host "$DATABASE_HOST" --username "$DATABASE_USER" --dbname "$DATABASE_NAME" --quiet && echo true || echo false)"
  if pg_isready --host "$DATABASE_HOST" --username "$DATABASE_USER" --dbname "$DATABASE_NAME" --quiet; then
    write_summary "$DATABASE_NAME" /tmp/current-summary.txt
    cat /tmp/current-summary.txt
    psql_database "$DATABASE_NAME" --tuples-only --no-align --command \
      "SELECT 'worker_status=' || status || ',operation=' || COALESCE(current_operation, 'none') || ',last_fixture_success=' || COALESCE(last_fixture_success_at::text, 'never') || ',last_error=' || COALESCE(last_error_code, 'none') FROM local_worker_state WHERE singleton_key = 1;"
    psql_database "$DATABASE_NAME" --tuples-only --no-align --command \
      "SELECT 'provider_requests_today=' || count(*) FROM provider_requests WHERE requested_at >= date_trunc('day', now());"
  fi
  echo "model_disk_usage=$(du -sh "$MODEL_ROOT" | awk '{print $1}')"
  echo "backup_disk_usage=$(du -sh "$BACKUP_ROOT" | awk '{print $1}')"
  echo "model_files=$(find "$MODEL_ROOT" -type f | wc -l | tr -d ' ')"
  echo "backup_bundles=$(find "$BACKUP_ROOT" -mindepth 1 -maxdepth 1 -type d -name 'prem-engine-*' | wc -l | tr -d ' ')"
}

case "${1:-diagnostics}" in
  backup) backup ;;
  verify) shift; verify "${1:-}" ;;
  restore) shift; restore "${1:-}" "${2:-}" ;;
  diagnostics) diagnostics ;;
  *) echo "Usage: prem-engine-operations {backup|verify BUNDLE|restore BUNDLE CONFIRMATION|diagnostics}" >&2; exit 2 ;;
esac
