"""Stamp only test-owned freshly created ORM databases with their actual schema."""

from sqlalchemy import Engine

from job_apply_pro.services.backup import BackupService


def stamp_current_schema(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "CREATE TABLE IF NOT EXISTS alembic_version "
            "(version_num VARCHAR(32) NOT NULL PRIMARY KEY)"
        )
        revisions = connection.exec_driver_sql("SELECT version_num FROM alembic_version").all()
        if not revisions:
            connection.exec_driver_sql(
                "INSERT INTO alembic_version VALUES (?)", (BackupService.SCHEMA_REVISION,)
            )
        else:
            assert [row[0] for row in revisions] == [BackupService.SCHEMA_REVISION]
