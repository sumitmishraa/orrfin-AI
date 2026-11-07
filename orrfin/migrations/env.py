import os

from alembic import context
from sqlalchemy import create_engine, pool

from orrfin.models import Base

target_metadata = Base.metadata


def run_migrations_online() -> None:
    engine = create_engine(os.environ["OWNER_DATABASE_URL"], poolclass=pool.NullPool)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    raise RuntimeError("Offline migrations are not supported.")
run_migrations_online()
