import React from 'react';
import {AbsoluteFill, OffthreadVideo, Img, staticFile} from 'remotion';
import {C, F, DATA, HOOK, ease, P, lerp, eio, eo, iv, rng} from './theme';
import {Paper, Kicker, Drift, Vignette, Sticky, Tape, Hand, Room, FEAT, Polaroid, Card, SketchLine, SketchCircle} from './ui';
import {City3D, Dome, Target, Marker, ZonePoly, ll2m} from './City3D';

type S = {t: number; d: number};

// ---------------- HOOK ----------------
export const Hook: React.FC<S & {i: number}> = ({t, d, i}) => {
  const h = HOOK[i];
  const push = 1.04 + t * 0.012;
  return (
    <AbsoluteFill style={{background: '#000'}}>
      <AbsoluteFill style={{transform: `scale(${push})`, filter: 'contrast(1.08) saturate(0.82) brightness(0.95)'}}>
        <OffthreadVideo src={staticFile(h.src)} startFrom={Math.round(h.start * 30)} volume={(f) => {const s = f / 30; const v = (h as any).vol as number[][]; let out = v[0][1]; for (let j = 0; j < v.length - 1; j++) if (s >= v[j][0] && s <= v[j + 1][0]) out = lerp(v[j][1], v[j + 1][1], (s - v[j][0]) / (v[j + 1][0] - v[j][0])); return out * Math.min(1, f / 5) * Math.min(1, (h.dur * 30 - f) / 8);}} />
      </AbsoluteFill>
      {h.blur && (
        // soften the small thumbnails in the France 24 frame; keep the code words readable
        <div style={{position: 'absolute', left: 120 * push, top: 100, width: 1500, height: 440, backdropFilter: 'blur(26px)', WebkitBackdropFilter: 'blur(26px)'}} />
      )}
      <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(0,0,0,.7) 0%, rgba(0,0,0,0) 28%, rgba(0,0,0,0) 70%, rgba(0,0,0,.45) 100%)'}} />
      {/* letterbox */}
      <div style={{position: 'absolute', left: 0, right: 0, top: 0, height: 64, background: '#000'}} />
      <div style={{position: 'absolute', left: 0, right: 0, bottom: 0, height: 64, background: '#000'}} />
      <div style={{position: 'absolute', left: 90, top: 96, opacity: ease(t, 0.15, 0.6)}}>
        <div style={{fontFamily: F.sans, fontSize: 22, letterSpacing: 4, color: C.dim, textTransform: 'uppercase', fontWeight: 600}}>Footage · {h.credit}</div>
        <div style={{fontFamily: F.serif, fontSize: 52, color: '#fff', marginTop: 6, textShadow: '0 2px 18px rgba(0,0,0,.6)'}}>{h.title}</div>
      </div>
      <Vignette s={0.6} />
    </AbsoluteFill>
  );
};

export const Cut: React.FC<S> = ({t}) => {
  const f = 1 - P(t, 0, 0.12);
  return <AbsoluteFill style={{background: '#000'}}><AbsoluteFill style={{background: '#fff', opacity: f * 0.85}} /></AbsoluteFill>;
};

// ---------------- FRIEND ----------------
export const Friend: React.FC<S> = ({t}) => {
  const l1 = 'A friend of ours was taken in high school.';
  const n = Math.floor(P(t, 0.25, 2.4) * l1.length);
  return (
    <AbsoluteFill style={{background: '#050505', alignItems: 'center', justifyContent: 'center'}}>
      <div style={{transform: `scale(${1 + t * 0.006})`, textAlign: 'center'}}>
        <div style={{fontFamily: F.serif, fontSize: 84, color: C.paper}}>{l1.slice(0, n)}<span style={{opacity: t % 1 < 0.5 && n < l1.length ? 1 : 0}}>|</span></div>
        <div style={{fontFamily: F.serif, fontStyle: 'italic', fontSize: 60, color: C.muted, marginTop: 26, opacity: ease(t, 2.9, 3.8)}}>For a whole year, nobody knew where she was.</div>
      </div>
    </AbsoluteFill>
  );
};

// ---------------- PROBLEM ----------------
const AdPost: React.FC<{seed: number; flag?: number}> = ({seed, flag = 0}) => {
  const r = rng(seed);
  const handle = ['sunny', 'luna', 'vip', 'rose', 'nina'][seed % 5] + '.' + ['rooms', 'new', 'city', 'tx'][seed % 4];
  return (
    <div style={{background: '#fbf8f3', borderRadius: 14, padding: 16, marginBottom: 18, boxShadow: '0 2px 0 rgba(0,0,0,.05)'}}>
      <div style={{display: 'flex', alignItems: 'center', gap: 10, fontFamily: F.sans, fontSize: 19, fontWeight: 600, color: '#2a2622'}}>
        <div style={{width: 34, height: 34, borderRadius: 17, background: '#cbbfae'}} />@{handle}
        {flag > 0 && <span style={{marginLeft: 'auto', fontFamily: F.hand, fontSize: 26, color: C.red, opacity: flag, transform: 'rotate(-6deg)'}}>flagged</span>}
      </div>
      <div style={{marginTop: 12, borderRadius: 8, overflow: 'hidden'}}><Room w={300} h={210} /></div>
      <div style={{marginTop: 12, height: 10, width: `${60 + r() * 30}%`, background: '#e2dad0', borderRadius: 5}} />
      <div style={{marginTop: 8, height: 10, width: `${40 + r() * 30}%`, background: '#e2dad0', borderRadius: 5}} />
      <div style={{marginTop: 10, fontFamily: F.mono, fontSize: 18, color: '#3a3530'}}>call 555-01{10 + Math.floor(r() * 89)}</div>
    </div>
  );
};
export const Problem: React.FC<S> = ({t}) => {
  const px = iv(t, [0, 1.1], [-520, 260]);
  const scroll = eio(P(t, 0.8, 4.6)) * 560;
  const k = eio(P(t, 4.3, 5.6));
  const k2 = ease(t, 7.0, 7.9);
  return (
    <Paper>
      <Drift>
        {/* phone */}
        <div style={{position: 'absolute', left: px, top: 120, width: 380, height: 800, borderRadius: 54, background: '#090807', border: '3px solid #3a342d', padding: 14, boxShadow: '0 40px 80px rgba(0,0,0,.6)'}}>
          <div style={{width: '100%', height: '100%', borderRadius: 42, overflow: 'hidden', background: '#ece6dc', padding: '40px 14px'}}>
            <div style={{transform: `translateY(${-scroll}px)`}}>
              {[201, 202, 203, 204].map((s, i) => <AdPost key={s} seed={s} flag={i === 1 ? ease(t, 2.3, 2.8) : 0} />)}
            </div>
          </div>
        </div>
        {/* lifted photo */}
        {k > 0 && <>
          <Polaroid x={lerp(300, 820, k)} y={lerp(380, 210, k)} w={lerp(300, 560, k)} h={lerp(210, 392, k)} rot={lerp(0, -3, k)} caption="">
            <Room w={560} h={392} />
          </Polaroid>
          <Tape x={lerp(380, 1010, k)} y={lerp(370, 190, k)} rot={-4} />
          <Hand x={850} y={720} a={ease(t, 5.4, 6.0)} color={C.green} size={56}>the photo ✓</Hand>
        </>}
        {k2 > 0 && <div style={{position: 'absolute', left: 1480, top: 230, opacity: k2, transform: `rotate(${2 + (1 - k2) * 4}deg)`}}>
          <div style={{width: 340, height: 400, background: '#1b1915', border: `2px dashed ${C.amber}`, borderRadius: 6, display: 'flex', alignItems: 'center', justifyContent: 'center',
            fontFamily: F.serif, fontSize: 280, color: C.amber, lineHeight: 1}}>?</div>
          <Hand x={10} y={420} a={ease(t, 7.7, 8.3)} color={C.amber} size={56}>the address… almost never</Hand>
        </div>}
      </Drift>
      <Vignette />
    </Paper>
  );
};

