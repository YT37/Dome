import '@fontsource/instrument-serif/400.css';
import '@fontsource/instrument-serif/400-italic.css';
import '@fontsource/inter/400.css';
import '@fontsource/inter/500.css';
import '@fontsource/inter/600.css';
import '@fontsource/inter/700.css';
import '@fontsource/jetbrains-mono/400.css';
import '@fontsource/jetbrains-mono/600.css';
import '@fontsource/caveat/500.css';
import '@fontsource/caveat/700.css';
import {interpolate, Easing} from 'remotion';
import DATA from './data.json';

export {DATA};
export const FPS = 30;
export const W = 1920, H = 1080;

export const C = {
  ink: '#0e0d0b', ink2: '#171512', ink3: '#211e1a', line: '#2e2a24',
  paper: '#efe7da', paper2: '#e3d9c8', muted: '#8a8275', dim: '#b4ab9c',
  accent: '#ff5b35', teal: '#5cc2ad', amber: '#e9b24c', sticky: '#f4d66a', red: '#e5484d', green: '#58b56f',
};
export const F = {
  serif: '"Instrument Serif", Georgia, serif',
  sans: 'Inter, sans-serif',
  mono: '"JetBrains Mono", monospace',
  hand: 'Caveat, cursive',
};

// ---------- timeline (seconds) ----------
export const HOOK = [
  {src: 'clips/us.mp4', from: 0, dur: 10, start: 0, credit: 'BBC News', title: "'Epidemic' of US children sold for sex", vol: [[0, 0.9], [10, 0.9]]},
  {src: 'clips/tz.mp4', from: 10, dur: 10, start: 0, credit: 'BBC Africa Eye', title: "Forced to beg: Tanzania's trafficked kids", vol: [[0, 0.85], [2.0, 0.85], [2.6, 0.22], [10, 0.22]]},
  {src: 'clips/fr.mp4', from: 20, dur: 10, start: 0, credit: 'France 24', title: 'Recruiting on TikTok, in code', vol: [[0, 0.25], [10, 0.25]]},
];
export const HOOK_END = 30;
export const REVEAL = [30, 33.2];
// voiceover start times: the first two lines play over the Tanzania and France 24 footage
const STARTS0 = [12.4, 18.2, 30.6];
const GAP = 0.35;
export const VO: {start: number; dur: number; text: string}[] = [];
{
  let t = 0;
  DATA.vo.forEach((d: number, i: number) => {
    const s = i < 3 ? STARTS0[i] : t + GAP;
    VO.push({start: s, dur: d, text: DATA.lines[i]});
    t = s + d;
  });
}
export const END = VO[11].start + VO[11].dur + 1.7;
export const SCENES: [string, number, number][] = (() => {
  const s = (i: number) => VO[i].start - 0.15;
  return [
    ['hook', 0, HOOK_END], ['reveal', REVEAL[0], REVEAL[1]], ['title', REVEAL[1], s(3)], ['pipeline', s(3), s(4)], ['linker', s(4), s(5)], ['zoner', s(5), s(6)],
    ['lister', s(6), s(7)], ['locator', s(7), s(8)], ['briefer', s(8), s(9)], ['run', s(9), s(10)],
    ['guard', s(10), s(11)], ['close', s(11), END],
  ];
})();

// ---------- helpers ----------
export const clamp = (v: number, a = 0, b = 1) => Math.max(a, Math.min(b, v));
export const P = (t: number, a: number, b: number) => clamp((t - a) / (b - a));
export const eo = (x: number) => 1 - Math.pow(1 - x, 3);
export const eio = (x: number) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2);
export const ease = (t: number, a: number, b: number) => eo(P(t, a, b));
export const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
export const iv = (t: number, inp: number[], out: number[]) =>
  interpolate(t, inp, out, {extrapolateLeft: 'clamp', extrapolateRight: 'clamp', easing: Easing.bezier(0.33, 1, 0.68, 1)});
export function rng(seed: number) {
  return function () {
    seed |= 0; seed = (seed + 0x6d2b79f5) | 0;
    let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
// a wobbly hand-drawn path through points
export function sketch(pts: [number, number][], seed = 1, wob = 2.2) {
  const r = rng(seed);
  let d = '';
  pts.forEach(([x, y], i) => {
    const jx = (r() - 0.5) * wob, jy = (r() - 0.5) * wob;
    if (i === 0) d += `M${x + jx},${y + jy}`;
    else {
      const [px, py] = pts[i - 1];
      const mx = (px + x) / 2 + (r() - 0.5) * wob * 2, my = (py + y) / 2 + (r() - 0.5) * wob * 2;
      d += ` Q${mx},${my} ${x + jx},${y + jy}`;
    }
  });
  return d;
}
export function sketchEllipse(cx: number, cy: number, rx: number, ry: number, seed = 3, turns = 1.08) {
  const r = rng(seed); const pts: [number, number][] = [];
  const n = 28; const a0 = r() * Math.PI * 2;
  for (let i = 0; i <= n * turns; i++) {
    const a = a0 + (i / n) * Math.PI * 2;
    const k = 1 + (r() - 0.5) * 0.05 + i * 0.002;
    pts.push([cx + Math.cos(a) * rx * k, cy + Math.sin(a) * ry * k]);
  }
  return sketch(pts, seed + 1, 1.5);
}
