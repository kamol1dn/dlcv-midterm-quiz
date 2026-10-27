#!/usr/bin/env python3
"""Midterm flashcards for Deep Learning for Computer Vision ("Robot and AI", weeks 0-6).

    python quiz.py              all weeks
    python quiz.py 4            only week 4, walking  (any of 0-6; 2 includes 2b, 2b alone is 2b)
    python quiz.py 5 6          several weeks
    python quiz.py --missed     only cards you got wrong and haven't fixed yet
    python quiz.py --mix        new cards in random order, weighted by exam share
                                (default: course order, week 0 first, as the guide teaches it)
    python quiz.py stats        progress per week + weakest topics
    python quiz.py --deck embedded       another deck: dl (default), embedded, distinguished, ai;
                                         combine with the options above, each deck has its own progress
    python quiz.py reset        wipe all progress

Keys on a question:   a-d (or 1-4) answer  ·  Enter = just show me  ·  q = quit
Keys after:           Enter = next  ·  k = typo, I knew it (count it right)  ·  q = quit

Progress is written to progress.json after every card, so quitting at any
point (q, Ctrl+C, closing the window) loses nothing.

How cards are picked (a Leitner box scheme over "turns", i.e. cards shown):
  - A card starts in no box. First-try right puts it straight in box 3, so
    things you already know drop out fast. Another right answer = mastered.
  - Wrong or "just show me" puts it in box 0. It comes back after ~4 cards,
    then climbs a box each time you get it right.
  - Higher boxes wait longer (GAP) and pull less (BASE), so mastered cards
    turn up rarely but never vanish completely.
  - Topics you keep missing (e.g. "Capture point") get extra weight, so new
    and old cards on them come up more.
  - Weeks come up in a guessed exam share (the professor gave no split; the
    denser weeks get more), whatever the size of their question bank. Once a
    week's new cards run out the others fill in, so everything gets covered.
"""

from __future__ import annotations

import collections
import json
import os
import random
import shutil
import sys
import textwrap
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).resolve().parent

# deck -> (question folder, progress file, answer log, exam share). Pick one with --deck NAME.
DECKS = {
    "dl": ("questions", "progress.json", "answers.jsonl",
           {(0,): 0.10, (1,): 0.15, (2,): 0.20, (3,): 0.12, (4,): 0.15, (5,): 0.14, (6,): 0.14}),
    "embedded": ("embedded/questions", "progress-embedded.json", "answers-embedded.jsonl", None),
    "distinguished": ("distinguished/questions", "progress-distinguished.json", "answers-distinguished.jsonl",
                      {(5,): 0.30, (1, 6, 10, 12): 0.60, (2, 4, 11): 0.10}),
    # A guess: no split was announced. Decision trees, K-Means and PCA are the topics flagged for the exam.
    "ai": ("ai/questions", "progress-ai.json", "answers-ai.jsonl",
           {(1,): 0.10, (2,): 0.17, (3,): 0.17, (4,): 0.20, (5,): 0.12, (6,): 0.24}),
}
BANK = HERE / "questions"
PROGRESS = HERE / "progress.json"
ANSWER_LOG = HERE / "answers.jsonl"  # one line per answered card, so mistakes can be reviewed later

BASE = [8.0, 4.0, 2.0, 1.0, 0.5, 0.25]  # pull of each box
GAP = [4, 10, 25, 60, 150, 400]         # cards shown before a box is "ready" again
FIRST_TRY_BOX = 3
MASTERED = 4
COOLDOWN = 10                           # no repeats within this many cards (missed ones: GAP[0])
# Share of the 33 exam questions per week. A guess: the study guide gives no split,
# so this follows how much of the guide each week fills (2 includes 2b).
EXAM_SHARE = {(0,): 0.10, (1,): 0.15, (2,): 0.20, (3,): 0.12, (4,): 0.15, (5,): 0.14, (6,): 0.14}
LETTERS = "abcd"

