import React, {useMemo, useLayoutEffect, useRef} from 'react';
import {ThreeCanvas} from '@remotion/three';
import {useThree} from '@react-three/fiber';
import * as THREE from 'three';
import {Line} from '@react-three/drei';
import {C, DATA, W, H, rng} from './theme';

// metres around the matched building (x east, z south)
const LAT0 = 29.7603, LON0 = -95.3681;
export const ll2m = (lat: number, lon: number): [number, number] => [
  (lon - LON0) * 111320 * Math.cos((LAT0 * Math.PI) / 180), -(lat - LAT0) * 110540];

type B = {x: number; z: number; w: number; d: number; h: number; c: number};
const BUILDINGS: B[] = (() => {
  const r = rng(42); const out: B[] = [];
  const xs: number[] = [], zs: number[] = [];
  for (let x = -2600; x < 2600; x += 90 + r() * 80) xs.push(x);
  for (let z = -2600; z < 2600; z += 90 + r() * 80) zs.push(z);
  for (let i = 0; i < xs.length - 1; i++) for (let j = 0; j < zs.length - 1; j++) {
    const x0 = xs[i] + 12, x1 = xs[i + 1] - 12, z0 = zs[j] + 12, z1 = zs[j + 1] - 12;
    const cx = (x0 + x1) / 2, cz = (z0 + z1) / 2; const dist = Math.hypot(cx - 250, cz + 150);
    if (Math.abs(cx) < 60 && Math.abs(cz) < 60) continue; // keep target block clear
    if (r() < 0.08) continue;
    const tall = dist < 700 ? 1 : dist < 1500 ? 0.45 : 0.2;
    const parts = r() < 0.5 ? 1 : 2;
    for (let k = 0; k < parts; k++) {
      const pw = parts === 1 ? x1 - x0 : (x1 - x0) / 2 - 6;
      const px = parts === 1 ? cx : x0 + pw / 2 + k * (pw + 12);
      const h = 8 + Math.pow(r(), 2.4) * 120 * tall + (r() < 0.025 * tall ? 90 : 0);
      if (dist > 2600) continue;
      out.push({x: px, z: cz, w: pw * (0.75 + r() * 0.25), d: (z1 - z0) * (0.7 + r() * 0.3), h, c: r()});
    }
  }
  return out;
})();

const Buildings: React.FC = () => {
  const ref = useRef<THREE.InstancedMesh>(null);
  useLayoutEffect(() => {
    const m = new THREE.Matrix4(); const col = new THREE.Color();
    BUILDINGS.forEach((b, i) => {
      m.compose(new THREE.Vector3(b.x, b.h / 2, b.z), new THREE.Quaternion(), new THREE.Vector3(b.w, b.h, b.d));
      ref.current!.setMatrixAt(i, m);
      col.setHSL(0.08, 0.06 + b.c * 0.05, 0.16 + b.c * 0.12);
      ref.current!.setColorAt(i, col);
    });
    ref.current!.instanceMatrix.needsUpdate = true;
    if (ref.current!.instanceColor) ref.current!.instanceColor.needsUpdate = true;
  }, []);
  return (
    <instancedMesh ref={ref} args={[undefined as any, undefined as any, BUILDINGS.length]}>
      <boxGeometry args={[1, 1, 1]} />
      <meshStandardMaterial roughness={0.9} metalness={0.05} />
    </instancedMesh>
  );
};

export type Cam = {pos: [number, number, number]; look: [number, number, number]; fov?: number};
const CamRig: React.FC<{cam: Cam}> = ({cam}) => {
  const {camera} = useThree();
  useLayoutEffect(() => {
    camera.position.set(...cam.pos);
    (camera as THREE.PerspectiveCamera).fov = cam.fov ?? 40;
    camera.near = 2; camera.far = 30000;
    camera.lookAt(...cam.look);
    camera.updateProjectionMatrix();
  });
  return null;
};

