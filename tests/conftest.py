import os
import pytest
import pipeline.env as env

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


@pytest.fixture(scope="session")
def toolchain():
    if not env.docker_available():
        pytest.skip("Docker/Colima not available")
    env.ensure_image()
    tc = env.start_toolchain(os.path.join(FIX, "minirepo"))
    yield tc
    tc.stop()
