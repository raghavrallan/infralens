// Console Azure reads go through the isolated CLI sandbox in ./sandbox.js.
// This module stays so an old import fails closed instead of calling Azure over HTTP.

function blocked() {
  throw new Error("Azure reads sign in with the Azure CLI inside the project sandbox. Direct REST calls are not used.");
}

export async function armToken() {
  blocked();
}

export async function listVisibleSubscriptions() {
  blocked();
}

export async function readConnection() {
  blocked();
}

export function costQueryHttp() {
  blocked();
}

export async function activityLog() {
  blocked();
}
