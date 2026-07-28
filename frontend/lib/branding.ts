/**
 * Display-only EQIP → mlife branding.
 * Backend already rewrites API / SSE payloads; this keeps chat markdown,
 * dashboard cards, and selects consistent if any raw name still reaches the client.
 *
 * Covers:
 * - eqip / eqip_backend / eqip-frontend → mlife*
 * - eq-foo / eq_foo / eq123 → ml*
 * - glued Azure ids: eqacrregistry…, eqdevstorage…, eqcommonstorage → ml*
 */

const EQIP_TOKEN = /(?<![A-Za-z0-9])eqip(?![A-Za-z])/gi;

const EQ_ENGLISH =
  "(?:ual(?:ly|s|ity|ize|ised|ized)?|uation(?:s)?|uip(?:ment|ped|ping)?|uity|uivalent(?:ly)?|uator|uilibrium|uine|uate(?:d|s|ing)?|uidistant|uilateral|uanimous(?:ly)?)";

const EQ_GLUED = new RegExp(
  `(?<![A-Za-z0-9])eq(?!${EQ_ENGLISH}\\b)(?=[a-z]{2,})`,
  "gi",
);

const EQ_RESOURCE =
  /(?<![A-Za-z0-9])eq(?=[-_])|(?<=[-_])eq(?=[-_]|$)|(?<![A-Za-z0-9])eq(?=\d)/gi;

function brandEqToken(token: string): string {
  if (token === token.toUpperCase()) return "ML";
  if (token[0] === token[0]?.toUpperCase()) return "Ml";
  return "ml";
}

export function displayBrandText(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .replace(EQIP_TOKEN, "mlife")
    .replace(EQ_GLUED, brandEqToken)
    .replace(EQ_RESOURCE, brandEqToken);
}
