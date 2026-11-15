import React from 'react';
import {AbsoluteFill, useCurrentFrame, Img, staticFile} from 'remotion';
import {C, F, FPS, ease, P, sketch, sketchEllipse, rng, eo} from './theme';

export const useT = () => useCurrentFrame() / FPS;

export const Grain: React.FC<{o?: number}> = ({o = 0.09}) => {
  const f = useCurrentFrame();
  return (
    <AbsoluteFill style={{pointerEvents: 'none', mixBlendMode: 'overlay', opacity: o}}>
      <Img src={staticFile(`grain/g${Math.floor(f / 2) % 6}.png`)} style={{width: '100%', height: '100%'}} />
    </AbsoluteFill>
  );
};

export const Vignette: React.FC<{s?: number}> = ({s = 0.55}) => (
  <AbsoluteFill style={{pointerEvents: 'none', background: `radial-gradient(ellipse at 50% 45%, rgba(0,0,0,0) 45%, rgba(0,0,0,${s}) 100%)`}} />
);

// gentle handheld drift for 2D scenes
export const Drift: React.FC<{children: React.ReactNode; amt?: number}> = ({children, amt = 1}) => {
  const t = useT();
  const x = (Math.sin(t * 0.7) * 3 + Math.sin(t * 1.9) * 1.2) * amt;
  const y = (Math.cos(t * 0.6) * 2.5 + Math.sin(t * 2.3) * 1) * amt;
  const r = Math.sin(t * 0.4) * 0.12 * amt;
  return <AbsoluteFill style={{transform: `translate(${x}px,${y}px) rotate(${r}deg) scale(1.01)`}}>{children}</AbsoluteFill>;
};

export const Paper: React.FC<{children?: React.ReactNode}> = ({children}) => (
  <AbsoluteFill style={{background: `radial-gradient(ellipse at 40% 30%, #1d1a16 0%, ${C.ink} 70%)`}}>{children}</AbsoluteFill>
);

export const Kicker: React.FC<{t: number; n: string; title: string; x?: number; y?: number}> = ({t, n, title, x = 110, y = 96}) => {
  const a = ease(t, 0.1, 0.7);
  return (
    <div style={{position: 'absolute', left: x, top: y, opacity: a, transform: `translateY(${(1 - a) * 14}px)`}}>
      <div style={{fontFamily: F.hand, fontSize: 40, color: C.accent, fontWeight: 700, transform: 'rotate(-2deg)', transformOrigin: 'left'}}>{n}</div>
      <div style={{fontFamily: F.serif, fontSize: 76, color: C.paper, lineHeight: 1.0, marginTop: 2}}>{title}</div>
    </div>
  );
};

export const SketchLine: React.FC<{pts: [number, number][]; p: number; color?: string; w?: number; seed?: number; dash?: boolean}> = ({pts, p, color = C.accent, w = 4, seed = 1, dash}) => {
  const d = sketch(pts, seed);
  return (
    <path d={d} fill="none" stroke={color} strokeWidth={w} strokeLinecap="round" strokeLinejoin="round"
      pathLength={1} strokeDasharray={dash ? '0.02 0.02' : `${p} 2`} opacity={dash ? p : 1} />
  );
};
export const SketchCircle: React.FC<{cx: number; cy: number; rx: number; ry: number; p: number; color?: string; w?: number; seed?: number}> = ({cx, cy, rx, ry, p, color = C.accent, w = 4, seed = 3}) => (
  <path d={sketchEllipse(cx, cy, rx, ry, seed)} fill="none" stroke={color} strokeWidth={w} strokeLinecap="round" pathLength={1} strokeDasharray={`${p} 2`} />
);

