import { mkdir, readFile, stat, unlink, writeFile } from "node:fs/promises";
import path from "node:path";
import { saveInvoicePdf } from "./azure/sandbox.js";

const ROOT = path.resolve(process.cwd(), "data", "invoices");

export function invoiceFolder(projectId) {
  if (!/^[a-z0-9-]{8,64}$/i.test(projectId)) throw new Error("Choose a project.");
  const folder = path.resolve(ROOT, projectId);
  if (folder !== path.join(ROOT, projectId)) throw new Error("Choose a project.");
  return folder;
}

export function invoiceFileName(name) {
  const clean = String(name || "").replace(/[^A-Za-z0-9._-]/g, "_").replace(/^\.+/, "").slice(0, 120);
  if (!clean || clean === "." || clean === "..") throw new Error("That invoice is not available.");
  return `${clean}.pdf`;
}

async function isPdf(file) {
  try {
    const info = await stat(file);
    if (!info.isFile() || info.size < 5) return false;
    const bytes = await readFile(file);
    return bytes.subarray(0, 4).toString() === "%PDF";
  } catch {
    return false;
  }
}

export async function readInvoiceIndex(projectId) {
  try {
    const body = JSON.parse(await readFile(path.join(invoiceFolder(projectId), "index.json"), "utf8"));
    return {
      checkedAt: Number(body.checkedAt) || 0,
      message: String(body.message || ""),
      invoices: Array.isArray(body.invoices) ? body.invoices : [],
    };
  } catch {
    return { checkedAt: 0, message: "", invoices: [] };
  }
}

export async function writeInvoiceIndex(projectId, index) {
  const folder = invoiceFolder(projectId);
  await mkdir(folder, { recursive: true });
  const invoices = (index.invoices || []).map((item) => ({
    name: String(item.name || ""),
    file: invoiceFileName(item.name),
    subscriptionId: String(item.subscriptionId || ""),
    subscription: String(item.subscription || ""),
    start: String(item.start || ""),
    end: String(item.end || ""),
    status: String(item.status || ""),
    amount: Number(item.amount) || 0,
    currency: String(item.currency || "USD"),
    saved: Boolean(item.saved),
  })).filter((item) => item.name);
  await writeFile(path.join(folder, "index.json"), JSON.stringify({
    checkedAt: Date.now(),
    message: String(index.message || ""),
    invoices,
  }, null, 2));
  return { checkedAt: Date.now(), message: String(index.message || ""), invoices };
}

export async function readSavedPdf(projectId, name) {
  const file = path.join(invoiceFolder(projectId), invoiceFileName(name));
  if (!(await isPdf(file))) return null;
  return readFile(file);
}

export async function keepInvoicePdf(profile, projectId, invoice) {
  const folder = invoiceFolder(projectId);
  await mkdir(folder, { recursive: true });
  const file = path.join(folder, invoiceFileName(invoice.name));
  if (await isPdf(file)) return { file: path.basename(file), saved: true, skipped: true };
  const url = String(invoice.download || "");
  if (!url) return { file: path.basename(file), saved: false, skipped: false };
  try {
    await saveInvoicePdf(profile, url, file);
    if (!(await isPdf(file))) {
      await unlink(file).catch(() => {});
      return { file: path.basename(file), saved: false, skipped: false };
    }
    return { file: path.basename(file), saved: true, skipped: false };
  } catch {
    await unlink(file).catch(() => {});
    return { file: path.basename(file), saved: false, skipped: false };
  }
}
