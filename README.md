# Deep Learning for Computer Vision: midterm flashcards

A terminal flashcard game for the Inha Tashkent SOC4180 ("Robot and AI") midterm: 33 MCQ, 60 min, no calculator,
weeks 0–6. **600 cards** written from Prof. Jeong Hong's study guide and week decks: hand calculations, traps and
numbers worth knowing, each with an explanation.

This repo also carries my progress (`progress.json`, `answers.jsonl`), so I can carry on between my laptop and my
phone. **The quiz pulls when it starts and pushes when you quit with `q` or Ctrl+C.** Closing the window or the
app without quitting skips the push.

## Run it

```bash
python quiz.py            # new cards in course order, week 0 → 6; misses come back
python quiz.py 2          # only week 2 (and 2b); `2b` alone for 2b
python quiz.py --mix      # random order weighted by exam share
python quiz.py --missed   # only what you got wrong
python quiz.py stats      # progress per week
python quiz.py --deck embedded        # other decks: embedded, distinguished, ai (dl is the default)
```

**Web version, no install:** https://iut-midterm-flashcards.vercel.app (progress saved in your browser).

Windows: `quiz.bat`. Termux / Linux: `./quiz.sh`.

Keys: `a`–`d` (or `1`–`4`) answer · Enter shows the answer · after the answer, Enter goes on and `k` marks
"typo, I knew it" · `q` quits (and pushes).

## Termux setup (once)

```bash
pkg install git python gh
gh auth login
gh auth setup-git
git clone https://github.com/kamol1dn/dlcv-midterm-quiz
cd dlcv-midterm-quiz && chmod +x quiz.sh && ./quiz.sh
```

Want to use it yourself? Fork it and delete `progress.json` and `answers.jsonl` to start clean.
