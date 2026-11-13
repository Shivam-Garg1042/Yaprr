"""Word error rate (WER) for speech-to-text providers on your own recorded clips.

WER = (substitutions + deletions + insertions) / words in the correct transcript.
  reference : "kal paanch hazaar de dunga"        (5 words)
  STT heard : "kal paanch hazaar dunga"           -> 1 deletion ("de")
  WER = 1 / 5 = 20%. Lower is better; 0% is perfect.

Why it matters here: if STT hears "pachchees" as "pachaas", the agent logs the
wrong date. WER on *your* audio (Hinglish, phone mic, traffic noise) beats any
vendor benchmark.

Setup:
  evals/wer_clips/clips.csv        file,reference
                                   001.wav,मैं कल पाँच हज़ार दे दूँगा
  evals/wer_clips/001.wav ...      16 kHz mono WAV, 3-10 s each

Write each reference the way the STT should write it (Hindi in Devanagari, English
words in Latin, numbers as spoken words). Script mismatches count as errors, so
be consistent.

    python -m evals.wer                      # all providers with a key set
    python -m evals.wer --providers deepgram

Keys: DEEPGRAM_API_KEY, SARVAM_API_KEY. Sarvam model/mode via SARVAM_MODEL (default saaras:v3)
and SARVAM_MODE (default codemix); per Sarvam's docs, `mode` applies to saaras:v3.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import unicodedata
from datetime import datetime
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()
HERE = Path(__file__).resolve().parent
CLIPS = HERE / "wer_clips"


def normalize(text: str) -> list[str]:
    text = unicodedata.normalize("NFC", text.lower())
    text = text.replace("़", "")  # nukta: ज़/ज are the same word to a listener
    text = re.sub(r"[^\w\s]|_", " ", text)  # punctuation, including the danda (।)
    return text.split()


def edit_counts(ref: list[str], hyp: list[str]) -> tuple[int, int, int]:
    """(substitutions, deletions, insertions) from a word-level Levenshtein alignment."""
    rows, cols = len(ref) + 1, len(hyp) + 1
    d = [[(0, 0, 0, 0)] * cols for _ in range(rows)]  # (cost, sub, del, ins)
    for i in range(1, rows):
        d[i][0] = (i, 0, i, 0)
    for j in range(1, cols):
        d[0][j] = (j, 0, 0, j)
    for i in range(1, rows):
        for j in range(1, cols):
            if ref[i - 1] == hyp[j - 1]:
                d[i][j] = d[i - 1][j - 1]
                continue
            s, de, ins = d[i - 1][j - 1], d[i - 1][j], d[i][j - 1]
            d[i][j] = min((s[0] + 1, s[1] + 1, s[2], s[3]), (de[0] + 1, de[1], de[2] + 1, de[3]),
                          (ins[0] + 1, ins[1], ins[2], ins[3] + 1))
    _, sub, dele, ins = d[-1][-1]
    return sub, dele, ins


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = normalize(reference), normalize(hypothesis)
    return sum(edit_counts(ref, hyp)) / max(len(ref), 1)


def deepgram(path: Path) -> str:
    params = {"model": os.getenv("DEEPGRAM_MODEL", "nova-3"), "language": os.getenv("STT_LANGUAGE", "hi")}
    r = httpx.post("https://api.deepgram.com/v1/listen", params=params, content=path.read_bytes(), timeout=60,
                   headers={"Authorization": f"Token {os.environ['DEEPGRAM_API_KEY']}", "Content-Type": "audio/wav"})
    r.raise_for_status()
    return r.json()["results"]["channels"][0]["alternatives"][0]["transcript"]


def sarvam(path: Path) -> str:
    data = {"model": os.getenv("SARVAM_MODEL", "saaras:v3"), "mode": os.getenv("SARVAM_MODE", "codemix"),
            "language_code": os.getenv("SARVAM_LANGUAGE", "hi-IN")}
    with path.open("rb") as f:
        r = httpx.post("https://api.sarvam.ai/speech-to-text", data=data, timeout=60,
                       files={"file": (path.name, f, "audio/wav")},
                       headers={"api-subscription-key": os.environ["SARVAM_API_KEY"]})
    r.raise_for_status()
    return r.json()["transcript"]


PROVIDERS = {"deepgram": ("DEEPGRAM_API_KEY", deepgram), "sarvam": ("SARVAM_API_KEY", sarvam)}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--providers", default="", help="comma-separated; default: every provider with a key")
    args = ap.parse_args()
    clips = list(csv.DictReader((CLIPS / "clips.csv").open(encoding="utf-8")))
    names = args.providers.split(",") if args.providers else [n for n, (k, _) in PROVIDERS.items() if os.getenv(k)]
    report: dict[str, dict] = {}
    for name in names:
        fn = PROVIDERS[name][1]
        errors = words = 0
        rows = []
        for c in clips:
            try:
                hyp = fn(CLIPS / c["file"])
            except Exception as exc:  # noqa: BLE001
                hyp = ""
                print(f"  {name} {c['file']}: {exc}")
            ref = normalize(c["reference"])
            e = sum(edit_counts(ref, normalize(hyp)))
            errors, words = errors + e, words + len(ref)
            rows.append({"file": c["file"], "reference": c["reference"], "heard": hyp, "wer": round(e / max(len(ref), 1), 3)})
        report[name] = {"wer": errors / max(words, 1), "clips": rows}
        print(f"{name:<10} WER {report[name]['wer'] * 100:.1f}%  ({errors} errors / {words} words, {len(clips)} clips)")
    out = HERE / "results" / f"{datetime.now():%Y%m%d-%H%M}_wer.json"
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Saved {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
