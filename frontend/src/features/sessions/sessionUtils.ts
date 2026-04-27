import { SessionEvent, SessionUserIndexItem } from "@/lib/api";

export function fullEventBody(event: SessionEvent) {
  if (event.text !== undefined && event.text !== null) return event.text;
  if (event.arguments !== undefined && event.arguments !== null) return JSON.stringify(event.arguments, null, 2);
  if (event.data !== undefined && event.data !== null) return JSON.stringify(event.data, null, 2);
  return "";
}

export function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"] as const;
  let value = bytes;
  let unitIndex = 0;
  while (value >= 1024 && unitIndex < units.length - 1) {
    value /= 1024;
    unitIndex += 1;
  }
  const maximumFractionDigits = unitIndex === 0 ? 0 : value < 10 ? 1 : 0;
  return `${new Intl.NumberFormat(undefined, { maximumFractionDigits }).format(value)} ${units[unitIndex]}`;
}

export function userIndexLabel(item: SessionUserIndexItem) {
  return item.body_preview.trim().split(/\r?\n/, 1)[0] || "Empty user message";
}
