/* eslint-disable react-refresh/only-export-components */
import * as React from "react";
import { AlertDialog as HeroAlertDialog } from "@heroui/react";
import { cn } from "@/lib/utils";

function AlertDialogRoot(props: React.ComponentProps<typeof HeroAlertDialog>) {
  return <HeroAlertDialog {...props} />;
}

function AlertDialogBackdrop({ className, variant = "opaque", ...props }: React.ComponentProps<typeof HeroAlertDialog.Backdrop>) {
  return <HeroAlertDialog.Backdrop className={cn(className)} variant={variant} {...props} />;
}

function AlertDialogContainer({ className, placement = "center", size = "sm", ...props }: React.ComponentProps<typeof HeroAlertDialog.Container>) {
  return <HeroAlertDialog.Container className={cn("p-3", className)} placement={placement} size={size} {...props} />;
}

function AlertDialogDialog({ className, ...props }: React.ComponentProps<typeof HeroAlertDialog.Dialog>) {
  return <HeroAlertDialog.Dialog className={cn("overflow-hidden rounded-md bg-background p-0", className)} {...props} />;
}

function AlertDialogHeader({ className, ...props }: React.ComponentProps<typeof HeroAlertDialog.Header>) {
  return <HeroAlertDialog.Header className={cn("flex-row items-start gap-3 border-b px-4 py-3", className)} {...props} />;
}

function AlertDialogHeading({ className, ...props }: React.ComponentProps<typeof HeroAlertDialog.Heading>) {
  return <HeroAlertDialog.Heading className={cn("text-sm font-semibold", className)} {...props} />;
}

function AlertDialogBody({ className, ...props }: React.ComponentProps<typeof HeroAlertDialog.Body>) {
  return <HeroAlertDialog.Body className={cn("px-4 py-4 text-sm leading-6 text-muted-foreground", className)} {...props} />;
}

function AlertDialogFooter({ className, ...props }: React.ComponentProps<typeof HeroAlertDialog.Footer>) {
  return <HeroAlertDialog.Footer className={cn("justify-end gap-2 border-t px-4 py-3", className)} {...props} />;
}

function AlertDialogIcon({ className, status = "danger", ...props }: React.ComponentProps<typeof HeroAlertDialog.Icon>) {
  return <HeroAlertDialog.Icon className={cn("shrink-0", className)} status={status} {...props} />;
}

export const AlertDialog = Object.assign(AlertDialogRoot, {
  Backdrop: AlertDialogBackdrop,
  Body: AlertDialogBody,
  Container: AlertDialogContainer,
  Dialog: AlertDialogDialog,
  Footer: AlertDialogFooter,
  Header: AlertDialogHeader,
  Heading: AlertDialogHeading,
  Icon: AlertDialogIcon,
});
