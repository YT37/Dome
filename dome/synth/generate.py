"""Synthetic data generator for Dome.

    python -m dome.synth.generate --out data/synth --seed 37

Writes accounts.json, posts.json, interactions.json and renders.json to --out, and the answer
key to data/answer_key/answer_key.json.

IMPORTANT: agents must NEVER read data/answer_key/. It exists only for the checker and for
scoring (briefer --answer-key). Nothing in the pipeline may open it.

Everything here is synthetic: made-up handles, "Platform X", 555 phone numbers only, and
bland, neutral ad text. Same seed -> byte-identical output.

Groups:
  Ring A   12 accounts / 90 posts + 3 recruiters + 5 amplifiers, clues around Building A
           (the demo is one ring; decoy D is a scanned building inside Ring A's zone)
  Hard negatives (~150), each sharing at most ONE kind of key with anything:
     rental hosts (photo key), spa chain (text key), delivery drivers (none, clues everywhere),
     friend groups (interaction key), independents (nothing)
  Background (~600) ordinary accounts
"""

import argparse
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

from dome.synth.common import load_buildings, load_gazetteer, offset_point, save_json

PLATFORM = "Platform X"
START = datetime(2026, 10, 1, tzinfo=timezone.utc)
DAYS = 40

# ---------------------------------------------------------------------------------------------
# Ring definitions. "sites" = where a ring's photos and place clues come from.
# ---------------------------------------------------------------------------------------------

RINGS = {
    "A": {
        "accounts": 12, "posts": 90, "phones": ["555-0142", "555-0187"], "area_code": "713",
        "created": datetime(2026, 9, 2, 20, 0, tzinfo=timezone.utc), "vpn_rate": 0.2,
        "window_photos": True,
        "sites": [{"building": "A", "areas": ["Downtown"],
                   "landmarks": ["Main Street Square", "Market Square Park", "Central station"]}],
        "script": "New in town, text {phone}. {place}Available this week.",
        "reworded": "Just arrived in the city, message {phone}. {place}Open most days.",
        "recruiters": 3, "amplifiers": 5,
    },
}

HARD_NEGATIVES = {"rental_host": 20, "spa_chain": 10, "delivery_driver": 3,
                  "friend_group": 30, "independent": 87}
BACKGROUND = 600

# Far-away VPN exit points (lat, lon). Logins through these say nothing about location.
VPN_EXITS = [(32.78, -96.80), (41.88, -87.63), (39.04, -77.49), (34.05, -118.24), (47.61, -122.33)]

# ---------------------------------------------------------------------------------------------
# Word lists (all neutral). Handles and ordinary posts are built from these.
# ---------------------------------------------------------------------------------------------

HANDLE_A = ["maple", "river", "cedar", "nova", "pixel", "juniper", "amber", "willow", "harbor",
            "copper", "sunny", "quiet", "lucky", "violet", "indigo", "coral", "misty", "golden",
            "silver", "rustic", "breezy", "cobalt", "olive", "sage", "stormy", "velvet", "jade"]
HANDLE_B = ["fox", "lark", "fern", "stone", "comet", "otter", "pine", "wren", "brook", "lantern",
            "meadow", "kite", "harp", "maple", "finch", "orbit", "tide", "ember", "acorn", "moss",
            "cloud", "reef", "trail", "pebble", "heron", "birch", "quill"]

OPENERS = ["Finally tried", "Really enjoyed", "Can't stop thinking about", "Spent the morning at",
           "Took my parents to", "Grabbed lunch near", "Walked past", "Found a great spot for",
           "Picked up groceries at", "Watched the game at", "Signed up for", "Fixed up",
           "Started reading about", "Planning a trip to", "Saw a cool mural near", "Volunteered at",
           "Repainted", "Learned about", "Shared a table at", "Waited forever at"]
SUBJECTS = ["the new taco truck", "the farmers market", "the community garden", "a bike repair shop",
            "the public library", "a ramen place", "the dog park", "an old bookstore",
            "the climbing gym", "a jazz night", "the hardware store", "a pottery class",
            "the coffee roaster", "the night market", "a trivia night", "the science museum",
            "a vintage shop", "the rooftop garden", "a pho spot", "the ballpark"]
