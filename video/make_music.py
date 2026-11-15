import numpy as np, wave
SR=48000; D=117.80; n=int(SR*D); t=np.arange(n)/SR
rng=np.random.default_rng(1)
END=117.80; CLOSE=108.05
# riser into the reveal

def env(a,b,fi=1.0,fo=1.0):
    e=np.clip((t-a)/fi,0,1)*np.clip((b-t)/fo,0,1); return e
def lp(x,k):  # one-pole lowpass via cumulative trick (simple)
    y=np.empty_like(x); acc=0.0; a=k
    for i in range(0,len(x),1024):
        seg=x[i:i+1024]; out=np.empty_like(seg)
        for j,v in enumerate(seg): acc+=a*(v-acc); out[j]=acc
        y[i:i+1024]=out
    return y
out=np.zeros(n)
# low drone throughout (A minor-ish), slow LFO
lfo=0.6+0.4*np.sin(2*np.pi*t/7.0)
drone=(np.sin(2*np.pi*55*t)+.6*np.sin(2*np.pi*82.41*t+1)+.35*np.sin(2*np.pi*110*t+2))*lfo
dr_env=np.maximum(env(0,30.0,1.5,.05)*0.35, env(33.2,END,2.0,2.5)*0.55)
out+=drone*dr_env*0.12
# heartbeat in intro
for k in np.arange(0.4,29.6,0.86):
    for off,amp in((0,1),(0.18,.6)):
        s=int((k+off)*SR); L=int(.25*SR); tt=np.arange(L)/SR
        out[s:s+L]+=amp*np.sin(2*np.pi*(50+40*np.exp(-tt*30))*tt)*np.exp(-tt*18)*0.35*min(1,(k+1)/4)
# boom hits
def boom(at,amp=1.0):
    s=int(at*SR); L=int(3*SR); tt=np.arange(L)/SR
    sig=np.sin(2*np.pi*(30+70*np.exp(-tt*6))*tt)*np.exp(-tt*1.6)
    nz=rng.standard_normal(L)*np.exp(-tt*9)*0.25
    e=min(L,n-s); out[s:s+e]+=amp*(sig+nz)[:e]
boom(30.0,1.0); boom(33.2,.45); boom(CLOSE,.55)
# high ring during transition line
m=env(30.1,31.4,.2,.6); out+=np.sin(2*np.pi*1760*t)*m*0.03+np.sin(2*np.pi*880*t)*m*0.03
# warm pad from title on: Am - F - C - G cycle, 4 s per chord
chords=[[220,261.63,329.63],[174.61,220,261.63],[196,261.63,329.63],[196,246.94,293.66]]
pad=np.zeros(n)
for i,start in enumerate(np.arange(33.2,END,4.0)):
    ch=chords[i%4]; s=int(start*SR); L=int(4.6*SR); e=min(L,n-s); tt=np.arange(e)/SR
    a=np.clip(tt/1.2,0,1)*np.clip((4.6-tt)/1.2,0,1)
    for f in ch: pad[s:s+e]+=a*(np.sin(2*np.pi*f*tt)+.3*np.sin(2*np.pi*f*2.003*tt))
out+=pad*0.022*env(33.2,END,2,2.5)
# soft pulse (ticks) during how-it-works
for k in np.arange(35.80,99.60,0.5):
    s=int(k*SR); L=int(.08*SR); tt=np.arange(L)/SR
    out[s:s+L]+=np.sin(2*np.pi*1200*tt)*np.exp(-tt*80)*0.025
# final swell
out+=np.sin(2*np.pi*110*t)*env(CLOSE,END,4,2.5)*0.05
rz=env(27.0,30.0,3.0,.02); out+=rng.standard_normal(n)*rz*0.05*np.clip((t-27)/3,0,1)+np.sin(2*np.pi*(200+600*np.clip((t-27)/3,0,1))*t)*rz*0.03
out=out/np.max(np.abs(out))*0.9
st=np.stack([out,out],1)
st[:,1]=np.roll(out,int(.012*SR))
w=wave.open('public/music.wav','wb');w.setnchannels(2);w.setsampwidth(2);w.setframerate(SR);w.writeframes((st*32767).astype(np.int16).tobytes());w.close()
print('ok')
