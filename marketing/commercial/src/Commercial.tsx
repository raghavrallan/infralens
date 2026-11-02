import { AbsoluteFill, Audio, interpolate, Sequence, staticFile, useCurrentFrame, useVideoConfig } from "remotion";
import { Background, CaptionBar } from "./components";
import { SceneView } from "./scenes";
import { theme } from "./theme";
import type { Timeline } from "./types";

export const Commercial: React.FC<{ timeline: Timeline }> = ({ timeline }) => {
  const frame = useCurrentFrame();
  const { durationInFrames, fps } = useVideoConfig();
  const line = timeline.scenes
    .flatMap((scene) => scene.lines)
    .find((item) => frame >= item.from && frame < item.from + item.frames);
  const fadeIn = interpolate(frame, [0, Math.round(fps * 1.2)], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const fadeOut = interpolate(frame, [durationInFrames - Math.round(fps * 2.2), durationInFrames], [1, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill style={{ backgroundColor: theme.bg, fontFamily: theme.font }}>
      <Background />
      {timeline.scenes.map((scene) => (
        <Sequence key={scene.id} from={scene.from} durationInFrames={scene.frames}>
          <SceneView scene={scene} />
        </Sequence>
      ))}
      <CaptionBar text={line?.text ?? ""} />
      {timeline.hasAudio && (
        <>
          <Audio src={staticFile("voiceover.wav")} />
          <Audio src={staticFile("music.mp3")} loop volume={(timeline.musicVolume ?? 0.2) * Math.min(fadeIn, fadeOut)} />
          {timeline.hasSfx && <Audio src={staticFile("sfx.wav")} volume={0.55} />}
        </>
      )}
    </AbsoluteFill>
  );
};