ENDINGS = ["and it was worth it", "with my cousins", "before the rain started", "after work",
           "for the third time this month", "on a whim", "with the whole team",
           "and now I need a nap", "without a reservation", "on my day off", "with my neighbor",
           "and got lost twice", "right at closing time", "with a borrowed umbrella",
           "and ran into old friends", "while the band played", "during the long weekend",
           "and took too many pictures", "after the parade", "on the first cool day"]
CLOSERS = ["Recommend it.", "Would go again.", "Ten out of ten.", "Not bad at all.", "Who's in next time?",
           "Pictures later.", "Long day but good.", "Anyone else been?", "Back to work tomorrow.", ""]

RENTAL_OPEN = ["Furnished", "Bright", "Quiet", "Newly updated", "Spacious", "Comfortable",
               "Modern", "Renovated", "Sunny", "Clean"]
RENTAL_UNIT = ["studio", "one bedroom", "two bedroom", "loft", "garden unit", "corner unit",
               "townhome", "duplex half"]
RENTAL_FEATURE = ["with parking", "with a balcony", "close to the rail line", "with washer and dryer",
                  "with a pool", "with pets welcome", "with a home office", "with new appliances",
                  "with a shared courtyard", "with high ceilings"]
RENTAL_TERMS = ["Monthly rates available.", "Short stays welcome.", "Weekly or monthly terms.",
                "Flexible move-in dates.", "Utilities are included.", "Minimum stay of one month.",
                "Corporate stays welcome.", "Discount for longer stays."]
RENTAL_CONTACT = ["Call {phone}.", "Reach the host at {phone}.", "Questions? {phone}.",
                  "Text {phone} to set up a viewing.", "Leasing line {phone}."]

# One layout per host in a rental group, so hosts share photos but never wording.
RENTAL_LAYOUTS = [
    "{open} {unit} {feature}. Located in {area}. {terms} {contact}",
    "Available now in {area}: {unit}, {feature}. {contact} {terms}",
    "{terms} Our {unit} in {area} is {open_lower}, {feature}. {contact}",
    "Listing update. {contact} Ask about the {unit} {feature}, {area} location.",
]

SPA_SCRIPT ="Day spa: facials, manicures and wellness packages. Book at {phone}. {place}Gift cards available."

RECRUITER_BIOS = ["Modelling agency. Now hiring.", "Job offers: hostess, promo, front desk.",
                  "Talent and modelling agency."]
RECRUITER_POSTS = ["Now hiring front desk and promo staff. Housing help available. DM for details.",
                   "Open casting this month for catalogue modelling. Travel covered. DM us.",
                   "Hiring event staff, no experience needed, start right away. Message for details."]

BIO_PARTS = ["Coffee first.", "Dog person.", "Weekend cyclist.", "Plant collector.", "Home cook.",
             "Runner.", "Bookworm.", "Amateur photographer.", "Board game fan.", "Gardener.",
             "Music lover.", "Houston local.", "Night owl.", "Early riser.", "Foodie.",
             "Movie buff.", "Swimmer.", "Learning guitar.", "Proud aunt.", "Proud uncle."]


