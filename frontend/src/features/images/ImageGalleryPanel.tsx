import { Checkbox } from "@heroui/react";
import {
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  Clock3,
  Download,
  ImageIcon,
  Loader2,
  Trash2,
  XCircle,
} from "lucide-react";
import { Button } from "@/components/heroui/button";
import { PageSelector } from "@/components/PageSelector";
import { Card, CardContent, CardHeader } from "@/components/heroui/card";
import { useI18n } from "@/i18n";
import type { ImageGalleryJob } from "@/lib/api";
import { STATUS_LABEL_KEYS } from "@/features/images/constants";
import type { GalleryItem } from "@/features/images/types";
import { formatJobTime, isActiveJob, isSelectableGalleryItem } from "@/features/images/imageUtils";

export function ImageJobStatusIcon({ job }: { job: ImageGalleryJob }) {
  if (job.status === "succeeded") return <CheckCircle2 size={15} className="text-emerald-600" />;
  if (job.status === "failed") return <XCircle size={15} className="text-destructive" />;
  if (job.status === "running") return <Loader2 size={15} className="animate-spin text-primary" />;
  return <Clock3 size={15} className="text-muted-foreground" />;
}

function ImageGallery({
  items,
  loading,
  selecting,
  selectedKeys,
  deleting,
  onOpenPreview,
  onToggleSelected,
}: {
  items: GalleryItem[];
  loading: boolean;
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
        <Loader2 size={18} className="mr-2 animate-spin" />
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
    <div className="grid auto-rows-[220px] grid-cols-[repeat(auto-fit,minmax(220px,1fr))] gap-3">
      {items.map((item) => {
        const statusLabel = t(STATUS_LABEL_KEYS[item.job.status]);
        const active = isActiveJob(item.job);
        const selectable = isSelectableGalleryItem(item);
        const selected = selectedKeys.has(item.key);
        return (
          <div
            key={item.key}
            className={`group relative flex h-[220px] min-w-0 flex-col overflow-hidden rounded-md border bg-white text-left transition-colors hover:border-primary/50 focus-within:ring-2 focus-within:ring-ring ${
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
              <div className="flex min-h-0 flex-1 items-center justify-center bg-muted/60 p-2">
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
              <div className="h-11 shrink-0 border-t px-3 py-2.5">
                <div className="flex min-w-0 items-center justify-between gap-2 text-xs text-muted-foreground">
                  <span className="flex min-w-0 items-center gap-1">{active ? <ImageJobStatusIcon job={item.job} /> : null}</span>
                  <span className="shrink-0">{formatJobTime(item.job.updated_at)}</span>
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
  selecting,
  selectedItems,
  selectedKeys,
  selectedDownloadableCount,
  deleting,
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
  selecting: boolean;
  selectedItems: GalleryItem[];
  selectedKeys: Set<string>;
  selectedDownloadableCount: number;
  deleting: boolean;
  onDownloadSelected: () => void;
  onDeleteSelected: () => void;
  onToggleSelecting: () => void;
  onSelectPage: (page: number) => void;
  onOpenPreview: (key: string) => void;
  onToggleSelected: (key: string) => void;
}) {
  const { t } = useI18n();

  return (
    <Card className="flex min-h-[520px] flex-col">
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2">
            <ImageIcon size={18} className="text-primary" />
            <h2 className="truncate text-base font-bold">{t("images.gallery")}</h2>
          </div>
          <div className="flex flex-wrap items-center justify-end gap-1">
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
                  {deleting ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
                  {t("images.delete")}
                </Button>
              </>
            ) : null}
            <Button variant={selecting ? "secondary" : "default"} size="sm" onClick={onToggleSelecting} disabled={loading || deleting}>
              {selecting ? t("common.cancel") : t("images.select")}
            </Button>
            <Button
              aria-label={t("common.previousPage")}
              title={t("common.previousPage")}
              variant="secondary"
              size="icon"
              className="h-8 w-8 rounded-md"
              onClick={() => onSelectPage(Math.max(1, page - 1))}
              disabled={page === 1 || fetching}
            >
              <ChevronLeft size={15} />
            </Button>
            <PageSelector
              page={page}
              totalPages={totalPages}
              disabled={fetching}
              jumping={fetching}
              className={fetching ? "opacity-70" : ""}
              buttonClassName="flex h-8 min-w-28 items-center justify-center gap-1 rounded-md px-2 text-center text-xs font-semibold text-foreground transition-colors hover:bg-muted disabled:pointer-events-none disabled:opacity-50"
              menuClassName="max-h-48 w-52 rounded-md"
              showChevron
              chevronSize={14}
              onSelect={onSelectPage}
            />
            <Button
              aria-label={t("common.nextPage")}
              title={t("common.nextPage")}
              variant="secondary"
              size="icon"
              className="h-8 w-8 rounded-md"
              onClick={() => onSelectPage(Math.min(totalPages, page + 1))}
              disabled={page >= totalPages || fetching}
            >
              <ChevronRight size={15} />
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="min-h-[456px] flex-1 p-4">
        <div ref={bodyRef}>
          <ImageGallery
            items={items}
            loading={loading}
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
