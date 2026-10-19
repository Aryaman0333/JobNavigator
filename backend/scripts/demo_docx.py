"""Build the demo's pre-made Word files with the backend's own docx builder (no database, no network).

    python -m backend.scripts.demo_docx <data.json> <out_dir>

Writes <out_dir>/<resume_id>.docx for every base résumé in the demo data.
"""
import json
import sys
from pathlib import Path


def main(argv=None) -> int:
    from backend.api.routes_resumes import _build_docx

    src, out = Path(argv[0]), Path(argv[1])
    out.mkdir(parents=True, exist_ok=True)
    data = json.loads(src.read_text(encoding="utf-8"))
    n = 0
    for r in data["resumes"]:
        if not r["is_base"]:
            continue
        (out / f"{r['id']}.docx").write_bytes(_build_docx(r["json_data"], r.get("page_format") or "letter", ""))
        n += 1
    print(f"wrote {n} docx files to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
