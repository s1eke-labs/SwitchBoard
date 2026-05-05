import { PlugZap, Settings } from "lucide-react";
import { SegmentedControl } from "@/components/heroui/toggle-button-group";
import { ImageDispatcherSettingsPage } from "@/pages/ImageDispatcherSettingsPage";
import { useI18n } from "@/i18n";

type SettingsSection = "imageDispatcher";

export function SettingsPage({
  section,
  onNavigate,
}: {
  section: SettingsSection;
  onNavigate: (path: string, replace?: boolean) => void;
}) {
  const { t } = useI18n();
  const sections = [
    {
      value: "imageDispatcher",
      path: "/settings/dispatcher",
      label: (
        <>
          <PlugZap size={16} />
          {t("settings.imageDispatcher")}
        </>
      ),
    },
  ] as const;

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Settings size={20} className="text-primary" />
          <h1 className="text-lg font-bold">{t("settings.title")}</h1>
        </div>
        <SegmentedControl
          aria-label={t("settings.title")}
          value={section}
          options={sections}
          onChange={(value) => {
            const item = sections.find((settingsSection) => settingsSection.value === value);
            if (item) onNavigate(item.path);
          }}
        />
      </div>
      <ImageDispatcherSettingsPage />
    </div>
  );
}
