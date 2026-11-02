import { interpolate, useCurrentFrame } from "remotion";
import { enter, Kicker, LogoMark } from "./components";
import { asArray, asString, theme } from "./theme";
import type { TimelineScene } from "./types";

const shell: React.CSSProperties = {
  position: "absolute",
  inset: "72px 88px 196px",
  display: "flex",
  flexDirection: "column",
  justifyContent: "center",
  gap: 28,
  fontFamily: theme.font,
  color: theme.text,
};

const panel: React.CSSProperties = {
  background: theme.panel,
  border: `1px solid ${theme.line}`,
  borderRadius: 22,
  boxShadow: "0 18px 40px rgba(35,35,35,0.06)",
};

export const SceneView: React.FC<{ scene: TimelineScene }> = ({ scene }) => {
  const frame = useCurrentFrame();
  const fade = Math.min(
    interpolate(frame, [0, 12], [0, 1], { extrapolateRight: "clamp" }),
    scene.id === "close"
      ? 1
      : interpolate(frame, [scene.frames - 12, scene.frames], [1, 0], { extrapolateLeft: "clamp" }),
  );
  const dense = scene.kind === "console" || scene.kind === "identify" || scene.kind === "resolve";
  return (
    <div style={{ ...shell, opacity: fade, justifyContent: dense ? "flex-start" : "center" }}>
      {scene.kind === "opening" && <Opening scene={scene} frame={frame} />}
      {scene.kind === "stats" && <Stats scene={scene} frame={frame} />}
      {scene.kind === "gap" && <Gap scene={scene} frame={frame} />}
      {scene.kind === "intro" && <Intro scene={scene} frame={frame} />}
      {scene.kind === "console" && <Console scene={scene} frame={frame} />}
      {scene.kind === "identify" && <Identify scene={scene} frame={frame} />}
      {scene.kind === "resolve" && <Resolve scene={scene} frame={frame} />}
      {scene.kind === "value" && <Value scene={scene} frame={frame} />}
      {scene.kind === "close" && <Close scene={scene} frame={frame} />}
    </div>
  );
};

const Opening: React.FC<{ scene: TimelineScene; frame: number }> = ({ scene, frame }) => {
  const title = enter(frame, 4);
  const sub = enter(frame, 16);
  const width = interpolate(frame, [8, 36], [0, 280], { extrapolateRight: "clamp" });
  return (
    <div style={{ maxWidth: 1500 }}>
      <div style={title}>
        <Kicker>{asString(scene.visual, "kicker")}</Kicker>
      </div>
      <h1 style={{ ...title, fontSize: 92, lineHeight: 1.02, fontWeight: 700, margin: "22px 0 0", letterSpacing: "-0.03em" }}>
        {asString(scene.visual, "title")}
      </h1>
      <div style={{ width, height: 6, borderRadius: 6, background: theme.brand, marginTop: 28 }} />
      <p style={{ ...sub, fontSize: 44, color: theme.muted, marginTop: 28, fontWeight: 500 }}>
        {asString(scene.visual, "subtitle")}
      </p>
    </div>
  );
};

const Stats: React.FC<{ scene: TimelineScene; frame: number }> = ({ scene, frame }) => {
  const stats = asArray<{ value: number; suffix: string; label: string }>(scene.visual, "stats");
  const head = enter(frame, 0);
  return (
    <div>
      <div style={head}>
        <Kicker>{asString(scene.visual, "kicker")}</Kicker>
        <h2 style={{ fontSize: 54, margin: "14px 0 28px", letterSpacing: "-0.03em", fontWeight: 700 }}>
          {asString(scene.visual, "title")}
        </h2>
      </div>
      <div style={{ display: "flex", gap: 28 }}>
        {stats.map((stat, index) => {
          const shown = Math.round(
            interpolate(frame, [12 + index * 8, 42 + index * 8], [0, stat.value], {
              extrapolateLeft: "clamp",
              extrapolateRight: "clamp",
            }),
          );
          const motion = enter(frame, 8 + index * 8);
          return (
            <div key={stat.label} style={{ ...panel, ...motion, flex: 1, padding: "36px 40px" }}>
              <div style={{ fontSize: 108, fontWeight: 700, letterSpacing: "-0.04em", color: theme.text }}>
                {shown}
                <span style={{ color: theme.brand }}>{stat.suffix}</span>
              </div>
              <div style={{ fontSize: 28, color: theme.muted, lineHeight: 1.35, maxWidth: 640 }}>{stat.label}</div>
            </div>
          );
        })}
      </div>
      <p style={{ marginTop: 22, color: theme.muted, fontSize: 20 }}>{asString(scene.visual, "source")}</p>
    </div>
  );
};

