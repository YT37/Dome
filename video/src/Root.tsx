import React from 'react';
import {Composition} from 'remotion';
import {DomeVideo} from './Video';
import {END, FPS, W, H} from './theme';
export const Root: React.FC = () => (
  <Composition id="Dome" component={DomeVideo} durationInFrames={Math.round(END * FPS)} fps={FPS} width={W} height={H} />
);
