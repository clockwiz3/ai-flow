"""Real-container checks of the isolation guarantees. Skipped when no Docker daemon is running."""

import asyncio
import os
from pathlib import Path

import pytest

from forgeloop.tools.sandbox import DockerSandbox, docker_ready, ensure_image

pytestmark = pytest.mark.docker

if not asyncio.run(docker_ready()):
    pytest.skip("Docker daemon is not running", allow_module_level=True)


@pytest.fixture(scope="module", autouse=True)
def image() -> None:
    asyncio.run(ensure_image())


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    (ws / ".git").mkdir(parents=True)
    (ws / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (ws / "probe.py").write_text(
        "import os, socket, sys\n"
        "print('KEY' if any('API_KEY' in k for k in os.environ) else 'NOKEY')\n"
        "try:\n"
        "    socket.create_connection(('1.1.1.1', 53), timeout=3)\n"
        "    print('NET')\n"
        "except OSError:\n"
        "    print('NONET')\n"
        "try:\n"
        "    open('.git/HEAD', 'a').write('x')\n"
        "    print('GITRW')\n"
        "except OSError:\n"
        "    print('GITRO')\n",
        encoding="utf-8",
    )
    return ws


def test_container_has_no_network_no_secrets_and_readonly_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-must-not-leak")
    ws = _workspace(tmp_path)

    async def scenario() -> str:
        box = await DockerSandbox.start(ws)
        try:
            return (await box.exec(["python", "probe.py"], 30)).output
        finally:
            await box.close()

    out = asyncio.run(scenario()).split()
    assert out == ["NOKEY", "NONET", "GITRO"]
    assert (ws / ".git" / "HEAD").read_text(encoding="utf-8") == "ref: refs/heads/main\n"
    assert os.environ["OPENROUTER_API_KEY"] == "sk-must-not-leak"  # the host still has it, the container did not


def test_commands_are_killed_at_the_timeout(tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    (ws / "spin.py").write_text("while True:\n    pass\n", encoding="utf-8")

    async def scenario() -> bool:
        box = await DockerSandbox.start(ws)
        try:
            return (await box.exec(["python", "spin.py"], 2)).timed_out
        finally:
            await box.close()

    assert asyncio.run(scenario())