const Gap: React.FC<{ scene: TimelineScene; frame: number }> = ({ scene, frame }) => {
  const cards = asArray<string>(scene.visual, "cards");
  const notes = asArray<string>(scene.visual, "notes");
  return (
    <div>
      <Kicker>{asString(scene.visual, "kicker")}</Kicker>
      <h2 style={{ fontSize: 48, margin: "14px 0 32px", fontWeight: 700, letterSpacing: "-0.03em" }}>
        {asString(scene.visual, "title")}
      </h2>
      <div style={{ display: "flex", alignItems: "center", gap: 18 }}>
        {cards.map((card, index) => {
          const motion = enter(frame, index * 8);
          return (
            <div key={card} style={{ display: "flex", alignItems: "center", gap: 18, flex: 1 }}>
              <div style={{ ...panel, ...motion, flex: 1, padding: "42px 28px", textAlign: "center", fontSize: 36, fontWeight: 650 }}>
                {card}
              </div>
              {index < cards.length - 1 && (
                <div style={{ width: 42, height: 2, background: theme.line, position: "relative" }}>
                  <div style={{ position: "absolute", right: -2, top: -7, color: theme.danger, fontSize: 22 }}>×</div>
                </div>
              )}
            </div>
          );
        })}
      </div>
      <div style={{ display: "flex", gap: 22, marginTop: 28 }}>
        {notes.map((note, index) => (
          <div
            key={note}
            style={{
              ...panel,
              ...enter(frame, 24 + index * 8),
              flex: 1,
              padding: "22px 26px",
              fontSize: 28,
              borderColor: "rgba(226,119,60,0.45)",
            }}
          >
            {note}
          </div>
        ))}
      </div>
    </div>
  );
};

const Intro: React.FC<{ scene: TimelineScene; frame: number }> = ({ scene, frame }) => {
  const scale = interpolate(frame, [0, 20], [0.92, 1], { extrapolateRight: "clamp" });
  const motion = enter(frame, 8);
  return (
    <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start" }}>
      <div style={{ transform: `scale(${scale})` }}>
        <LogoMark size={148} />
      </div>
      <div style={{ ...motion, marginTop: 28 }}>
        <Kicker>{asString(scene.visual, "kicker")}</Kicker>
        <h1 style={{ fontSize: 88, margin: "12px 0 0", letterSpacing: "-0.04em", fontWeight: 700 }}>
          {asString(scene.visual, "title")}
        </h1>
        <p style={{ fontSize: 36, color: theme.muted, marginTop: 12 }}>{asString(scene.visual, "subtitle")}</p>
      </div>
    </div>
  );
};

const Console: React.FC<{ scene: TimelineScene; frame: number }> = ({ scene, frame }) => {
  const nav = asArray<string>(scene.visual, "nav");
  const services = asArray<{ name: string; color: string }>(scene.visual, "services");
  const tiles = asArray<{ label: string; value: string }>(scene.visual, "tiles");
  const active = asString(scene.visual, "active");
  const motion = enter(frame, 4);
  return (
    <div style={{ ...panel, ...motion, display: "flex", overflow: "hidden", minHeight: 0, flex: 1 }}>
      <aside style={{ width: 280, borderRight: `1px solid ${theme.line}`, padding: "22px 16px", background: "#F6F6F6" }}>
        <div style={{ display: "flex", gap: 10, alignItems: "center", padding: "4px 10px 18px" }}>
          <LogoMark size={28} />
          <strong style={{ fontSize: 18 }}>Infralens</strong>
        </div>
        {nav.map((item) => (
          <div
            key={item}
            style={{
              padding: "10px 12px",
              borderRadius: 10,
              marginBottom: 4,
              fontSize: 18,
              background: item === active ? "#FFF4EC" : "transparent",
              boxShadow: item === active ? "inset 3px 0 0 #E2773C" : "none",
              color: item === active ? theme.text : theme.muted,
            }}
          >
            {item}
          </div>
        ))}
      </aside>
      <div style={{ flex: 1, padding: "26px 32px", display: "flex", flexDirection: "column", gap: 18 }}>
        <div style={{ color: theme.muted, fontSize: 16 }}>{asString(scene.visual, "project")}</div>
        <div style={{ fontSize: 40, fontWeight: 700 }}>{asString(scene.visual, "title")}</div>
        <div style={{ display: "flex", gap: 12 }}>
          {services.map((service) => (
            <div key={service.name} style={{ padding: "8px 14px", borderRadius: 999, border: `1px solid ${service.color}`, color: service.color, fontSize: 18 }}>
              {service.name}
            </div>
          ))}
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14, flex: 1 }}>
          {tiles.map((tile) => (
            <div key={tile.label} style={{ borderRadius: 16, background: "rgba(255,255,255,0.03)", border: `1px solid ${theme.line}`, padding: "18px 20px" }}>
              <div style={{ color: theme.muted, fontSize: 16 }}>{tile.label}</div>
              <div style={{ fontSize: 32, fontWeight: 650, marginTop: 8 }}>{tile.value}</div>
            </div>
          ))}
        </div>
        <div style={{ color: theme.muted, fontSize: 16 }}>{asString(scene.visual, "footnote")}</div>
      </div>
    </div>
  );
};

