"""DWG -> DXF with a completeness check of the result (tools/dwg_convert.py; every setting in presets/dwg_convert.json).

A .dwg is converted into an output folder; a .dxf is accepted as it is (no conversion; recorded). The original is only read.
The result record (<stem>.convert.json) holds: the DWG header version and release name, the converter route / version / exit code /
message counts, the converter lines that point to errors or unsupported objects, the allow-listed lines (each with its reason and,
where the preset names one, the result of its verification on THIS file), the DXF's section markers and raw entity-marker
counts, entity counts per layout, layers, blocks, the ezdxf audit and the attribute evidence.

Converter routes (preset `converter_route`)
    oda    the ODA File Converter (a program you install yourself; it converts whole folders, so the file is staged)
    nix    LibreDWG's dwg2dxf from nix/libredwg.nix (LibreDWG 0.14; the 0.13.x of nixpkgs can cut a DXF off after the BLOCKS section)
    path   a converter named by the preset found on PATH (tests use stand-in converters this way)
    auto   oda when it is installed, else nix: the route used is recorded; a route that cannot run is could-not-tell, never
           a silent switch to another one after it has failed

Three outcomes (a conversion that looks fine is not a pass unless the written file is complete)
    FAIL            the DXF as written is cut off: no EOF marker, a required section missing (R12 / AC1009 has no OBJECTS section
                    by design), or model space empty while block definitions hold entities
    INDETERMINATE   anything that leaves the result unconfirmed: the converter cannot run / times out / exits non-zero / reports
                    lines about errors or unsupported objects that no allow-list entry accepts (or whose verification fails on
                    this file), ezdxf cannot load the DXF or its audit leaves unfixed errors, proxy objects, no entities at all,
                    an unknown DWG version
    PASS            none of the above
Exit codes of the tool: 0 PASS, 1 FAIL, 2 usage (input missing / not a DWG or DXF), 3 INDETERMINATE. An unexpected error writes
the record with status INDETERMINATE and the error text and exits 3.
"""
from __future__ import annotations

import datetime as dt
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import tempfile
import traceback
from collections import Counter

from ezdxf import recover

from vpt import DATA, PRESETS, ROOT

PRESET = PRESETS / "dwg_convert.json"
PASS, FAIL, UNK = "PASS", "FAIL", "INDETERMINATE"


class UsageError(Exception):
    pass


# ---- crash handling ----------------------------------------------------------------------------------------

def crash_record(exc: BaseException) -> dict:
    tb = traceback.format_exception(type(exc), exc, exc.__traceback__)
    return {"type": type(exc).__name__, "message": str(exc), "traceback": "".join(tb).splitlines()[-12:]}


def write_crash_result(path: pathlib.Path, base: dict, exc: BaseException) -> dict:
    """A step that crashed leaves a record: INDETERMINATE (could not tell), never FAIL, never no record."""
    res = dict(base)
    res.update(status=UNK, crash=crash_record(exc), unknowns=[f"step crashed: {type(exc).__name__}: {exc}"], failures=[])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return res


# ---- the converter -----------------------------------------------------------------------------------------

def _abs(p: str) -> pathlib.Path:
    q = pathlib.Path(p).expanduser()
    return q if q.is_absolute() else DATA / q


def find_oda(preset: dict) -> str | None:
    for cand in [shutil.which("ODAFileConverter"), *[str(_abs(c)) for c in preset.get("oda_candidates", [])]]:
        if cand and pathlib.Path(cand).is_file():
            return cand
    return None


