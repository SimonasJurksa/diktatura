"""A, K1. Privatumo sargas: .gitignore, git hooks, darbinio medžio auditas (tests/privacy_guard_test.sh)."""
import subprocess

from testenv import REPO


def test_privacy_guard_suite():
    r = subprocess.run(["bash", str(REPO / "tests" / "privacy_guard_test.sh")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-3000:] + r.stderr[-2000:]
    assert "0 ✗" in r.stdout
