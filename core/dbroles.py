import os

import psycopg
from psycopg import sql


def _role_exists(connection, name):
    row = connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (name,)).fetchone()
    return row is not None


def _ensure_role(connection, name, password):
    if _role_exists(connection, name):
        connection.execute(
            sql.SQL("ALTER ROLE {} WITH LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
                sql.Identifier(name), sql.Literal(password)
            )
        )
        return
    connection.execute(
        sql.SQL("CREATE ROLE {} LOGIN PASSWORD {} NOSUPERUSER NOCREATEDB NOCREATEROLE").format(
            sql.Identifier(name), sql.Literal(password)
        )
    )


def provision(dsn, *, database, migrate_role, migrate_password, app_role, app_password):
    with psycopg.connect(dsn, autocommit=True) as connection:
        _ensure_role(connection, migrate_role, migrate_password)
        _ensure_role(connection, app_role, app_password)
        connection.execute(
            sql.SQL("GRANT CONNECT ON DATABASE {} TO {}, {}").format(
                sql.Identifier(database), sql.Identifier(migrate_role), sql.Identifier(app_role)
            )
        )
        connection.execute(sql.SQL("GRANT USAGE, CREATE ON SCHEMA public TO {}").format(sql.Identifier(migrate_role)))
        connection.execute(sql.SQL("GRANT USAGE ON SCHEMA public TO {}").format(sql.Identifier(app_role)))
        connection.execute(sql.SQL("REVOKE CREATE ON SCHEMA public FROM {}").format(sql.Identifier(app_role)))
        connection.execute(
            sql.SQL("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {}").format(sql.Identifier(app_role))
        )
        connection.execute(sql.SQL("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {}").format(sql.Identifier(app_role)))
        connection.execute(
            sql.SQL(
                "ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {}"
            ).format(sql.Identifier(migrate_role), sql.Identifier(app_role))
        )
        connection.execute(
            sql.SQL("ALTER DEFAULT PRIVILEGES FOR ROLE {} IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO {}").format(
                sql.Identifier(migrate_role), sql.Identifier(app_role)
            )
        )


def admin_dsn_from_env(database):
    password = os.getenv("POSTGRES_ADMIN_PASSWORD")
    path = os.getenv("POSTGRES_ADMIN_PASSWORD_FILE")
    if path:
        password = open(path, encoding="utf-8").read().strip()
    user = os.getenv("POSTGRES_ADMIN_USER", "event_tables")
    host = os.getenv("POSTGRES_HOST", "db")
    port = os.getenv("POSTGRES_PORT", "5432")
    if not password:
        return None
    return f"host={host} port={port} dbname={database} user={user} password={password}"