def oda_command(exe: str, args: list[str], preset: dict) -> tuple[list[str], dict | None, bool]:
    """(argv, env, exit code observable) for one ODA File Converter launch: the ONE place ODA is started (tool and tests).
    The preset's `oda_launch` decides whether its Qt window can appear on the screen:
        offscreen   QT_QPA_PLATFORM=offscreen: no window (needs the offscreen Qt plugin in the app bundle; the macOS app has none)
        background  macOS `open -W -g -j -n`: launched hidden, not brought to front, waited for. `open` gives no exit code of the
                    converter: success is judged from the output files by the callers (None exit code = not observable)
        direct      the plain binary (the window may appear)"""
    mode = preset.get("oda_launch", "background")
    if mode not in ("offscreen", "background", "direct"):
        raise UsageError(f"oda_launch must be offscreen, background or direct, not {mode!r}")
    if mode == "offscreen":
        return [exe, *args], {**os.environ, "QT_QPA_PLATFORM": "offscreen"}, True
    if mode == "background":
        app = pathlib.Path(exe)
        bundle = next((str(a) for a in app.parents if a.suffix == ".app"), None)
        if bundle and shutil.which("open"):
            return ["open", "-W", "-g", "-j", "-n", "-a", bundle, "--args", *args], None, False
        mode = "direct"    # no app bundle / no `open` (Linux): the plain binary
    return [exe, *args], None, True


def run_oda(exe: str, args: list[str], preset: dict, timeout: float) -> tuple[subprocess.CompletedProcess, bool]:
    """Run one ODA launch through oda_command. (process, exit code observable); subprocess.TimeoutExpired propagates."""
    argv, env, observable = oda_command(exe, args, preset)
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env), observable


def choose_route(preset: dict) -> tuple[str, str | None]:
    """(route, problem): the route to use for this run. `auto` is oda when installed, else nix."""
    route = preset.get("converter_route", "auto")
    if route not in ("auto", "oda", "nix", "path"):
        raise UsageError(f"converter_route must be auto, oda, nix or path, not {route!r}")
    if route == "auto":
        route = "oda" if find_oda(preset) else "nix"
    return route, None


def tool_argv(tool: str, args: list[str], preset: dict, route: str | None = None) -> tuple[list[str] | None, dict]:
    """(argv, route info) to run a LibreDWG-style `tool args` by the nix or path route; argv None (and info["problem"]) when it
    cannot run."""
    route = route or choose_route(preset)[0]
    if route == "path":
        exe = shutil.which(tool)
        info = {"route": "path", "description": exe or f"{tool} (not on PATH)", "nix_file": None, "nix_rev": None}
        if exe is None:
            info["problem"] = f"{tool} not found on PATH (converter_route is 'path')"
            return None, info
        return [exe, *args], info
    nix = preset.get("converter_nix_shell")
    rev = preset.get("converter_nix_rev")
    info = {"route": "nix", "nix_file": nix, "nix_rev": rev}
    nix_file = _abs(nix) if nix else None
    nix_shell = shutil.which("nix-shell")
    if not nix_file or not nix_file.is_file() or not nix_shell:
        info["description"] = f"nix-shell {nix_file}"
        info["problem"] = ("no converter_nix_shell set in the preset" if not nix else
                           f"converter nix file {nix} not found" if not nix_file.is_file() else "nix-shell not on PATH")
        return None, info
    rev_args = ["--argstr", "rev", str(rev)] if rev else []
    info["description"] = f"nix-shell {nix_file}" + (f" --argstr rev {rev}" if rev else "")
    return [nix_shell, str(nix_file), *rev_args, "--run", shlex.join([tool, *args])], info


def converter_version(preset: dict, route: str) -> str | None:
    """The converter's own version line, through the same route (None when it cannot be read; ODA has no version flag)."""
    if route == "oda":
        return None
    argv, _ = tool_argv(preset["converter"], list(preset.get("version_args", ["--version"])), preset, route)
    if argv is None:
        return None
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=preset["timeout_s"])
    except (subprocess.TimeoutExpired, OSError):
        return None
    lines = [ln.strip() for ln in (p.stdout + "\n" + p.stderr).splitlines() if ln.strip()]
    return lines[0] if (p.returncode == 0 and lines) else None


