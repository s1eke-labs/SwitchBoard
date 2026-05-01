import * as React from "react";
import {
  Card as HeroCard,
  CardContent as HeroCardContent,
  CardHeader as HeroCardHeader,
  type CardContentProps,
  type CardHeaderProps,
  type CardProps,
} from "@heroui/react";
import { cn } from "@/lib/utils";

export function Card({ className, ...props }: CardProps) {
  return <HeroCard className={cn("gap-0 rounded-lg border bg-white p-0 shadow-soft", className)} {...props} />;
}

export function CardHeader({ className, ...props }: CardHeaderProps) {
  return <HeroCardHeader className={cn("border-b px-4 py-3", className)} {...props} />;
}

export function CardContent({ className, ...props }: CardContentProps) {
  return <HeroCardContent className={cn("p-4", className)} {...props} />;
}
