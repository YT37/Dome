"""Writes a small SYNTHETIC dataset for building and testing the Linker before Ishaan's
full generator lands. Same shape as the full dataset (handoff section 6).

Everything is invented: account handles, 555 phone numbers, ad text, photo hashes.
Photo ids and paths line up with samples/scenarios/, so the whole pipeline runs on it.

Run:  python samples/data/make_mini.py
Out:  samples/data/mini/{accounts,posts,interactions,answer_key}.json
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent / "mini"
rng = random.Random(7)
T0 = datetime(2026, 10, 1, 9, 0, 0)

accounts, posts, interactions = [], [], []
answer = {"rings": {}, "hard_negatives": {}}


def ts(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def phash(seed: str) -> str:
    return f"{random.Random(seed).getrandbits(64):016x}"


def account(handle, bio="", created="2025-03-01", flags=()):
    accounts.append({"handle": handle, "display_name": f"Synthetic {handle}", "bio": bio,
                     "created": created, "last_active": "2026-11-12", "flags": list(flags)})


def post(acct, text, when, photos=(), phones=(), area="", area_code="", landmarks=()):
    pid = f"post_{len(posts) + 1:04d}"
    posts.append({"post_id": pid, "account": acct, "text": text, "time": ts(when),
                  "photos": list(photos), "phones": list(phones), "stated_area": area,
                  "area_code": area_code, "landmarks": list(landmarks)})
    return pid


def photo(pid: str, window=False, hash_seed=None):
    return {"photo_id": pid, "path": f"data/photos/{pid}.jpg", "phash": phash(hash_seed or pid),
            "has_window": window}


def interact(a, b, kind, when, post_id=None):
    interactions.append({"from": a, "to": b, "kind": kind, "time": ts(when), "post": post_id})


# ------------------------------------------------------------------ Ring A
# 4 posters (one phone, one script with rewordings, shared photos), 3 recruiters, 5 amplifiers.
A_SCRIPT = [
    "New in town and available all this week. Sweet and discreet, private apartment near midtown. "
    "Text {p} to book your visit, ask for {n}.",
    "new in town & available all this week!! sweet and discreet, private apartment near midtown. "
    "text {p} to book your visit, ask for {n}",
    "Just arrived in the city and free every day this week. Discreet and friendly, my own flat "
    "close to midtown. Message {p} to arrange a time, {n} will answer.",
]
A_PHONES = ["555-0142", "five5five 0142", "(713) 555 0142", "5 5 5 - 0 1 4 2"]
A_POSTERS = ["acct_017", "acct_102", "acct_118", "acct_131"]
A_RECRUITERS = ["acct_233", "acct_234", "acct_235"]
A_AMPS = ["acct_241", "acct_242", "acct_243", "acct_244", "acct_245"]
for h in A_POSTERS:
    account(h, "dm for bookings", "2026-08-02", ["ad_pattern"])
for h in A_RECRUITERS:
    account(h, "Modelling agency. Job offers for new faces, travel paid.", "2026-08-02",
            ["recruiter_pattern"])
for h in A_AMPS:
    account(h, "", "2026-08-02", ["amplifier_pattern"])   # batch-created with the rest

a_photos = [photo(f"img_{311 + i}", window=i < 3) for i in range(9)]
a_posts = []
for i in range(28):
    h = A_POSTERS[i % 4]
    # acct_131 only ever uses the reworded script: MinHash misses it, embeddings catch it
    tmpl = A_SCRIPT[2] if h == "acct_131" else A_SCRIPT[i % 2]
    when = T0 + timedelta(days=i // 4, hours=(i % 4) * 2, minutes=rng.randint(0, 20))
    pid = post(h, tmpl.format(p=A_PHONES[i % 4], n=rng.choice(["Mia", "Lena", "Kay"])), when,
               photos=[a_photos[i % 9], a_photos[(i + 4) % 9]], area="Midtown", area_code="713",
               landmarks=["Midtown Park"] if i % 3 == 0 else [])
    a_posts.append((pid, h, when))
for i, (pid, owner, when) in enumerate(a_posts[:20]):
    for j, amp in enumerate(A_AMPS):          # amplifiers repost the same ad within the hour
        if (i + j) % 2 == 0:
            interact(amp, owner, "repost", when + timedelta(minutes=5 + 7 * j), pid)
    rec = A_RECRUITERS[i % 3]                  # recruiters reply into the ring
    interact(rec, owner, "reply", when + timedelta(minutes=30), pid)
    interact(rec, A_POSTERS[(i + 1) % 4], "repost", when + timedelta(minutes=40), pid)
for i in range(6):                             # posters repost each other
    interact(A_POSTERS[i % 4], A_POSTERS[(i + 1) % 4], "repost", T0 + timedelta(days=i, hours=5))
    interact(A_POSTERS[(i + 2) % 4], A_POSTERS[i % 4], "reply", T0 + timedelta(days=i, hours=6))
answer["rings"]["A"] = {"members": A_POSTERS + A_RECRUITERS + A_AMPS,
                        "recruiters": A_RECRUITERS, "building": "CS-88412", "scan": "mp_4471",
                        "unit": "4C", "scenario": "ring_a"}

# an ordinary Midtown resident: same area as Ring A, nothing else (must stay unlinked)
account("acct_404", "midtown foodie", "2025-01-14")
post("acct_404", "Best tacos near Midtown Park, go before noon.", T0 + timedelta(days=2),
     photos=[photo("img_390"), photo("img_391")], area="Midtown", area_code="713")

# ------------------------------------------------------------------ Ring B
# 8 accounts, one phone + one payment tag, one script, two areas, photos from two buildings.
B = [f"acct_5{n:02d}" for n in (1, 2, 3, 4, 17, 18, 30, 31)]
B_SCRIPT = ("Weekend specials, limited slots. Cozy private room, easy parking, no rush. "
            "Deposit to $bcash77 then call {p}. {a} side.")
for h in B:
    account(h, "serious inquiries only", "2026-06-20" if h < "acct_517" else "2026-06-21",
            ["ad_pattern"])
b_photos = [photo(f"img_{601 + i}", window=i < 4) for i in range(8)]
b_posts = []
for i in range(24):
    h = B[i % 8]
    side = "Montrose" if i % 8 < 4 else "Northside"
    when = T0 + timedelta(days=3 + i // 8, hours=i % 8, minutes=rng.randint(0, 15))
    pid = post(h, B_SCRIPT.format(p=["555-0177", "five five five 0177"][i % 2], a=side), when,
               photos=[b_photos[i % 8]], area=side, area_code="713" if side == "Montrose" else "832",
               landmarks=["Westheimer mural"] if side == "Montrose" and i % 2 else [])
    b_posts.append((pid, h, when))
for i, (pid, owner, when) in enumerate(b_posts):
    for k in (1, 2):
        interact(B[(B.index(owner) + k) % 8], owner, "repost", when + timedelta(minutes=10 * k), pid)
answer["rings"]["B"] = {"members": B, "recruiters": [], "building": ["CS-51010", "CS-52070"],
                        "scan": ["mp_5101", "mp_5207"], "scenario": "ring_b"}

# ------------------------------------------------------------------ Ring C
# 6 accounts, NO shared phone. Every account rewords the script, clues are city-wide,
# no window photos. One outside account shares a single photo (a weak hint).
C = [f"acct_70{n}" for n in range(1, 7)]
C_SCRIPT = [
    "Visiting Houston for a short while, evenings only. Quiet place, relaxed company, "
    "serious people only. Send a direct message to set up a time.",
    "In Houston for a short time, evenings only. A quiet spot and relaxed company, "
    "only serious people please. Direct message me to set up a time.",
    "Staying in Houston briefly and only free in the evenings. Calm location, easygoing company, "
    "no time wasters. DM to schedule.",
    "Here in Houston for a few days, free evenings only. Peaceful place and laid back company, "
    "serious inquiries only. Message directly to arrange a time.",
    "Short stay in Houston, available evenings. Quiet setting, relaxed company, genuine people "
    "only. Send me a direct message and we will set a time.",
    "Briefly in Houston, evenings only. Quiet and relaxed, serious people only. "
    "Direct message to book a time.",
]
for h in C:
    account(h, "", "2026-09-03", ["ad_pattern"])
c_photos = [photo(f"img_{801 + i}") for i in range(5)]
c_posts = []
for i in range(18):
    h = C[i % 6]
    when = T0 + timedelta(days=6 + i // 6, hours=19, minutes=(i % 6) * 2)   # lockstep evenings
    pid = post(h, C_SCRIPT[i % 6], when, photos=[c_photos[i % 5]], area="Houston")
    c_posts.append((pid, h, when))
for i, (pid, owner, when) in enumerate(c_posts):
    interact(C[(C.index(owner) + 1) % 6], owner, "repost", when + timedelta(minutes=12), pid)
    interact(C[(C.index(owner) + 3) % 6], owner, "reply", when + timedelta(minutes=25), pid)
answer["rings"]["C"] = {"members": C, "recruiters": [], "building": "CS-60030", "scan": "mp_6003",
                        "scenario": "ring_c"}

account("acct_744", "room for rent, flexible", "2024-11-02")
post("acct_744", "Spare room available, flexible dates, utilities included.", T0 + timedelta(days=7),
     photos=[photo("img_890", hash_seed="img_802"),    # the same picture as a Ring C photo
             photo("img_850"), photo("img_851"), photo("img_852")], area="Houston")

# ------------------------------------------------------------------ hard negatives
# Rental hosts: reuse the same listing photos in the same area. Photo + place, nothing else.
hosts = [f"host_{i:02d}" for i in range(1, 7)]
listing = [photo(f"img_list_{i}") for i in range(4)]
for i, h in enumerate(hosts):
    account(h, "short term rentals", f"2024-0{1 + i}-15")
    for k in range(3):
        post(h, rng.choice(["Bright one bedroom, walk to the park, weekly discount.",
                            "Renovated studio, fast wifi, self check in.",
                            "Two bed with balcony, great for families, pets ok."]),
             T0 + timedelta(days=k * 3 + i, hours=11), photos=[listing[(i + k) % 4]],
             area="Montrose", area_code="713")
answer["hard_negatives"]["rental_hosts"] = hosts

# Spa chain: one script and one front-desk phone on every branch account. No interactions.
spas = [f"spa_{i:02d}" for i in range(1, 7)]
for i, h in enumerate(spas):
    account(h, "Licensed day spa, walk ins welcome", f"2023-{3 + i:02d}-10")
    for k in range(4):
        post(h, "Licensed day spa open daily. Deep tissue, hot stone and facials by certified "
                "staff. Call 555-0199 or book online, gift cards available.",
             T0 + timedelta(days=k * 2, hours=8 + i, minutes=17 * i),
             phones=["555-0199"], area=["Heights", "Galleria", "Katy"][i % 3])
answer["hard_negatives"]["spa_chain"] = spas

# Delivery driver: posts from every neighbourhood. Place only.
account("driver_01", "on the road all day", "2024-05-05")
for i, area in enumerate(["Midtown", "Montrose", "Northside", "Heights", "Galleria", "Katy",
                          "Houston", "Midtown", "Montrose", "Northside"]):
    post("driver_01", f"Drop number {i + 1} done, traffic is wild today.", T0 + timedelta(days=i, hours=13),
         area=area, landmarks=["Midtown Park"] if area == "Midtown" else [])
answer["hard_negatives"]["delivery_driver"] = ["driver_01"]

# Friend groups: lots of replies to each other and the same neighbourhood. No shared content.
friend_groups = []
for g, area in enumerate(["Heights", "Midtown"]):
    grp = [f"friend_{g}{i}" for i in range(5)]
    friend_groups += grp
    for i, h in enumerate(grp):
        account(h, rng.choice(["coffee and dogs", "runner", "plant parent", "sports fan"]),
                f"20{22 + i % 3}-{1 + (3 * i + g) % 12:02d}-{5 + 4 * i:02d}")
        for k in range(3):
            post(h, rng.choice(["Brunch was unreal this morning.", "Who is up for trivia on Thursday?",
                                "Finally finished that puzzle.", "Game night at mine, bring snacks.",
                                "Long run by the bayou today."]) + f" ({h[-2:]}{k})",
                 T0 + timedelta(days=k * 2 + i, hours=10 + 2 * i, minutes=13 * i + g), area=area)
    for i in range(20):
        a, b = rng.sample(grp, 2)
        interact(a, b, "reply", T0 + timedelta(days=i % 9, hours=15 + g, minutes=i))
answer["hard_negatives"]["friend_groups"] = friend_groups

# ------------------------------------------------------------------ background
AREAS = ["Midtown", "Montrose", "Northside", "Heights", "Galleria", "Katy", "Houston", ""]
CHATTER = ["Anyone know a good mechanic around here?", "The sunset tonight was incredible.",
           "Selling a barely used bike, message me.", "Trying a new recipe for dinner tonight.",
           "Looking for a study group for the certification exam.", "My cat knocked over the plant again.",
           "Great turnout at the farmers market this weekend.", "Road work on the main street again.",
           "Finished my first ten kilometre race.", "Open mic at the corner cafe on Friday."]
account("city_news", "Local news and events", "2019-01-01")           # the account everyone reposts
for k in range(6):
    post("city_news", f"Weekend events roundup number {k + 1}: markets, music and road closures.",
         T0 + timedelta(days=k * 2, hours=7), area="Houston")
bg = [f"user_{i:03d}" for i in range(1, 81)]
for i, h in enumerate(bg):
    account(h, "", f"20{20 + i % 6}-{1 + i % 12:02d}-{1 + (i * 11) % 28:02d}")
    for k in range(rng.randint(1, 3)):
        post(h, rng.choice(CHATTER) + f" [{i}-{k}]",
             T0 + timedelta(days=rng.randint(0, 12), hours=rng.randint(6, 23), minutes=rng.randint(0, 59)),
             area=rng.choice(AREAS), area_code=rng.choice(["713", "832", "281"]))
    if i % 2 == 0:
        interact(h, "city_news", "repost", T0 + timedelta(days=i % 12, hours=8, minutes=i % 50))
    if i % 5 == 0:
        interact(h, rng.choice(bg), "follow", T0 + timedelta(days=i % 12))

if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    for name, data in [("accounts", accounts), ("posts", posts), ("interactions", interactions),
                       ("answer_key", answer)]:
        (OUT / f"{name}.json").write_text(json.dumps(data, indent=1), encoding="utf-8")
    print(f"wrote {OUT}: {len(accounts)} accounts, {len(posts)} posts, {len(interactions)} interactions")