export const Dome: React.FC<{r: number; x?: number; z?: number; a?: number; spin?: number}> = ({r, x = 0, z = 0, a = 1, spin = 0}) => {
  if (r < 1) return null;
  return (
    <group position={[x, 0, z]} rotation={[0, spin, 0]}>
      <mesh scale={[r, r * 0.82, r]}>
        <sphereGeometry args={[1, 48, 24, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <meshStandardMaterial color={C.teal} transparent opacity={0.1 * a} side={THREE.DoubleSide} depthWrite={false} emissive={C.teal} emissiveIntensity={0.25} />
      </mesh>
      <mesh scale={[r * 1.001, r * 0.821, r * 1.001]}>
        <sphereGeometry args={[1, 18, 7, 0, Math.PI * 2, 0, Math.PI / 2]} />
        <meshBasicMaterial color={'#bfeee4'} wireframe transparent opacity={0.32 * a} depthWrite={false} />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 1.5, 0]}>
        <ringGeometry args={[r * 0.985, r * 1.01, 128]} />
        <meshBasicMaterial color={'#c9f3ea'} transparent opacity={0.85 * a} depthWrite={false} />
      </mesh>
    </group>
  );
};

export const Target: React.FC<{glow: number}> = ({glow}) => {
  const col = new THREE.Color('#3a332b').lerp(new THREE.Color(C.accent), glow);
  return (
    <mesh position={[0, 30, 0]}>
      <boxGeometry args={[70, 60, 55]} />
      <meshStandardMaterial color={col} emissive={C.accent} emissiveIntensity={glow * 0.9} roughness={0.7} />
    </mesh>
  );
};

export const Marker: React.FC<{x: number; z: number; h?: number; color?: string; a?: number; size?: number}> = ({x, z, h = 70, color = C.amber, a = 1, size = 14}) => (
  <group position={[x, 0, z]}>
    <mesh position={[0, h / 2, 0]}><cylinderGeometry args={[1.6, 1.6, h, 6]} /><meshBasicMaterial color={color} transparent opacity={a} /></mesh>
    <mesh position={[0, h, 0]}><sphereGeometry args={[size, 16, 12]} /><meshStandardMaterial color={color} emissive={color} emissiveIntensity={0.6} transparent opacity={a} /></mesh>
  </group>
);

export const ZonePoly: React.FC<{p: number; a?: number}> = ({p, a = 1}) => {
  const pts = useMemo(() => DATA.poly.map(([la, lo]: number[]) => {const [x, z] = ll2m(la, lo); return new THREE.Vector3(x, 3, z);}), []);
  if (p <= 0) return null;
  // draw partial outline
  const total = pts.length - 1; const upto = p * total; const n = Math.floor(upto);
  const seg = pts.slice(0, n + 1);
  if (n < total) seg.push(pts[n].clone().lerp(pts[n + 1], upto - n));
  return <Line points={seg} color={C.accent} lineWidth={4} transparent opacity={a} />;
};

export const City3D: React.FC<{cam: Cam; children?: React.ReactNode; fog?: [number, number]}> = ({cam, children, fog = [900, 4200]}) => (
  <ThreeCanvas width={W} height={H} style={{position: 'absolute', inset: 0}} gl={{antialias: true}} dpr={1}>
    <color attach="background" args={['#0d0c0a']} />
    <fog attach="fog" args={['#0d0c0a', fog[0], fog[1]]} />
    <CamRig cam={cam} />
    <ambientLight intensity={0.55} color={'#fff1e0'} />
    <hemisphereLight args={['#ffe6c7', '#1a1612', 0.6]} />
    <directionalLight position={[-900, 1200, 600]} intensity={1.5} color={'#ffd9b0'} />
    <directionalLight position={[800, 500, -900]} intensity={0.45} color={'#9fc4ff'} />
    <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, 0, 0]}>
      <planeGeometry args={[9000, 9000]} />
      <meshStandardMaterial color={'#15130f'} roughness={1} />
    </mesh>
    {/* bayou */}
    <mesh rotation={[-Math.PI / 2, 0, -0.18]} position={[0, 0.5, -1150]}>
      <planeGeometry args={[7000, 70]} />
      <meshStandardMaterial color={'#1d2a33'} roughness={0.4} />
    </mesh>
    <Buildings />
    {children}
  </ThreeCanvas>
);