os.system("")  # turns on ANSI colours in the classic Windows console
BOLD, DIM, RED, GREEN, YELLOW, CYAN, RESET = (
    "\033[1m", "\033[2m", "\033[91m", "\033[92m", "\033[93m", "\033[96m", "\033[0m")


# ---------------------------------------------------------------- data

def load_cards() -> list[dict]:
    cards, seen = [], set()
    for path in sorted(BANK.glob("*.json")):
        try:
            items = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            print(f"{YELLOW}skipping {path.name}: {e}{RESET}")
            continue
        for c in items:
            if c.get("id") in seen or len(c.get("choices", [])) != 4:
                continue
            seen.add(c["id"])
            c["chnum"] = int(c["id"].split("-")[0][2:])
            c["week"] = f"{c['chnum']}b" if c["id"].split("-")[1].startswith("b") else str(c["chnum"])
            cards.append(c)
    return cards


def load_progress() -> dict:
    if PROGRESS.exists():
        try:
            return json.loads(PROGRESS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            backup = PROGRESS.with_suffix(".broken.json")
            PROGRESS.replace(backup)
            print(f"{YELLOW}progress.json was unreadable; moved it to {backup.name}{RESET}")
    return {"version": 1, "turn": 0, "recent": [], "cards": {}}


def log_answer(card: dict, chosen_text: str | None, right: bool, typo: bool = False) -> None:
    import datetime
    entry = {"time": datetime.datetime.now().isoformat(timespec="seconds"), "id": card["id"],
             "week": card.get("week", card["chnum"]), "topic": card["topic"], "kind": card.get("kind"),
             "q": card["q"], "picked": chosen_text, "answer": card["choices"][0],
             "result": "typo-knew-it" if typo else "right" if right else "shown" if chosen_text is None else "wrong"}
    with ANSWER_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------- sync between devices
# Only when this folder is its own git repo (the phone/PC sync repo). Pull on start, push on quit,
# so progress.json and answers.jsonl follow you between the laptop and Termux.

SYNC_FILES = [name for _, prog, log, _ in DECKS.values() for name in (prog, log)]


def git(*args: str, timeout: int = 30) -> bool:
    return git_out(*args, timeout=timeout) is not None


def git_out(*args: str, timeout: int = 30) -> bytes | None:
    import subprocess
    try:
        r = subprocess.run(["git", "-C", str(HERE), *args], capture_output=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return r.stdout if r.returncode == 0 else None


def read_progress_text(text: str) -> dict:
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        return {}


def answer_lines(text: str) -> list[str]:
    # Keeps only real log lines, so conflict markers from an old merge are dropped.
    return [l for l in text.splitlines() if l.startswith("{")]


def merge_progress(a: dict, b: dict) -> dict:
    """Card by card, keep the state with more attempts; turn = the larger."""
    tries = lambda s: -1 if s is None else s["right"] + s["wrong"]
    out = {"version": 1, "turn": max(a.get("turn", 0), b.get("turn", 0)),
           "recent": a.get("recent") or b.get("recent") or [], "cards": {}}
    for cid in sorted(set(a.get("cards", {})) | set(b.get("cards", {}))):  # stable order keeps git diffs small
        sa, sb = a.get("cards", {}).get(cid), b.get("cards", {}).get(cid)
        out["cards"][cid] = sa if tries(sa) >= tries(sb) else sb
    return out


def sync_pull() -> None:
    """Fetch GitHub's copy and merge it into this device's progress; git never merges these files."""
    if not (HERE / ".git").exists():
        return
    print(f"{DIM}Pulling progress from GitHub…{RESET}", flush=True)
    git("rebase", "--abort")  # leftovers from the first version of this script
    git("merge", "--abort")
    if not git("fetch", "-q", "origin"):
        print(f"{YELLOW}Couldn't pull (offline?). Using the progress on this device.{RESET}")
        return
    merged = {}  # every deck's files, so playing one deck never drops another deck's unpushed progress
    for _, prog_name, log_name, _ in DECKS.values():
        broken = Path(prog_name).with_suffix(".broken.json").name
        remote_prog = read_progress_text((git_out("show", f"origin/main:{prog_name}") or b"").decode("utf-8"))
        remote_ans = answer_lines((git_out("show", f"origin/main:{log_name}") or b"").decode("utf-8"))
        local_prog, local_ans = {}, []
        for name in (prog_name, broken):
            if (HERE / name).exists():
                local_prog = merge_progress(local_prog, read_progress_text((HERE / name).read_text(encoding="utf-8")))
        if (HERE / log_name).exists():
            local_ans = answer_lines((HERE / log_name).read_text(encoding="utf-8"))
        prog = merge_progress(local_prog, remote_prog)
        lines = sorted(set(local_ans) | set(remote_ans), key=lambda l: json.loads(l).get("time", ""))
        merged[prog_name] = json.dumps(prog, ensure_ascii=False, indent=0) if prog["cards"] else None
        merged[log_name] = "".join(l + "\n" for l in lines) if lines else None
        merged[broken] = None
    git("reset", "-q", "--hard", "origin/main")  # code and questions as on GitHub
    for name, text in merged.items():
        if text is not None:
            (HERE / name).write_text(text, encoding="utf-8")
        elif name.endswith(".broken.json"):
            (HERE / name).unlink(missing_ok=True)


def sync_push() -> None:
    if not (HERE / ".git").exists():
        return
    import datetime
    # A fresh git install (Termux) has no name/email, and then every commit fails.
    who = [] if git_out("config", "user.email") else ["-c", "user.name=quiz", "-c", "user.email=quiz@localhost"]
    for attempt in range(2):
        git("add", *[f for f in SYNC_FILES if (HERE / f).exists()])
        if not git("diff", "--cached", "--quiet") and \
                not git(*who, "commit", "-q", "-m", f"progress {datetime.datetime.now():%Y-%m-%d %H:%M}"):
            print(f"{YELLOW}Couldn't commit the progress. Saved on this device only.{RESET}")
            return
        print(f"{DIM}Pushing progress to GitHub…{RESET}", flush=True)
        if git("push", "-q", "origin", "HEAD:main"):
            print(f"{GREEN}Progress pushed.{RESET}")
            return
        if attempt == 0:
            sync_pull()  # the other device pushed in between: merge its progress in and try again
    print(f"{YELLOW}Couldn't push (offline or not logged in?). Saved here; it goes up next time you quit online.{RESET}")


def save_progress(prog: dict) -> None:
    tmp = PROGRESS.with_suffix(".tmp")
    tmp.write_text(json.dumps(prog, ensure_ascii=False, indent=0), encoding="utf-8")
    os.replace(tmp, PROGRESS)


# ---------------------------------------------------------------- scheduling

def topic_weights(cards: list[dict], prog: dict) -> dict[str, float]:
    """1.0 for a topic you always get right, up to 2.0 for one you always miss."""
    tally: dict[str, list[int]] = {}
    for c in cards:
        st = prog["cards"].get(c["id"])
        if st:
            t = tally.setdefault(c["topic"], [0, 0])
            t[0] += st["right"]
            t[1] += st["right"] + st["wrong"]
    return {topic: 2.0 - right / total for topic, (right, total) in tally.items() if total}


def chapter_weights(cards: list[dict]) -> dict[int, float]:
    """Per-card weight that gives each chapter group its exam share; averages 1.0."""
    if not EXAM_SHARE:
        return {}
    group_of = {ch: g for g in EXAM_SHARE for ch in g}
    sizes = collections.Counter(group_of.get(c["chnum"]) for c in cards)
    raw = {ch: EXAM_SHARE[g] / sizes[g] for g in EXAM_SHARE for ch in g if sizes[g]}
    mean = sum(raw.get(c["chnum"], 1.0) for c in cards) / len(cards)
    return {ch: w / mean for ch, w in raw.items()}


def weighted_choice(items: list[dict], weights: list[float]) -> dict:
    if sum(weights) <= 0:
        return random.choice(items)
    return random.choices(items, weights=weights, k=1)[0]


def course_order(c: dict) -> tuple:
    """Week 0 → 6 (2b after 2), and within a week the order the guide teaches it."""
    tail = c["id"].split("-")[1]
    return (c["chnum"], tail.startswith("b"), int(tail.lstrip("b")))


def pick(cards: list[dict], prog: dict, in_order: bool = True) -> dict:
    turn, states = prog["turn"], prog["cards"]
    tw = topic_weights(cards, prog)
    cw = chapter_weights(cards)

    # 1. Missed cards come back after GAP[0] cards, ahead of everything else.
    due = [c for c in cards if c["id"] in states and states[c["id"]]["box"] == 0
           and turn - states[c["id"]]["last"] >= min(GAP[0], len(cards) - 1)]
    if due and random.random() < 0.6:
        return min(due, key=lambda c: states[c["id"]]["last"])

    recent = set(prog["recent"][-min(COOLDOWN, len(cards) // 3):]) if len(cards) > 3 else set()
    pool = [c for c in cards if c["id"] not in recent] or cards
    new = [c for c in pool if c["id"] not in states]
    review = [c for c in pool if c["id"] in states]

    # 2. New vs review: ease off new cards while many are still shaky.
    learning = sum(1 for c in cards if c["id"] in states and states[c["id"]]["box"] <= 1)
    p_new = 0.6 if learning < 15 else 0.4 if learning < 30 else 0.2
    if new and (not review or random.random() < p_new):
        if in_order:
            return min(new, key=course_order)
        return weighted_choice(new, [cw.get(c["chnum"], 1.0) * tw.get(c["topic"], 1.0)
                                     for c in new])

    def review_weight(c: dict) -> float:
        st = states[c["id"]]
        ready = min(2.0, (turn - st["last"]) / GAP[st["box"]])
        return (BASE[st["box"]] * max(ready, 0.02)
                * cw.get(c["chnum"], 1.0) * tw.get(c["topic"], 1.0))

    return weighted_choice(review, [review_weight(c) for c in review])


def record(prog: dict, card: dict, right: bool) -> None:
    st = prog["cards"].setdefault(card["id"], {"box": 0, "right": 0, "wrong": 0, "last": 0})
    first_time = st["right"] + st["wrong"] == 0
    if right:
        st["right"] += 1
        st["box"] = FIRST_TRY_BOX if first_time else min(len(BASE) - 1, st["box"] + 1)
    else:
        st["wrong"] += 1
        st["box"] = 0
    st["last"] = prog["turn"]


# ---------------------------------------------------------------- terminal

def posix_key_reader():
    """One keypress without Enter on Linux / Termux / macOS."""
    try:
        import termios
        import tty
    except ImportError:
        return None
    fd = sys.stdin.fileno()

    def read() -> str:
        old = termios.tcgetattr(fd)
        try:
            tty.setcbreak(fd)  # keeps Ctrl+C working
            ch = sys.stdin.read(1)
            if ch == "\x1b":  # arrow keys etc.: swallow the rest of the sequence
                sys.stdin.read(2)
                return ""
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)
        return "enter" if ch in ("\r", "\n") else ch.lower()
    return read


def single_key_reader():
    if not sys.stdin.isatty():
        return None
    if os.name != "nt":
        return posix_key_reader()
    try:
        import msvcrt
    except ImportError:
        return None

    def read() -> str:
        while True:
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):  # arrow / function key: swallow its second half
                msvcrt.getwch()
                continue
            if ch == "\x03":
                raise KeyboardInterrupt
            return "enter" if ch in ("\r", "\n") else ch.lower()
    return read


READ_KEY = single_key_reader()


def get_key(valid: str) -> str:
    """Return 'enter' or one character from `valid`. Digits 1-4 map to a-d."""
    while True:
        if READ_KEY:
            k = READ_KEY()
        else:
            s = input(f"{DIM}> {RESET}").strip().lower()
            k = "enter" if not s else s[0]
        if k in ("1", "2", "3", "4"):
            k = LETTERS[int(k) - 1]
        if k == "enter" or k in valid:
            return k


def width() -> int:
    return max(40, min(100, shutil.get_terminal_size((90, 30)).columns - 2))


def wrap(text: str, indent: str = " ", hang: str | None = None) -> str:
    return textwrap.fill(text, width(), initial_indent=indent,
                         subsequent_indent=hang if hang is not None else indent)


def status_tag(st: dict | None) -> str:
    if st is None:
        tag = f"{CYAN}NEW{RESET}"
    elif st["box"] == 0:
        tag = f"{RED}MISSED BEFORE{RESET}"
    elif st["box"] >= MASTERED:
        tag = f"{GREEN}MASTERED{RESET}"
    else:
        tag = f"{YELLOW}REVIEW{RESET}"
    return tag


def draw(card: dict, order: list[int], prog: dict, cards: list[dict], session: dict, tag: str,
         chosen: int | None = None, done: bool = False) -> None:
    states = prog["cards"]
    mastered = sum(1 for c in cards if states.get(c["id"], {}).get("box", 0) >= MASTERED)
    seen = sum(1 for c in cards if c["id"] in states)

    print("\033[2J\033[H", end="")
    print(f" {DIM}{card['chapter']} · {card['topic']}{RESET}   {tag}")
    print(f" {DIM}session {session['n']} ({session['right']} right) · seen {seen}/{len(cards)}"
          f" · mastered {mastered}/{len(cards)}{RESET}")
    print(" " + "─" * (width() - 1))
    print(BOLD + wrap(card["q"]) + RESET + "\n")

    for pos, idx in enumerate(order):
        text = wrap(f"{LETTERS[pos]}) {card['choices'][idx]}", "   ", "      ")
        if done and idx == 0:
            text = GREEN + BOLD + text + RESET
        elif done and pos == chosen:
            text = RED + text + RESET
        elif done:
            text = DIM + text + RESET
        print(text)
    print()


# ---------------------------------------------------------------- game

def play(cards: list[dict], prog: dict, in_order: bool = True) -> None:
    session = {"n": 0, "right": 0, "new": 0,
               "mastered_before": sum(1 for c in cards
                                      if prog["cards"].get(c["id"], {}).get("box", 0) >= MASTERED)}
    try:
        while True:
            card = pick(cards, prog, in_order)
            order = [0, 1, 2, 3]
            random.shuffle(order)
            tag = status_tag(prog["cards"].get(card["id"]))
            draw(card, order, prog, cards, session, tag)
            print(f" {DIM}a-d answer · Enter show · q quit{RESET}")

            k = get_key("abcdq")
            if k == "q":
                break
            before = dict(prog["cards"].get(card["id"], {})) or None
            chosen = None if k == "enter" else LETTERS.index(k)
            right = chosen is not None and order[chosen] == 0

            prog["turn"] += 1
            prog["recent"] = (prog["recent"] + [card["id"]])[-50:]
            record(prog, card, right)
            save_progress(prog)
            log_answer(card, None if chosen is None else card["choices"][order[chosen]], right)
            session["n"] += 1
            session["right"] += right
            session["new"] += before is None

            draw(card, order, prog, cards, session, tag, chosen=chosen, done=True)
            answer = f"{LETTERS[order.index(0)]}) {card['choices'][0]}"
            if right:
                print(f" {GREEN}{BOLD}CORRECT{RESET}")
            elif chosen is None:
                print(f" {YELLOW}{BOLD}Answer:{RESET} {GREEN}{answer}{RESET}")
            else:
                print(f" {RED}{BOLD}WRONG{RESET}  answer: {GREEN}{answer}{RESET}")
            print(wrap(card["why"]))
            if card.get("source"):
                print(f" {DIM}{card['source']}{RESET}")
            hint = "Enter next · q quit" + ("" if right else " · k typo, I knew it")
            print(f"\n {DIM}{hint}{RESET}")

            k = get_key("q" if right else "qk")
            if k == "k":
                # Undo the miss and count it as a right answer instead.
                if before is None:
                    del prog["cards"][card["id"]]
                else:
                    prog["cards"][card["id"]] = before
                record(prog, card, True)
                save_progress(prog)
                log_answer(card, None if chosen is None else card["choices"][order[chosen]], True, typo=True)
                session["right"] += 1
            elif k == "q":
                break
    except (KeyboardInterrupt, EOFError):
        pass
    save_progress(prog)

    mastered = sum(1 for c in cards if prog["cards"].get(c["id"], {}).get("box", 0) >= MASTERED)
    pct = f"{100 * session['right'] // session['n']}%" if session["n"] else "-"
    print(f"\n {BOLD}Session:{RESET} {session['n']} cards · {session['right']} right ({pct})"
          f" · {session['new']} new · mastered {mastered}/{len(cards)}"
          f" (+{mastered - session['mastered_before']})")
    print(f" {DIM}Progress saved to {PROGRESS.name}.{RESET}\n")


def stats(cards: list[dict], prog: dict) -> None:
    states = prog["cards"]
    chapters: dict[str, list[dict]] = {}
    for c in cards:
        chapters.setdefault(c["chapter"], []).append(c)

    print(f"\n {BOLD}{'Chapter':34} {'cards':>5} {'seen':>5} {'mastered':>8} {'accuracy':>8}{RESET}")
    for name, cs in sorted(chapters.items(), key=lambda kv: kv[1][0]["chnum"]):
        sts = [states[c["id"]] for c in cs if c["id"] in states]
        right = sum(s["right"] for s in sts)
        total = right + sum(s["wrong"] for s in sts)
        mastered = sum(1 for s in sts if s["box"] >= MASTERED)
        acc = f"{100 * right // total}%" if total else "-"
        print(f" {name:34} {len(cs):>5} {len(sts):>5} {mastered:>8} {acc:>8}")

    weak = []
    for topic, w in topic_weights(cards, prog).items():
        attempts = sum(states[c["id"]]["right"] + states[c["id"]]["wrong"]
                       for c in cards if c["topic"] == topic and c["id"] in states)
        if attempts >= 3 and w > 1.0:
            weak.append((w, topic, attempts))
    if weak:
        print(f"\n {BOLD}Weakest topics{RESET} (3+ attempts)")
        for w, topic, attempts in sorted(weak, reverse=True)[:12]:
            print(f"   {100 - round(100 * (w - 1)):>3}%  {topic}  {DIM}({attempts} tries){RESET}")
    print()


def main(argv: list[str]) -> None:
    global BANK, PROGRESS, ANSWER_LOG, EXAM_SHARE
    if "--deck" in argv:
        i = argv.index("--deck")
        name = argv[i + 1] if i + 1 < len(argv) else ""
        if name not in DECKS:
            sys.exit(f"--deck takes one of: {', '.join(DECKS)}")
        folder, prog_name, log_name, EXAM_SHARE = DECKS[name]
        BANK, PROGRESS, ANSWER_LOG = HERE / folder, HERE / prog_name, HERE / log_name
        argv = argv[:i] + argv[i + 2:]
    if not (argv and argv[0] == "reset"):
        sync_pull()
    cards = load_cards()
    if not cards:
        sys.exit(f"No questions found in {BANK}")
    prog = load_progress()

    if argv and argv[0] == "stats":
        return stats(cards, prog)
    if argv and argv[0] == "reset":
        if input("Wipe all progress? type yes: ").strip().lower() == "yes":
            PROGRESS.unlink(missing_ok=True)
            print("Progress wiped.")
        return

    weeks = {a.lower() for a in argv if a.isdigit() or a.lower() in ("2b",)}
    if weeks:
        cards = [c for c in cards if str(c["chnum"]) in weeks or c["week"] in weeks]
    if "--missed" in argv:
        cards = [c for c in cards if prog["cards"].get(c["id"], {}).get("box", 99) <= 1]
    if not cards:
        sys.exit("Nothing to ask with those filters.")
    play(cards, prog, in_order="--mix" not in argv)
    sync_push()


if __name__ == "__main__":
    main(sys.argv[1:])
