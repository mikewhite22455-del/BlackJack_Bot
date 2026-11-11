from pathlib import Path
import shutil
import subprocess

import pytest


@pytest.mark.skipif(not shutil.which("node"), reason="Node is needed only for browser-client unit tests")
def test_capture_client_lifecycle():
    script = Path(__file__).parent / "tests" / "capture-client.test.cjs"
    result = subprocess.run([shutil.which("node"), "--test", str(script)],
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr
