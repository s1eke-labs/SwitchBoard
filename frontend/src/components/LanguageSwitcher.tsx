import { Locale, useI18n } from "@/i18n";
import { cn } from "@/lib/utils";

const localeButtons: Array<{ locale: Locale; label: string }> = [
  { locale: "en", label: "EN" },
  { locale: "zh-CN", label: "中文" },
];

export function LanguageSwitcher({ className }: { className?: string }) {
  const { locale, setLocale, t } = useI18n();

  return (
    <div
      className={cn("inline-flex items-center rounded-md border bg-white p-1", className)}
      role="group"
      aria-label={t("language.label")}
    >
      {localeButtons.map((item) => {
        const active = item.locale === locale;
        return (
          <button
            key={item.locale}
            type="button"
            onClick={() => setLocale(item.locale)}
            className={cn(
              "h-8 min-w-12 rounded-sm px-3 text-sm font-semibold transition-colors",
              active ? "bg-foreground text-white" : "text-muted-foreground hover:bg-muted hover:text-foreground",
            )}
            aria-pressed={active}
          >
            {item.label}
          </button>
        );
      })}
    </div>
  );
}