const Identify: React.FC<{ scene: TimelineScene; frame: number }> = ({ scene, frame }) => {
  const columns = asArray<{ heading: string; rows: string[] }>(scene.visual, "columns");
  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, flex: 1 }}>
      <Kicker>{asString(scene.visual, "kicker")}</Kicker>
      <h2 style={{ fontSize: 42, margin: "12px 0 24px", fontWeight: 700, letterSpacing: "-0.03em" }}>
        {asString(scene.visual, "title")}
      </h2>
      <div style={{ display: "flex", gap: 22, flex: 1 }}>
        {columns.map((column, index) => (
          <div key={column.heading} style={{ ...panel, ...enter(frame, index * 8), flex: 1, padding: "28px 26px" }}>
            <div style={{ fontSize: 28, fontWeight: 700, color: theme.brand, marginBottom: 18 }}>{column.heading}</div>
            {column.rows.map((row) => (
              <div key={row} style={{ fontSize: 24, lineHeight: 1.4, padding: "12px 0", borderTop: `1px solid ${theme.line}`, color: theme.text }}>
                {row}
              </div>
            ))}
          </div>
        ))}
      </div>
    </div>
  );
};

const Resolve: React.FC<{ scene: TimelineScene; frame: number }> = ({ scene, frame }) => {
  const steps = asArray<string>(scene.visual, "steps");
  return (
    <div style={{ display: "flex", flexDirection: "column", minHeight: 0, flex: 1 }}>
      <Kicker>{asString(scene.visual, "kicker")}</Kicker>
      <h2 style={{ fontSize: 42, margin: "12px 0 22px", fontWeight: 700 }}>{asString(scene.visual, "title")}</h2>
      <div style={{ display: "flex", gap: 24, flex: 1 }}>
        <div style={{ flex: 1.3, display: "flex", flexDirection: "column", gap: 14 }}>
          {steps.map((step, index) => {
            const shown = frame > 10 + index * 18;
            return (
              <div key={step} style={{ ...panel, ...enter(frame, index * 10), padding: "18px 22px", display: "flex", gap: 16, opacity: shown ? 1 : 0.35 }}>
                <div style={{ width: 42, height: 42, borderRadius: 12, background: theme.brand, color: "#FFFFFF", fontWeight: 700, display: "flex", alignItems: "center", justifyContent: "center", fontSize: 22 }}>
                  {index + 1}
                </div>
                <div style={{ fontSize: 24, lineHeight: 1.35 }}>{step}</div>
              </div>
            );
          })}
        </div>
        <div style={{ ...panel, ...enter(frame, 16), flex: 0.9, padding: 28, display: "flex", flexDirection: "column" }}>
          <div style={{ color: theme.muted, fontSize: 16 }}>Skills suite</div>
          <div style={{ fontSize: 36, fontWeight: 700, marginTop: 6 }}>{asString(scene.visual, "approvalTitle")}</div>
          <p style={{ fontSize: 24, lineHeight: 1.4, color: theme.muted }}>{asString(scene.visual, "approvalBody")}</p>
          <div style={{ marginTop: "auto", display: "flex", gap: 12 }}>
            <div style={{ padding: "12px 22px", borderRadius: 12, border: `1px solid ${theme.danger}`, color: theme.danger, fontSize: 20 }}>Reject</div>
            <div style={{ padding: "12px 22px", borderRadius: 12, background: theme.brand, color: "#FFFFFF", fontWeight: 700, fontSize: 20 }}>Approve</div>
          </div>
        </div>
      </div>
    </div>
  );
};

const Value: React.FC<{ scene: TimelineScene; frame: number }> = ({ scene, frame }) => {
  const items = asArray<{ title: string; body: string }>(scene.visual, "items");
  return (
    <div>
      <Kicker>{asString(scene.visual, "kicker")}</Kicker>
      <h2 style={{ fontSize: 48, margin: "12px 0 28px", fontWeight: 700, letterSpacing: "-0.03em" }}>
        {asString(scene.visual, "title")}
      </h2>
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 20 }}>
        {items.map((item, index) => (
          <div key={item.title} style={{ ...panel, ...enter(frame, index * 6), padding: "28px 30px" }}>
            <div style={{ fontSize: 32, fontWeight: 700, color: theme.brand }}>{item.title}</div>
            <div style={{ fontSize: 26, marginTop: 8, color: theme.text, lineHeight: 1.35 }}>{item.body}</div>
          </div>
        ))}
      </div>
    </div>
  );
};

const Close: React.FC<{ scene: TimelineScene; frame: number }> = ({ scene, frame }) => {
  const motion = enter(frame, 6);
  return (
    <div style={motion}>
      <LogoMark size={132} />
      <h1 style={{ fontSize: 84, margin: "24px 0 0", fontWeight: 700, letterSpacing: "-0.04em" }}>
        {asString(scene.visual, "title")}
      </h1>
      <p style={{ fontSize: 36, color: theme.text, marginTop: 8 }}>{asString(scene.visual, "subtitle")}</p>
      <p style={{ fontSize: 26, color: theme.brand, marginTop: 18 }}>{asString(scene.visual, "url")}</p>
    </div>
  );
};
