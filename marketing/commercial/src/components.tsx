import { AbsoluteFill, interpolate, useCurrentFrame } from "remotion";
import { theme } from "./theme";

export const Background: React.FC = () => {
  const frame = useCurrentFrame();
  const drift = (frame * 0.35) % 80;
  return (
    <AbsoluteFill style={{ backgroundColor: theme.bg }}>
      <AbsoluteFill
        style={{
          background:
            "radial-gradient(980px 640px at 8% 0%, rgba(226,119,60,0.22), transparent 58%), radial-gradient(860px 560px at 100% 100%, rgba(226,119,60,0.14), transparent 60%), #F7F6F4",
          transform: `translate(${drift * 0.15}px, ${drift * -0.08}px)`,
        }}
      />
      <AbsoluteFill
        style={{
          opacity: 0.35,
          backgroundImage:
            "linear-gradient(rgba(226,119,60,0.08) 1px, transparent 1px), linear-gradient(90deg, rgba(226,119,60,0.08) 1px, transparent 1px)",
          backgroundSize: "120px 120px",
          backgroundPosition: `${drift}px ${drift * 0.25}px`,
        }}
      />
    </AbsoluteFill>
  );
};

export const LogoMark: React.FC<{ size?: number }> = ({ size = 120 }) => (
  <svg width={size} height={size} viewBox="0 0 32 32" aria-label="Infralens">
    <rect width="32" height="32" rx="8" fill="#E2773C" />
    <circle cx="16" cy="16" r="9" fill="none" stroke="#FFFFFF" strokeWidth="1.6" />
    <circle cx="16" cy="16" r="4.2" fill="none" stroke="#FFFFFF" strokeWidth="1.5" />
    <circle cx="16" cy="16" r="1.6" fill="#FFFFFF" />
    <path d="M16 3.2v2.4M16 26.4v2.4M3.2 16h2.4M26.4 16h2.4" stroke="#FFFFFF" strokeWidth="1.3" strokeLinecap="round" />
  </svg>
);

export const Kicker: React.FC<{ children: string }> = ({ children }) => (
  <div
    style={{
      color: theme.brand,
      fontFamily: theme.font,
      fontWeight: 600,
      letterSpacing: "0.22em",
      fontSize: 18,
      textTransform: "uppercase",
    }}
  >
    {children}
  </div>
);

export function enter(frame: number, delay = 0): { opacity: number; y: number } {
  const opacity = interpolate(frame, [delay, delay + 14], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  const y = interpolate(frame, [delay, delay + 16], [22, 0], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return { opacity, y };
}

export const CaptionBar: React.FC<{ text: string }> = ({ text }) => {
  if (!text) return null;
  return (
    <AbsoluteFill style={{ justifyContent: "flex-end", alignItems: "center", padding: "0 120px 54px" }}>
      <div
        style={{
          maxWidth: 1400,
          background: "#FFFFFF",
          border: "1px solid #E7E5E4",
          borderRadius: 14,
          padding: "16px 28px",
          color: "#232323",
          boxShadow: "0 10px 28px rgba(226,119,60,0.12)",
          fontFamily: theme.font,
          fontSize: 30,
          fontWeight: 500,
          lineHeight: 1.35,
          textAlign: "center",
        }}
      >
        {text}
      </div>
    </AbsoluteFill>
  );
};
