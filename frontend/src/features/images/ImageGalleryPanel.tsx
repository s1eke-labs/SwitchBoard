import {
  CheckCircle2,
  Clock3,
  Download,
  Filter,
  ImageIcon,
  Trash2,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/heroui/button";
import { Checkbox } from "@/components/heroui/checkbox";
import { PageSelector } from "@/components/PageSelector";
import { Card, CardContent, CardHeader } from "@/components/heroui/card";
import { Select } from "@/components/heroui/select";
import { Spinner } from "@/components/heroui/spinner";
import { Toolbar } from "@/components/heroui/toolbar";
import { useI18n } from "@/i18n";
import type { ImageGalleryJob } from "@/lib/api";
import { GALLERY_CARD_HEIGHT, GALLERY_GRID_GAP, STATUS_LABEL_KEYS } from "@/features/images/constants";
import type { GalleryItem } from "@/features/images/types";
import { formatJobTime, isSelectableGalleryItem } from "@/features/images/imageUtils";

export function ImageJobStatusIcon({ job }: { job: ImageGalleryJob }) {
  if (job.status === "succeeded") return <CheckCircle2 size={15} className="text-emerald-600" />;
  if (job.status === "failed") return <XCircle size={15} className="text-destructive" />;
  if (job.status === "running") return <Spinner className="text-primary" />;
  return <Clock3 size={15} className="text-muted-foreground" />;
}

function ImageGallery({
  items,
  loading,
  columnCount,
  selecting,
  selectedKeys,
  deleting,
  onOpenPreview,
  onToggleSelected,
}: {
  items: GalleryItem[];
  loading: boolean;
  columnCount: number;
  selecting: boolean;
  selectedKeys: Set<string>;
  deleting: boolean;
  onOpenPreview: (key: string) => void;
  onToggleSelected: (key: string) => void;
}) {
  const { t } = useI18n();
  if (loading) {
    return (
      <div className="flex min-h-[456px] flex-1 items-center justify-center text-sm text-muted-foreground">
        <Spinner className="mr-2" />
        {t("common.loading")}
      </div>
    );
  }
  if (items.length === 0) {
    return (
      <div className="flex min-h-[456px] flex-1 flex-col items-center justify-center text-sm text-muted-foreground">
        <ImageIcon size={32} className="mb-2" />
        {t("images.emptyGallery")}
      </div>
    );
  }
  return (
    <div
      className="grid"
      style={{
        gap: GALLERY_GRID_GAP,
        gridAutoRows: GALLERY_CARD_HEIGHT,
        gridTemplateColumns: `repeat(${columnCount}, minmax(0, 1fr))`,
      }}
    >
      {items.map((item) => {
        const statusLabel = t(STATUS_LABEL_KEYS[item.job.status]);
        const selectable = isSelectableGalleryItem(item);
        const selected = selectedKeys.has(item.key);
        return (
          <div
            key={item.key}
            className={`group relative flex min-w-0 flex-col overflow-hidden rounded-md border bg-white text-left transition-colors hover:border-primary/50 focus-within:ring-2 focus-within:ring-ring ${
              selected ? "border-primary ring-2 ring-ring" : ""
            }`}
          >
            {selecting ? (
              <div className="absolute left-2 top-2 z-10 rounded-md bg-white/90 px-1.5 py-1 shadow-soft">
                <Checkbox
                  aria-label={t("images.selectImage")}
                  isSelected={selected}
                  isDisabled={!selectable || deleting}
                  onChange={() => onToggleSelected(item.key)}
                />
              </div>
            ) : null}
            <button
              type="button"
              onClick={() => {
                if (selecting) {
                  if (selectable && !deleting) onToggleSelected(item.key);
                  return;
                }
                onOpenPreview(item.key);
              }}
              aria-label={selecting ? t("images.selectImage") : `${t("images.preview")} · ${statusLabel}`}
              className="flex min-h-0 flex-1 flex-col text-left focus:outline-none"
            >
              <div className="flex min-h-0 flex-1 items-center justify-center bg-muted/60 p-1.5">
                {item.thumbnailSrc ? (
                  <img
                    src={item.thumbnailSrc}
                    alt={item.job.prompt}
                    className="h-full w-full object-contain transition-transform group-hover:scale-[1.01]"
                  />
                ) : (
                  <div className="flex items-center text-muted-foreground" aria-label={statusLabel}>
                    <ImageJobStatusIcon job={item.job} />
                  </div>
                )}
              </div>
              <div className="h-9 shrink-0 border-t px-3 py-2">
                <div className="flex min-w-0 items-center gap-1 text-xs text-muted-foreground">
                  <span className="min-w-0 truncate">{formatJobTime(item.job.updated_at)}</span>
                  <span className="shrink-0">·</span>
                  <span className="min-w-0 truncate">{item.job.source_label}</span>
                </div>
              </div>
            </button>
          </div>
        );
      })}
    </div>
  );
}

export function ImageGalleryPanel({
  bodyRef,
  items,
  loading,
  fetching,
  page,
  totalPages,
  columnCount,
  selecting,
  selectedItems,
  selectedKeys,
  selectedDownloadableCount,
  deleting,
  source,
  sourceOptions,
  onSourceChange,
  onDownloadSelected,
  onDeleteSelected,
  onToggleSelecting,
  onSelectPage,
  onOpenPreview,
  onToggleSelected,
}: {
  bodyRef: React.RefObject<HTMLDivElement | null>;
  items: GalleryItem[];
  loading: boolean;
  fetching: boolean;
  page: number;
  totalPages: number;
  columnCount: number;
  selecting: boolean;
  selectedItems: GalleryItem[];
  selectedKeys: Set<string>;
  selectedDownloadableCount: number;
  deleting: boolean;
  source: string;
  sourceOptions: { value: string; label: string }[];
  onSourceChange: (source: string) => void;
  onDownloadSelected: () => void;
  onDeleteSelected: () => void;
  onToggleSelecting: () => void;
  onSelectPage: (page: number) => void;
  onOpenPreview: (key: string) => void;
  onToggleSelected: (key: string) => void;
}) {
  const { t } = useI18n();
  const sourceLabel = sourceOptions.find((option) => option.value === source)?.label ?? t("images.source.all");

  return (
    <Card className="flex min-h-[520px] flex-col self-start">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <ImageIcon size={18} className="text-primary" />
            <h2 className="truncate text-base font-bold">{t("images.gallery")}</h2>
          </div>
          <Toolbar aria-label={t("images.gallery")} className="justify-end gap-1">
            <Select
              aria-label={t("images.sourceFilter")}
              className="w-44 max-w-full"
              fullWidth={false}
              selectedKey={source}
              isDisabled={loading || deleting}
              onSelectionChange={(key) => {
                if (typeof key === "string") onSourceChange(key);
              }}
            >
              <Select.Trigger>
                <span className="inline-flex min-w-0 items-center gap-2">
                  <Filter size={15} className="shrink-0 text-muted-foreground" />
                  <span className="truncate">{sourceLabel}</span>
                </span>
                <Select.Indicator />
              </Select.Trigger>
              <Select.Popover>
                <Select.ListBox aria-label={t("images.sourceFilter")}>
                  {sourceOptions.map((option) => (
                    <Select.Item key={option.value} id={option.value} textValue={option.label}>
                      <span className="truncate">{option.label}</span>
                    </Select.Item>
                  ))}
                </Select.ListBox>
              </Select.Popover>
            </Select>
            {selecting ? (
              <>
                <span className="px-2 text-xs font-semibold text-muted-foreground">
                  {t("images.selectedCount", { count: selectedItems.length })}
                </span>
                <Button
                  variant="secondary"
                  size="sm"
                  disabled={selectedDownloadableCount === 0 || deleting}
                  onClick={onDownloadSelected}
                >
                  <Download size={15} />
                  {t("images.download")}
                </Button>
                <Button variant="destructive" size="sm" disabled={selectedItems.length === 0 || deleting} onClick={onDeleteSelected}>
                  {deleting ? <Spinner /> : <Trash2 size={15} />}
                  {t("images.delete")}
                </Button>
              </>
            ) : null}
            <Button variant={selecting ? "secondary" : "default"} size="sm" onClick={onToggleSelecting} disabled={loading || deleting}>
              {selecting ? t("common.cancel") : t("images.select")}
            </Button>
            <PageSelector
              page={page}
              totalPages={totalPages}
              disabled={fetching}
              jumping={fetching}
              className={fetching ? "opacity-70" : ""}
              size="sm"
              onSelect={onSelectPage}
            />
          </Toolbar>
        </div>
      </CardHeader>
      <CardContent className="min-h-[456px] flex-1 p-3">
        <div ref={bodyRef}>
          <ImageGallery
            items={items}
            loading={loading}
            columnCount={columnCount}
            selecting={selecting}
            selectedKeys={selectedKeys}
            deleting={deleting}
            onOpenPreview={onOpenPreview}
            onToggleSelected={onToggleSelected}
          />
        </div>
      </CardContent>
    </Card>
  );
}
