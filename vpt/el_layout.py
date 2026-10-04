"""The layout file of the electrical editor: <drawing>__<storey>.electrical.json (schema: schema/el_layout.schema.json).

What the page saves, copies, opens and accepts by paste (the page mirrors validate() and check_layout() in JavaScript, from the
same schema embedded in the page):
  - make_layout(): the file's content (schema el_layout, version 2: symbols, switch-light links, the placement rule set);
  - migrate(): a version-1 file becomes version 2 (no links, the default rule set); one with links is refused;
  - validate(): a JSON Schema validator for exactly the subset of keywords the toolkit's schemas use (an unsupported keyword
    is an error, never silently ignored); it validates the plan file and the parameter file too;
  - check_layout() / check_text(): may this file be opened on this drawing's storey? Three outcomes: "match" (same drawing
    checksum and storey, valid, every symbol code in the set), "different" (another drawing or storey: refused),
    "could-not-tell" (not a valid layout, unknown set, code or rule set, a link the symbols' lists do not allow, or the
    plan does not know its drawing's checksum: refused);
  - view_to_model() / model_to_view(): symbol positions are stored in MODEL coordinates (the DXF's), independent of zoom and
    portable to the DXF later: the inverse of the model -> viewBox affine that vpt/dxf_svg.py records.
"""
from __future__ import annotations

import json
import pathlib
import re

from vpt import PRESETS, SCHEMAS

SCHEMA = SCHEMAS / "el_layout.schema.json"
PAGE = PRESETS / "el_page.json"

SUPPORTED = {"type", "const", "enum", "required", "properties", "additionalProperties", "items", "minItems", "maxItems", "minimum",
             "exclusiveMinimum", "minLength", "pattern", "$ref", "$defs", "description", "title", "$comment"}
_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def load_schema(path: pathlib.Path = SCHEMA) -> dict:
    return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))


def load_page(path: pathlib.Path = PAGE, params: dict | None = None) -> dict:
    """The page settings: the fixed ones of presets/el_page.json and the tunable ones (symbol_scale, room_label_max_m, with
    their notes) from presets/el_parameters.json sections.page (their one home)."""
    from vpt import el_params
    cfg = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    for k, v in (params or el_params.load())["sections"]["page"]["values"].items():
        cfg[k], cfg[k + "_note"] = v["value"], v.get("note", "")
    return cfg


def unsupported_keywords(schema) -> list[str]:
    out: list[str] = []

    def walk(s, in_props=False):
        if not isinstance(s, dict):
            return
        for k, v in s.items():
            if in_props:                       # keys of "properties" / "$defs" are names, not keywords
                walk(v)
                continue
            if k not in SUPPORTED:
                out.append(k)
            if k in ("properties", "$defs"):
                walk(v, in_props=True)
            elif k == "items" or k == "additionalProperties":
                walk(v)
    walk(schema)
    return sorted(set(out))


def _is_type(x, t: str) -> bool:
    if t == "number":
        return isinstance(x, (int, float)) and not isinstance(x, bool)
    if t == "integer":
        return (isinstance(x, int) and not isinstance(x, bool)) or (isinstance(x, float) and x.is_integer())
    return isinstance(x, _TYPES[t]) and not (t != "boolean" and isinstance(x, bool))


def validate(doc, schema: dict) -> list[str]:
    """Problems of doc against schema (empty = valid). Raises ValueError when the schema uses a keyword outside the subset."""
    bad = unsupported_keywords(schema)
    if bad:
        raise ValueError(f"schema keyword(s) not supported by this validator: {bad}")
    out: list[str] = []

    def ref(r: str) -> dict:
        if not r.startswith("#/$defs/"):
            raise ValueError(f"only local #/$defs/ references are supported: {r}")
        return schema["$defs"][r[len("#/$defs/"):]]

    def go(x, s: dict, path: str) -> None:
        if "$ref" in s:
            s = ref(s["$ref"])
        if "type" in s:
            ts = s["type"] if isinstance(s["type"], list) else [s["type"]]
            if not any(_is_type(x, t) for t in ts):
                out.append(f"{path}: type is {type(x).__name__}, want {'/'.join(ts)}")
                return
        if "const" in s and x != s["const"]:
            out.append(f"{path}: const {s['const']!r} wanted, got {x!r}")
        if "enum" in s and x not in s["enum"]:
            out.append(f"{path}: enum {s['enum']} does not contain {x!r}")
        if isinstance(x, str):
            if "minLength" in s and len(x) < s["minLength"]:
                out.append(f"{path}: minLength {s['minLength']}")
            if "pattern" in s and not re.search(s["pattern"], x):
                out.append(f"{path}: pattern {s['pattern']} does not match")
        if _is_type(x, "number"):
            if "minimum" in s and x < s["minimum"]:
                out.append(f"{path}: minimum {s['minimum']}")
            if "exclusiveMinimum" in s and not x > s["exclusiveMinimum"]:
                out.append(f"{path}: exclusiveMinimum {s['exclusiveMinimum']}")
        if isinstance(x, dict):
            for k in s.get("required", []):
                if k not in x:
                    out.append(f"{path}: required property {k!r} missing")
            props = s.get("properties", {})
            for k, v in x.items():
                if k in props:
                    go(v, props[k], f"{path}.{k}")
                elif s.get("additionalProperties") is False:
                    out.append(f"{path}: additional property {k!r} not allowed")
                elif isinstance(s.get("additionalProperties"), dict):         # a schema every further property must meet
                    go(v, s["additionalProperties"], f"{path}.{k}")
        if isinstance(x, list):
            if "minItems" in s and len(x) < s["minItems"]:
                out.append(f"{path}: minItems {s['minItems']}")
            if "maxItems" in s and len(x) > s["maxItems"]:
                out.append(f"{path}: maxItems {s['maxItems']}")
            if "items" in s:
                for i, v in enumerate(x):
                    go(v, s["items"], f"{path}[{i}]")

    go(doc, schema, "$")
    return out