def header_version(path: pathlib.Path) -> str:
    """The 6-byte version string at the start of a DWG file (e.g. 'AC1032'); UsageError if it is not one."""
    with open(path, "rb") as f:
        head = f.read(6)
    code = head.decode("ascii", errors="replace")
    if not re.fullmatch(r"AC\d{4}", code):
        raise UsageError(f"{path.name}: not a DWG file (first bytes {head!r})")
    return code


def dxf_version(path: pathlib.Path) -> str | None:
    """$ACADVER from a DXF without loading it (None if not found in the header)."""
    with open(path, "rb") as f:
        head = f.read(4096).decode("latin-1", errors="replace")
    m = re.search(r"\$ACADVER\s*\r?\n\s*1\s*\r?\n\s*(AC\d{4})", head)
    return m.group(1) if m else None


def run_converter(src: pathlib.Path, dxf: pathlib.Path, preset: dict, route: str) -> tuple[dict, list[str] | None, int | None, list[str], str | None]:
    """Convert `src` (DWG) into `dxf`. Returns (route info, argv, exit code, log lines, problem). problem is set (and the rest
    partly None) when the converter could not run or did not finish."""
    if route == "oda":
        exe = find_oda(preset)
        info = {"route": "oda", "description": exe or "ODAFileConverter (not installed)", "nix_file": None, "nix_rev": None}
        if exe is None:
            info["problem"] = "ODAFileConverter not found (converter_route is 'oda')"
            return info, None, None, [], info["problem"]
        with tempfile.TemporaryDirectory(prefix="vpt_oda_") as td:
            tin, tout = pathlib.Path(td, "in"), pathlib.Path(td, "out")
            tin.mkdir()
            tout.mkdir()
            shutil.copy2(src, tin / src.name)
            argv = [exe, str(tin), str(tout), preset.get("oda_output_version", "ACAD2018"), "DXF", "0", "1", src.name]
            try:
                p, observable = run_oda(exe, argv[1:], preset, preset["timeout_s"])
            except subprocess.TimeoutExpired:
                return info, argv, None, [], f"ODAFileConverter did not finish within {preset['timeout_s']} s"
            made = tout / (src.stem + ".dxf")
            if made.is_file():
                shutil.move(str(made), str(dxf))
            lines = [ln for ln in (p.stderr + "\n" + p.stdout).splitlines() if ln.strip()]
            lines += [ln for f in sorted(tout.glob("*.err")) for ln in f.read_text(errors="replace").splitlines() if ln.strip()]
            return info, argv, (p.returncode if observable else None), lines, None
    argv, info = tool_argv(preset["converter"], [*preset["converter_args"], "-o", str(dxf), str(src)], preset, route)
    if argv is None:
        return info, None, None, [], f"{preset['converter']} cannot run: {info['problem']}"
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=preset["timeout_s"])
    except subprocess.TimeoutExpired:
        return info, argv, None, [], f"{preset['converter']} did not finish within {preset['timeout_s']} s"
    return info, argv, p.returncode, [ln for ln in (p.stderr + "\n" + p.stdout).splitlines() if ln.strip()], None


# ---- the DXF as written ------------------------------------------------------------------------------------

MARKED = ("ATTRIB", "ATTDEF", "INSERT", "SEQEND")


def dxf_markers(path: pathlib.Path) -> dict:
    """Section names in file order, whether the EOF marker is there, and raw counts of some entity markers, read as (group code,
    value) line pairs: what is IN the file, not what a reader repairs. A binary DXF is reported as such (not scanned)."""
    with open(path, "rb") as f:
        if f.read(22).startswith(b"AutoCAD Binary DXF"):
            return {"binary": True, "sections": [], "eof": None, "markers": {}}
    sections: list[str] = []
    eof = False
    markers: Counter = Counter()
    with open(path, encoding="utf-8", errors="replace") as f:
        it = iter(f)
        for code in it:
            value = next(it, None)
            if value is None:
                break
            if code.strip() != "0":
                continue
            v = value.strip()
            if v == "SECTION":
                c2, v2 = next(it, ""), next(it, "")
                if c2.strip() == "2":
                    sections.append(v2.strip())
            elif v == "EOF":
                eof = True
            elif v in MARKED:
                markers[v] += 1
    return {"binary": False, "sections": sections, "eof": eof, "markers": dict(markers)}


