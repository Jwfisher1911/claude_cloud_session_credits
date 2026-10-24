"""Write the workbook's worksheet pages as JSON for the renderer.

    python3 video/worksheets.py output/markdown/core/01-battle-rhythm-workbook.md pages.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from verc.worksheet_pages import workbook_pages  # noqa: E402

if __name__ == "__main__":
    pages = workbook_pages(Path(sys.argv[1]).read_text(encoding="utf-8"))
    Path(sys.argv[2]).write_text(json.dumps(pages), encoding="utf-8")
    print(f"{len(pages)} worksheet pages")
