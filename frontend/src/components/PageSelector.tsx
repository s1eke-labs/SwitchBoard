import { useState } from "react";
import { Dropdown } from "@heroui/react";
import { ChevronDown } from "lucide-react";
import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

export function PageSelector({
  page,
  totalPages,
  disabled,
  jumping,
  onSelect,
  className,
  buttonClassName,
  menuClassName,
  showChevron = false,
  chevronSize = 15,
}: {
  page: number;
  totalPages: number;
  disabled: boolean;
  jumping: boolean;
  onSelect: (page: number) => void;
  className?: string;
  buttonClassName?: string;
  menuClassName?: string;
  showChevron?: boolean;
  chevronSize?: number;
}) {
  const { t } = useI18n();
  const [open, setOpen] = useState(false);
  const pageCount = Math.max(1, totalPages);
  const label = jumping ? t("common.loadingEllipsis") : t("common.pageLabel", { page: Math.min(page, pageCount), total: pageCount });

  return (
    <div className={cn("relative", className)} aria-busy={jumping}>
      <Dropdown.Root isOpen={open} onOpenChange={setOpen}>
        <Dropdown.Trigger
          className={cn(
            "h-9 min-w-24 rounded-md px-3 text-center text-sm font-semibold text-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-50",
            buttonClassName,
          )}
          isDisabled={disabled || pageCount <= 1}
        >
          {showChevron ? (
            <>
              <span>{label}</span>
              <ChevronDown size={chevronSize} className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
            </>
          ) : (
            label
          )}
        </Dropdown.Trigger>
        <Dropdown.Popover
          placement="top"
          className={cn(
            "max-h-56 w-56 overflow-auto rounded-lg border bg-white p-2 shadow-soft",
            menuClassName,
          )}
        >
          <Dropdown.Menu className="grid grid-cols-4 gap-1" aria-label={t("common.selectPage")}>
            {Array.from({ length: pageCount }, (_, index) => {
              const pageNumber = index + 1;
              const active = pageNumber === page;
              return (
                <Dropdown.Item
                  key={pageNumber}
                  id={String(pageNumber)}
                  className={cn(
                    "flex h-8 items-center justify-center rounded-md text-sm font-semibold transition-colors hover:bg-muted",
                    active ? "bg-foreground text-white hover:bg-foreground" : "text-foreground",
                  )}
                  onAction={() => onSelect(pageNumber)}
                  textValue={String(pageNumber)}
                >
                  {pageNumber}
                </Dropdown.Item>
              );
            })}
          </Dropdown.Menu>
        </Dropdown.Popover>
      </Dropdown.Root>
    </div>
  );
}
