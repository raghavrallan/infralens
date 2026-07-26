/**
 * Display-only EQIP → mlife branding.
 * Backend already rewrites API payloads; this keeps selects/labels consistent
 * if any raw name still reaches the client.
 */

const EQIP_WORD = /\beqip\b/gi;
const EQ_RESOURCE =
  /(?<![A-Za-z0-9])eq(?=[-_])|(?<=[-_])eq(?=[-_]|$)|(?<![A-Za-z0-9])eq(?=\d)/gi;

export function displayBrandText(value: string | null | undefined): string {
  if (!value) return "";
  return value
    .replace(EQIP_WORD, "mlife")
    .replace(EQ_RESOURCE, (token) => {
      if (token === token.toUpperCase()) return "ML";
      if (token[0] === token[0]?.toUpperCase()) return "Ml";
      return "ml";
    });
}