// ---------------- TITLE (3D) ----------------
export const Title: React.FC<S & {close?: boolean}> = ({t, d, close}) => {
  const z = eio(P(t, 0, close ? 4 : d + 0.5));
  const ang = lerp(-0.75, -0.25, z) + (close ? 0.6 : 0);
  const dist = lerp(3200, 1250, z), hgt = lerp(2300, 820, z);
  const cam = {pos: [Math.sin(ang) * dist, hgt, Math.cos(ang) * dist] as [number, number, number], look: [0, 30, 0] as [number, number, number], fov: 34};
  const k = eio(P(t, close ? 0.4 : 0.1, close ? 3.4 : d - 0.5));
  const r = lerp(1600, 60, k);
  const glow = close ? ease(t, 3.0, 3.8) : ease(t, d - 0.8, d - 0.2);
  const ta = 1;
  return (
    <AbsoluteFill>
      <City3D cam={cam}>
        <Target glow={glow} />
        <Dome r={r} spin={t * 0.15} a={ease(t, 0, 0.6)} />
      </City3D>
      <AbsoluteFill style={{background: 'radial-gradient(ellipse at 50% 55%, rgba(0,0,0,0) 40%, rgba(0,0,0,.65) 100%)'}} />
      {!close && <div style={{position: 'absolute', left: 0, right: 0, top: 120, textAlign: 'center', opacity: ta}}>
        <div style={{fontFamily: F.serif, fontStyle: 'italic', fontSize: 52, color: C.paper, marginTop: 16, opacity: ease(t, 0.2, 0.9)}}>a dome over the search area that shrinks to one building</div>
      </div>}
    </AbsoluteFill>
  );
};

// ---------------- PIPELINE ----------------
const NODES = [
  ['Linker', 'groups accounts into rings', 'rings.json', 'Arlequin'],
  ['Zoner', 'draws the search dome', 'zones.json', ''],
  ['Lister', 'buildings inside the dome', 'candidates.json', 'CoStar'],
  ['Locator', 'matches rooms + windows', 'matches.json', 'Matterport · Vexcel'],
  ['Briefer', 'ranks leads, with reasons', 'brief.json', ''],
];
export const Pipeline: React.FC<S> = ({t}) => {
  const nw = 300, gap = 44, x0 = (1920 - (nw * 5 + gap * 4)) / 2, y = 500;
  const act = P(t, 2.6, 7.2) * 5;
  return (
    <Paper>
      <Drift amt={0.6}>
        <Kicker t={t} n="how it works" title="Five agents, one supervisor." />
        <div style={{position: 'absolute', left: 560, top: 300, width: 800, padding: '22px 30px', border: `1.5px solid ${C.dim}`, borderRadius: 10, opacity: ease(t, 0.4, 1.0), textAlign: 'center'}}>
          <div style={{fontFamily: F.sans, fontWeight: 600, fontSize: 34, color: C.paper}}>LangChain deepagents supervisor</div>
          <div style={{fontFamily: F.sans, fontSize: 22, color: C.muted, marginTop: 6}}>plans the next step · checks every file · logs every decision</div>
        </div>
        <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
          {NODES.map((_, i) => <SketchLine key={i} seed={i + 4} pts={[[960, 400], [x0 + i * (nw + gap) + nw / 2, y - 8]]} p={ease(t, 0.8 + i * 0.15, 1.4 + i * 0.15)} color={C.muted} w={2} />)}
          <SketchLine seed={20} pts={[[x0 - 60, y + 130], [x0 + 5 * nw + 4 * gap + 60, y + 130]]} p={P(t, 2.4, 7.4)} color={C.accent} w={4} />
        </svg>
        {NODES.map(([n, s, file, sp], i) => {
          const a = ease(t, 0.7 + i * 0.18, 1.2 + i * 0.18); const on = act > i;
          return (
            <div key={n} style={{position: 'absolute', left: x0 + i * (nw + gap), top: y, width: nw, height: 260, padding: 24, boxSizing: 'border-box', background: on ? '#f1e9db' : C.ink2,
              color: on ? '#1d1a16' : C.paper, borderRadius: 8, border: `1.5px solid ${on ? '#f1e9db' : C.line}`, opacity: a, transform: `translateY(${(1 - a) * 20}px) rotate(${(i % 2 ? 0.6 : -0.5)}deg)`,
              boxShadow: '0 16px 30px rgba(0,0,0,.35)'}}>
              <div style={{fontFamily: F.hand, fontSize: 44, fontWeight: 700, color: C.accent, lineHeight: 1}}>{i + 1}</div>
              <div style={{fontFamily: F.serif, fontSize: 52, lineHeight: 1.1}}>{n}</div>
              <div style={{fontFamily: F.sans, fontSize: 21, opacity: 0.7, marginTop: 6}}>{s}</div>
              <div style={{fontFamily: F.mono, fontSize: 18, position: 'absolute', bottom: 22, opacity: 0.6}}>{file}</div>
              {sp && <div style={{position: 'absolute', top: 280, left: 0, right: 0, textAlign: 'center', fontFamily: F.hand, fontSize: 32, color: C.amber, opacity: ease(t, 1.8, 2.4)}}>{sp}</div>}
            </div>
          );
        })}
        <div style={{position: 'absolute', left: x0, top: 880, fontFamily: F.sans, fontSize: 26, color: C.muted, opacity: ease(t, 1.5, 2.1)}}>flagged accounts in</div>
        <div style={{position: 'absolute', right: x0, top: 880, fontFamily: F.sans, fontSize: 26, color: C.paper, opacity: ease(t, 6.4, 7.0)}}>a ranked list of buildings out, each with a reason</div>
      </Drift>
      <Vignette />
    </Paper>
  );
};

