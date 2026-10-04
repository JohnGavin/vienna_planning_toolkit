import sys
from pathlib import Path

import ezdxf
import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))

import synthetic_flat  # noqa: E402

PRESET_PATH = ROOT / "presets" / "synthetic_flat.json"
SAMPLE_PATH = ROOT / "samples" / "synthetic_flat.dxf"


@pytest.fixture(scope="session")
def preset():
    return synthetic_flat.load_preset(PRESET_PATH)


@pytest.fixture(scope="session")
def generated(tmp_path_factory):
    """A freshly generated DXF (independent of the committed sample)."""
    out = tmp_path_factory.mktemp("gen") / "flat.dxf"
    summary = synthetic_flat.generate(PRESET_PATH, out)
    return out, summary


@pytest.fixture
def doc(generated):
    """A fresh, mutable document per test (falsification tests edit it)."""
    return ezdxf.readfile(generated[0])
