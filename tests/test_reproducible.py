"""The generated files must be the same on every computer, not only in the nix shell:

- the DXF must not depend on Python's string hashing (ezdxf adds CLASS entries from a set; the nix shell pins
  PYTHONHASHSEED=0, CI and other machines do not);
- the plan file must not depend on the machine's fonts (ezdxf measures and draws text with whatever system font it finds).

Each test has a positive control showing it can fail."""
import os
import subprocess
import sys

import ezdxf
import pytest

from conftest import ROOT, SAMPLE_PATH
from vpt import plan

PLAN_PATH = ROOT / "samples" / "synthetic_flat.plan.json"


@pytest.mark.parametrize("seed", ["4", "7", "10"])          # seeds that gave another CLASS order before the fix
def test_dxf_is_the_same_for_any_hash_seed(tmp_path, seed):
    out = tmp_path / "flat.dxf"
    env = dict(os.environ, PYTHONHASHSEED=seed)
    subprocess.run([sys.executable, str(ROOT / "tools" / "synthetic_flat.py"), "--output", str(out)], check=True, env=env,
                   capture_output=True)
    assert out.read_bytes() == SAMPLE_PATH.read_bytes()


@pytest.fixture
def no_fonts(monkeypatch):
    """Any use of a font (measuring or drawing text) raises."""
    from ezdxf.fonts import fonts

    def refuse(*a, **k):
        raise RuntimeError("a font was used")
    monkeypatch.setattr(fonts, "make_font", refuse)
    return refuse


def test_font_guard_can_fail(no_fonts):
    """Positive control: measuring an MTEXT with ezdxf.bbox (what the page extent used before) touches a font."""
    from ezdxf import bbox
    doc = ezdxf.readfile(SAMPLE_PATH)
    mtext = doc.modelspace().query("MTEXT")[0]
    with pytest.raises(RuntimeError, match="font"):
        bbox.extents([mtext])


def test_plan_export_uses_no_font(no_fonts):
    assert plan.dumps(plan.export(SAMPLE_PATH, synthetic=True)) == PLAN_PATH.read_text(encoding="utf-8")
