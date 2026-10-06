"""README gate: punchy, not prose. No paragraph over 30 words, no list item over 20 words (inline code not counted),
and every ## section holds a list, table or code block (no paragraph-only section). Falsified in the tests below."""
import re

from conftest import ROOT

MAX_PARA, MAX_ITEM = 30, 20
LIST_RE = re.compile(r"^\s*(?:[-*]|\d+\.)\s+")


def _words(text):
    text = re.sub(r"`[^`]*`", " ", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    return len(text.split())


def problems(md):
    out = []
    md = re.sub(r"</?(details|summary)[^>]*>.*", "", md)  # tag lines are not prose
    blocks, in_code = [], False
    for chunk in re.split(r"\n\s*\n", md):
        if chunk.count("```") % 2 == 1:
            in_code = not in_code
            continue
        if not in_code and "```" not in chunk:
            blocks.append(chunk.strip("\n"))
    section, has_structure, seen = None, False, []
    for line_block in re.split(r"\n(?=## )|\A", md):
        if line_block.startswith("## "):
            seen.append((line_block.splitlines()[0], line_block))
    for head, body in seen:
        if not (re.search(r"^\s*(?:[-*]|\d+\.)\s", body, re.M) or re.search(r"^\|", body, re.M) or "```" in body):
            out.append(f"section '{head}' is paragraph-only")
    for b in blocks:
        if not b.strip() or b.lstrip().startswith(("#", "|", "<")):
            continue
        lines = b.splitlines()
        if LIST_RE.match(lines[0]):
            items, cur = [], []
            for ln in lines:
                if LIST_RE.match(ln):
                    items.append(" ".join(cur))
                    cur = [LIST_RE.sub("", ln)]
                else:
                    cur.append(ln.strip())
            items.append(" ".join(cur))
            for it in items:
                if it.strip() and _words(it) > MAX_ITEM:
                    out.append(f"list item of {_words(it)} words: {it[:40]}")
        elif _words(b) > MAX_PARA:
            out.append(f"paragraph of {_words(b)} words: {b[:40]}")
    return out


def test_readme_is_punchy():
    md = (ROOT / "README.md").read_text(encoding="utf-8")
    assert problems(md) == []


def test_gate_falsified():
    md = (ROOT / "README.md").read_text(encoding="utf-8")
    long_para = "\n\nword " + "word " * 35 + "\n"
    long_item = "\n\n- " + "word " * 25 + "\n"
    prose_section = "\n\n## Prose only\n\nJust a sentence.\n"
    assert any("paragraph of" in p for p in problems(md + long_para))
    assert any("list item of" in p for p in problems(md + long_item))
    assert any("paragraph-only" in p for p in problems(md + prose_section))
