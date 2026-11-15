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
  {src: 'clips/us.mp4', from: 0, dur: 5.0, start: 0, credit: 'BBC News', title: "'Epidemic' of US children sold for sex"},
  {src: 'clips/tz.mp4', from: 5.0, dur: 2.0, start: 0.5, credit: 'BBC Africa Eye', title: "Forced to beg: Tanzania's trafficked kids"},
  {src: 'clips/fr_53.mp4', from: 7.0, dur: 3.8, start: 0.6, credit: 'France 24', title: 'Recruiting on TikTok: the code words', blur: true},
  {src: 'clips/fr_63.5.mp4', from: 10.8, dur: 3.4, start: 0.1, credit: 'France 24', title: 'The lure: housed, fed, transport, safety'},
];
export const HOOK_END = 14.2;
export const VO_FIRST = 15.4;
const GAPS = [0, 0.33, 0.47, 0.35, 0.33, 0.35, 0.33, 0.35, 0.35, 0.35, 0.35, 0.5];
export const VO: {start: number; dur: number; text: string}[] = [];
{
  let t = VO_FIRST;
  DATA.vo.forEach((d: number, i: number) => {
    if (i > 0) t += GAPS[i];
    VO.push({start: t, dur: d, text: DATA.lines[i]});
    t += d;
  });
}
export const END = VO[11].start + VO[11].dur + 1.7;
export const SCENES: [string, number, number][] = (() => {
  const s = (i: number) => VO[i].start - 0.15;
  return [
    ['hook', 0, HOOK_END], ['cut', HOOK_END, 15.2], ['friend', 15.2, s(1)], ['problem', s(1), s(2)],
    ['title', s(2), s(3)], ['pipeline', s(3), s(4)], ['linker', s(4), s(5)], ['zoner', s(5), s(6)],
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
