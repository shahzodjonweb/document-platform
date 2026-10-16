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



@pytest.fixture(autouse=True)
def no_photo_network(monkeypatch):
    """Nothing in the suite may reach Pixabay. Tests that exercise the fetcher replace this."""
    def refuse(*args, **kwargs):
        raise AssertionError('a test tried to reach the photo provider')
    monkeypatch.setattr('apps.studio.photos._open', refuse)
    # Nor the model that chooses between photos: that call is faked where it is tested.
    monkeypatch.setattr('apps.studio.photo_choice._post', refuse)
    # Nor Telegram, when checking whether a customer joined the owner's channels.
    monkeypatch.setattr('apps.core.channel_gate._call', refuse)


@pytest.fixture(autouse=True)
def object_storage_isolated():
    """Object storage settings are cached per process; never let one test's
    bucket (or a fake one) reach the next."""
    from apps.core import storage
    storage.forget_config()
    storage.client_factory = None
    storage._last_sweep['at'] = 0.0
    yield
    storage.forget_config()
    storage.client_factory = None


@pytest.fixture
def hold_back(monkeypatch):
    """Take a tool away from some plans in the catalog, for this test only.

    Every plan has every tool now, so a test of the refusal itself has to make a
    plan lack one first. The catalog is the one place that decides, so that is
    what changes; the entry is put back after the test.
    """
    from apps.core.policy import FEATURES

    def take(feature_id, *plans):
        for plan in plans:
            monkeypatch.setitem(FEATURES[feature_id]['plans'], plan, 'none')
    return take
