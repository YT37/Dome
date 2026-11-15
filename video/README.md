# Dome video (Remotion + three.js)

The 2-minute Devpost video, built as code: Remotion renders React scenes frame by frame,
React Three Fiber (three.js) draws the 3D city and the dome, and the audio is mixed in the composition.

## Set up

```bash
cd video
npm install
npx remotion studio          # live preview in the browser, scrub the timeline
npm run render               # writes out/dome.mp4
```

Optional, for Claude Code on your machine: `npx skills add remotion-dev/skills` adds Remotion's
agent skills (best practices for compositions, captions and rendering).

## News footage (not in git)

The hook uses short excerpts of BBC News, BBC Africa Eye and France 24 reports, credited on screen.
They are not committed. Put the four cut clips in `public/clips/`:
`us.mp4`, `tz.mp4`, `fr_53.mp4`, `fr_63.5.mp4` (copies are in the project files under `dome/video/clips/`).

## Where things are

| File | What |
|---|---|
| `src/theme.ts` | colours, fonts, the timeline (hook clips, voiceover start times, scene list) |
| `src/scenes.tsx` | one component per scene (hook, friend, problem, title, pipeline, five agents, real run, guardrails, close) |
| `src/City3D.tsx` | three.js city, dome, zone outline, markers |
| `src/ui.tsx` | grain, handheld drift, sticky notes, polaroids, hand-drawn lines, the synthetic room |
| `src/Video.tsx` | puts scenes in sequence, word-by-word captions, voiceover and music |
| `src/data.json` | numbers from a real `synth-a` run (ring, zone, candidates, match, brief, log) |
| `lines.json` | the voiceover script; `public/vo/` holds the generated lines (Kokoro TTS) |
| `make_music.py` | the generated music bed (`public/music.wav`) |

To record your own voice instead of the TTS, replace `public/vo/l01.wav` … `l12.wav` and update the
durations in `src/data.json` (`vo`); the timeline and captions follow them.

All accounts in the video are synthetic. Building data comes from the Dome pipeline. Leads are for human verification only.