def model_to_view(affine: list[float], x: float, y: float) -> tuple[float, float]:
    a, b, c, d, e, f = affine
    return a * x + c * y + e, b * x + d * y + f


def view_to_model(affine: list[float], X: float, Y: float) -> tuple[float, float]:
    """Inverse of the affine X = a*x + c*y + e, Y = b*x + d*y + f (vpt/dxf_svg.py render)."""
    a, b, c, d, e, f = affine
    det = a * d - b * c
    if abs(det) < 1e-12:
        raise ValueError("the drawing's affine cannot be inverted")
    X, Y = X - e, Y - f
    return (d * X - c * Y) / det, (-b * X + a * Y) / det


def file_name(drawing_file: str, storey: str, suffix: str) -> str:
    return f"{pathlib.Path(drawing_file).stem}__{storey}{suffix}"


VERSION = 2


def make_layout(*, drawing_file: str, sha256: str, storey: str, storey_label: str, model_units_mm, symbol_set: dict, background: dict,
                symbols: list[dict], saved: str, links: list[dict] | None = None, rule_set: str = "starting",
                app: str = "vpt/el_layout.py") -> dict:
    return {"schema": "el_layout", "schema_version": VERSION,
            "drawing": {"file": drawing_file, "sha256": sha256, "storey": storey, "storey_label": storey_label},
            "model_units_mm": model_units_mm,
            "symbol_set": {"id": symbol_set["id"], "version": symbol_set["version"], "verified": bool(symbol_set.get("verified"))},
            "background": background, "symbols": symbols, "links": list(links or []), "rule_set": rule_set, "saved": saved, "app": app}


def migrate(doc: dict, default_rule_set: str) -> tuple[dict | None, str]:
    """(a version-2 copy of a VALID layout, "") or (None, why). Version 1 had no links (reserved, always empty) and no rule
    set: it becomes version 2 with no links and the default rule set; a version-1 file WITH links is refused."""
    if doc["schema_version"] == VERSION:
        return dict(doc, rule_set=doc.get("rule_set") or default_rule_set), ""
    if doc["schema_version"] == 1:
        if doc["links"]:
            return None, "a version-1 file with links (version 1 had none)"
        if "rule_set" in doc:
            return None, "a version-1 file with a rule set (version 1 had none)"
        return dict(doc, schema_version=VERSION, links=[], rule_set=default_rule_set), ""
    return None, f"unknown schema_version {doc['schema_version']!r}"


def check_layout(doc, *, sha256: str | None, storey: str, lib: dict, schema: dict, rules: dict | None = None) -> tuple[str, str]:
    """("match" | "different" | "could-not-tell", message). Only "match" may be opened."""
    from vpt import el_links, el_rules
    rules = rules or el_rules.load()
    problems = validate(doc, schema)
    if problems:
        return "could-not-tell", f"not a valid layout file ({len(problems)} problem(s), first: {problems[0]})"
    doc, why = migrate(doc, rules["default_rule_set"])
    if doc is None:
        return "could-not-tell", f"not a valid layout file: {why}"
    if not sha256:
        return "could-not-tell", "the plan does not know its drawing's checksum, so it cannot tell whether the file belongs to it"
    d = doc["drawing"]
    if d["sha256"] != sha256:
        return "different", f"the file belongs to another drawing ({d['file']}, checksum {d['sha256'][:12]}…), not to this one ({sha256[:12]}…)"
    if d["storey"] != storey:
        return "different", f"the file belongs to storey {d['storey']}, not to storey {storey}"
    sets = {s["id"]: s for s in lib["sets"]}
    s = sets.get(doc["symbol_set"]["id"])
    if s is None:
        return "could-not-tell", f"the file uses symbol set {doc['symbol_set']['id']!r}, which this page does not offer"
    codes = {x["code"] for x in s["symbols"]}
    unknown = sorted({x["code"] for x in doc["symbols"]} - codes)
    if unknown:
        return "could-not-tell", f"symbol code(s) {unknown} are not in set {s['id']}"
    if el_rules.rule_set(rules, doc["rule_set"]) is None:
        return "could-not-tell", f"the file uses rule set {doc['rule_set']!r}, which this page does not offer"
    lp = el_links.link_problems(doc["symbols"], doc["links"], s, rules["switching"])
    if lp:
        return "could-not-tell", f"{len(lp)} link problem(s), first: {lp[0]}"
    return "match", f"{len(doc['symbols'])} symbol(s), {len(doc['links'])} link(s), drawing and storey match"


def check_text(text: str, **kw) -> tuple[str, str]:
    try:
        doc = json.loads(text)
    except (json.JSONDecodeError, TypeError) as e:
        return "could-not-tell", f"not JSON ({e})"
    return check_layout(doc, **kw)
