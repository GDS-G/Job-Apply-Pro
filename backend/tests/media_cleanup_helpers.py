from typing import cast

from sqlalchemy import Table, create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from job_apply_pro.security.encryption import SensitiveDataCipher
from job_apply_pro.security.keys import StaticKeyProvider
from job_apply_pro.services.media_cleanup import DurableMediaJournal
from job_apply_pro.storage.media_cleanup_repository import MediaCleanupRepository
from job_apply_pro.storage.models import MediaCleanupRow


def new_test_journal() -> DurableMediaJournal:
    """Real transactional journal for isolated provider transport fixtures."""
    engine = create_engine("sqlite://", poolclass=StaticPool)
    cast(Table, MediaCleanupRow.__table__).create(engine)
    repository = MediaCleanupRepository(
        sessionmaker(bind=engine), SensitiveDataCipher(StaticKeyProvider(b"j" * 32))
    )
    return DurableMediaJournal(repository, "gemini", "a" * 64)