export const Sticky: React.FC<{x: number; y: number; text: string; a: number; rot?: number; w?: number; color?: string; size?: number}> = ({x, y, text, a, rot = -3, w = 210, color = C.sticky, size = 30}) => (
  <div style={{position: 'absolute', left: x, top: y, width: w, padding: '14px 16px 18px', background: color, color: '#2a2412',
    fontFamily: F.hand, fontSize: size, fontWeight: 700, lineHeight: 1.0, boxShadow: '0 10px 18px rgba(0,0,0,.35)',
    transform: `rotate(${rot}deg) scale(${0.85 + 0.15 * a})`, opacity: a, transformOrigin: 'top left'}}>
    {text}
  </div>
);

export const Tape: React.FC<{x: number; y: number; rot?: number}> = ({x, y, rot = -6}) => (
  <div style={{position: 'absolute', left: x, top: y, width: 120, height: 34, background: 'rgba(235,225,200,.55)', transform: `rotate(${rot}deg)`,
    boxShadow: '0 1px 2px rgba(0,0,0,.2)'}} />
);

export const Hand: React.FC<{x: number; y: number; a: number; children: React.ReactNode; color?: string; size?: number; rot?: number}> = ({x, y, a, children, color = C.accent, size = 44, rot = -2}) => (
  <div style={{position: 'absolute', left: x, top: y, fontFamily: F.hand, fontWeight: 700, fontSize: size, color, opacity: a,
    transform: `rotate(${rot}deg) translateY(${(1 - a) * 8}px)`, whiteSpace: 'nowrap'}}>{children}</div>
);

// ---------- synthetic room (SVG) ----------
export const Room: React.FC<{w: number; h: number; scan?: boolean; person?: boolean; feats?: number; featP?: number}> = ({w, h, scan, person = true}) => {
  const st = scan ? C.teal : 'none';
  const sw = scan ? 2 : 0;
  const r = rng(7);
  const dots = scan ? Array.from({length: 420}, () => [r() * w, r() * h]) : [];
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{display: 'block'}}>
      <defs>
        <linearGradient id="wall" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#c8bba6" /><stop offset="1" stopColor="#ad9f88" /></linearGradient>
        <linearGradient id="sky" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#d6e4ec" /><stop offset="1" stopColor="#eef0ea" /></linearGradient>
      </defs>
      {scan ? <rect width={w} height={h} fill="#0b1513" /> : <>
        <rect width={w} height={h * 0.62} fill="url(#wall)" />
        <rect y={h * 0.62} width={w} height={h * 0.38} fill="#6b5641" />
        <rect y={h * 0.62} width={w} height={h * 0.38} fill="url(#floorlines)" opacity={0.2} />
      </>}
      {/* window */}
      {!scan && <>
        <rect x={w * 0.56} y={h * 0.14} width={w * 0.3} height={h * 0.38} fill="url(#sky)" />
        <rect x={w * 0.575} y={h * 0.27} width={w * 0.1} height={h * 0.25} fill="#9aa5ad" />
        <rect x={w * 0.72} y={h * 0.33} width={w * 0.12} height={h * 0.19} fill="#8b959c" />
        <rect x={w * 0.56} y={h * 0.47} width={w * 0.3} height={h * 0.05} fill="#5d676c" />
      </>}
      <rect x={w * 0.56} y={h * 0.14} width={w * 0.3} height={h * 0.38} fill="none" stroke={scan ? st : '#f1ebe0'} strokeWidth={scan ? sw : w * 0.012} />
      <line x1={w * 0.71} y1={h * 0.14} x2={w * 0.71} y2={h * 0.52} stroke={scan ? st : '#f1ebe0'} strokeWidth={scan ? sw : w * 0.008} />
      {/* frame */}
      <rect x={w * 0.14} y={h * 0.2} width={w * 0.16} height={h * 0.2} fill={scan ? 'none' : '#3f3a35'} stroke={st} strokeWidth={sw} />
      {!scan && <rect x={w * 0.152} y={h * 0.22} width={w * 0.136} height={h * 0.16} fill="#8f8068" />}
      {/* bed */}
      {!scan && <rect x={w * 0.08} y={h * 0.43} width={w * 0.06} height={h * 0.34} fill="#4a3b30" />}
      <rect x={w * 0.12} y={h * 0.55} width={w * 0.5} height={h * 0.22} fill={scan ? 'none' : '#ebe5dc'} stroke={st} strokeWidth={sw} />
      {!scan && <rect x={w * 0.33} y={h * 0.55} width={w * 0.29} height={h * 0.22} fill="#8e9cae" />}
      {!scan && <rect x={w * 0.14} y={h * 0.57} width={w * 0.12} height={h * 0.07} fill="#f7f3ec" />}
      {/* lamp table */}
      <rect x={w * 0.66} y={h * 0.6} width={w * 0.12} height={h * 0.17} fill={scan ? 'none' : '#3d3128'} stroke={st} strokeWidth={sw} />
      <path d={`M${w * 0.69},${h * 0.47} L${w * 0.75},${h * 0.47} L${w * 0.76},${h * 0.55} L${w * 0.68},${h * 0.55}Z`} fill={scan ? 'none' : '#f2d595'} stroke={st} strokeWidth={sw} />
      {scan && <>
        {dots.map(([x, y], i) => <rect key={i} x={x} y={y} width={2} height={2} fill={C.teal} opacity={0.35} />)}
        <line x1={0} y1={h * 0.62} x2={w} y2={h * 0.62} stroke={C.teal} strokeOpacity={0.3} />
        {Array.from({length: 11}, (_, i) => <line key={i} x1={(w * i) / 10} y1={h * 0.62} x2={w * ((i / 10 - 0.5) * 2.4) + w / 2} y2={h} stroke={C.teal} strokeOpacity={0.2} />)}
      </>}
      {!scan && person && <g fill="rgba(92,96,104,.93)">
        <circle cx={w * 0.86} cy={h * 0.38} r={h * 0.06} />
        <rect x={w * 0.805} y={h * 0.455} width={w * 0.11} height={h * 0.42} rx={w * 0.04} />
      </g>}
    </svg>
  );
};
export const FEAT: [number, number][] = (() => {
  const r = rng(99); const f: [number, number][] = [];
  const g = [[0.56, 0.14, 0.3, 0.38], [0.14, 0.2, 0.16, 0.2], [0.12, 0.55, 0.5, 0.22], [0.66, 0.47, 0.12, 0.3], [0.08, 0.43, 0.06, 0.34]];
  for (let i = 0; i < 44; i++) { const q = g[i % g.length]; f.push([q[0] + r() * q[2], q[1] + r() * q[3]]); }
  return f;
})();

