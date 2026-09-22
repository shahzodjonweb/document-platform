import pytest
from django.core.cache import cache
@pytest.fixture(autouse=True)
def commerce_defaults(settings,tmp_path):
    settings.DEBUG=True
    settings.COMMERCE_SANDBOX_ENABLED=True
    settings.COMMERCE_LIVE_ENABLED=False
    settings.COMMERCE_LIVE_OFFERS={}
    settings.ENABLE_BETA_TOOLS=True
    settings.LOCAL_SYNC_JOBS=True
    settings.PRIVATE_STORAGE_ROOT=tmp_path/'private'
    cache.clear()