// ---------------- LINKER ----------------
const G = (() => {
  const r = rng(11); const nodes: any[] = [];
  for (let i = 0; i < 12; i++) { const a = (i / 12) * Math.PI * 2 + r() * 0.3, rad = 120 + r() * 110; nodes.push({ring: 1, sx: 140 + r() * 1050, sy: 300 + r() * 640, tx: 650 + Math.cos(a) * rad, ty: 620 + Math.sin(a) * rad * 0.8}); }
  for (let i = 0; i < 3; i++) { const a = -0.6 + i * 0.9; nodes.push({rec: 1, sx: 140 + r() * 1050, sy: 300 + r() * 640, tx: 650 + Math.cos(a) * 340, ty: 620 + Math.sin(a) * 300}); }
  for (let i = 0; i < 30; i++) { let x, y; do { x = 120 + r() * 1100; y = 300 + r() * 660; } while (Math.hypot(x - 650, (y - 620) * 1.2) < 350); nodes.push({sx: x, sy: y, tx: x, ty: y}); }
  const edges: [number, number, number][] = []; for (let i = 0; i < 12; i++) for (let j = i + 1; j < 12; j++) if (r() < 0.4 || j === i + 1) edges.push([i, j, r()]);
  return {nodes, edges, rec: [[12, 1], [12, 4], [13, 6], [14, 9], [13, 2]], weak: [[16, 20], [22, 27], [18, 31], [25, 35]]};
})();
const NOTES: [string, number][] = [['contact / phone', 0.9], ['money / wallet', 0.9], ['DM thread', 0.85], ['same room', 0.8], ['same photo', 0.8], ['device', 0.7], ['ad script', 0.6], ['writing style', 0.5], ['route', 0.5], ['merchant', 0.4]];
export const Linker: React.FC<S> = ({t}) => {
  const mv = eio(P(t, 6.2, 9.2));
  const pos = G.nodes.map((n) => [lerp(n.sx, n.tx, n.ring || n.rec ? mv : 0), lerp(n.sy, n.ty, n.ring || n.rec ? mv : 0)]);
  const wk = P(t, 9.4, 10.2) * (1 - P(t, 12.8, 13.6));
  const tags: [number, string, number, number][] = [[0, '555-0187', 2.3, -4], [3, 'wallet 7f3a', 3.2, 3], [5, 'photo #a91f', 4.1, -2], [8, 'same script, reworded', 5.2, 4]];
  return (
    <Paper>
      <Drift amt={0.5}>
        <Kicker t={t} n="1 · linker" title="Which accounts are one ring?" />
        <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
          {mv > 0.9 && <SketchCircle cx={650} cy={630} rx={330} ry={270} p={P(t, 9.0, 10.2)} color={C.accent} w={3} seed={9} />}
          {G.edges.map(([i, j, o], k) => { const p = P(t, 5.0 + o * 3, 5.6 + o * 3); if (p <= 0) return null; const [a, b] = pos[i], [e, f] = pos[j];
            return <line key={k} x1={a} y1={b} x2={lerp(a, e, p)} y2={lerp(b, f, p)} stroke={C.paper} strokeOpacity={0.45} strokeWidth={1.6} />; })}
          {G.rec.map(([i, j], k) => { const p = P(t, 10.3, 11.3); if (p <= 0) return null; const [a, b] = pos[i], [e, f] = pos[j];
            return <line key={k} x1={a} y1={b} x2={lerp(a, e, p)} y2={lerp(b, f, p)} stroke={C.amber} strokeOpacity={0.7} strokeWidth={1.8} />; })}
          {G.weak.map(([i, j], k) => { const [a, b] = pos[i], [e, f] = pos[j];
            return <line key={k} x1={a} y1={b} x2={e} y2={f} stroke={C.muted} strokeDasharray="6 8" strokeWidth={2} opacity={wk} />; })}
          {G.nodes.map((n, i) => { const a = ease(t, 0.2 + (i % 10) * 0.06, 0.8 + (i % 10) * 0.06); const [x, y] = pos[i];
            const col = n.rec && t > 10.3 ? C.amber : n.ring && t > 5 ? C.paper : '#5d574d';
            return <circle key={i} cx={x} cy={y} r={n.ring && t > 5 ? 11 : 8} fill={col} opacity={a} />; })}
        </svg>
        {tags.map(([i, s, t0, rot]) => { const a = ease(t, t0, t0 + 0.4) * (1 - P(t, 8.4, 9.0)); if (a <= 0) return null; const [x, y] = pos[i];
          return <Sticky key={s} x={x + 14} y={y - 86} text={s} a={a} rot={rot} w={s.length > 12 ? 250 : 170} size={28} />; })}
        {wk > 0 && <Hand x={880} y={250} a={wk} color={C.dim} size={36}>dashed: one kind = just a hint</Hand>}
        <Hand x={430} y={250} a={ease(t, 9.6, 10.2)} color={C.accent} size={46}>ring R-1 · 12 accounts · 0.95</Hand>
        <Hand x={1000} y={800} a={ease(t, 10.6, 11.2)} color={C.amber} size={38}>3 likely recruiters</Hand>
        {/* notebook */}
        <div style={{position: 'absolute', left: 1360, top: 250, width: 460, padding: '26px 30px', background: '#f1e9db', color: '#24201b', borderRadius: 6,
          transform: `rotate(1.2deg) translateY(${(1 - ease(t, 0.9, 1.5)) * 30}px)`, opacity: ease(t, 0.9, 1.5), boxShadow: '0 20px 40px rgba(0,0,0,.45)',
          backgroundImage: 'repeating-linear-gradient(180deg, transparent 0 45px, rgba(80,110,160,.18) 45px 46px)'}}>
          <div style={{fontFamily: F.hand, fontSize: 42, fontWeight: 700}}>sticky notes <span style={{fontSize: 28, opacity: 0.6}}>(weight)</span></div>
          {NOTES.map(([n, w], i) => (
            <div key={n} style={{display: 'flex', alignItems: 'center', height: 46, opacity: ease(t, 1.3 + i * 0.16, 1.7 + i * 0.16), fontFamily: F.sans, fontSize: 22}}>
              <div style={{width: 220}}>{n}</div>
              <div style={{width: 130, height: 8, background: 'rgba(0,0,0,.08)', borderRadius: 4}}><div style={{width: `${w * 100 * ease(t, 1.5 + i * 0.16, 2.3 + i * 0.16)}%`, height: 8, background: C.accent, borderRadius: 4}} /></div>
              <div style={{marginLeft: 16, fontFamily: F.mono, fontSize: 19, opacity: 0.6}}>{w}</div>
            </div>
          ))}
          <div style={{marginTop: 14, fontFamily: F.hand, fontSize: 40, fontWeight: 700, color: C.accent, opacity: ease(t, 11.7, 12.3), transform: 'rotate(-2deg)'}}>link = 2+ different kinds</div>
          <div style={{fontFamily: F.sans, fontSize: 19, opacity: ease(t, 12.6, 13.2) * 0.7}}>plus patterns: relay race · heartbeat · echo</div>
        </div>
      </Drift>
      <Vignette />
    </Paper>
  );
};

