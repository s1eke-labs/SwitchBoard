import * as React from "react";
import { Chip, type ChipProps } from "@heroui/react";
import { cn } from "@/lib/utils";

type BadgeProps = Omit<ChipProps, "color" | "size" | "variant"> & {
  tone?: "blue" | "green" | "orange" | "neutral";
};

const toneMap: Record<NonNullable<BadgeProps["tone"]>, ChipProps["color"]> = {
  blue: "accent",
  green: "success",
  orange: "warning",
  neutral: "default",
};

export function Badge({ className, tone = "neutral", ...props }: BadgeProps) {
  return (
    <Chip
      className={cn(
        "h-6 rounded-full border px-2 text-xs font-semibold",
        tone === "blue" && "border-blue-100 bg-blue-50 text-blue-700",
        tone === "green" && "border-emerald-100 bg-emerald-50 text-emerald-700",
        tone === "orange" && "border-orange-100 bg-orange-50 text-orange-700",
        tone === "neutral" && "border-border bg-muted text-muted-foreground",
        className,
      )}
      color={toneMap[tone]}
      size="md"
      variant="soft"
      {...props}
    />
  );
}
