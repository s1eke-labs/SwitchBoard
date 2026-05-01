import { Locale, useI18n } from "@/i18n";
import { SegmentedControl } from "@/components/heroui/toggle-button-group";

const localeButtons: Array<{ locale: Locale; label: string }> = [
  { locale: "en", label: "EN" },
  { locale: "zh-CN", label: "中文" },
];

export function LanguageSwitcher({ className }: { className?: string }) {
  const { locale, setLocale, t } = useI18n();

  return (
    <SegmentedControl
      aria-label={t("language.label")}
      className={className}
      value={locale}
      options={localeButtons.map((item) => ({ value: item.locale, label: item.label }))}
      onChange={(value) => setLocale(value)}
    />
  );
}