// ---------------- ZONER (3D) ----------------
const CLUES: [number, number, string, number][] = [[29.759, -95.363, 'Main Street Square', 0.4], [29.762, -95.36, 'Market Square Park', 0.9], [29.7552, -95.37, 'Downtown', 1.4], [29.768, -95.366, 'Downtown', 1.8], [29.765, -95.372, '"near the square"', 2.2]];
export const Zoner: React.FC<S> = ({t}) => {
  const ang = -0.35 + t * 0.03;
  const cam = {pos: [Math.sin(ang) * 2600 + 700, 3300, Math.cos(ang) * 2600] as [number, number, number], look: [700, 0, -300] as [number, number, number], fov: 40};
  const k = eio(P(t, 2.6, 4.2));
  return (
    <AbsoluteFill>
      <City3D cam={cam} fog={[2500, 7000]}>
        {CLUES.map(([la, lo, , t0], i) => { const [x, z] = ll2m(la, lo); return <Marker key={i} x={x} z={z} a={ease(t, t0, t0 + 0.4)} h={160} size={26} color={C.amber} />; })}
        <ZonePoly p={k} />
        <Dome r={950} x={700} z={-300} a={ease(t, 3.6, 4.8) * 0.8} spin={t * 0.1} />
      </City3D>
      <AbsoluteFill style={{background: 'radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 45%, rgba(0,0,0,.6) 100%)'}} />
      <Kicker t={t} n="2 · zoner" title="Where is the ring active?" />
      <Card x={1330} y={300} w={480} a={ease(t, 4.0, 4.6)} style={{padding: '24px 28px'}}>
        <div style={{fontFamily: F.serif, fontSize: 48, color: C.paper}}>Zone Z-1-1</div>
        <div style={{fontFamily: F.sans, fontSize: 23, color: C.dim, marginTop: 6}}>{DATA.zone.area_km2} km² · {Math.round(DATA.zone.weight_share * 100)}% of place-clue weight</div>
        <div style={{fontFamily: F.sans, fontSize: 23, color: C.dim, marginTop: 4}}>72 ads name Downtown landmarks</div>
        <div style={{fontFamily: F.sans, fontSize: 23, color: C.dim, marginTop: 4}}>area code 713: city-wide, weak</div>
      </Card>
      <Hand x={1340} y={560} a={ease(t, 5.0, 5.6)} color={C.accent} size={52}>an area, never a pin</Hand>
    </AbsoluteFill>
  );
};

