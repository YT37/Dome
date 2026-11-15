import React from 'react';
import {AbsoluteFill, Sequence, Audio, staticFile, useCurrentFrame} from 'remotion';
import {C, F, FPS, SCENES, VO, HOOK, P} from './theme';
import {Grain} from './ui';
import * as Sc from './scenes';

const sceneFor: Record<string, React.FC<any>> = {
  cut: Sc.Cut, friend: Sc.Friend, problem: Sc.Problem, title: Sc.Title, pipeline: Sc.Pipeline, linker: Sc.Linker,
  zoner: Sc.Zoner, lister: Sc.Lister, locator: Sc.Locator, briefer: Sc.Briefer, run: Sc.Run, guard: Sc.Guard, close: Sc.Close,
};

const Local: React.FC<{name: string; d: number; i?: number}> = ({name, d, i}) => {
  const t = useCurrentFrame() / FPS;
  const Comp = name === 'hook' ? Sc.Hook : sceneFor[name];
  const fade = name === 'hook' || name === 'cut' || name === 'friend' ? 1 : Math.min(P(t, 0, 0.35), 1 - P(t, d - 0.25, d));
  return <AbsoluteFill style={{opacity: fade, background: '#000'}}><Comp t={t} d={d} i={i} /></AbsoluteFill>;
};

// word-by-word captions
const Captions: React.FC = () => {
  const t = useCurrentFrame() / FPS;
  for (let li = 0; li < VO.length; li++) {
    const v = VO[li];
    if (li === 0) continue; // the friend line is already on screen
    if (t < v.start || t > v.start + v.dur + 0.3) continue;
    const words = v.text.split(' ');
    const weights = words.map((w) => w.length + 2 + (/[.,]$/.test(w) ? 5 : 0));
    const tot = weights.reduce((a, b) => a + b, 0);
    let acc = v.start; const times = weights.map((w) => {const s = acc; acc += (w / tot) * v.dur; return s;});
    let cur = times.findIndex((s, i) => t >= s && (i === times.length - 1 || t < times[i + 1]));
    if (cur < 0) cur = words.length - 1;
    // chunk: break on punctuation or every ~7 words
    const chunks: number[][] = []; let c: number[] = [];
    words.forEach((w, i) => {c.push(i); if (/[.,?]$/.test(w) && c.length >= 3 || c.length >= 7) {chunks.push(c); c = [];}});
    if (c.length) chunks.push(c);
    const ch = chunks.find((k) => k.includes(cur)) || chunks[chunks.length - 1];
    return (
      <div style={{position: 'absolute', left: 0, right: 0, bottom: 70, display: 'flex', justifyContent: 'center'}}>
        <div style={{background: 'rgba(10,9,8,.72)', padding: '12px 26px', borderRadius: 12, fontFamily: F.sans, fontWeight: 600, fontSize: 40, color: C.paper, letterSpacing: -0.2}}>
          {ch.map((i) => (
            <span key={i} style={{color: i === cur ? C.accent : i < cur ? C.paper : 'rgba(239,231,218,.55)'}}>{words[i]} </span>
          ))}
        </div>
      </div>
    );
  }
  return null;
};

export const DomeVideo: React.FC = () => {
  let hookIdx = 0;
  return (
    <AbsoluteFill style={{background: '#000'}}>
      {SCENES.map(([name, a, b]) => {
        if (name === 'hook') {
          return HOOK.map((h, i) => (
            <Sequence key={'h' + i} from={Math.round(h.from * FPS)} durationInFrames={Math.round(h.dur * FPS)}>
              <Local name="hook" d={h.dur} i={i} />
            </Sequence>
          ));
        }
        return (
          <Sequence key={name} from={Math.round(a * FPS)} durationInFrames={Math.round((b - a) * FPS)}>
            <Local name={name} d={b - a} />
          </Sequence>
        );
      })}
      <Grain o={0.08} />
      <Captions />
      <Audio src={staticFile('music.wav')} volume={0.32} />
      {VO.map((v, i) => (
        <Sequence key={'vo' + i} from={Math.round(v.start * FPS)}>
          <Audio src={staticFile(`vo/l${String(i + 1).padStart(2, '0')}.wav`)} volume={1} />
        </Sequence>
      ))}
    </AbsoluteFill>
  );
};
