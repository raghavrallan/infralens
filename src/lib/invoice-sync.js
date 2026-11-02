import { bindAzCaller } from "./azure/calls.js";
import { readInvoices } from "./billing-read.js";
import { readInvoiceIndex, writeInvoiceIndex } from "./invoice-store.js";

export async function syncProjectInvoices({ orgId, projectId }) {
  bindAzCaller({ orgId, projectId, caller: "estate.sync invoices" });
  const previous = await readInvoiceIndex(projectId);
  let remote;
  try {
    remote = await readInvoices({ orgId, projectId, save: true });
  } catch {
    return previous;
  }
  if (!remote.invoices.length) {
    return writeInvoiceIndex(projectId, {
      message: remote.message || previous.message,
      invoices: previous.invoices,
    });
  }
  const saved = new Map(previous.invoices.filter((item) => item.saved).map((item) => [item.name, item]));
  const invoices = remote.invoices.map((item) => ({
    name: item.name,
    subscriptionId: item.subscriptionId,
    subscription: item.subscription,
    start: item.start,
    end: item.end,
    status: item.status,
    amount: item.amount,
    currency: item.currency,
    saved: Boolean(item.saved || saved.get(item.name)?.saved),
  }));
  return writeInvoiceIndex(projectId, { message: remote.message || "", invoices });
}
