from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection, Dialect
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from sqlalchemy.pool import ConnectionPoolEntry

from job_apply_pro.config import get_settings
from job_apply_pro.restore_admission import assert_runtime_admission


class Base(DeclarativeBase):
    pass


settings = get_settings()
assert_runtime_admission(settings)
engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False} if settings.database_url.startswith("sqlite") else {},
)
SessionFactory = sessionmaker(bind=engine, expire_on_commit=False)


@event.listens_for(engine, "do_connect")
def _before_connect(
    _dialect: Dialect,
    _connection: ConnectionPoolEntry,
    _args: list[object],
    _kwargs: dict[str, object],
) -> DBAPIConnection | None:
    assert_runtime_admission(settings)
    settings.ensure_runtime_directories()
    return None


def get_session() -> Generator[Session]:
    with SessionFactory() as session:
        yield session