def completeness(marks: dict, version: str | None, msp_entities: int | None, block_entities: int | None, cfg: dict) -> tuple[list[str], list[str]]:
    """(failures, unknowns): the reasons a written DXF is cut off (observable in the file: FAIL) or cannot be checked."""
    if marks.get("binary"):
        return [], ["binary DXF: its section markers were not checked"]
    out = []
    if cfg.get("require_eof", True) and not marks["eof"]:
        out.append("the DXF has no EOF marker: the file was cut off")
    for sec in cfg.get("required_sections", ["ENTITIES", "OBJECTS"]):
        if sec == "OBJECTS" and version in cfg.get("no_objects_section_versions", ["AC1009"]):
            continue
        if sec not in marks["sections"]:
            out.append(f"the DXF has no {sec} section")
    n_min = cfg.get("empty_model_min_block_entities", 1)
    if msp_entities == 0 and block_entities is not None and block_entities >= n_min:
        out.append(f"model space has no entities while the block definitions hold {block_entities}: the drawing itself is missing")
    return out, []


def read_dxf(path: pathlib.Path):
    """ezdxf recover mode: (doc, audit). When ezdxf cannot load the file at all, doc is None and audit["load_error"] holds the
    error text: a could-not-tell for the caller, never an exception."""
    try:
        doc, auditor = recover.readfile(str(path))
    except Exception as e:     # noqa: BLE001 - every loader error is a recorded could-not-tell with its text
        return None, {"errors": [], "fixes": [], "load_error": f"{type(e).__name__}: {e}"}
    return doc, {"errors": [str(e.message) for e in auditor.errors], "fixes": [str(f.message) for f in auditor.fixes]}


def _is_layout_block(name: str) -> bool:
    n = name.lower()
    return n.startswith("*model_space") or n.startswith("*paper_space")


def inventory(doc) -> dict:
    """Entity counts by type per layout, layers, user block names, entities in block definitions."""
    by_layout = {layout.name: dict(Counter(e.dxftype() for e in layout)) for layout in doc.layouts}
    return {
        "entities_by_layout": by_layout,
        "entities_total": sum(sum(c.values()) for c in by_layout.values()),
        "model_entities": sum(by_layout.get("Model", {}).values()),
        "block_entities": sum(len(b) for b in doc.blocks if not _is_layout_block(b.name)),
        "layers": sorted(layer.dxf.name for layer in doc.layers),
        "blocks": sorted(b.name for b in doc.blocks if not b.name.startswith("*")),
    }


def attribute_evidence(doc, marks: dict) -> dict:
    """Whether block attributes survived: every INSERT whose block defines ATTDEFs should carry as many ATTRIBs; the ATTRIBs ezdxf
    read should equal the ATTRIB markers in the file."""
    attdefs = {b.name: sum(1 for e in b if e.dxftype() == "ATTDEF") for b in doc.blocks if not _is_layout_block(b.name)}
    attdefs = {k: v for k, v in attdefs.items() if v}
    inserts = [e for layout in doc.layouts for e in layout if e.dxftype() == "INSERT"]
    inserts += [e for b in doc.blocks if not _is_layout_block(b.name) for e in b if e.dxftype() == "INSERT"]
    needing = [e for e in inserts if e.dxf.name in attdefs]
    short = [e for e in needing if len(e.attribs) < attdefs[e.dxf.name]]
    return {"blocks_with_attdef": len(attdefs), "attdef_total": sum(attdefs.values()), "inserts": len(inserts),
            "inserts_of_attdef_blocks": len(needing), "inserts_with_fewer_attribs": len(short),
            "attribs_read": sum(len(e.attribs) for e in inserts), "attrib_markers_in_file": (marks.get("markers") or {}).get("ATTRIB")}


