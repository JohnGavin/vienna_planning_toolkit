"""DWG -> DXF conversion and its completeness check (vpt/dwg_convert.py, tools/dwg_convert.py).

Three outcomes, each falsified: PASS on the synthetic flat, FAIL on a DXF that is cut off, INDETERMINATE when the converter
cannot run, exits non-zero, or logs a line about unsupported objects. Stand-in converters on PATH make the converter's behaviour
controllable; a real DWG (made from the synthetic DXF with the ODA File Converter) is converted end to end where a converter is
installed, else those tests are skipped (never counted as passed).
"""
import json
import os
import shutil
import stat
import subprocess

import pytest

import dwg_convert as tool
from conftest import PRESET_PATH, ROOT, SAMPLE_PATH
from vpt import dwg_convert as dc

PRESET = json.loads(dc.PRESET.read_text(encoding="utf-8"))
ODA = dc.find_oda(PRESET)
# the ODA File Converter is a GUI app: real launches are opt-in so an ordinary pytest run never touches the screen
ODA_OPT_IN = os.environ.get("VPT_TEST_ODA") == "1"


def path_preset(**kw) -> dict:
    return dict(PRESET, converter_route="path", **kw)


def make_dwg(path):
    """A file with a DWG header (the stand-in converters do not read it)."""
    path.write_bytes(b"AC1032" + b"\x00" * 64)
    return path


