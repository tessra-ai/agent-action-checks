"""Re-check every quotation in prior_work.md against the papers' full text.

    python experiments/2026-11-20-closing-writeup/check_prior_work.py [--dir PAPERS_DIR]

Downloads the cited PDFs from arXiv into PAPERS_DIR (default: a folder next to this file that git
ignores) and converts them with `pdftotext -layout`. The papers are not committed. A quote matches
when it occurs in a paper's text after whitespace, typographic quotes, ligatures and line-end
hyphenation are normalised. Two-column pages interleave in the extracted text, so the check also
accepts a match with all spaces removed. Exits non-zero if any quote is missing.

Known limits: a hyphen at a PDF line end is either a word split or a real hyphen, and the text alone
cannot say which. A quote that relies on one of those joinings is accepted either way (so "resign"
would verify against a wrapped "re-sign"), and a quote that crosses one of each kind is rejected.
Quotations that cross a line-end hyphen deserve a look at the PDF.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
# section number in prior_work.md -> the arXiv revision read
PAPERS = {
    1: "2610.38620v1",
    2: "2610.17301v1",
    3: "2406.12045v1",
    4: "2606.02668v1",
    5: "2610.16838v1",
    6: "2610.05532v1",
    7: "2606.09863v1",
    8: "2610.27548v2",
    9: "2609.26550v6",
    10: "2512.07850v1",
    11: "2603.03116v1",
    12: "2605.11003v1",
}


def norm(s: str) -> str:
    s = re.sub(r"-\s*\n\s*", "", s)  # a line-end ASCII hyphen: word split, before dashes are folded
    for a, b in (
        ("\u2019", "'"),
        ("\u2018", "'"),
        ("\u201c", '"'),
        ("\u201d", '"'),
        ("\ufb01", "fi"),
        ("\ufb02", "fl"),
        ("\u2013", "-"),
        ("\u2014", "-"),
    ):
        s = s.replace(a, b)
    return re.sub(r"\s+", " ", s).strip().lower()


def fetch(d: Path) -> dict[int, str]:
    """The text of each paper at the cited revision, cached by revision."""
    d.mkdir(parents=True, exist_ok=True)
    texts = {}
    for sec, pid in PAPERS.items():
        pdf, txt = d / f"{pid}.pdf", d / f"{pid}.txt"
        if not pdf.exists():  # download to a temporary name, publish only when complete
            tmp = pdf.with_suffix(".part")
            urllib.request.urlretrieve(f"https://arxiv.org/pdf/{pid}", tmp)
            tmp.replace(pdf)
        if not txt.exists():  # convert to a temporary name, publish only when complete
            part = txt.with_suffix(".txt.part")
            subprocess.run(
                ["pdftotext", "-layout", str(pdf), str(part)], check=True, capture_output=True
            )
            part.replace(txt)
        raw = txt.read_text(errors="replace")
        # a hyphen at a line end is either a typeset word split ("op-" / "eration") or a real
        # hyphen ("tool-" / "using"): keep both joinings, separated so no match spans them
        # (known limit: a quotation that crosses one line-end hyphen of each kind matches neither
        # joining, so the check fails; it can reject a correct quotation, never accept a wrong one)
        texts[sec] = norm(raw) + " \x00 " + norm(re.sub(r"-\s*\n\s*", "-", raw))
    return texts


def sections(md: str) -> dict[int | None, str]:
    """prior_work.md split by its numbered paper headings ('## 3. ...'); other text is None."""
    out: dict[int | None, str] = {None: ""}
    cur: int | None = None
    for line in md.splitlines(keepends=True):
        m = re.match(r"## (\d+)\. ", line)
        if m:
            cur = int(m.group(1))
            if cur in out:
                raise SystemExit(f"prior_work.md: section {cur} appears twice")
            out[cur] = ""
        elif line.startswith("## "):
            cur = None
        out[cur] += line
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=str(HERE / "runs/papers"))
    texts = fetch(Path(ap.parse_args().dir))
    missing, quotes = [], []
    for sec, text in sections((HERE / "prior_work.md").read_text()).items():
        body = re.sub(r"\n(?!\n|- |\*\*|#)", " ", text)
        # a quotation is checked against the paper its section is about; text outside the paper
        # sections may quote any of them
        pool = [texts[sec]] if sec is not None else list(texts.values())
        # quotations use straight double quotes only; anything else would be skipped silently
        if "\u201c" in body or "\u201d" in body:
            missing.append(
                f"[section {sec}] curly double quotes: use straight ones so the span is checked"
            )
        if body.count('"') % 2:
            missing.append(
                f"[section {sec}] an odd number of double quotes: a quotation is unbalanced"
            )
        for q in re.findall(r'"([^"]*)"', body):
            quotes.append(q)
            # trim surrounding punctuation; a trailing dash is a line-end hyphen, but a leading
            # minus attached to a number is kept ("-1.8 points" must not match "1.8 points")
            n = norm(q).strip(" .,;:")
            n = re.sub(r"[-\u2013]+$", "", n).strip()
            n = re.sub(r"^[-\u2013]+(?!\d)", "", n).strip()
            # titles are set in letter-spaced small caps, which the extraction splits; only a quote
            # that is a heading title may match with spaces removed. Every other quotation must
            # match with its word boundaries intact.
            is_title = any(
                line.startswith("## ") and f'"{q}"' in line for line in text.splitlines()
            )
            if not n:
                missing.append(f"[section {sec}] a quotation with no words: {q!r}")
                continue
            # word boundaries at the ends: "authorized" must not match inside "unauthorized"
            pat = re.escape(n)
            # whole numbers at both ends: "14" must not match "14.0" or "+14", "26" not "26%"
            if n[:1].isdigit() or (n[:1] in "+-\u2212" and n[1:2].isdigit()):
                pat = r"(?<![\w.+\-\u2212])(?<!\d,)" + pat
            elif n[:1].isalnum():
                pat = r"(?<!\w)" + pat
            if n[-1:].isdigit():
                pat = pat + r"(?![\w%]|[.,]\d)"
            elif n[-1:].isalnum():
                pat = pat + r"(?!\w)"
            if not any(
                re.search(pat, t) or (is_title and n.replace(" ", "") in t.replace(" ", ""))
                for t in pool
            ):
                missing.append(f"[section {sec}] {q}")
    print(f"{len(quotes)} quotes, {len(missing)} not found in the cited paper")
    for q in missing:
        print("  NOT FOUND:", q[:160])
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
