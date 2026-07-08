import os
import subprocess
import tempfile
import uuid
from dataclasses import dataclass

IMAGE = "disasm-toolchain:latest"
_DOCKERFILE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "docker")


def _run(argv, **kw):
    return subprocess.run(argv, capture_output=True, text=True, **kw)


def docker_available() -> bool:
    try:
        return _run(["docker", "info"]).returncode == 0
    except FileNotFoundError:
        return False


def _ensure_colima():
    st = _run(["colima", "status"])
    if st.returncode != 0:
        _run(["colima", "start"])


def ensure_image(image: str = IMAGE) -> None:
    _ensure_colima()
    if _run(["docker", "image", "inspect", image]).returncode == 0:
        return
    build = _run(["docker", "build", "--platform", "linux/amd64",
                  "-t", image, _DOCKERFILE_DIR])
    if build.returncode != 0:
        raise RuntimeError(f"toolchain image build failed:\n{build.stderr}")


@dataclass
class Toolchain:
    container: str
    scratch: str

    def exec(self, argv, input=None):
        return _run(["docker", "exec", "-i", self.container] + list(argv), input=input)

    def stop(self):
        _run(["docker", "rm", "-f", self.container])


def start_toolchain(repo_dir: str, image: str = IMAGE) -> Toolchain:
    ensure_image(image)
    scratch = tempfile.mkdtemp(prefix="disasm_out_")
    name = "disasm_tc_" + uuid.uuid4().hex[:12]
    run = _run(["docker", "run", "-d", "--platform", "linux/amd64", "--name", name,
                "-v", f"{os.path.abspath(repo_dir)}:/src:ro",
                "-v", f"{scratch}:/out",
                image])
    if run.returncode != 0:
        raise RuntimeError(f"container start failed:\n{run.stderr}")
    return Toolchain(container=name, scratch=scratch)