// ---------------- LISTER (3D + list) ----------------
export const Lister: React.FC<S> = ({t}) => {
  const cs = [...DATA.cands].sort((a: any, b: any) => b.fit - a.fit || b.has_scan - a.has_scan);
  const filt = P(t, 3.0, 3.6);
  const ang = -0.6 + t * 0.04;
  const cam = {pos: [Math.sin(ang) * 1300 - 150, 900, Math.cos(ang) * 1300 + 50] as [number, number, number], look: [-150, 0, 50] as [number, number, number], fov: 40};
  return (
    <AbsoluteFill>
      <City3D cam={cam} fog={[1200, 4500]}>
        {cs.map((b: any, i: number) => { const [x, z] = ll2m(b.lat, b.lon); const good = b.fit >= 0.5 && b.has_scan;
          return <Marker key={b.property_id} x={x} z={z} h={good ? 220 : 160} size={good ? 22 : 16} color={good ? C.accent : '#cfc6b8'} a={ease(t, 0.5 + i * 0.15, 0.9 + i * 0.15) * (good ? 1 : 1 - filt * 0.75)} />; })}
        <ZonePoly p={1} a={0.5} />
      </City3D>
      <AbsoluteFill style={{background: 'linear-gradient(90deg, rgba(0,0,0,.55) 0%, rgba(0,0,0,0) 35%, rgba(0,0,0,0) 55%, rgba(0,0,0,.7) 100%)'}} />
      <Kicker t={t} n="3 · lister" title="Which buildings fit the photos?" />
      <Card x={1180} y={250} w={640} a={ease(t, 0.3, 0.8)} style={{padding: '24px 26px'}}>
        <div style={{fontFamily: F.serif, fontSize: 42, color: C.paper}}>CoStar buildings in the dome</div>
        <div style={{display: 'flex', gap: 10, marginTop: 12, flexWrap: 'wrap'}}>
          {['apartment', 'view from floors 3–5', 'balcony', 'street trees'].map((s, i) => (
            <span key={s} style={{fontFamily: F.hand, fontSize: 28, color: '#2a2412', background: C.sticky, padding: '2px 12px', transform: `rotate(${i % 2 ? 2 : -2}deg)`, opacity: ease(t, 1.6 + i * 0.2, 2.0 + i * 0.2)}}>{s}</span>
          ))}
        </div>
        <div style={{fontFamily: F.sans, fontSize: 19, color: C.muted, marginTop: 8, opacity: ease(t, 2, 2.5)}}>photo cues, read once by a vision model</div>
        {cs.map((b: any, i: number) => { const good = b.fit >= 0.5 && b.has_scan; const fa = good ? 1 : 1 - filt * 0.6;
          return (
            <div key={b.property_id} style={{display: 'flex', alignItems: 'center', height: 54, opacity: ease(t, 0.7 + i * 0.15, 1.1 + i * 0.15) * fa, borderTop: `1px solid ${C.line}`,
              background: good && filt > 0 ? `rgba(255,91,53,${0.12 * filt})` : 'transparent', paddingLeft: 8}}>
              <div style={{width: 150, fontFamily: F.mono, fontSize: 20, color: C.paper}}>{b.property_id}</div>
              <div style={{width: 240, fontFamily: F.sans, fontSize: 20, color: C.dim}}>{b.type.replace('_', ' ')} · {b.floors} fl</div>
              <div style={{width: 110, height: 8, background: C.line, borderRadius: 4}}><div style={{width: `${b.fit * 100 * ease(t, 1 + i * 0.15, 1.8 + i * 0.15)}%`, height: 8, borderRadius: 4, background: good ? C.accent : C.muted}} /></div>
              {b.has_scan && <div style={{marginLeft: 'auto', marginRight: 10, fontFamily: F.hand, fontSize: 28, color: C.teal, whiteSpace: 'nowrap'}}>3D scan</div>}
            </div>
          ); })}
      </Card>
    </AbsoluteFill>
  );
};

// ---------------- LOCATOR ----------------
export const Locator: React.FC<S> = ({t}) => {
  const ph1 = 1 - P(t, 5.0, 5.5), ph2 = P(t, 5.2, 5.7) * (1 - P(t, 8.7, 9.2)), ph3 = P(t, 8.9, 9.4);
  const n = Math.floor(FEAT.length * eo(P(t, 1, 4)));
  const aw = 700, ah = 490, ax = 140, bx = 1080, ay = 300;
  return (
    <Paper>
      <Drift amt={0.5}>
        <Kicker t={t} n="4 · locator" title="Which room? Which window?" />
        {ph1 > 0 && <AbsoluteFill style={{opacity: ph1}}>
          <Polaroid x={ax - 14} y={ay - 14} w={aw} h={ah} rot={-1.5} caption="ad photo (synthetic)"><Room w={aw} h={ah} /></Polaroid>
          <div style={{position: 'absolute', left: bx, top: ay, width: aw, height: ah, border: `1.5px solid ${C.teal}`, borderRadius: 6, overflow: 'hidden'}}><Room w={aw} h={ah} scan /></div>
          <div style={{position: 'absolute', left: bx, top: ay + ah + 22, fontFamily: F.sans, fontSize: 24, color: C.teal}}>Matterport scan · mp_4471 / sweep 12</div>
          <svg width={1920} height={1080} style={{position: 'absolute', inset: 0}}>
            {FEAT.slice(0, n).map(([fx, fy], i) => {
              const x1 = ax + fx * aw * Math.cos(-0.026) - (fy * ah) * Math.sin(-0.026), y1 = ay + fy * ah + fx * aw * Math.sin(-0.026);
              const x2 = bx + fx * aw, y2 = ay + fy * ah;
              return <g key={i}><line x1={x1} y1={y1} x2={x2} y2={y2} stroke={i % 3 ? C.amber : C.teal} strokeOpacity={0.5} strokeWidth={1.3} />
                <circle cx={x1} cy={y1} r={3} fill="#fff" /><circle cx={x2} cy={y2} r={3} fill="#fff" /></g>;
            })}
          </svg>
          <div style={{position: 'absolute', left: 0, right: 0, top: 800, textAlign: 'center', opacity: ease(t, 2.4, 3)}}>
            <span style={{fontFamily: F.serif, fontSize: 64, color: C.paper}}>room match </span>
            <span style={{fontFamily: F.mono, fontSize: 52, color: C.accent}}>P {(0.78 * eo(P(t, 2.4, 4))).toFixed(2)}</span>
            <span style={{fontFamily: F.sans, fontSize: 24, color: C.muted, marginLeft: 22}}>{Math.round(376 * eo(P(t, 1, 4)))} matched points</span>
          </div>
        </AbsoluteFill>}
        {ph2 > 0 && <AbsoluteFill style={{opacity: ph2}}>
          <Polaroid x={160} y={280} w={520} h={440} rot={-2} caption="window crop from the ad">
            <div style={{width: 520, height: 440, overflow: 'hidden', position: 'relative'}}>
              <div style={{position: 'absolute', left: -0.56 * 1730, top: -0.14 * 1158}}><Room w={1730} h={1158} person={false} /></div>
            </div>
          </Polaroid>
          <div style={{position: 'absolute', left: 1000, top: 290, width: 760, height: 470, borderRadius: 6, overflow: 'hidden', border: `1.5px solid ${C.teal}`}}>
            <svg width={760} height={470}>
              <rect width={760} height={470} fill="#22262a" />
              <g transform="translate(380 235) rotate(-20)">
                <rect x={-600} y={-40} width={1200} height={90} fill="#3a3f45" />
                {Array.from({length: 20}, (_, i) => <rect key={i} x={-600 + i * 60} y={2} width={30} height={5} fill="#d9c770" />)}
                <rect x={-300} y={70} width={420} height={170} fill="#34393f" />
                {Array.from({length: 12}, (_, i) => <line key={i} x1={-290 + i * 36} y1={80} x2={-290 + i * 36} y2={150} stroke="#c9ced4" strokeWidth={2} />)}
                <rect x={-340} y={-260} width={300} height={190} fill="#4b5058" />
                {Array.from({length: 8}, (_, i) => <circle key={i} cx={-200 + i * 70} cy={-60} r={18} fill="#3d6b4b" />)}
              </g>
              <path d="M418,56 L114,446 L646,446Z" fill={C.accent} opacity={0.18 * ease(t, 5.8, 6.6)} />
            </svg>
          </div>
          <div style={{position: 'absolute', left: 1000, top: 775, fontFamily: F.sans, fontSize: 24, color: C.teal}}>Vexcel aerial · looking out from the scan</div>
          {[['road in front ✓', C.green], ['parking in front ✓', C.green], ['building across: not seen', C.dim]].map(([s, col], i) => (
            <Hand key={i} x={1030 + (i % 2) * 330} y={310 + Math.floor(i / 2) * 60} a={ease(t, 6.2 + i * 0.4, 6.6 + i * 0.4)} color={col as string} size={38} rot={i % 2 ? 2 : -2}>{s}</Hand>
          ))}
          <div style={{position: 'absolute', left: 0, right: 0, top: 800, textAlign: 'center', opacity: ease(t, 7.2, 7.8)}}>
            <span style={{fontFamily: F.serif, fontSize: 64, color: C.paper}}>window check </span>
            <span style={{fontFamily: F.mono, fontSize: 52, color: C.accent}}>W 0.67</span>
          </div>
        </AbsoluteFill>}
        {ph3 > 0 && <AbsoluteFill style={{opacity: ph3}}>
          <GpsFix t={t - 9} />
        </AbsoluteFill>}
      </Drift>
      <Vignette />
    </Paper>
  );
};
const GpsFix: React.FC<{t: number}> = ({t}) => {
  const k = eio(P(t, 0.4, 1.6));
  const cam = {pos: [-260, 900, 520] as [number, number, number], look: [-60, 0, -20] as [number, number, number], fov: 40};
  const [ox, oz] = [-110, -130];
  return (
    <AbsoluteFill>
      <City3D cam={cam} fog={[800, 3000]}>
        <Target glow={0.9} />
        <Marker x={ox} z={oz} h={110} size={14} color={'#9a9286'} a={1 - k * 0.5} />
        <Marker x={lerp(ox, 0, k)} z={lerp(oz, 0, k)} h={130} size={18} color={C.teal} />
      </City3D>
      <AbsoluteFill style={{background: 'radial-gradient(ellipse at 50% 50%, rgba(0,0,0,0) 45%, rgba(0,0,0,.6) 100%)'}} />
      <Kicker t={10} n="4 · locator" title="Which room? Which window?" />
      <Hand x={1180} y={420} a={ease(t, 0.6, 1.2)} color={C.amber} size={46}>scan GPS was {Math.round(139 * k)} m off</Hand>
      <div style={{position: 'absolute', left: 0, right: 0, top: 800, textAlign: 'center', opacity: ease(t, 1.4, 2)}}>
        <span style={{fontFamily: F.serif, fontSize: 64, color: C.paper}}>scan location fixed </span>
        <span style={{fontFamily: F.mono, fontSize: 48, color: C.teal}}>± 12 m</span>
      </div>
    </AbsoluteFill>
  );
};

