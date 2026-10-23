import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def alembic(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, "-m", "alembic", *args], cwd=ROOT, env=os.environ.copy(),
                          capture_output=True, text=True)


def test_models_and_migrations_are_in_sync():
    """Fails if someone changes a model without generating a migration."""
    r = alembic("check")
    assert r.returncode == 0, r.stdout + r.stderr


def test_single_head_and_full_downgrade_upgrade_cycle():
    heads = alembic("heads")
    assert heads.returncode == 0 and heads.stdout.count("(head)") == 1
    assert alembic("downgrade", "base").returncode == 0
    up = alembic("upgrade", "head")
    assert up.returncode == 0, up.stderr
    assert alembic("current").returncode == 0
