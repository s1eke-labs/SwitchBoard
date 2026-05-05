/* eslint-disable react-refresh/only-export-components */
import * as React from "react";
import { Avatar as HeroAvatar, type AvatarFallbackProps, type AvatarProps } from "@heroui/react";
import { cn } from "@/lib/utils";

function AvatarRoot({ className, size = "sm", ...props }: AvatarProps) {
  return <HeroAvatar className={cn("shrink-0", className)} size={size} {...props} />;
}

function AvatarFallback({ className, ...props }: AvatarFallbackProps) {
  return <HeroAvatar.Fallback className={cn("text-sm font-bold", className)} {...props} />;
}

export const Avatar = Object.assign(AvatarRoot, {
  Fallback: AvatarFallback,
});
