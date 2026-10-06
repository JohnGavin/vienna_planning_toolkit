"""Layer stripping: an electrical planning base from a DXF (tools/strip_layers.py; every list in presets/layer_strip.json).

The layers an electrical planner does not need are DELETED (not hidden), the rest is left unchanged. Which layers go is decided
per layer from three things, never from a layer's content:

    storey    the layer's storey (presets/plan_extract.json `layer_regex`, via vpt.plan_extract.layer_info): one base per storey, so
              every other storey's layers are deleted; a layer without a storey (0, Defpoints, anything that does not match) is
              classified by its own name and, when it has content and stays, FLAGGED (X8): it lands in every storey's base and is
              never assigned to one storey by guessing. A drawing without storey layers is one pseudo-storey "all".
    status    the layer's status prefix (Abbruch = to demolish, Neubau = new): statuses in `drop_status` go (demolished content is not
              wired)
    base name the layer's base name: on the `drop` list it goes, on the `keep` list it stays; `ignore` layers stay untouched;
              a name on neither list is UNCLASSIFIED: kept, and flagged (X5) until someone decides

Checks per storey, on the SAVED file read back (match / different / could-not-tell):
    X1 no dropped layer left          no layer-table entry and no entity on a dropped layer, in any layout or block definition
    X2 kept layers unchanged          entity count per remaining layer equal before and after (layouts and blocks separately)
    X3 removal accounted for          entities removed = entities the dropped layers held; total before - removed = total after
    X4 output layers = kept set       the layer table after equals the set the preset's decisions keep (derived from the names, not from
                                      what the strip did), plus the ignored layers
    X5 layers classified              a layer of the storey WITH content on neither list: could-not-tell, FLAGGED (kept)
    X6 output file readable           the saved DXF reads strictly and its audit shows no errors the source did not have
    X8 layers without a storey        (several storeys only) layers with content and no storey: could-not-tell, FLAGGED (kept)
Result: FAIL when a check is different, INDETERMINATE when one could not tell (a flag included: a flag is never a match), else
PASS. The tool's exit codes: 0 / 1 / 3, usage 2.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
from collections import Counter

import ezdxf

from vpt import PRESETS, plan_extract
from vpt.plan_extract import DIFF, MATCH, UNK, Check

PRESET = PRESETS / "layer_strip.json"
SUFFIX = "__electrical_base"


class UsageError(Exception):
    pass


def load_preset(path: pathlib.Path = PRESET) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def validate(lp: dict) -> list[str]:
    """Problems with the lists: a base name on more than one of keep / drop / undecided / ignore (one home per layer)."""
    keep, drop, und, ign = (set(lp.get(k) or []) for k in ("keep", "drop", "undecided", "ignore"))
    out = []
    for (a, sa), (b, sb) in ((("keep", keep), ("drop", drop)), (("keep", keep), ("undecided", und)), (("drop", drop), ("undecided", und)),
                             (("drop", drop), ("ignore", ign)), (("keep", keep), ("ignore", ign))):
        if sa & sb:
            out.append(f"{sorted(sa & sb)} on both {a} and {b}")
    return out


# ---- counting and stripping --------------------------------------------------------------------------------

def _is_layout_block(name: str) -> bool:
    n = name.lower()
    return n.startswith("*model_space") or n.startswith("*paper_space")


def layer_counts(doc) -> dict[str, Counter]:
    """Entities per layer: {"layouts": model space + every paper-space layout, "blocks": block definitions (not layout blocks)}."""
    lay, blk = Counter(), Counter()
    for layout in doc.layouts:
        for e in layout:
            lay[e.dxf.get("layer", "0")] += 1
    for b in doc.blocks:
        if _is_layout_block(b.name):
            continue
        for e in b:
            blk[e.dxf.get("layer", "0")] += 1
    return {"layouts": lay, "blocks": blk}


def layer_names(doc) -> set[str]:
    return {layer.dxf.name for layer in doc.layers}


def strip(doc, drop: set[str]) -> Counter:
    """Delete every entity on a layer in `drop` (model space, all layouts, block definitions), then the layers themselves.
    Returns the number of entities deleted per layer."""
    removed: Counter = Counter()
    for layout in doc.layouts:
        for e in list(layout):
            if e.dxf.get("layer", "0") in drop:
                removed[e.dxf.get("layer", "0")] += 1
                layout.delete_entity(e)
    for b in doc.blocks:
        if _is_layout_block(b.name):
            continue
        for e in list(b):
            if e.dxf.get("layer", "0") in drop:
                removed[e.dxf.get("layer", "0")] += 1
                b.delete_entity(e)
    if doc.header.get("$CLAYER") in drop:
        doc.header["$CLAYER"] = "0"
    for name in drop & layer_names(doc):
        doc.layers.discard(name)
    return removed


# ---- the decision per layer ----------------------------------------------------------------------------------

def storeys_of(info: dict[str, dict]) -> list[dict]:
    """[{key, layers}] in key order; a drawing in which no layer has a storey is one storey 'all' (layer_info does that)."""
    keys = sorted({v["storey"] for v in info.values() if v["storey"]})
    return [{"key": k, "layers": sorted(n for n, v in info.items() if v["storey"] == k)} for k in keys]


def decide(name: str, info: dict, own: set[str], multi: bool, lp: dict, has_content: bool) -> str:
    """The action for one layer of one storey's base: 'drop (other storey)', 'ignored (kept)', 'drop (status X)', 'drop', 'keep',
    'undecided (kept)', 'no storey (kept)', 'unclassified (kept)' (and the '..., empty (kept)' forms for a layer without content)."""
    i = info.get(name, {"storey": None, "status": None, "base": name})
    if multi and i["storey"] is not None and name not in own:
        return "drop (other storey)"
    if i["base"] in set(lp.get("ignore") or []) or name in set(lp.get("ignore") or []):
        return "ignored (kept)"
    if i["status"] in set(lp.get("drop_status") or []):
        return f"drop (status {i['status']})"
    if i["base"] in set(lp["drop"]):
        return "drop"
    if i["base"] in set(lp["keep"]):
        return "keep"
    if i["base"] in set(lp.get("undecided") or []):
        return "undecided (kept)"
    if multi and i["storey"] is None:
        return "no storey (kept)" if has_content else "no storey, empty (kept)"
    return "unclassified (kept)" if has_content else "not listed, empty (kept)"


# ---- the run -------------------------------------------------------------------------------------------------

def _read(path: pathlib.Path):
    """(doc, audit errors, load error). Recover mode, so a damaged file is described, not a crash."""
    from vpt.dwg_convert import read_dxf
    doc, audit = read_dxf(path)
    return doc, audit["errors"], audit.get("load_error", "")


def one_storey(doc, key: str, label: str, own: set[str], multi: bool, info: dict, lp: dict, before: dict, table_before: set[str],
               names_before: set[str], src_errors: int, out_dxf: pathlib.Path) -> dict:
    content = lambda n: before["layouts"][n] + before["blocks"][n]     # noqa: E731
    total = lambda c: sum(c["layouts"].values()) + sum(c["blocks"].values())     # noqa: E731
    acts = {n: decide(n, info, own, multi, lp, bool(content(n))) for n in names_before}
    drop_now = {n for n, a in acts.items() if a.startswith("drop")}
    ignore = set(lp.get("ignore") or [])
    unclassified = sorted(n for n in names_before if acts[n] == "unclassified (kept)")
    no_storey = sorted(n for n in names_before if multi and info.get(n, {}).get("storey") is None and content(n)
                       and not acts[n].startswith("drop") and acts[n] != "ignored (kept)")
    removed = strip(doc, drop_now)
    doc.saveas(out_dxf)
    out_doc, out_errors, load_error = _read(out_dxf)
    base = {"key": key, "label": label, "output_dxf": out_dxf.name}
    checks: list[Check] = []
    if out_doc is None:
        c = Check("X6", "Output DXF readable and clean", DIFF, f"the saved DXF cannot be read: {load_error}")
        return dict(base, status="FAIL", failures=[f"{c.id} {c.title}: {c.detail}"], unknowns=[], flagged=[], checks=[c.as_dict()], layers=[],
                    entities={}, unclassified=unclassified, no_storey=no_storey)
    after = layer_counts(out_doc)
    names_after = layer_names(out_doc)
    held = {n: content(n) for n in drop_now}
    left = {n: after["layouts"][n] + after["blocks"][n] for n in drop_now if after["layouts"][n] + after["blocks"][n]}
    in_table = sorted(drop_now & names_after)
    items = [{"layer": n, "kind": "entities left", "count": c, "status": DIFF} for n, c in sorted(left.items())] \
        + [{"layer": n, "kind": "still in the layer table", "count": 0, "status": DIFF} for n in in_table]
    checks.append(Check("X1", "No dropped layer left", DIFF if items else MATCH,
                        (f"{len(left)} dropped layer(s) still hold entities, {len(in_table)} still in the layer table" if items else
                         f"{len(held)} dropped layer(s) ({sum(held.values())} entities) are gone"), items))
    kept = sorted((names_before - drop_now) | set(after["layouts"]) | set(after["blocks"]))
    changed = [{"layer": n, "where": w, "before": before[w][n], "after": after[w][n], "status": DIFF}
               for n in kept for w in ("layouts", "blocks") if before[w][n] != after[w][n]]
    checks.append(Check("X2", "Kept layers unchanged", DIFF if changed else MATCH,
                        (f"{len(changed)} (layer, place) pair(s) changed their entity count" if changed else
                         f"entity counts equal before and after on all {len(kept)} remaining layers (model space, layouts and block definitions)"), changed))
    acc = sum(removed.values()) == sum(held.values()) and total(before) - sum(removed.values()) == total(after)
    checks.append(Check("X3", "Removal accounted for", MATCH if acc else DIFF,
                        f"removed {sum(removed.values())} entities, the dropped layers held {sum(held.values())}; "
                        f"{total(before)} before - {sum(removed.values())} = {total(after)} after" + ("" if acc else " is not true")))
    want = {n for n in table_before if not decide(n, info, own, multi, lp, bool(content(n))).startswith("drop")}
    gone, extra = sorted(want - names_after), sorted(names_after - want - ignore)
    checks.append(Check("X4", "Output layers = the kept set", DIFF if (gone or extra) else MATCH,
                        f"{len(names_after)} layers after; missing {gone or 'none'}; unexpected {extra or 'none'}",
                        [{"layer": n, "kind": "lost", "status": DIFF} for n in gone] + [{"layer": n, "kind": "unexpected", "status": DIFF} for n in extra]))
    x5 = Check("X5", "Every layer with content is classified", UNK if unclassified else MATCH,
               (f"{len(unclassified)} layer(s) with content are on neither the keep nor the drop list: kept until classified "
                f"(add their base names to the preset): {', '.join(unclassified)}" if unclassified else
                "every layer with content is on the keep or drop list (or ignored, or dropped by status)"),
               [{"layer": n, "entities": content(n), "status": UNK} for n in unclassified])
    x5.gap = f"{len(unclassified)} layer(s) with content are on neither list" if unclassified else ""
    checks.append(x5)
    try:
        ezdxf.readfile(str(out_dxf))
        strict_ok, strict_err = True, ""
    except (OSError, ezdxf.DXFError) as e:
        strict_ok, strict_err = False, f"{type(e).__name__}: {e}"
    n_new = len(out_errors)
    if not strict_ok:
        x6 = Check("X6", "Output DXF readable and clean", DIFF, f"the saved DXF does not read strictly: {strict_err}")
    elif n_new > src_errors:
        x6 = Check("X6", "Output DXF readable and clean", UNK, f"audit of the saved DXF: {n_new} unfixed error(s), the source had {src_errors}")
    else:
        x6 = Check("X6", "Output DXF readable and clean", MATCH, f"reads strictly; audit errors {n_new} (source: {src_errors})")
    checks.append(x6)
    if multi:
        x8 = Check("X8", "Every layer with content belongs to a storey", UNK if no_storey else MATCH,
                   (f"{len(no_storey)} layer(s) with content have no storey: kept in every storey's base and listed, never assigned by guessing: "
                    f"{', '.join(no_storey)}") if no_storey else "every layer with content has a storey (or is ignored or dropped)",
                   [{"layer": n, "entities": content(n), "status": UNK} for n in no_storey])
        x8.gap = f"{len(no_storey)} layer(s) with content have no storey" if no_storey else ""
        checks.append(x8)
    failures = [f"{c.id} {c.title}: {c.detail}" for c in checks if c.status == DIFF]
    flagged = [{"id": c.id, "title": c.title, "reason": getattr(c, "gap", "")} for c in checks if c.status == UNK and getattr(c, "gap", "")]
    unknowns = [f"{c.id} {c.title}: {c.detail}" for c in checks if c.status == UNK and not getattr(c, "gap", "")]
    rows = [{"layer": n, "action": acts[n], "source_entities": content(n), "removed": removed.get(n, 0), "left": after["layouts"][n] + after["blocks"][n],
             "in_output_table": n in names_after} for n in sorted(names_before) if acts[n] != "drop (other storey)"]
    return dict(base, status="FAIL" if failures else ("INDETERMINATE" if (unknowns or flagged) else "PASS"), failures=failures, unknowns=unknowns,
                flagged=flagged, checks=[c.as_dict() | {"gap": getattr(c, "gap", "")} for c in checks], layers=rows,
                layer_actions=dict(Counter(a for a in acts.values() if a != "drop (other storey)")),
                other_storey_layers=sum(1 for a in acts.values() if a == "drop (other storey)"),
                entities={"source": total(before), "removed": sum(removed.values()), "output": total(after)},
                unclassified=unclassified, no_storey=no_storey)


def run(src: pathlib.Path, outdir: pathlib.Path, lp: dict | None = None, pre: dict | None = None) -> dict:
    """Build the electrical base of every storey of the DXF `src` into `outdir`; returns (and writes outdir/strip.json) the result."""
    src, outdir = pathlib.Path(src), pathlib.Path(outdir)
    lp = lp or load_preset()
    pre = pre or json.loads(plan_extract_preset().read_text(encoding="utf-8"))
    if problems := validate(lp):
        raise UsageError("the layer lists overlap: " + "; ".join(problems))
    if src.suffix.lower() != ".dxf" or not src.is_file():
        raise UsageError(f"input must be an existing .dxf file: {src}")
    outdir.mkdir(parents=True, exist_ok=True)
    for old in [outdir / "strip.json", *outdir.glob(f"{src.stem}*{SUFFIX}.dxf")]:
        old.unlink(missing_ok=True)       # a crash must never leave an old result looking current
    result: dict = {"test": "layer_strip", "input": src.name, "input_sha256": hashlib.sha256(src.read_bytes()).hexdigest(),
                    "drop_status": sorted(lp.get("drop_status") or []), "storeys": []}
    doc, src_errors, load_error = _read(src)
    if doc is None:
        result.update(status="INDETERMINATE", failures=[], flagged=[], unknowns=[f"the DXF cannot be read: {load_error}"], checks=[])
        (outdir / "strip.json").write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
        return result
    before = layer_counts(doc)
    table_before = layer_names(doc)
    names_before = table_before | set(before["layouts"]) | set(before["blocks"])      # DXF allows entities on a layer missing from the table
    info = plan_extract.layer_info(sorted(names_before), pre)
    storeys = storeys_of(info) or [{"key": plan_extract.ALL, "layers": []}]
    multi = storeys[0]["key"] != plan_extract.ALL          # layers with storey prefixes: one base per storey
    failures, unknowns, flagged, checks = [], [], [], []
    for k, s in enumerate(storeys):
        if k > 0:
            doc, _, err = _read(src)      # stripping changes the document: every storey starts from the source again
            if doc is None:
                raise RuntimeError(f"the DXF could be read once but not again: {err}")
        label = plan_extract.storey_label(s["key"], pre)
        tag = f"__{s['key']}" if multi else ""
        r = one_storey(doc, s["key"], label, set(s["layers"]), multi, info, lp, before, table_before, names_before, len(src_errors),
                       outdir / f"{src.stem}{tag}{SUFFIX}.dxf")
        result["storeys"].append(r)
        failures += [f"[{label}] {f}" for f in r["failures"]]
        unknowns += [f"[{label}] {u}" for u in r["unknowns"]]
        flagged += [dict(f, scope=s["key"]) for f in r["flagged"]]
        checks += [dict(c, scope=s["key"]) for c in r["checks"]]
    result.update(failures=failures, unknowns=unknowns, flagged=flagged, checks=checks, mode="storeys" if multi else "all",
                  status="FAIL" if failures else ("INDETERMINATE" if (unknowns or flagged) else "PASS"))
    (outdir / "strip.json").write_text(json.dumps(result, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return result


def plan_extract_preset() -> pathlib.Path:
    from vpt import plan
    return plan.EXTRACT_PRESET
