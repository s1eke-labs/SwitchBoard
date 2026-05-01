import * as React from "react";
import { Button as HeroButton, type ButtonProps as HeroButtonProps } from "@heroui/react";
import { cn } from "@/lib/utils";

type ButtonVariant = "default" | "secondary" | "ghost" | "destructive";
type ButtonSize = "default" | "sm" | "icon";

export interface ButtonProps
  extends Omit<HeroButtonProps, "variant" | "size" | "isIconOnly" | "isDisabled"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  disabled?: boolean;
  isDisabled?: boolean;
  title?: string;
}

const variantMap: Record<ButtonVariant, HeroButtonProps["variant"]> = {
  default: "primary",
  secondary: "outline",
  ghost: "ghost",
  destructive: "danger",
};

const sizeMap: Record<ButtonSize, HeroButtonProps["size"]> = {
  default: "md",
  sm: "sm",
  icon: "md",
};

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", disabled, isDisabled, ...props }, ref) => {
    return (
      <HeroButton
        ref={ref}
        className={cn(
          "rounded-md font-semibold",
          size === "sm" && "text-xs",
          size === "icon" && "h-9 w-9 px-0",
          className,
        )}
        isDisabled={isDisabled ?? disabled}
        isIconOnly={size === "icon"}
        size={sizeMap[size]}
        variant={variantMap[variant]}
        {...props}
      />
    );
  },
);
Button.displayName = "Button";