// ---------------- BRIEFER ----------------
export const Briefer: React.FC<S> = ({t}) => {
  const L = DATA.lead; const f = L.factors; const names: any = {R: 'ring', Z: 'zone', F: 'fit', P: 'room', W: 'window'};
  const a = ease(t, 0.15, 0.7);
  const reasons = ['12 accounts share a phone, photos and one script', 'room photos match the unit scan (376 points)', 'window view: road and parking in front', 'a 6-floor apartment fits a floor 3–5 view'];
  return (
    <Paper>
      <Drift amt={0.5}>
        <Kicker t={t} n="5 · briefer" title="How strong is each lead, and why?" />
        <div style={{position: 'absolute', left: 190, top: 290, width: 1540, height: 560, background: '#f1e9db', color: '#1d1a16', borderRadius: 4, padding: '36px 48px', boxSizing: 'border-box',
          opacity: a, transform: `translateY(${(1 - a) * 30}px) rotate(-0.6deg)`, boxShadow: '0 30px 60px rgba(0,0,0,.5)'}}>
          <div style={{display: 'flex', alignItems: 'baseline', gap: 20}}>
            <div style={{fontFamily: F.serif, fontSize: 60}}>#1 Building A</div>
            <div style={{fontFamily: F.mono, fontSize: 20, opacity: 0.6}}>CS-88412 · zone Z-1-1 · scan mp_4471 · synthetic case</div>
          </div>
          <div style={{position: 'absolute', right: 56, top: 26, textAlign: 'right'}}>
            <div style={{fontFamily: F.serif, fontSize: 130, lineHeight: 1}}>{Math.round(66 * eo(P(t, 0.5, 2.6)))}</div>
            <div style={{fontFamily: F.sans, fontSize: 18, opacity: 0.6}}>score / 100</div>
          </div>
          <div style={{position: 'absolute', right: 240, top: 50, fontFamily: F.hand, fontWeight: 700, fontSize: 64, color: C.red, transform: `rotate(-8deg) scale(${lerp(1.6, 1, ease(t, 2.4, 2.9))})`, opacity: ease(t, 2.4, 2.8),
            border: `4px solid ${C.red}`, padding: '0 18px', borderRadius: 10}}>HIGH</div>
          <div style={{display: 'flex', marginTop: 50}}>
            <div style={{width: 600}}>
              {['R', 'Z', 'F', 'P', 'W'].map((k, i) => (
                <div key={k} style={{display: 'flex', alignItems: 'center', height: 62, opacity: ease(t, 0.7 + i * 0.18, 1.1 + i * 0.18)}}>
                  <div style={{width: 160, fontFamily: F.sans, fontSize: 25, fontWeight: 600}}>{k} <span style={{fontWeight: 400, opacity: 0.6}}>{names[k]}</span></div>
                  <div style={{width: 300, height: 10, background: 'rgba(0,0,0,.08)', borderRadius: 5}}><div style={{width: `${(f as any)[k] * 100 * ease(t, 0.9 + i * 0.18, 1.8 + i * 0.18)}%`, height: 10, borderRadius: 5, background: (f as any)[k] >= 0.6 ? '#1d1a16' : C.amber}} /></div>
                  <div style={{marginLeft: 18, fontFamily: F.mono, fontSize: 22}}>{(f as any)[k].toFixed(2)}</div>
                </div>
              ))}
            </div>
            <div style={{flex: 1, paddingLeft: 30, borderLeft: '1px solid rgba(0,0,0,.12)'}}>
              {reasons.map((s, i) => <div key={i} style={{fontFamily: F.sans, fontSize: 25, lineHeight: 1.25, marginBottom: 20, opacity: ease(t, 1.8 + i * 0.35, 2.3 + i * 0.35)}}>— {s}</div>)}
              <div style={{fontFamily: F.hand, fontSize: 34, color: C.accent, opacity: ease(t, 3.6, 4.2), transform: 'rotate(-1deg)'}}>next: through legal process, booking records for floors 3–5</div>
            </div>
          </div>
        </div>
        <div style={{position: 'absolute', left: 0, right: 0, top: 900, textAlign: 'center', fontFamily: F.mono, fontSize: 22, color: C.muted, opacity: ease(t, 3.2, 3.8)}}>
          score = 100 · R · (0.15 Z + 0.10 F + 0.45 P + 0.30 W) &nbsp;·&nbsp; High needs a room AND a window match
        </div>
      </Drift>
      <Vignette />
    </Paper>
  );
};

