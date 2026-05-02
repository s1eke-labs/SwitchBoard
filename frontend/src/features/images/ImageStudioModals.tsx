import { Download, ImageIcon, Info, Pencil, Trash2, WandSparkles } from "lucide-react";
import { Alert } from "@/components/heroui/alert";
import { AlertDialog } from "@/components/heroui/alert-dialog";
import { Button } from "@/components/heroui/button";
import { CloseButton } from "@/components/heroui/close-button";
import { Modal } from "@/components/heroui/modal";
import { Spinner } from "@/components/heroui/spinner";
import { Toolbar } from "@/components/heroui/toolbar";
import { Tooltip } from "@/components/heroui/tooltip";
import { useI18n } from "@/i18n";
import { STATUS_LABEL_KEYS } from "@/features/images/constants";
import type { GalleryItem, PendingReferenceImage } from "@/features/images/types";
import { downloadGalleryItem, formatBytes, formatDuration, isSelectableGalleryItem } from "@/features/images/imageUtils";
import { ImageJobStatusIcon } from "@/features/images/ImageGalleryPanel";
import type { ImageUpstreamMetadata } from "@/lib/api";

export function ReferencePreviewModal({
  reference,
  onClose,
}: {
  reference: PendingReferenceImage;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <Modal isOpen onOpenChange={(open) => { if (!open) onClose(); }}>
      <Modal.Backdrop variant="opaque">
        <Modal.Container placement="center" size="cover" className="p-3 sm:p-6">
          <Modal.Dialog className="max-h-[92vh] max-w-3xl overflow-hidden rounded-md bg-background p-0">
            <Modal.Header className="flex-row items-center justify-between gap-3 border-b px-4 py-3">
              <Modal.Heading className="truncate text-sm font-semibold">{t("images.references")}</Modal.Heading>
              <Tooltip content={t("images.closePreview")}>
                <CloseButton type="button" aria-label={t("images.closePreview")} onPress={onClose} />
              </Tooltip>
            </Modal.Header>
            <Modal.Body className="flex min-h-[320px] items-center justify-center bg-muted p-4">
              <img src={reference.previewUrl} alt={reference.fileName} className="max-h-[78vh] max-w-full rounded-md object-contain" />
            </Modal.Body>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}

export function DeleteConfirmModal({
  count,
  deleting,
  onConfirm,
  onClose,
}: {
  count: number;
  deleting: boolean;
  onConfirm: () => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  return (
    <AlertDialog isOpen onOpenChange={(open) => { if (!open && !deleting) onClose(); }}>
      <AlertDialog.Backdrop>
        <AlertDialog.Container>
          <AlertDialog.Dialog>
            <AlertDialog.Header>
              <AlertDialog.Icon status="danger" />
              <AlertDialog.Heading>{t("images.deleteConfirmTitle")}</AlertDialog.Heading>
            </AlertDialog.Header>
            <AlertDialog.Body>{t("images.deleteConfirm", { count })}</AlertDialog.Body>
            <AlertDialog.Footer>
              <Button type="button" variant="secondary" disabled={deleting} onClick={onClose}>
                {t("common.cancel")}
              </Button>
              <Button type="button" variant="destructive" disabled={deleting} onClick={onConfirm}>
                {deleting ? <Spinner /> : <Trash2 size={15} />}
                {t("images.deleteConfirmAction")}
              </Button>
            </AlertDialog.Footer>
          </AlertDialog.Dialog>
        </AlertDialog.Container>
      </AlertDialog.Backdrop>
    </AlertDialog>
  );
}

function formatDimensionText(value: string | null | undefined, autoLabel: string, unknownLabel: string) {
  if (!value) return unknownLabel;
  if (value === "auto") return autoLabel;
  const dimensions = value.match(/^(\d+)x(\d+)$/);
  if (dimensions) return `${dimensions[1]} x ${dimensions[2]}`;
  return value;
}

function formatToken(value: number | null | undefined, unknownLabel: string) {
  return value == null ? unknownLabel : value.toLocaleString();
}

function hasTokenMetadata(metadata: ImageUpstreamMetadata | null) {
  return Boolean(metadata?.image_usage);
}

export function ImagePreviewModal({
  item,
  editing,
  deleting,
  retrying,
  onEdit,
  onDelete,
  onRetry,
  onClose,
}: {
  item: GalleryItem;
  editing: boolean;
  deleting: boolean;
  retrying: boolean;
  onEdit: (item: GalleryItem) => void;
  onDelete: (item: GalleryItem) => void;
  onRetry: (item: GalleryItem) => void;
  onClose: () => void;
}) {
  const { t } = useI18n();
  const { job } = item;
  const src = item.fullSrc;
  const revisedPrompt = item.revisedPrompt;
  const upstreamMetadata = job.upstream_metadata[item.index] ?? job.upstream_metadata[0] ?? null;
  const generationDuration = upstreamMetadata?.duration_seconds ?? item.durationSeconds ?? (job.status === "queued" ? null : Math.max(0, job.updated_at - job.created_at));
  const imageResolution = upstreamMetadata?.resolved_size
    ? formatDimensionText(upstreamMetadata.resolved_size, t("images.size.auto"), t("common.unknown"))
    : item.width && item.height
      ? `${item.width} x ${item.height}`
      : t("common.unknown");
  const imageSize = item.sizeBytes ? formatBytes(item.sizeBytes) : t("common.unknown");
  const promptModel = upstreamMetadata?.response_model ?? null;
  const imageModel = upstreamMetadata?.image_model ?? t("common.unknown");
  const showTokens = hasTokenMetadata(upstreamMetadata);
  const infoRowClass = "grid grid-cols-[76px_minmax(0,1fr)] items-center gap-3 px-3 py-1.5";

  function handleDownload() {
    downloadGalleryItem(item);
  }

  return (
    <Modal isOpen onOpenChange={(open) => { if (!open) onClose(); }}>
      <Modal.Backdrop variant="opaque">
        <Modal.Container placement="center" size="cover" className="p-3 sm:p-6">
          <Modal.Dialog className="max-h-[92vh] max-w-5xl overflow-hidden rounded-md bg-background p-0">
            <Modal.Header className="flex-row items-center justify-between gap-3 border-b px-4 py-3">
              <Modal.Heading className="flex min-w-0 items-center gap-2">
                <ImageJobStatusIcon job={job} />
                <span className="truncate text-sm font-semibold">{t(STATUS_LABEL_KEYS[job.status])}</span>
              </Modal.Heading>
              <Toolbar aria-label={t("images.preview")}>
                <Button variant="secondary" size="sm" disabled={!src} onClick={handleDownload}>
                  <Download size={15} />
                  {t("images.download")}
                </Button>
                <Button variant="secondary" size="sm" disabled={!src || editing} onClick={() => onEdit(item)}>
                  {editing ? <Spinner /> : <Pencil size={15} />}
                  {t("images.edit")}
                </Button>
                {job.status === "failed" ? (
                  <Button variant="secondary" size="sm" disabled={retrying} onClick={() => onRetry(item)}>
                    {retrying ? <Spinner /> : <WandSparkles size={15} />}
                    {t("images.retry")}
                  </Button>
                ) : null}
                <Button variant="destructive" size="sm" disabled={!isSelectableGalleryItem(item) || deleting} onClick={() => onDelete(item)}>
                  {deleting ? <Spinner /> : <Trash2 size={15} />}
                  {t("images.delete")}
                </Button>
                <Tooltip content={t("images.closePreview")}>
                  <CloseButton type="button" aria-label={t("images.closePreview")} onPress={onClose} />
                </Tooltip>
              </Toolbar>
            </Modal.Header>
            <Modal.Body className="grid min-h-0 flex-1 gap-0 overflow-auto p-0 lg:grid-cols-[minmax(0,1fr)_320px]">
              <div className="flex min-h-[360px] items-center justify-center bg-muted p-4">
                {src ? (
                  <img src={src} alt={revisedPrompt || t("images.preview")} className="max-h-[72vh] max-w-full rounded-md object-contain" />
                ) : (
                  <div className="flex items-center text-sm text-muted-foreground">
                    <ImageJobStatusIcon job={job} />
                    <span className="ml-2">{t(STATUS_LABEL_KEYS[job.status])}</span>
                  </div>
                )}
              </div>
              <div className="space-y-4 overflow-auto border-t p-4 lg:border-l lg:border-t-0">
                <div>
                  <div className="mb-1 flex items-center gap-1 text-xs font-semibold uppercase text-muted-foreground">
                    <Info size={13} />
                    {t("images.info")}
                  </div>
                  <dl className="divide-y divide-border rounded-md border text-sm">
                    <div className={infoRowClass}>
                      <dt className="text-muted-foreground">{t("images.generationDuration")}</dt>
                      <dd className="min-w-0 truncate text-foreground">
                        {generationDuration === null ? t("common.unknown") : formatDuration(generationDuration)}
                      </dd>
                    </div>
                    <div className={infoRowClass}>
                      <dt className="text-muted-foreground">{t("images.resolution")}</dt>
                      <dd className="min-w-0 truncate text-foreground">{imageResolution}</dd>
                    </div>
                    <div className={infoRowClass}>
                      <dt className="text-muted-foreground">{t("images.fileSize")}</dt>
                      <dd className="min-w-0 truncate text-foreground">{imageSize}</dd>
                    </div>
                    <div className={infoRowClass}>
                      <dt className="text-muted-foreground">{t("images.imageModel")}</dt>
                      <dd className="min-w-0 truncate text-foreground">{imageModel}</dd>
                    </div>
                    {showTokens ? (
                      <>
                        <div className={infoRowClass}>
                          <dt className="text-muted-foreground">{t("images.tokenInputImage")}</dt>
                          <dd className="min-w-0 truncate text-foreground">{formatToken(upstreamMetadata?.image_usage?.input_image_tokens, t("common.unknown"))}</dd>
                        </div>
                        <div className={infoRowClass}>
                          <dt className="text-muted-foreground">{t("images.tokenOutputImage")}</dt>
                          <dd className="min-w-0 truncate text-foreground">{formatToken(upstreamMetadata?.image_usage?.output_image_tokens, t("common.unknown"))}</dd>
                        </div>
                      </>
                    ) : null}
                  </dl>
                </div>
                <div>
                  <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">{t("images.prompt")}</div>
                  <p className="whitespace-pre-wrap break-words text-sm leading-6">{job.prompt}</p>
                </div>
                {revisedPrompt ? (
                  <div>
                    <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">{t("images.revisedPrompt")}</div>
                    {(promptModel || upstreamMetadata?.image_usage?.input_text_tokens != null) ? (
                      <dl className="mb-2 divide-y divide-border rounded-md border text-xs">
                        {promptModel ? (
                          <div className="grid grid-cols-[76px_minmax(0,1fr)] items-center gap-3 px-3 py-1.5">
                            <dt className="text-muted-foreground">{t("images.promptModel")}</dt>
                            <dd className="min-w-0 truncate text-foreground">{promptModel}</dd>
                          </div>
                        ) : null}
                        {upstreamMetadata?.image_usage?.input_text_tokens != null ? (
                          <div className="grid grid-cols-[76px_minmax(0,1fr)] items-center gap-3 px-3 py-1.5">
                            <dt className="text-muted-foreground">{t("images.promptTokens")}</dt>
                            <dd className="min-w-0 truncate text-foreground">{formatToken(upstreamMetadata.image_usage.input_text_tokens, t("common.unknown"))}</dd>
                          </div>
                        ) : null}
                      </dl>
                    ) : null}
                    <p className="whitespace-pre-wrap break-words text-sm leading-6">{revisedPrompt}</p>
                  </div>
                ) : null}
                {job.references.length ? (
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">{t("images.references")}</div>
                    <div className="grid grid-cols-2 gap-2">
                      {job.references.map((reference) => (
                        <div key={reference.id} className="overflow-hidden rounded-md border bg-white">
                          {reference.thumbnail_url ? (
                            <img src={reference.thumbnail_url} alt={reference.original_file_name} className="aspect-square w-full object-cover" />
                          ) : (
                            <div className="flex aspect-square w-full items-center justify-center bg-muted text-muted-foreground">
                              <ImageIcon size={18} />
                            </div>
                          )}
                          <div className="px-2 py-1.5 text-xs">
                            <div className="truncate font-semibold">{reference.original_file_name}</div>
                            <div className="text-muted-foreground">{formatBytes(reference.size_bytes)}</div>
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
                {job.error ? (
                  <Alert tone="danger" className="p-3">
                    {job.error.message}
                  </Alert>
                ) : null}
              </div>
            </Modal.Body>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
