import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";
import { getCurrentLocale, translate } from "@/i18n";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatPercent(value: number | null | undefined) {
  if (value === null || value === undefined || Number.isNaN(value)) return translate("common.notAvailable");
  return `${Math.round(value)}%`;
}

export function formatNumber(value: number | null | undefined) {
  if (value === null || value === undefined) return "0";
  return new Intl.NumberFormat(getCurrentLocale()).format(value);
}

export function formatTime(seconds: number | null | undefined) {
  if (!seconds) return translate("common.notAvailable");
  return new Intl.DateTimeFormat(getCurrentLocale(), {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(seconds * 1000));
}

export function formatDuration(seconds: number | null | undefined) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return translate("common.notAvailable");
  const totalMinutes = Math.max(0, Math.floor(seconds / 60));
  const locale = getCurrentLocale();
  const number = new Intl.NumberFormat(locale);
  const unit = (value: number, enUnit: string, zhUnit: string) =>
    locale === "zh-CN" ? `${number.format(value)} ${zhUnit}` : `${number.format(value)} ${enUnit}`;

  if (totalMinutes < 60) {
    return unit(totalMinutes, "min", "分钟");
  }

  const totalHours = Math.floor(totalMinutes / 60);
  const minutes = totalMinutes % 60;
  if (totalHours < 24) {
    return minutes > 0
      ? `${unit(totalHours, "h", "小时")} ${unit(minutes, "min", "分钟")}`
      : unit(totalHours, "h", "小时");
  }

  const totalDays = Math.floor(totalHours / 24);
  const hours = totalHours % 24;
  if (totalDays < 30) {
    return hours > 0 ? `${unit(totalDays, "d", "天")} ${unit(hours, "h", "小时")}` : unit(totalDays, "d", "天");
  }

  const months = Math.floor(totalDays / 30);
  const days = totalDays % 30;
  return days > 0 ? `${unit(months, "mo", "个月")} ${unit(days, "d", "天")}` : unit(months, "mo", "个月");
}

export function formatChartTime(seconds: number | null | undefined, bucket: "hour" | "day" | "week") {
  if (!seconds) return translate("common.notAvailable");
  const options: Intl.DateTimeFormatOptions =
    bucket === "hour"
      ? { hour: "2-digit", minute: "2-digit" }
      : { month: "short", day: "numeric" };
  return new Intl.DateTimeFormat(getCurrentLocale(), options).format(new Date(seconds * 1000));
}

export function shortId(value: string) {
  return value.length <= 8 ? value : value.slice(0, 8);
}
