import { Composition } from "remotion";
import timelineJson from "../public/timeline.json";
import { Commercial } from "./Commercial";
import type { Timeline } from "./types";

const timeline = timelineJson as Timeline;

export const RemotionRoot: React.FC = () => {
  const last = timeline.scenes[timeline.scenes.length - 1];
  const durationInFrames = last ? last.from + last.frames : 90;
  return (
    <Composition
      id="Commercial"
      component={Commercial}
      durationInFrames={durationInFrames}
      fps={timeline.fps || 30}
      width={timeline.width || 1920}
      height={timeline.height || 1080}
      defaultProps={{ timeline }}
    />
  );
};
