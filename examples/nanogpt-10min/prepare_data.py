"""Build the byte-level corpus this hill trains and scores on.

The text is synthesized from a seeded word-bigram chain rather than downloaded,
so the example is fully offline and identical on every machine. A real hill
would point at real data here; everything else about the hill is unchanged.

    python prepare_data.py

Writes data/train.bin (public) and private/data/{val,test}.bin (held out).
Tokens are one byte each, stored as uint16, so bits-per-byte and
bits-per-token are the same number.
"""

import random
from pathlib import Path

import numpy as np

HILL = Path(__file__).resolve().parent
TRAIN_BYTES = 4 * 1024 * 1024
HELDOUT_BYTES = 256 * 1024
SEED = 20260809

CONSONANTS = "bcdfghklmnprstvwz"
VOWELS = "aeiou"
LEXICON_SIZE = 512
SUCCESSORS = 6


def build_lexicon(rng: random.Random) -> list[str]:
    words = set()
    while len(words) < LEXICON_SIZE:
        syllables = rng.randint(1, 3)
        word = "".join(
            rng.choice(CONSONANTS) + rng.choice(VOWELS) + rng.choice("" + CONSONANTS[:6])
            for _ in range(syllables)
        )
        words.add(word)
    return sorted(words)


def build_chain(rng: random.Random, size: int) -> list[list[int]]:
    """Each word may be followed by a small fixed set of others."""
    return [
        [rng.randrange(size) for _ in range(SUCCESSORS)] for _ in range(size)
    ]


def generate(n_bytes: int, rng: random.Random, lexicon, chain) -> bytes:
    pieces = []
    total = 0
    current = rng.randrange(len(lexicon))
    while total < n_bytes:
        sentence = []
        for _ in range(rng.randint(4, 14)):
            sentence.append(lexicon[current])
            current = rng.choice(chain[current])
        text = " ".join(sentence).capitalize() + rng.choice([".", ".", ".", "?", "!"]) + " "
        pieces.append(text)
        total += len(text)
    return "".join(pieces).encode("utf-8")[:n_bytes]


def write_split(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.frombuffer(data, dtype=np.uint8).astype(np.uint16).tofile(path)
    print(f"  {path.relative_to(HILL)}  {len(data):,} tokens")


def main() -> None:
    rng = random.Random(SEED)
    lexicon = build_lexicon(rng)
    chain = build_chain(rng, len(lexicon))

    print(f"vocabulary: {len(lexicon)} words, {SUCCESSORS} successors each")
    write_split(HILL / "data" / "train.bin", generate(TRAIN_BYTES, rng, lexicon, chain))
    write_split(HILL / "private" / "data" / "val.bin", generate(HELDOUT_BYTES, rng, lexicon, chain))
    write_split(HILL / "private" / "data" / "test.bin", generate(HELDOUT_BYTES, rng, lexicon, chain))
    print("\nNow run: hills check nanogpt-10min")


if __name__ == "__main__":
    main()
