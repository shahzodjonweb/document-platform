import os
os.environ.setdefault('DEBUG','1')
os.environ.setdefault('ENABLE_BETA_TOOLS','1')
os.environ.setdefault('DEVELOPMENT_LOGIN_ENABLED','1')
import pytest
from django.core.cache import cache
@pytest.fixture(autouse=True)
def private_storage(settings,tmp_path):
    settings.PRIVATE_STORAGE_ROOT=tmp_path/'private'
    settings.ENABLE_BETA_TOOLS=True
    settings.LOCAL_SYNC_JOBS=True
    cache.clear()


@pytest.fixture
def bot_verification_disabled(monkeypatch):
    """Legacy domain/transport tests start after the independently tested gate."""
    monkeypatch.setattr('telegram.verification.enabled', lambda: False)
