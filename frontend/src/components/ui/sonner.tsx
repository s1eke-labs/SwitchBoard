import { CheckCircle2, CircleX, Loader2, TriangleAlert } from "lucide-react";
import { Toaster as Sonner, type ToasterProps } from "sonner";

const Toaster = ({ ...props }: ToasterProps) => {
  return (
    <Sonner
      className="toaster group"
      position="top-center"
      offset={{ top: 92 }}
      mobileOffset={{ top: 84, left: 16, right: 16 }}
      duration={3000}
      icons={{
        loading: <Loader2 className="h-4 w-4 animate-spin text-[#0075de]" />,
        success: <CheckCircle2 className="h-4 w-4 text-[#2a9d99]" />,
        warning: <TriangleAlert className="h-4 w-4 text-[#dd5b00]" />,
        error: <CircleX className="h-4 w-4 text-[#dd5b00]" />,
      }}
      toastOptions={{
        unstyled: true,
        classNames: {
          toast:
            "flex w-[var(--width)] items-start gap-2.5 rounded-lg border border-[#cfe8ff] bg-[#f2f9ff] px-3.5 py-3 text-sm text-[#31302e] shadow-[0_4px_18px_rgba(0,0,0,0.04),0_2.025px_7.84688px_rgba(0,0,0,0.027),0_0.8px_2.925px_rgba(0,0,0,0.02),0_0.175px_1.04062px_rgba(0,0,0,0.01)]",
          content: "min-w-0 flex-1",
          title: "text-sm font-semibold leading-5 text-[#31302e]",
          description: "mt-0.5 text-xs leading-5 text-[#615d59]",
          icon: "relative mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center",
          loader: "!static !left-auto !top-auto !translate-x-0 !translate-y-0 !transform-none",
          loading: "border-[#cfe8ff] bg-[#f2f9ff]",
          success: "border-[#cfe8ff] bg-[#f2f9ff]",
          warning: "border-[#f2d3ba] bg-[#fff8f2]",
          error: "border-[#f2d3ba] bg-[#fff8f2]",
          actionButton: "rounded-md bg-primary px-2.5 py-1 text-xs font-semibold text-primary-foreground",
          cancelButton: "rounded-md bg-[rgba(49,48,46,0.08)] px-2.5 py-1 text-xs font-semibold text-[#615d59]",
        },
      }}
      {...props}
    />
  );
};

export { Toaster };
