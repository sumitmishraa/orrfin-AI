"""One-shot startup step: create database roles idempotently, then run Alembic as the owner."""
import os
import time

import boto3
import psycopg
from alembic import command
from alembic.config import Config
from botocore.exceptions import ClientError, EndpointConnectionError
from psycopg import sql


def ensure_roles() -> None:
    passwords = {
        "orrfin_owner": os.environ["ORRFIN_OWNER_DB_PASSWORD"],
        "orrfin_app": os.environ["ORRFIN_APP_DB_PASSWORD"],
    }
    with psycopg.connect(os.environ["ADMIN_DATABASE_URL"], autocommit=True) as connection:
        for role, password in passwords.items():
            exists = connection.execute("SELECT 1 FROM pg_roles WHERE rolname = %s", (role,)).fetchone()
            verb = "ALTER" if exists else "CREATE"
            connection.execute(
                sql.SQL("{} ROLE {} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEROLE NOCREATEDB PASSWORD {}").format(
                    sql.SQL(verb), sql.Identifier(role), sql.Literal(password)
                )
            )
        connection.execute("ALTER DATABASE orrfin OWNER TO orrfin_owner")
        connection.execute("ALTER SCHEMA public OWNER TO orrfin_owner")
        connection.execute("GRANT USAGE ON SCHEMA public TO orrfin_app")
        connection.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")


def ensure_bucket() -> None:
    client = boto3.client(
        "s3",
        endpoint_url=os.environ["S3_ENDPOINT_URL"],
        aws_access_key_id=os.environ["S3_ACCESS_KEY"],
        aws_secret_access_key=os.environ["S3_SECRET_KEY"],
        region_name="us-east-1",
    )
    bucket = os.environ.get("S3_BUCKET", "orrfin-documents")
    for attempt in range(30):
        try:
            client.head_bucket(Bucket=bucket)
            return
        except ClientError as error:
            status = error.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status == 404:
                try:
                    client.create_bucket(Bucket=bucket)
                    return
                except ClientError:
                    pass
            elif status in (401, 403):
                raise
        except EndpointConnectionError:
            pass
        time.sleep(1 + attempt * 0.2)
    raise RuntimeError("Object store did not become ready.")


def main() -> None:
    ensure_roles()
    config = Config("alembic.ini")
    command.upgrade(config, "head")
    ensure_bucket()
    print("Migrations applied; object store ready.")


if __name__ == "__main__":
    main()
