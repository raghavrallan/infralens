import { loadFont } from "@remotion/google-fonts/DMSans";

const loaded = loadFont("normal", {
  weights: ["400", "500", "600", "700"],
  subsets: ["latin"],
});

export const theme = {
  bg: "#F7F6F4",
  panel: "#FFFFFF",
  panelSolid: "#FFFFFF",
  line: "#E7E5E4",
  text: "#232323",
  muted: "#717171",
  brand: "#E2773C",
  brandDeep: "#C45E28",
  blue: "#0084FF",
  green: "#0BAA60",
  purple: "#7C6AE8",
  danger: "#F03D3D",
  font: loaded.fontFamily,
};

export function asString(visual: Record<string, unknown>, key: string, fallback = ""): string {
  const value = visual[key];
  return typeof value === "string" ? value : fallback;
}

export function asArray<T>(visual: Record<string, unknown>, key: string): T[] {
  const value = visual[key];
  return Array.isArray(value) ? (value as T[]) : [];
}
