export type SceneKind =
  | "opening"
  | "stats"
  | "gap"
  | "intro"
  | "console"
  | "identify"
  | "resolve"
  | "value"
  | "close";

export type TimelineLine = {
  text: string;
  from: number;
  frames: number;
};

export type TimelineScene = {
  id: string;
  kind: SceneKind;
  from: number;
  frames: number;
  lines: TimelineLine[];
  visual: Record<string, unknown>;
};

export type Timeline = {
  fps: number;
  width: number;
  height: number;
  hasAudio: boolean;
  hasSfx: boolean;
  musicVolume: number;
  scenes: TimelineScene[];
};
