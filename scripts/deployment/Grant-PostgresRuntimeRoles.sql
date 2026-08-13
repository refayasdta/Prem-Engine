\set QUIET 1
\set ON_ERROR_STOP on

BEGIN;

SELECT set_config('prem_engine.api_role', :'api_role', false);
SELECT set_config('prem_engine.worker_role', :'worker_role', false);
SELECT set_config('prem_engine.backup_role', :'backup_role', false);

DO $bootstrap$
DECLARE
    supplied_role text;
    supplied_oid oid;
    allowed_group text;
    unexpected_memberships text[];
BEGIN
    IF current_setting('prem_engine.api_role') IN (
        current_setting('prem_engine.worker_role'),
        current_setting('prem_engine.backup_role')
    ) OR current_setting('prem_engine.worker_role') = current_setting('prem_engine.backup_role') THEN
        RAISE EXCEPTION 'API, worker, and backup role names must be distinct';
    END IF;
    IF NOT has_schema_privilege(current_user, 'public', 'CREATE') THEN
        RAISE EXCEPTION 'migration role % cannot create objects in schema public', current_user;
    END IF;

    FOREACH supplied_role IN ARRAY ARRAY[
        current_setting('prem_engine.api_role'),
        current_setting('prem_engine.worker_role'),
        current_setting('prem_engine.backup_role')
    ]
    LOOP
        SELECT oid
        INTO supplied_oid
        FROM pg_roles
        WHERE rolname = supplied_role;

        IF supplied_oid IS NULL THEN
            RAISE EXCEPTION 'required login role % does not exist', supplied_role;
        END IF;
        IF supplied_role = current_user THEN
            RAISE EXCEPTION 'runtime role % must not be the migration role', supplied_role;
        END IF;
        IF EXISTS (
            SELECT 1
            FROM pg_roles
            WHERE oid = supplied_oid
              AND (
                  NOT rolcanlogin
                  OR rolsuper
                  OR rolcreaterole
                  OR rolcreatedb
                  OR rolreplication
                  OR rolbypassrls
                  OR NOT rolinherit
              )
        ) THEN
            RAISE EXCEPTION 'runtime role % is not an unprivileged login role', supplied_role;
        END IF;
        IF EXISTS (SELECT 1 FROM pg_database WHERE datdba = supplied_oid) OR
           EXISTS (SELECT 1 FROM pg_namespace WHERE nspowner = supplied_oid) OR
           EXISTS (SELECT 1 FROM pg_class WHERE relowner = supplied_oid) THEN
            RAISE EXCEPTION 'runtime role % owns database objects and cannot be safely restricted', supplied_role;
        END IF;

        allowed_group := CASE supplied_role
            WHEN current_setting('prem_engine.api_role') THEN 'prem_engine_api_access'
            WHEN current_setting('prem_engine.worker_role') THEN 'prem_engine_worker_access'
            ELSE 'prem_engine_backup_access'
        END;
        SELECT array_agg(parent.rolname ORDER BY parent.rolname)
        INTO unexpected_memberships
        FROM pg_roles AS parent
        WHERE parent.rolname <> supplied_role
          AND parent.rolname <> allowed_group
          AND pg_has_role(supplied_role, parent.oid, 'MEMBER');
        IF unexpected_memberships IS NOT NULL THEN
            RAISE EXCEPTION 'runtime role % has unexpected memberships: %',
                supplied_role,
                unexpected_memberships;
        END IF;
    END LOOP;

    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'prem_engine_api_access') THEN
        CREATE ROLE prem_engine_api_access NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'prem_engine_worker_access') THEN
        CREATE ROLE prem_engine_worker_access NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'prem_engine_backup_access') THEN
        CREATE ROLE prem_engine_backup_access NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
            NOINHERIT NOREPLICATION NOBYPASSRLS;
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_roles
        WHERE rolname IN (
            'prem_engine_api_access',
            'prem_engine_worker_access',
            'prem_engine_backup_access'
        )
          AND (
              rolcanlogin
              OR rolsuper
              OR rolcreaterole
              OR rolcreatedb
              OR rolreplication
              OR rolbypassrls
          )
    ) THEN
        RAISE EXCEPTION 'a fixed Prem Engine access group has unsafe role attributes';
    END IF;
    IF EXISTS (
        SELECT 1
        FROM pg_roles AS access_group
        JOIN pg_roles AS parent ON parent.rolname <> access_group.rolname
        WHERE access_group.rolname IN (
            'prem_engine_api_access',
            'prem_engine_worker_access',
            'prem_engine_backup_access'
        )
          AND pg_has_role(access_group.oid, parent.oid, 'MEMBER')
    ) THEN
        RAISE EXCEPTION 'a fixed Prem Engine access group inherits an unexpected role';
    END IF;
END
$bootstrap$;

SELECT current_database() AS target_database \gset

REVOKE CREATE ON SCHEMA public FROM PUBLIC;
REVOKE ALL PRIVILEGES ON DATABASE :"target_database"
    FROM prem_engine_api_access, prem_engine_worker_access, prem_engine_backup_access,
         :"api_role", :"worker_role", :"backup_role";
REVOKE ALL PRIVILEGES ON SCHEMA public
    FROM prem_engine_api_access, prem_engine_worker_access, prem_engine_backup_access,
         :"api_role", :"worker_role", :"backup_role";
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public
    FROM prem_engine_api_access, prem_engine_worker_access, prem_engine_backup_access,
         :"api_role", :"worker_role", :"backup_role";
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public
    FROM prem_engine_api_access, prem_engine_worker_access, prem_engine_backup_access,
         :"api_role", :"worker_role", :"backup_role";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL PRIVILEGES ON TABLES
    FROM prem_engine_api_access, prem_engine_worker_access, prem_engine_backup_access,
         :"api_role", :"worker_role", :"backup_role";
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    REVOKE ALL PRIVILEGES ON SEQUENCES
    FROM prem_engine_api_access, prem_engine_worker_access, prem_engine_backup_access,
         :"api_role", :"worker_role", :"backup_role";

GRANT CONNECT ON DATABASE :"target_database" TO prem_engine_api_access;
GRANT USAGE ON SCHEMA public TO prem_engine_api_access;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO prem_engine_api_access;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO prem_engine_api_access;

GRANT CONNECT ON DATABASE :"target_database" TO prem_engine_worker_access;
GRANT USAGE ON SCHEMA public TO prem_engine_worker_access;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
    TO prem_engine_worker_access;
GRANT USAGE, SELECT, UPDATE ON ALL SEQUENCES IN SCHEMA public
    TO prem_engine_worker_access;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO prem_engine_worker_access;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT USAGE, SELECT, UPDATE ON SEQUENCES TO prem_engine_worker_access;

GRANT CONNECT ON DATABASE :"target_database" TO prem_engine_backup_access;
GRANT USAGE ON SCHEMA public TO prem_engine_backup_access;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO prem_engine_backup_access;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO prem_engine_backup_access;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON TABLES TO prem_engine_backup_access;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT SELECT ON SEQUENCES TO prem_engine_backup_access;

GRANT prem_engine_api_access TO :"api_role";
GRANT prem_engine_worker_access TO :"worker_role";
GRANT prem_engine_backup_access TO :"backup_role";

COMMIT;

\set QUIET 0
SELECT current_database() AS database,
       current_user AS grantor,
       :'api_role' AS api_role,
       :'worker_role' AS worker_role,
       :'backup_role' AS backup_role;