@pytest.fixture
def standin(tmp_path, monkeypatch):
    """A `dwg2dxf` on PATH that writes $VPT_FIXTURE to the -o file, prints $VPT_MSG on stderr and exits with $VPT_RC."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    exe = bindir / "dwg2dxf"
    exe.write_text('#!/bin/sh\nif [ "$1" = "--version" ]; then echo "standin 1.0"; exit 0; fi\n'
                   'out="$3"\n[ -n "$VPT_FIXTURE" ] && cp "$VPT_FIXTURE" "$out"\n'
                   '[ -n "$VPT_MSG" ] && echo "$VPT_MSG" >&2\nexit ${VPT_RC:-0}\n')
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setenv("PATH", f"{bindir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("VPT_FIXTURE", str(SAMPLE_PATH))
    monkeypatch.delenv("VPT_MSG", raising=False)
    monkeypatch.delenv("VPT_RC", raising=False)
    return monkeypatch


def convert(tmp_path, preset):
    return dc.run(make_dwg(tmp_path / "plan.dwg"), tmp_path / "out", preset)


# ---- a DXF is accepted as it is ------------------------------------------------------------------------------

def test_dxf_input_passes(tmp_path):
    rec = dc.run(SAMPLE_PATH, tmp_path)
    assert rec["status"] == dc.PASS and rec["failures"] == [] and rec["unknowns"] == []
    assert rec["converter"] is None and rec["version"] == "AC1032" and rec["dxf_markers"]["eof"] is True
    assert {"ENTITIES", "OBJECTS"} <= set(rec["dxf_markers"]["sections"])
    assert rec["entities_total"] > 0 and rec["model_entities"] > 0
    assert (tmp_path / "synthetic_flat.convert.json").is_file() and "/" not in rec["input"]


def test_a_cut_off_dxf_fails(tmp_path):
    """Falsified: the synthetic DXF cut before its ENTITIES section has no ENTITIES, no OBJECTS and no EOF: FAIL, with each reason."""
    text = SAMPLE_PATH.read_text(encoding="utf-8")
    cut = tmp_path / "cut.dxf"
    cut.write_text(text[:text.index("ENTITIES")].rsplit("0\nSECTION", 1)[0], encoding="utf-8")
    rec = dc.run(cut, tmp_path / "out")
    assert rec["status"] == dc.FAIL
    why = " ".join(rec["failures"])
    assert "no EOF marker" in why and "no ENTITIES section" in why and "no OBJECTS section" in why


def test_unreadable_dxf_is_could_not_tell_not_fail(tmp_path):
    junk = tmp_path / "junk.dxf"
    junk.write_text("this is not a drawing\n" * 40, encoding="utf-8")
    rec = dc.run(junk, tmp_path / "out")
    assert rec["status"] != dc.PASS
    assert any("could not be loaded" in u or "no entities" in u or "audit" in u for u in rec["unknowns"]), rec["unknowns"]


# ---- usage and exit codes ------------------------------------------------------------------------------------

def test_exit_codes(tmp_path, capsys):
    assert tool.main([str(SAMPLE_PATH), "--outdir", str(tmp_path / "a")]) == 0
    assert tool.main([str(tmp_path / "missing.dwg"), "--outdir", str(tmp_path / "b")]) == 2
    other = tmp_path / "x.txt"
    other.write_text("x")
    assert tool.main([str(other), "--outdir", str(tmp_path / "c")]) == 2
    notdwg = tmp_path / "x.dwg"
    notdwg.write_bytes(b"hello world")
    assert tool.main([str(notdwg), "--outdir", str(tmp_path / "d")]) == 2
    text = SAMPLE_PATH.read_text(encoding="utf-8")
    cut = tmp_path / "cut.dxf"
    cut.write_text(text[:text.index("ENTITIES")].rsplit("0\nSECTION", 1)[0], encoding="utf-8")
    assert tool.main([str(cut), "--outdir", str(tmp_path / "e")]) == 1


# ---- the converter: stand-ins on PATH ------------------------------------------------------------------------

def test_standin_converter_pass(tmp_path, standin):
    rec = convert(tmp_path, path_preset())
    assert rec["status"] == dc.PASS and rec["converter_exit"] == 0 and rec["converter_info"]["version"] == "standin 1.0"
    assert rec["version"] == "AC1032" and rec["release"] == "AutoCAD 2018"
    assert (tmp_path / "out" / "plan.dxf").is_file() and (tmp_path / "out" / "plan.convert.log").is_file()


def test_converter_exit_code_is_not_trusted_either_way(tmp_path, standin):
    standin.setenv("VPT_RC", "1")
    rec = convert(tmp_path, path_preset())
    assert rec["status"] == dc.UNK and any("exited 1" in u for u in rec["unknowns"])


def test_error_line_is_could_not_tell(tmp_path, standin):
    standin.setenv("VPT_MSG", "ERROR: Something is wrong with an object")
    rec = convert(tmp_path, path_preset())
    assert rec["status"] == dc.UNK and rec["unsupported_messages_total"] == 1 and rec["entities_total"] > 0


def test_allow_list_accepts_a_line_only_with_its_verification(tmp_path, standin):
    """The allow-listed ATTRIB line is accepted (the flat has no attribute blocks, so the verification says 'not verified' and
    nothing contradicts it); the same line with a failing verification makes the result could-not-tell again."""
    standin.setenv("VPT_MSG", "ERROR: Invalid ATTRIB.keep_duplicate_records at 12")
    rec = convert(tmp_path, path_preset())
    assert rec["status"] == dc.PASS and rec["unsupported_messages_total"] == 0
    assert rec["allowed_messages"][0]["count"] == 1 and rec["allowed_messages"][0]["verification"] == "not verified"
    assert dc.verify_allowed("attribs", {"inserts_of_attdef_blocks": 2, "inserts_with_fewer_attribs": 1, "attribs_read": 3,
                                         "attrib_markers_in_file": 4, "blocks_with_attdef": 1, "attdef_total": 2})[0] == "failed"
    assert dc.verify_allowed("attribs", {"inserts_of_attdef_blocks": 2, "inserts_with_fewer_attribs": 0, "attribs_read": 4,
                                         "attrib_markers_in_file": 4, "blocks_with_attdef": 1, "attdef_total": 2})[0] == "verified"


def test_standin_that_cuts_the_dxf_off_fails_whatever_its_exit_code(tmp_path, standin):
    text = SAMPLE_PATH.read_text(encoding="utf-8")
    cut = tmp_path / "cut.dxf"
    cut.write_text(text[:text.index("ENTITIES")].rsplit("0\nSECTION", 1)[0], encoding="utf-8")
    standin.setenv("VPT_FIXTURE", str(cut))
    rec = convert(tmp_path, path_preset())
    assert rec["converter_exit"] == 0 and rec["status"] == dc.FAIL


def test_no_dxf_written_and_no_converter_are_could_not_tell(tmp_path, standin):
    standin.setenv("VPT_FIXTURE", "")
    rec = convert(tmp_path, path_preset())
    assert rec["status"] == dc.UNK and any("no DXF was written" in u for u in rec["unknowns"])
    standin.setenv("PATH", "/nonexistent")
    rec = dc.run(make_dwg(tmp_path / "again.dwg"), tmp_path / "out2", path_preset())
    assert rec["status"] == dc.UNK and any("not found on PATH" in u for u in rec["unknowns"]) and rec["dxf"] is None


def test_unknown_dwg_version_and_bad_route(tmp_path, standin):
    odd = tmp_path / "odd.dwg"
    odd.write_bytes(b"AC9999" + b"\x00" * 16)
    rec = dc.run(odd, tmp_path / "out", path_preset())
    assert rec["status"] == dc.UNK and any("unknown DWG version AC9999" in u for u in rec["unknowns"])
    with pytest.raises(dc.UsageError):
        dc.run(make_dwg(tmp_path / "p.dwg"), tmp_path / "o", dict(PRESET, converter_route="telepathy"))


# ---- real converters, where installed ------------------------------------------------------------------------

@pytest.fixture(scope="module")
def real_dwg(tmp_path_factory):
    """A real DWG made from the synthetic DXF by the ODA File Converter (DXF -> DWG)."""
    if not ODA_OPT_IN:
        pytest.skip("real ODA launches are opt-in: set VPT_TEST_ODA=1")
    if ODA is None:
        pytest.skip("ODA File Converter not installed")
    d = tmp_path_factory.mktemp("oda")
    (d / "in").mkdir()
    (d / "out").mkdir()
    shutil.copy2(SAMPLE_PATH, d / "in" / "synthetic_flat.dxf")
    p, _ = dc.run_oda(ODA, [str(d / "in"), str(d / "out"), "ACAD2018", "DWG", "0", "1", "synthetic_flat.dxf"], PRESET, 120)
    made = d / "out" / "synthetic_flat.dwg"
    if not made.is_file():
        pytest.skip(f"ODA File Converter could not make a DWG (exit {p.returncode})")
    return made


def test_oda_route_converts_a_real_dwg_completely(real_dwg, tmp_path):
    rec = dc.run(real_dwg, tmp_path, dict(PRESET, converter_route="oda"))
    assert rec["status"] == dc.PASS, rec["unknowns"] + rec["failures"]
    assert rec["converter_info"]["route"] == "oda" and rec["version"] == "AC1032"
    src = dc.run(SAMPLE_PATH, tmp_path / "src")
    assert rec["entities_total"] == src["entities_total"] and set(src["layers"]) <= set(rec["layers"])   # ODA adds its VIEWPORTS layer


def test_auto_route_prefers_oda_when_installed(real_dwg, tmp_path):
    assert dc.choose_route(PRESET)[0] == "oda"
    assert dc.choose_route(dict(PRESET, oda_candidates=["/nonexistent/ODAFileConverter"], converter_route="auto"))[0] in ("oda", "nix")


@pytest.mark.skipif(shutil.which("nix-shell") is None, reason="nix-shell not installed")
def test_libredwg_route_converts_the_same_drawing_and_reports_what_it_logged(real_dwg, tmp_path):
    rec = dc.run(real_dwg, tmp_path, dict(PRESET, converter_route="nix"))
    if rec["converter_info"]["version"] is None:
        pytest.skip("LibreDWG could not be built or run here (no version line)")
    src = dc.run(SAMPLE_PATH, tmp_path / "src")
    assert rec["entities_total"] == src["entities_total"]
    # LibreDWG 0.14 logs "Unhandled Object ..." for table styles it does not write: that is could-not-tell, never a quiet pass
    assert all("nhandled" in m for m in rec["unsupported_messages"])
    assert rec["status"] == (dc.UNK if rec["unsupported_messages"] else dc.PASS)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason="LibreDWG 0.14 dxf2dwg cannot read the synthetic DXF: 'Invalid DXF code 50 for MTEXT'. "
                                       "strict: when upstream fixes it this test must be turned into a real round-trip test")
@pytest.mark.skipif(shutil.which("nix-shell") is None, reason="nix-shell not installed")
def test_dxf_to_dwg_round_trip_with_libredwg(tmp_path):
    argv, info = dc.tool_argv("dxf2dwg", ["-y", "-o", str(tmp_path / "flat.dwg"), str(SAMPLE_PATH)], PRESET, "nix")
    if argv is None:
        pytest.skip(info.get("problem"))
    p = subprocess.run(argv, capture_output=True, text=True, timeout=250)
    assert "Invalid DXF code 50 for MTEXT" not in p.stderr + p.stdout
    assert p.returncode == 0 and (tmp_path / "flat.dwg").is_file()
    assert dc.header_version(tmp_path / "flat.dwg").startswith("AC")


def test_oda_launch_modes_build_the_right_command_and_env():
    exe = "/Applications/ODAFileConverter.app/Contents/MacOS/ODAFileConverter"
    args = ["/in", "/out", "ACAD2018", "DXF", "0", "1", "a.dwg"]
    argv, env, observable = dc.oda_command(exe, args, dict(PRESET, oda_launch="direct"))
    assert argv == [exe, *args] and env is None and observable
    argv, env, observable = dc.oda_command(exe, args, dict(PRESET, oda_launch="offscreen"))
    assert argv == [exe, *args] and env["QT_QPA_PLATFORM"] == "offscreen" and observable
    argv, env, observable = dc.oda_command(exe, args, dict(PRESET, oda_launch="background"))
    if shutil.which("open"):
        assert argv == ["open", "-W", "-g", "-j", "-n", "-a", "/Applications/ODAFileConverter.app", "--args", *args]
        assert env is None and not observable
    with pytest.raises(dc.UsageError):
        dc.oda_command(exe, args, dict(PRESET, oda_launch="visible"))


def test_every_oda_launch_goes_through_the_helper():
    for f in [*(ROOT / "vpt").glob("*.py"), *(ROOT / "tools").glob("*.py"), *(ROOT / "tests").glob("*.py")]:
        text = f.read_text(encoding="utf-8")
        if f.name != "test_dwg_convert.py" and not (f.name == "dwg_convert.py" and f.parent.name == "vpt"):
            assert "ODAFileConverter" not in text or "subprocess" not in text, f.name
