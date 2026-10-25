import pytest

from blufire_cp.context import REPO_ROOT, Context
from blufire_cp.db import make_sessions
from blufire_cp.gitstore import MemoryStore


@pytest.fixture
def ctx():
    return Context(store=MemoryStore.from_dir(REPO_ROOT), sessions=make_sessions("sqlite://"), ttl_s=0)
