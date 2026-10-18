from alembic import context
from app import models  # noqa: F401
from app.db import Base, engine


def include_object(obj, name, type_, reflected, compare_to):
    # LangGraph owns these tables and migrations independently in the same PostgreSQL database.
    return not (
        reflected
        and type_ == "table"
        and name in {"checkpoint_migrations", "checkpoints", "checkpoint_blobs", "checkpoint_writes"}
    )


if context.is_offline_mode():
    context.configure(url=str(engine.url), target_metadata=Base.metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=Base.metadata,
            compare_type=True,
            include_object=include_object,
        )
        with context.begin_transaction():
            context.run_migrations()