class World:
    """Holds everything generated so far. Each `add_*` method appends to one of the lists."""

    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.gaz = load_gazetteer()
        self.buildings = {b["label"]: b for b in load_buildings()}
        self.accounts, self.posts, self.interactions = [], [], []
        self.renders = {}
        self.groups = {}           # group name -> [account_id]
        self.answer_key = {}

        # Shuffled ID pools so IDs reveal nothing about which group an account is in.
        self._account_ids = [f"acct_{i:03d}" for i in range(1, 1000)]
        self._photo_ids = [f"img_{i:04d}" for i in range(1, 10000)]
        self.rng.shuffle(self._account_ids)
        self.rng.shuffle(self._photo_ids)

        reserved = {p for r in RINGS.values() for p in r["phones"]}
        self._phone_pool = [f"555-01{n:02d}" for n in range(100) if f"555-01{n:02d}" not in reserved]
        self.rng.shuffle(self._phone_pool)

        self._used_handles = set()
        self._used_sentences = set()   # casual sentences already used, so hard negatives never repeat one
        self.areas = [n for n, g in self.gaz.items() if g["kind"] == "area"]
        self.landmarks = [n for n, g in self.gaz.items() if g["kind"] == "landmark"]

    # ---- small random helpers ---------------------------------------------------------------

    def time_in(self, start, days):
        minutes = self.rng.randrange(int(days * 24 * 60))
        return start + timedelta(minutes=minutes)

    def unique_phone(self):
        return self._phone_pool.pop()

    def new_photo(self, scan_id, view):
        photo_id = self._photo_ids.pop()
        self.renders[photo_id] = {"scan_id": scan_id, "view": view, "path": None}
        return photo_id

    def handle(self):
        while True:
            h = f"{self.rng.choice(HANDLE_A)}_{self.rng.choice(HANDLE_B)}{self.rng.randrange(10, 100)}"
            if h not in self._used_handles:
                self._used_handles.add(h)
                return h

    def casual_text(self, place=None, fresh=False):
        """An ordinary post. fresh=True redraws until the main sentence is new, so hard
        negatives never share wording by chance (that would add a text key)."""
        r = self.rng
        while True:
            s = f"{r.choice(OPENERS)} {r.choice(SUBJECTS)} {r.choice(ENDINGS)}."
            if not fresh or s not in self._used_sentences:
                break
        self._used_sentences.add(s)
        if place:
            s += f" Over in {place}."
        closer = r.choice(CLOSERS)
        return f"{s} {closer}".strip()

    def place_sentence(self, area, landmark):
        if area and landmark:
            return f"In {area}, close to {landmark}. "
        if area:
            return f"In {area}. "
        if landmark:
            return f"Near {landmark}. "
        return ""

    def disguise(self, phone):
        """Write a 555 number the way people dodge filters."""
        tail = phone.split("-")[1]
        forms = [f"five5five-{tail}", f"555 {tail.replace('0', 'O')}", f"555.{tail}",
                 f"(555) {tail}", " ".join("555") + " - " + " ".join(tail)]
        return self.rng.choice(forms)

    def logins(self, center, n, vpn_rate, spread_km):
        out = []
        for _ in range(n):
            t = self.time_in(START, DAYS)
            if self.rng.random() < vpn_rate:
                lat, lon = self.rng.choice(VPN_EXITS)
                out.append({"time": iso(t), "lat": lat, "lon": lon, "precision_km": 50.0, "vpn": True})
            else:
                dx = self.rng.uniform(-spread_km, spread_km)
                dy = self.rng.uniform(-spread_km, spread_km)
                lat, lon = offset_point(center[0], center[1], dx, dy)
                prec = self.rng.choice([0.2, 0.5, 1.0, 2.0])
                out.append({"time": iso(t), "lat": lat, "lon": lon, "precision_km": prec, "vpn": False})
        out.sort(key=lambda x: x["time"])
        return out

    # ---- records ----------------------------------------------------------------------------

    def add_account(self, group, bio, created, flags, home, vpn_rate=0.05, spread_km=2.0):
        acct_id = self._account_ids.pop()
        h = self.handle()
        self.accounts.append({
            "account_id": acct_id,
            "platform": PLATFORM,
            "handle": h,
            "display_name": f"{h.split('_')[0].title()} {self.rng.choice('ABCDEFGHJKLMNPRSTW')}.",
            "bio": bio,
            "created": iso(created),
            "last_active": iso(self.time_in(START + timedelta(days=DAYS - 5), 5)),
            "flags": flags,
            "logins": self.logins(home, self.rng.randint(3, 6), vpn_rate, spread_km),
        })
        self.groups.setdefault(group, []).append(acct_id)
        return acct_id

    def add_post(self, acct, text, time, photos=(), phones=(), stated_area=None, area_code=None,
                 landmarks=()):
        post = {"post_id": None, "account_id": acct, "text": text, "photo_ids": list(photos),
                "phones": list(phones), "time": iso(time), "stated_area": stated_area,
                "area_code": area_code, "landmarks": list(landmarks)}
        self.posts.append(post)
        return post

    def add_interaction(self, a, b, kind, time, post=None):
        if a == b:
            return
        self.interactions.append({"from": a, "to": b, "kind": kind, "time": iso(time),
                                  "post_id": post})   # post dict; swapped for its ID in finish()

    def home_of(self, area):
        g = self.gaz[area]
        return (g["lat"], g["lon"])

    # ---- groups -----------------------------------------------------------------------------

    def build_background(self):
        r = self.rng
        for _ in range(BACKGROUND):
            area = r.choice(self.areas)
            created = self.time_in(datetime(2019, 1, 1, tzinfo=timezone.utc), 6 * 365)
            bio = " ".join(r.sample(BIO_PARTS, 2))
            acct = self.add_account("background", bio, created, [], self.home_of(area))
            for _ in range(r.randint(1, 4)):
                stated = area if r.random() < 0.5 else None
                lms = [r.choice(self.landmarks)] if r.random() < 0.1 else []
                photos = [self.new_photo(None, "other")] if r.random() < 0.3 else []
                code = r.choice(["713", "832", "281"]) if r.random() < 0.2 else None
                self.add_post(acct, self.casual_text(stated), self.time_in(START, DAYS),
                              photos=photos, stated_area=stated, area_code=code, landmarks=lms)
        bg = self.groups["background"]
        bg_posts = [p for p in self.posts if p["account_id"] in set(bg)]
        for acct in bg:
            for other in r.sample(bg, r.randint(3, 8)):
                self.add_interaction(acct, other, "follow", self.time_in(START, DAYS))
        for p in bg_posts:
            if r.random() < 0.2:
                fan = r.choice(bg)
                self.add_interaction(fan, p["account_id"], r.choice(["repost", "reply"]),
                                     parse(p["time"]) + timedelta(hours=r.randint(1, 48)), p)

    def build_ring(self, label):
        spec, r = RINGS[label], self.rng
        members = []
        for i in range(spec["accounts"]):
            created = spec["created"] + timedelta(minutes=r.randint(0, 180))   # one batch
            site = spec["sites"][i % len(spec["sites"])]
            b = self.buildings[site["building"]]
            members.append(self.add_account(
                f"ring_{label}", "New here. Message for info.", created,
                ["user_report"] if r.random() < 0.5 else ["keyword_match"],
                (b["lat"], b["lon"]), vpn_rate=spec["vpn_rate"], spread_km=0.8))

        # Photo pools: ~20 renders per ring building. Window views only if the ring has them.
        pools = {}
        for site in spec["sites"]:
            b = self.buildings[site["building"]]
            pools[site["building"]] = [
                self.new_photo(b["scan_id"], "window" if spec["window_photos"] and k % 4 == 0 else "interior")
                for k in range(20)]

        ring_posts = []
        for k in range(spec["posts"]):
            acct = members[k % len(members)]
            site = spec["sites"][k % len(spec["sites"])]
            area = r.choice(site["areas"]) if r.random() < 0.6 else None
            lm = r.choice(site["landmarks"]) if site["landmarks"] and r.random() < 0.5 else None
            place = self.place_sentence(area, lm)
            phone = r.choice(spec["phones"])
            shown = self.disguise(phone) if r.random() < 0.3 else phone
            template = spec["reworded"] if r.random() < 0.3 else spec["script"]
            text = template.format(phone=shown, place=place).strip()
            photos = r.sample(pools[site["building"]], r.randint(1, 3))
            code = spec["area_code"] if r.random() < 0.7 else None
            post = self.add_post(acct, text, self.time_in(START, DAYS), photos=photos, phones=[shown],
                                 stated_area=area, area_code=code, landmarks=[lm] if lm else [])
            ring_posts.append(post)

        # Dense interactions among members.
        for a in members:
            for b in members:
                if a != b and r.random() < 0.7:
                    self.add_interaction(a, b, "follow", spec["created"] + timedelta(hours=r.randint(1, 72)))
        for p in ring_posts:
            if r.random() < 0.4:
                fan = r.choice(members)
                self.add_interaction(fan, p["account_id"], r.choice(["repost", "reply"]),
                                     parse(p["time"]) + timedelta(hours=r.randint(1, 24)), p)

        # Recruiters: agency-style bios, most reposts go to ring accounts.
        recruiters = []
        for i in range(spec["recruiters"]):
            acct = self.add_account(f"ring_{label}_recruiter", RECRUITER_BIOS[i],
                                    self.time_in(datetime(2026, 6, 1, tzinfo=timezone.utc), 60),
                                    ["user_report"] if i < 2 else [], self.home_of("Downtown"))
            recruiters.append(acct)
            for j in range(3):
                self.add_post(acct, RECRUITER_POSTS[(i + j) % 3], self.time_in(START, DAYS))
            for p in r.sample(ring_posts, 8):
                self.add_interaction(acct, p["account_id"], "repost", parse(p["time"]) + timedelta(hours=2), p)
            bg_post = r.choice([p for p in self.posts if p["account_id"] in set(self.groups["background"])])
            self.add_interaction(acct, bg_post["account_id"], "repost", parse(bg_post["time"]) + timedelta(hours=3), bg_post)

        # Amplifiers: repost ring posts within an hour of posting.
        amplifiers = []
        for i in range(spec["amplifiers"]):
            area = r.choice(self.areas)
            acct = self.add_account(f"ring_{label}_amplifier", " ".join(r.sample(BIO_PARTS, 2)),
                                    self.time_in(datetime(2026, 8, 1, tzinfo=timezone.utc), 30),
                                    ["coordinated_activity"] if i < 3 else [], self.home_of(area))
            amplifiers.append(acct)
            for _ in range(2):
                self.add_post(acct, self.casual_text(), self.time_in(START, DAYS))
            for p in r.sample(ring_posts, 12):
                self.add_interaction(acct, p["account_id"], "repost",
                                     parse(p["time"]) + timedelta(minutes=r.randint(5, 55)), p)

        self.answer_key[label] = {
            "members": sorted(members),
            "recruiters": sorted(recruiters),
            "amplifiers": sorted(amplifiers),
            "phones": spec["phones"],
            "buildings": [{"label": s["building"],
                           "property_id": self.buildings[s["building"]]["property_id"],
                           "scan_id": self.buildings[s["building"]]["scan_id"],
                           "unit": self.buildings[s["building"]]["unit"]} for s in spec["sites"]],
        }

    def build_hard_negatives(self):
        r = self.rng
        old = datetime(2021, 1, 1, tzinfo=timezone.utc)

        # Rental hosts: groups of 4 reuse one set of listing photos (photo key only).
        # Two groups list units in decoy D (a scanned building near Building A, inside Ring A's
        # zone), so the Locator really compares against it. The other groups reuse listing
        # photos from no scanned building (scan_id null, nothing to render).
        decoys = ["D", "D", None, None, None]
        n_groups = HARD_NEGATIVES["rental_host"] // 4
        for g in range(n_groups):
            b = self.buildings[decoys[g]] if decoys[g] else None
            home = (b["lat"], b["lon"]) if b else self.home_of(r.choice(self.areas))
            shared_photos = [self.new_photo(b["scan_id"] if b else None, "interior" if b else "other")
                             for _ in range(6)]
            for layout in RENTAL_LAYOUTS:      # each host in a group writes listings differently
                area = r.choice(self.areas)
                acct = self.add_account("rental_host", "Short and mid-term rentals.",
                                        self.time_in(old, 900), ["image_reuse"], home)
                phone = self.unique_phone()
                for _ in range(r.randint(2, 4)):
                    text = layout.format(
                        open=(o := r.choice(RENTAL_OPEN)), open_lower=o.lower(), unit=r.choice(RENTAL_UNIT),
                        feature=r.choice(RENTAL_FEATURE), area=area, terms=r.choice(RENTAL_TERMS),
                        contact=r.choice(RENTAL_CONTACT).format(phone=phone))
                    self.add_post(acct, text, self.time_in(START, DAYS), photos=r.sample(shared_photos, 3),
                                  phones=[phone], stated_area=area)

        # Spa chain: one shared script, different phones, no interactions (text key only).
        for _ in range(HARD_NEGATIVES["spa_chain"]):
            area = r.choice(self.areas)
            acct = self.add_account("spa_chain", "Day spa. Locations across the city.",
                                    self.time_in(old, 900), ["keyword_match"], self.home_of(area))
            phone = self.unique_phone()
            for _ in range(r.randint(2, 4)):
                text = SPA_SCRIPT.format(phone=phone, place=self.place_sentence(area, None))
                self.add_post(acct, text, self.time_in(START, DAYS), phones=[phone], stated_area=area,
                              area_code=r.choice(["713", "832"]))

        # Delivery drivers: unique text, clues all over the city.
        for _ in range(HARD_NEGATIVES["delivery_driver"]):
            acct = self.add_account("delivery_driver", "Delivery driver. All over town.",
                                    self.time_in(old, 900), ["user_report"], self.home_of("Downtown"),
                                    spread_km=12.0)
            for area in r.sample(self.areas, 6):
                lm = [r.choice(self.landmarks)] if r.random() < 0.3 else []
                self.add_post(acct, self.casual_text(area, fresh=True), self.time_in(START, DAYS), stated_area=area,
                              landmarks=lm, area_code=r.choice(["713", "832", "281"]))

        # Friend groups: repost each other a lot (interaction key only).
        for g in range(HARD_NEGATIVES["friend_group"] // 5):
            area = r.choice(self.areas)
            friends = []
            for _ in range(5):
                acct = self.add_account("friend_group", " ".join(r.sample(BIO_PARTS, 2)),
                                        self.time_in(old, 900), ["coordinated_activity"], self.home_of(area))
                friends.append(acct)
                for _ in range(r.randint(2, 4)):
                    stated = area if r.random() < 0.5 else None
                    self.add_post(acct, self.casual_text(stated, fresh=True), self.time_in(START, DAYS), stated_area=stated)
            group_posts = [p for p in self.posts if p["account_id"] in set(friends)]
            for a in friends:
                for b in friends:
                    if a != b:
                        self.add_interaction(a, b, "follow", self.time_in(START, DAYS))
            for p in group_posts:
                for fan in r.sample(friends, 2):
                    self.add_interaction(fan, p["account_id"], "repost",
                                         parse(p["time"]) + timedelta(minutes=r.randint(10, 300)), p)

        # Independents: flagged single accounts with unique everything.
        for _ in range(HARD_NEGATIVES["independent"]):
            area = r.choice(self.areas)
            acct = self.add_account("independent", " ".join(r.sample(BIO_PARTS, 2)),
                                    self.time_in(old, 900), ["user_report"], self.home_of(area))
            phone = self.unique_phone() if r.random() < 0.3 else None
            for _ in range(r.randint(1, 3)):
                stated = area if r.random() < 0.5 else None
                text = self.casual_text(stated, fresh=True) + (f" Call {phone}." if phone else "")
                photos = [self.new_photo(None, "other")] if r.random() < 0.4 else []
                self.add_post(acct, text, self.time_in(START, DAYS), photos=photos,
                              phones=[phone] if phone else [], stated_area=stated)

        self.answer_key["hard_negatives"] = {
            kind: sorted(self.groups[kind]) for kind in HARD_NEGATIVES}
        self.answer_key["decoy_buildings"] = [
            {k: b[k] for k in ("label", "property_id", "scan_id")}
            for b in self.buildings.values() if b["role"] == "decoy"]

    # ---- output -----------------------------------------------------------------------------

    def finish(self):
        """Give posts stable IDs in time order and swap temporary post references for IDs."""
        order = sorted(range(len(self.posts)), key=lambda i: (self.posts[i]["time"], self.posts[i]["account_id"]))
        for n, i in enumerate(order, start=1):
            self.posts[i]["post_id"] = f"post_{n:04d}"
        for it in self.interactions:
            if it["post_id"] is not None:
                it["post_id"] = it["post_id"]["post_id"]
        self.posts.sort(key=lambda p: p["post_id"])
        self.accounts.sort(key=lambda a: a["account_id"])
        self.interactions.sort(key=lambda x: (x["time"], x["from"], x["to"], x["kind"]))
        self.renders = dict(sorted(self.renders.items()))


def iso(t):
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def parse(s):
    return datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def generate(out_dir, answer_key_dir, seed=37):
    w = World(seed)
    w.build_background()
    for label in RINGS:
        w.build_ring(label)
    w.build_hard_negatives()
    w.finish()

    out_dir = Path(out_dir)
    save_json(out_dir / "accounts.json", w.accounts)
    save_json(out_dir / "posts.json", w.posts)
    save_json(out_dir / "interactions.json", w.interactions)
    save_json(out_dir / "renders.json", w.renders)
    # Agents must never read this file. Scoring only.
    save_json(Path(answer_key_dir) / "answer_key.json", w.answer_key)
    return w


def main():
    ap = argparse.ArgumentParser(description="Generate Dome's synthetic case data.")
    ap.add_argument("--out", default="data/synth")
    ap.add_argument("--answer-key", default="data/answer_key", help="folder for answer_key.json")
    ap.add_argument("--seed", type=int, default=37)
    args = ap.parse_args()
    w = generate(args.out, args.answer_key, args.seed)
    print(f"accounts {len(w.accounts)}  posts {len(w.posts)}  interactions {len(w.interactions)}  "
          f"photos {len(w.renders)}")
    for group, ids in sorted(w.groups.items()):
        print(f"  {group:<22} {len(ids)}")
    print(f"wrote {args.out}/ and {args.answer_key}/answer_key.json")


if __name__ == "__main__":
    main()
