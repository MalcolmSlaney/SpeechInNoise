import sys
from absl import flags
import pytest

def pytest_configure(config):
    """Ensure absl flags are parsed before any tests run."""
    FLAGS = flags.FLAGS
    # Pass only the script name to avoid crashing on pytest's own CLI args
    FLAGS(sys.argv[:1])
