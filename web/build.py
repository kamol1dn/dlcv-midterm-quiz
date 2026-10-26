"""Bundle every deck's questions/*.json into web/decks/ for the static site.

    python web/build.py

Run it after adding or editing cards, then deploy web/. A deck whose folder has no
cards yet is left out of the site.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "web" / "decks"

DECKS = [
    {"key": "embedded", "title": "Embedded Software", "subtitle": "Lessons 00–08 · 33 MCQ, 60 min",
     "exam": "Wed 28 Oct, 09:30", "dir": "embedded/questions", "unit": "Lesson", "share": None},
    {"key": "distinguished", "title": "Distinguished Lecture", "subtitle": "Critical thinking · 30 MCQ, 60 min",
     "exam": "Fri 30 Oct, 09:30", "dir": "distinguished/questions", "unit": "Ch.",
     "share": [[[5], 0.30], [[1, 6, 10, 12], 0.60], [[2, 4, 11], 0.10]]},
    {"key": "dl", "title": "Deep Learning for Computer Vision", "subtitle": "Robot and AI · weeks 0–6 · 33 MCQ",
     "exam": "Midterm done 26 Oct · final in Dec", "dir": "questions", "unit": "Week",
     "share": [[[0], 0.10], [[1], 0.15], [[2], 0.20], [[3], 0.12], [[4], 0.15], [[5], 0.14], [[6], 0.14]]},
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    index = []
    for deck in DECKS:
        cards, seen = [], set()
        for path in sorted((ROOT / deck["dir"]).glob("*.json")):
            for c in json.loads(path.read_text(encoding="utf-8")):
                if c.get("id") in seen or len(c.get("choices", [])) != 4:
                    continue
                seen.add(c["id"])
                cards.append({k: c[k] for k in ("id", "chapter", "topic", "kind", "q", "choices", "why", "source")
                              if k in c})
        if not cards:
            print(f"skip {deck['key']}: no cards yet")
            continue
        (OUT / f"{deck['key']}.json").write_text(json.dumps(cards, ensure_ascii=False), encoding="utf-8")
        meta = {k: deck[k] for k in ("key", "title", "subtitle", "exam", "unit", "share")}
        index.append({**meta, "count": len(cards)})
        print(f"{deck['key']}: {len(cards)} cards")
    (OUT / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
