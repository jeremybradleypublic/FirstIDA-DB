import os
import shutil
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


def _ensure_colima(journal=None):
    st = _run(["colima", "status"])
    if st.returncode != 0:
        if journal is not None:
            journal.event("starting colima VM")
            journal.run(["colima", "start"])
        else:
            _run(["colima", "start"])


def ensure_image(image: str = IMAGE, journal=None) -> None:
    _ensure_colima(journal=journal)
    if _run(["docker", "image", "inspect", image]).returncode == 0:
        return
    build_argv = ["docker", "build", "--platform", "linux/amd64",
                  "-t", image, _DOCKERFILE_DIR]
    if journal is not None:
        journal.event(f"building toolchain image {image} (first run: apt-installs gcc/g++/clang)")
        rc, out = journal.run(build_argv)
        if rc != 0:
            raise RuntimeError(f"toolchain image build failed:\n{out[-2000:]}")
        journal.event(f"toolchain image {image} built")
        return
    build = _run(build_argv)
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
        shutil.rmtree(self.scratch, ignore_errors=True)


def start_toolchain(repo_dir: str, image: str = IMAGE, journal=None) -> Toolchain:
    ensure_image(image, journal=journal)
    scratch = tempfile.mkdtemp(prefix="disasm_out_")
    name = "disasm_tc_" + uuid.uuid4().hex[:12]
    run = _run(["docker", "run", "-d", "--platform", "linux/amd64", "--name", name,
                "-v", f"{os.path.abspath(repo_dir)}:/src:ro",
                "-v", f"{scratch}:/out",
                image])
    if run.returncode != 0:
        raise RuntimeError(f"container start failed:\n{run.stderr}")
    return Toolchain(container=name, scratch=scratch)
