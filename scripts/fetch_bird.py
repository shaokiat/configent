"""Fetch the BIRD dev set and unpack formula_1 + dev.json into data/bird/ (gitignored).

BIRD is CC BY-SA 4.0: the data stays out of the repo. Only the column-description CSVs are
copied into corpora/f1-analyst/descriptions/, with an attribution note beside them.
A checksum mismatch fails loudly: the eval must not run against a changed dataset.
"""
import hashlib
import io
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://bird-bench.oss-cn-beijing.aliyuncs.com/dev.zip"  # linked from bird-bench.github.io
SHA256 = "cdd6d19faeb45a23970b98d3ef6c40a87987c95459c2cf12076897a60cf5a630"

ROOT = Path(__file__).parents[1]
OUT = ROOT / "data" / "bird"
DESCRIPTIONS = ROOT / "corpora" / "f1-analyst" / "descriptions"
DB = "formula_1"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    archive = OUT / "dev.zip"
    if not archive.exists():
        print(f"downloading {URL}")
        urllib.request.urlretrieve(URL, archive)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != SHA256:
        sys.exit(f"checksum mismatch for {archive}: got {digest}, pinned {SHA256}")

    with zipfile.ZipFile(archive) as outer:
        names = outer.namelist()
        dev_json = next(n for n in names if n.endswith("/dev.json"))
        (OUT / "dev.json").write_bytes(outer.read(dev_json))
        inner_name = next(n for n in names if n.endswith("dev_databases.zip"))
        inner = zipfile.ZipFile(io.BytesIO(outer.read(inner_name)))
    DESCRIPTIONS.mkdir(parents=True, exist_ok=True)
    for n in inner.namelist():
        parts = Path(n).parts
        if DB not in parts or n.endswith("/") or "__MACOSX" in parts:
            continue
        rest = parts[parts.index(DB) + 1 :]
        if rest == (f"{DB}.sqlite",):
            (OUT / f"{DB}.sqlite").write_bytes(inner.read(n))
        elif rest[:1] == ("database_description",) and n.endswith(".csv"):
            (DESCRIPTIONS / rest[-1]).write_bytes(inner.read(n))
    shutil.rmtree(OUT / "__MACOSX", ignore_errors=True)
    print(f"ok: {OUT / (DB + '.sqlite')}")


if __name__ == "__main__":
    main()
