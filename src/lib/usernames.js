import { one } from "./db.js";
import { usernameFor } from "./ids.js";

export async function availableUsername(name, userId = "") {
  const stem = usernameFor(name);
  let candidate = stem;
  for (let n = 1; n < 40; n += 1) {
    const taken = await one("SELECT id FROM users WHERE lower(username) = lower(?)", [candidate]);
    if (!taken || taken.id === userId) return candidate;
    candidate = `${stem.slice(0, 58)}${n + 1}`;
  }
  return `${stem.slice(0, 48)}${String(userId).slice(0, 8)}`;
}