def verify_allowed(kind: str | None, evidence: dict | None) -> tuple[str, str]:
    """('verified' | 'failed' | 'not verified', why) for an allow-list entry's named verification on this file."""
    if not kind:
        return "not verified", "the entry names no verification"
    if kind == "attribs":
        if evidence is None:
            return "not verified", "the DXF could not be loaded: no attribute counts"
        if evidence["inserts_of_attdef_blocks"] == 0:
            return "not verified", "no INSERT of a block with attribute definitions: nothing to compare"
        ok = evidence["inserts_with_fewer_attribs"] == 0 and evidence["attribs_read"] == evidence["attrib_markers_in_file"]
        why = (f"{evidence['inserts_of_attdef_blocks']} INSERT(s) of {evidence['blocks_with_attdef']} block(s) with {evidence['attdef_total']} ATTDEF(s): "
               f"{evidence['inserts_with_fewer_attribs']} carry fewer ATTRIBs than their block defines; ATTRIBs read {evidence['attribs_read']}, "
               f"ATTRIB markers in the file {evidence['attrib_markers_in_file']}")
        return ("verified" if ok else "failed"), why
    return "not verified", f"unknown verification {kind!r}"


def sort_lines(lines: list[str], preset: dict) -> dict:
    """Split converter lines into unsupported (matching unsupported_patterns, no allow-list entry) and accepted (per entry)."""
    pats = [re.compile(x) for x in preset["unsupported_patterns"]]
    allowed = [(re.compile(a["pattern"]), a) for a in preset.get("allowed_messages", [])]
    accepted: dict[int, list[str]] = {}
    unsupported = []
    for ln in (x for x in lines if any(p.search(x) for p in pats)):
        k = next((i for i, (rx, _) in enumerate(allowed) if rx.search(ln)), None)
        if k is None:
            unsupported.append(ln)
        else:
            accepted.setdefault(k, []).append(ln)
    keep = int(preset.get("max_messages_kept", 200))
    return {"unsupported_total": len(unsupported), "unsupported": list(dict.fromkeys(unsupported))[:keep],
            "allowed": [{"pattern": allowed[k][1]["pattern"], "reason": allowed[k][1]["reason"], "verify": allowed[k][1].get("verify"),
                         "count": len(v), "lines": list(dict.fromkeys(v))[:20]} for k, v in sorted(accepted.items())]}


# ---- the run -----------------------------------------------------------------------------------------------

def _finish(rec: dict, path: pathlib.Path, failures: list[str], unknowns: list[str], dxf: pathlib.Path | None) -> dict:
    rec["dxf"] = str(dxf) if dxf else None
    rec["failures"], rec["unknowns"] = failures, unknowns
    rec["status"] = FAIL if failures else (UNK if unknowns else PASS)
    path.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    rec["record"] = str(path)
    return rec


