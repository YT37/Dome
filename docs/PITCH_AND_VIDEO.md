# Dome: slides and video plan (Sun 3:30 AM)

Numbers come only from the README Results table (written by `python -m dome.eval_night --results`)
or from the recorded case files. Refresh both after the 5:30 run; anything that didn't ship is cut.
All data is synthetic. No news footage, no personal stories, nothing that suggests a minor.

## Slides (5)

| # | Title | On the slide | Say (≈20 s each) |
| --- | --- | --- | --- |
| 1 | **Synthetic case. Real buildings.** | One line on a dark slide: "All accounts, ads, wallets and photos are synthetic. Real Houston buildings are used only as demo locations." Dome mark. | "Everything you'll see is synthetic. Dome turns flagged accounts into one building for a human to verify." |
| 2 | **Investigators get the photos. Not the address.** | Three synthetic room renders (grey silhouettes). A queue of flagged accounts, most of them false alarms. | "Ads come with room photos and burner phones. Most flagged accounts are noise: rental hosts, a spa chain, friends reposting. The question is which accounts are one ring, and where." |
| 3 | **The dome shrinks to one building** | UI screenshot: the dome over Houston → pin on Building A. Funnel: 129 buildings in the dome → 125 photo-checked → #1 Building A, P 0.68 · decoy D 0.00 → High, score 59. | "Five agents under a LangGraph deepagents supervisor. CoStar lists the buildings in the dome; Matterport scans and Vexcel imagery let us match the ad's room and window view." |
| 4 | **The supervisor decides, and shows its work** | Decision log screenshot (one decision row expanded with evidence) + the money flow: advertiser → collectors → aggregator → cash-out. | "Every step is logged with its evidence. The money confirms the ring: an advertiser wallet pays the ad platform minutes before the ring's posts." |
| 5 | **Leads, not verdicts** | Guardrails: synthetic data · human approval before the report · no contact or dispatch tools · every claim cited. Results: Linker precision 1.00 / recall 1.00, 0 of 150 look-alikes linked, wallet roles 1.00, Spotter precision@10 1.00. | "Dome finds the room so a human can find the person, faster. It never contacts anyone, and a person approves every report." |

Sponsor 60-second versions (Avishek writes them): CoStar → slide 3; Arlequin → slides 4–5 (ring + money + topology); LangChain → the supervisor, interrupt and decision log; Amazon → practical deployment by T&S teams.

## Video storyboard (2:00)

Voiceover in Ishaan's or Yug's own voice. Dark UI look throughout. Each beat is a real screen recording
(replay of the final run) plus a title overlay.

| Time | Beat | On screen | Voiceover |
| --- | --- | --- | --- |
| 0:00–0:08 | Hook | Three synthetic room renders fade in. Text: *An ad. A phone number. A room.* | "Investigators get the photos. They almost never get the address." |
| 0:08–0:18 | Spotter | Spotter queue: accounts ranked, each with 3+ signals (repeated phone, reworded script, batch-created look-alikes). Click **Start case from this account**. | "Dome's Spotter flags an account only when three different kinds of evidence agree. The analyst picks where to start." |
| 0:18–0:24 | Title | Dome mark; *A dome over the search area that shrinks to one building.* | "This is Dome." |
| 0:24–0:40 | **Arlequin: show the work (ring)** | Link chart builds edge by edge: same phone, reworded script, shared photos → Ring A lights up; look-alikes stay grey. Topology view: shared-key cells around the ring, model score beside the rules. | "The Linker joins accounts only when two kinds of evidence agree. Rental hosts, a spa chain and friends reposting each other share one clue, and stay grey. A topological model gives a second opinion; the rules make every link." |
| 0:40–0:52 | **Arlequin: show the work (money)** | Payment-then-post chart: ad-platform payments 2–15 min before ring posts, a spike far above the shuffled chance line. Then the flow: advertiser → collectors → aggregator → cash-out at Exchange X. | "The money confirms it. One wallet pays the ad platform minutes before the ring's posts, again and again. Payments flow from collectors to an aggregator and out through an exchange. No wallet was ever posted; it's found from behaviour." |
| 0:52–1:00 | Zoner | The dome draws over Houston (14 km²). | "Place clues in the ads give an area. Never an address." |
| 1:00–1:20 | **CoStar: show the work** | CoStar lists 129 buildings in the dome. Room match narrows: 125 scans → 6 on a shortlist → 1 (Building A, P 0.68; decoy D 0.00). Ad photo beside its matched scan view. Geo fix: the pin moves 23 m onto the building, floor 3. Window view checked against the oblique (W 0.60). | "CoStar gives us every building in the dome. We match the ad photos to rooms inside 125 Matterport scans. One building matches, the decoy next door doesn't, and the window view agrees. The scan's location is corrected by 23 meters." |
| 1:20–1:32 | Briefer + approval | Lead card: Building A (synthetic case), High, 59, factor bars, reasons, verify next. LangGraph interrupt: **Approve for report**. | "The Briefer explains every score in plain language, and lists the records to request through legal process. A person approves the report." |
| 1:32–1:42 | Ask about this case | Question → answer with citation chips (recorded from the final run). | "Ask anything about the case. Every answer cites the file it came from, or says it isn't there." |
| 1:42–1:54 | Proof + guardrails | Results: precision 1.00, recall 1.00, 0 of 150 look-alikes linked, decoy not a lead. Lines: *Synthetic data · Human approval · No contact tools*. | "On our test platform Dome found the whole ring, linked none of the 150 look-alikes, and ranked the true building first." |
| 1:54–2:00 | Close | Dome mark. *Find the room, faster.* Footer. | "Dome finds the room, so a human can find the person faster." |

Only include a beat if its feature ran in the final run (section 9 of the split handoff); otherwise
use the fallback or cut the line.
