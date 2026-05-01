/* eslint-disable react-refresh/only-export-components */
import * as React from "react";
import { Meter as HeroMeter } from "@heroui/react";
import { cn } from "@/lib/utils";

type MeterProps = React.ComponentProps<typeof HeroMeter>;
type MeterOutputProps = React.ComponentProps<typeof HeroMeter.Output>;
type MeterTrackProps = React.ComponentProps<typeof HeroMeter.Track>;
type MeterFillProps = React.ComponentProps<typeof HeroMeter.Fill>;

function MeterRoot({ className, color = "accent", size = "sm", ...props }: MeterProps) {
  return <HeroMeter className={cn("min-w-0", className)} color={color} size={size} {...props} />;
}

function MeterOutput({ className, ...props }: MeterOutputProps) {
  return <HeroMeter.Output className={cn("font-bold", className)} {...props} />;
}

function MeterTrack({ className, ...props }: MeterTrackProps) {
  return <HeroMeter.Track className={cn("h-2 w-full overflow-hidden rounded-full bg-muted", className)} {...props} />;
}

function MeterFill({ className, ...props }: MeterFillProps) {
  return <HeroMeter.Fill className={cn("h-full rounded-full limit-bar", className)} {...props} />;
}

export const Meter = Object.assign(MeterRoot, {
  Output: MeterOutput,
  Track: MeterTrack,
  Fill: MeterFill,
});