export const Polaroid: React.FC<{x: number; y: number; w: number; h: number; rot?: number; a?: number; caption?: string; children: React.ReactNode}> = ({x, y, w, h, rot = -2, a = 1, caption, children}) => (
  <div style={{position: 'absolute', left: x, top: y, width: w + 28, padding: '14px 14px 0', background: '#f3eee4', boxShadow: '0 18px 40px rgba(0,0,0,.45)',
    transform: `rotate(${rot}deg)`, opacity: a}}>
    <div style={{width: w, height: h, overflow: 'hidden'}}>{children}</div>
    <div style={{height: 64, fontFamily: F.hand, fontSize: 34, color: '#2b2722', display: 'flex', alignItems: 'center', paddingLeft: 6}}>{caption}</div>
  </div>
);

export const Card: React.FC<{x: number; y: number; w: number; h?: number; a?: number; style?: React.CSSProperties; children: React.ReactNode}> = ({x, y, w, h, a = 1, style, children}) => (
  <div style={{position: 'absolute', left: x, top: y, width: w, height: h, background: C.ink2, border: `1.5px solid ${C.line}`, borderRadius: 10,
    opacity: a, transform: `translateY(${(1 - a) * 18}px)`, boxShadow: '0 20px 40px rgba(0,0,0,.35)', ...style}}>{children}</div>
);

export {eo, P};
