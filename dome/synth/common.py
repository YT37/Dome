"""Small helpers shared by the synthetic data generator, the checker and tests.

Nothing here touches the network. Everything is plain Python so it is easy to explain.
"""

import json
import math
import re
from pathlib import Path

HERE = Path(__file__).parent

# A post pair whose masked word-trigrams overlap at least this much shares a "text" key.
TEXT_KEY_JACCARD = 0.5

# Words that must never appear anywhere in the synthetic data (safety check, not a filter).
BANNED_WORDS = [
    "sex", "sexy", "escort", "nude", "naked", "xxx", "adult", "erotic", "intimate",
    "young", "teen", "teens", "girl", "girls", "minor", "school", "barely", "petite",
    "fresh", "babe", "hot", "massage", "outcall", "incall",
]

_NUMBER_WORDS = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
}


def load_json(path):
    with open(path) as f:
        return json.load(f)


def save_json(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        json.dump(data, f, indent=2, sort_keys=False)
        f.write("\n")


def load_gazetteer():
    return load_json(HERE / "gazetteer.json")


def load_buildings():
    return load_json(HERE / "buildings.json")


def km_between(lat1, lon1, lat2, lon2):
    """Great-circle distance in km (haversine)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def offset_point(lat, lon, dx_km, dy_km):
    """Move a point dx km east and dy km north."""
    new_lat = lat + dy_km / 110.574
    new_lon = lon + dx_km / (111.320 * math.cos(math.radians(lat)))
    return round(new_lat, 5), round(new_lon, 5)


def normalize_phone(raw):
    """Turn disguised phones like 'five5five-O142' into '555-0142'."""
    s = raw.lower()
    for word, digit in _NUMBER_WORDS.items():
        s = s.replace(word, digit)
    s = s.replace("o", "0")
    digits = re.sub(r"\D", "", s)
    if len(digits) < 7:
        return None
    digits = digits[-7:]
    return f"{digits[:3]}-{digits[3:]}"


def mask_text(text, phones, place_names):
    """Lowercase, replace phones/places/digits with placeholders, drop punctuation."""
    s = text
    for p in phones:
        s = s.replace(p, " PHONE ")
    for name in sorted(place_names, key=len, reverse=True):
        s = s.replace(name, " PLACE ")
    s = s.lower()
    s = re.sub(r"\d+", "#", s)
    s = re.sub(r"[^a-z#\s]", " ", s)
    return s.split()


def trigrams(words):
    return frozenset(tuple(words[i:i + 3]) for i in range(len(words) - 2))


def jaccard(a, b):
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