def run(src: pathlib.Path, outdir: pathlib.Path, preset: dict | None = None) -> dict:
    preset = preset or json.loads(PRESET.read_text(encoding="utf-8"))
    src, outdir = pathlib.Path(src), pathlib.Path(outdir)
    if not src.is_file():
        raise UsageError(f"input not found: {src}")
    kind = src.suffix.lower()
    if kind not in (".dwg", ".dxf"):
        raise UsageError(f"input must be .dwg or .dxf: {src.name}")
    outdir.mkdir(parents=True, exist_ok=True)
    rec_path = outdir / f"{src.stem}.convert.json"
    rec_path.unlink(missing_ok=True)       # a crash must never leave an old record looking current
    failures: list[str] = []
    unknowns: list[str] = []
    rec: dict = {"test": "dwg_convert", "input": src.name, "kind": kind[1:], "allowed_messages": [], "unsupported_messages": []}

    if kind == ".dwg":
        code = header_version(src)
        rec["version"], rec["release"] = code, preset["versions"].get(code)
        if rec["release"] is None:
            unknowns.append(f"unknown DWG version {code}: not in the preset's version list")
        dxf = outdir / f"{src.stem}.dxf"
        dxf.unlink(missing_ok=True)
        route, _ = choose_route(preset)
        info, argv, code_exit, lines, problem = run_converter(src, dxf, preset, route)
        rec["converter"] = info["description"]
        rec["converter_info"] = {"name": preset["converter"] if route != "oda" else "ODAFileConverter", "route": info["route"],
                                 "nix_file": info.get("nix_file"), "nix_rev": info.get("nix_rev"), "version": None}
        if problem:
            unknowns.append(problem)
            return _finish(rec, rec_path, failures, unknowns, None)
        rec["converter_info"]["version"] = converter_version(preset, route)
        rec["args"] = argv[1:]
        log = outdir / f"{src.stem}.convert.log"
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        sl = sort_lines(lines, preset)
        rec.update(converter_exit=code_exit, converter_log=log.name, converter_messages_total=len(lines),
                   converter_message_kinds=dict(Counter(ln.split(":", 1)[0] if ":" in ln[:20] else "other" for ln in lines)),
                   converter_messages=lines[:int(preset.get("max_messages_kept", 200))], unsupported_messages_total=sl["unsupported_total"],
                   unsupported_messages=sl["unsupported"], allowed_messages=sl["allowed"])
        if code_exit is not None and code_exit != 0:
            unknowns.append(f"the converter exited {code_exit}")
        if sl["unsupported_total"]:
            unknowns.append(f"converter reported {sl['unsupported_total']} line(s) about errors or unsupported objects "
                            f"({len(sl['unsupported'])} distinct; not on the allow-list)")
        if not dxf.is_file() or dxf.stat().st_size == 0:
            unknowns.append("no DXF was written")
            return _finish(rec, rec_path, failures, unknowns, None)
    else:
        dxf = src
        rec["version"] = dxf_version(src)
        rec["release"] = preset["versions"].get(rec["version"] or "")
        rec["converter"] = rec["converter_info"] = None
        rec["note"] = "DXF given directly: no conversion"

    marks = dxf_markers(dxf)
    rec["dxf_markers"] = marks
    doc, audit = read_dxf(dxf)
    rec["audit"] = audit
    evidence = None
    ccfg = preset.get("completeness", {})
    if doc is None:
        unknowns.append(f"DXF could not be loaded: {audit['load_error']}")
        f, u = completeness(marks, rec.get("version"), None, None, ccfg)
        failures += f
        unknowns += u
    else:
        if audit["errors"]:
            unknowns.append(f"ezdxf audit: {len(audit['errors'])} unfixed error(s)")
        inv = inventory(doc)
        rec.update(inv)
        f, u = completeness(marks, rec.get("version"), inv["model_entities"], inv["block_entities"], ccfg)
        failures += f
        unknowns += u
        bad = Counter()
        for counts in inv["entities_by_layout"].values():
            for t in preset["unsupported_dxf_types"]:
                bad[t] += counts.get(t, 0)
        rec["unsupported_entities"] = {k: v for k, v in bad.items() if v}
        if rec["unsupported_entities"]:
            unknowns.append(f"DXF holds objects no reader can interpret: {rec['unsupported_entities']}")
        if inv["entities_total"] == 0:
            unknowns.append("the DXF has no entities at all")
        evidence = attribute_evidence(doc, marks)
        rec["attribute_evidence"] = evidence
    for a in rec["allowed_messages"]:
        a["verification"], a["verification_detail"] = verify_allowed(a.get("verify"), evidence)
        if a["verification"] == "failed":
            unknowns.append(f"allow-listed converter line(s) ({a['count']}x '{a['pattern']}') are accepted only if their verification holds; "
                            f"it failed on this file: {a['verification_detail']}")
    return _finish(rec, rec_path, failures, unknowns, dxf)


def default_outdir(root: pathlib.Path = ROOT) -> pathlib.Path:
    return root / "_scratch" / f"{dt.date.today().isoformat()}_dwg_convert"