// ---------------- REAL RUN ----------------
const TERM = ['$ python -m dome.supervisor --case synth-a --data synth --scripted', '', 'Case synth-a  (scripted)', 'Status: complete   ring: R-1   zones: Z-1-1',
  '  #1 CS-88412  High   score  66  zone Z-1-1', '     R 0.95 Z 0.41 F 0.8 P 0.78 W 0.67', '', 'Leads for human verification. Not evidence', "of anyone's presence. Generated from synthetic data."];
export const Run: React.FC<S> = ({t}) => {
  const chars = Math.floor(P(t, 0.3, 1.9) * TERM[0].length);
  const k = eio(P(t, 3.0, 4.2));
  const stats: [string, string, number][] = [['12 accounts', '1 ring', 0.4], ['10 km²', '7 buildings', 2.6], ['1 building', 'High · 66', 5.3]];
  return (
    <Paper>
      <Drift amt={0.4}>
        <Kicker t={t} n="real run" title="Our test case, end to end" />
        <div style={{position: 'absolute', left: 100, top: 280, width: 900, height: 470, background: '#0a0908', border: `1.5px solid ${C.line}`, borderRadius: 10, padding: '54px 28px', boxSizing: 'border-box', opacity: ease(t, 0, 0.4)}}>
          <div style={{position: 'absolute', top: 18, left: 22, display: 'flex', gap: 9}}>{['#ff5f57', '#febc2e', '#28c840'].map((c) => <div key={c} style={{width: 13, height: 13, borderRadius: 7, background: c}} />)}</div>
          {TERM.map((l, i) => (
            <div key={i} style={{fontFamily: F.mono, fontSize: 19, height: 40, color: i === 0 ? '#e8e0d2' : l.includes('High') ? C.accent : '#a69e90', opacity: i === 0 ? 1 : P(t, 2.0 + i * 0.16, 2.2 + i * 0.16), whiteSpace: 'pre'}}>
              {i === 0 ? l.slice(0, chars) : l}
            </div>
          ))}
        </div>
        {k > 0 && <div style={{position: 'absolute', left: lerp(1960, 1060, k), top: 270, width: 780, height: 500, overflow: 'hidden', borderRadius: 6, transform: 'rotate(1.2deg)', boxShadow: '0 30px 60px rgba(0,0,0,.55)'}}>
          <Img src={staticFile('summary.png')} style={{width: 780}} />
        </div>}
        {k > 0 && <Hand x={1080} y={790} a={ease(t, 4.0, 4.6)} color={C.dim} size={34}>the Briefer's summary page</Hand>}
        {stats.map(([a1, b1, t0], i) => (
          <div key={i} style={{position: 'absolute', left: 100 + i * 600, top: 860, width: 560, opacity: ease(t, t0, t0 + 0.5), transform: `translateY(${(1 - ease(t, t0, t0 + 0.5)) * 16}px)`}}>
            <span style={{fontFamily: F.serif, fontSize: 56, color: C.paper}}>{a1}</span>
            <span style={{fontFamily: F.hand, fontSize: 50, color: C.accent, marginLeft: 18}}>→ {b1}</span>
          </div>
        ))}
      </Drift>
      <Vignette />
    </Paper>
  );
};

// ---------------- GUARDRAILS ----------------
export const Guard: React.FC<S> = ({t}) => {
  const rows = [['A lead, for a human to verify.', 'Every result says what would confirm it or rule it out.'], ["It can't contact or dispatch anyone.", 'No email, no posting, no messages. It stops at the brief.'], ['Every decision is logged.', 'Each query, weight and decision goes into log.jsonl.']];
  return (
    <Paper>
      <Drift amt={0.5}>
        <Kicker t={t} n="guardrails" title="Built for analysts, not for action." />
        {rows.map(([a, b], i) => { const t0 = 0.3 + i * 1.7; return (
          <div key={i} style={{position: 'absolute', left: 200, top: 320 + i * 150, opacity: ease(t, t0, t0 + 0.5)}}>
            <svg width={70} height={70} style={{position: 'absolute', left: -90, top: 2}}>
              <SketchLine pts={[[10, 36], [26, 54], [60, 12]]} p={P(t, t0 + 0.2, t0 + 0.7)} color={C.accent} w={6} seed={i + 30} />
            </svg>
            <div style={{fontFamily: F.serif, fontSize: 62, color: C.paper}}>{a}</div>
            <div style={{fontFamily: F.sans, fontSize: 26, color: C.muted, marginTop: 2}}>{b}</div>
          </div>
        ); })}
        <div style={{position: 'absolute', left: 1180, top: 330, width: 640, padding: 22, background: '#0a0908', border: `1px solid ${C.line}`, borderRadius: 8, opacity: ease(t, 4.8, 5.4)}}>
          {DATA.log.slice(Math.floor(P(t, 5, 8.2) * 5), Math.floor(P(t, 5, 8.2) * 5) + 7).map((l: string, i: number) => {
            const j = JSON.parse(l);
            return <div key={i} style={{fontFamily: F.mono, fontSize: 16, color: '#8f877a', height: 34, whiteSpace: 'nowrap', overflow: 'hidden'}}>{j.ts.slice(11, 19)}  {j.event.padEnd(12)} {String(j.step ?? '').padEnd(8)} {j.message.slice(0, 34)}</div>;
          })}
        </div>
        <div style={{position: 'absolute', left: 0, right: 0, top: 860, textAlign: 'center', fontFamily: F.hand, fontSize: 46, color: C.dim, opacity: ease(t, 6.0, 6.6)}}>synthetic accounts · real building data · residents never looked up</div>
      </Drift>
      <Vignette />
    </Paper>
  );
};

// ---------------- CLOSE ----------------
export const Close: React.FC<S> = ({t, d}) => {
  const sp = ['CoStar', 'Matterport', 'Vexcel', 'LangChain deepagents', 'Arlequin'];
  return (
    <AbsoluteFill>
      <Title t={t} d={d} close />
      <AbsoluteFill style={{background: `rgba(0,0,0,${0.4 * ease(t, 0.6, 1.6)})`}} />
      <AbsoluteFill style={{background: 'linear-gradient(180deg, rgba(0,0,0,0) 50%, rgba(0,0,0,.75) 85%)', opacity: ease(t, 3, 4)}} />
      <div style={{position: 'absolute', left: 0, right: 0, top: 150, textAlign: 'center', opacity: ease(t, 0.8, 1.8)}}>
        <div style={{fontFamily: F.serif, fontSize: 210, color: C.paper, lineHeight: 0.9}}>Dome</div>
        <div style={{fontFamily: F.serif, fontStyle: 'italic', fontSize: 58, color: C.dim, marginTop: 12, opacity: ease(t, 1.6, 2.4)}}>Find the room. Find the person.</div>
      </div>
      <div style={{position: 'absolute', left: 0, right: 0, top: 700, textAlign: 'center', opacity: ease(t, 3.4, 4.0)}}>
        <div style={{fontFamily: F.sans, fontSize: 20, letterSpacing: 6, color: C.muted, fontWeight: 600}}>BUILT WITH</div>
        <div style={{display: 'flex', justifyContent: 'center', gap: 60, marginTop: 14}}>
          {sp.map((s, i) => <div key={s} style={{fontFamily: F.sans, fontWeight: 600, fontSize: 36, color: C.paper, opacity: ease(t, 3.6 + i * 0.15, 4.1 + i * 0.15)}}>{s}</div>)}
        </div>
        <div style={{fontFamily: F.sans, fontSize: 26, color: C.muted, marginTop: 40, opacity: ease(t, 4.6, 5.2)}}>HackPrinceton 2026 · Avishek · Ishaan · Yug</div>
      </div>
      <AbsoluteFill style={{background: '#000', opacity: P(t, d - 0.9, d)}} />
    </AbsoluteFill>
  );
};

// ---------------- REVEAL (cinematic title card in the spirit of a streaming intro) ----------------
export const Reveal: React.FC<S> = ({t, d}) => {
  const r = rng(5);
  const ribbons = Array.from({length: 46}, (_, i) => ({x: 760 + r() * 400, w: 3 + r() * 16, hue: r(), delay: r() * 0.5, sp: 0.6 + r() * 0.8}));
  const colors = ['#ff5b35', '#ffb36b', '#e94a2f', '#ffd7a8', '#c23a22', '#5cc2ad'];
  // phase 1 (0-1.1s): letters build up from light; phase 2 (1.6-2.6s): ribbons rush out and the camera pushes through
  const build = eo(P(t, 0.1, 1.2));
  const push = eio(P(t, 1.7, d));
  const scale = lerp(1.25, 1, build) * lerp(1, 7, push);
  const glow = 1 - P(t, 0.9, 1.6);
  return (
    <AbsoluteFill style={{background: '#000', overflow: 'hidden'}}>
      <AbsoluteFill style={{transform: `scale(${lerp(1, 4, push)})`, transformOrigin: '50% 50%', opacity: 1 - P(t, d - 0.35, d)}}>
        {ribbons.map((b, i) => {
          const p = P(t, 1.5 + b.delay * 0.6, 2.6 + b.delay * 0.6);
          const x = lerp(b.x, b.x + (b.x - 960) * 5, eio(p));
          const op = P(t, 1.4 + b.delay * 0.4, 1.7 + b.delay * 0.4) * (1 - P(t, 2.7, 3.1));
          return <div key={i} style={{position: 'absolute', left: x, top: 0, width: b.w * lerp(1, 6, p), height: 1080, opacity: op,
            background: `linear-gradient(180deg, transparent, ${colors[i % colors.length]} 30%, ${colors[(i + 2) % colors.length]} 70%, transparent)`, filter: 'blur(1.5px)'}} />;
        })}
      </AbsoluteFill>
      <AbsoluteFill style={{alignItems: 'center', justifyContent: 'center', opacity: P(t, 0.05, 0.4) * (1 - P(t, 2.0, 2.5))}}>
        <div style={{fontFamily: F.serif, fontSize: 300, color: C.paper, letterSpacing: lerp(60, 8, build), transform: `scale(${scale})`,
          textShadow: `0 0 ${40 + glow * 80}px rgba(255,120,70,${0.35 + glow * 0.5}), 0 0 ${10 + glow * 20}px rgba(255,200,160,${0.4 * glow})`}}>DOME</div>
      </AbsoluteFill>
      <AbsoluteFill style={{background: `radial-gradient(ellipse at 50% 50%, rgba(255,110,60,${0.25 * glow * build}) 0%, rgba(0,0,0,0) 45%)`}} />
    </AbsoluteFill>
  );
};
