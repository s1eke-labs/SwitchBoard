import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return "n/a";
  return `${Math.round(value)}%`;
}

export function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return "0";
  return new Intl.NumberFormat().format(value);
}

export function formatTime(seconds: number | null | undefined) {
  if (!seconds) return "n/a";
  return new Intl.DateTimeFormat(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(seconds * 1000));
}

export function formatChartTime(seconds: number | null | undefined, bucket: "hour" | "day" | "week") {
  if (!seconds) return "n/a";
  const options: Intl.DateTimeFormatOptions =
    bucket === "hour"
      ? { hour: "2-digit", minute: "2-digit" }
      : { month: "short", day: "numeric" };
  return new Intl.DateTimeFormat(undefined, options).format(new Date(seconds * 1000));
}

export function shortId(value: string) {
  return value.length <= 8 ? value : value.slice(0, 8);
}
