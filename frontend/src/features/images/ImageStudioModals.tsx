import { Modal } from "@heroui/react";
import { Download, Loader2, Palette, Pencil, Trash2, WandSparkles, X } from "lucide-react";
import { Button } from "@/components/heroui/button";
import { useI18n } from "@/i18n";
import { STATUS_LABEL_KEYS } from "@/features/images/constants";
import type { GalleryItem, PendingReferenceImage } from "@/features/images/types";
import { downloadGalleryItem, formatBytes, formatImageStyleLabel, isSelectableGalleryItem } from "@/features/images/imageUtils";
import { ImageJobStatusIcon } from "@/features/images/ImageGalleryPanel";

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
              <Button type="button" variant="ghost" size="icon" aria-label={t("images.closePreview")} onClick={onClose}>
                <X size={18} />
              </Button>
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
    <Modal isOpen onOpenChange={(open) => { if (!open && !deleting) onClose(); }}>
      <Modal.Backdrop variant="opaque">
        <Modal.Container placement="center" size="sm" className="p-3">
          <Modal.Dialog className="overflow-hidden rounded-md bg-background p-0">
            <Modal.Header className="flex-row items-center justify-between gap-3 border-b px-4 py-3">
              <Modal.Heading className="truncate text-sm font-semibold">{t("images.deleteConfirmTitle")}</Modal.Heading>
              <Button type="button" variant="ghost" size="icon" aria-label={t("common.cancel")} disabled={deleting} onClick={onClose}>
                <X size={18} />
              </Button>
            </Modal.Header>
            <Modal.Body className="px-4 py-4">
              <p className="text-sm leading-6 text-muted-foreground">{t("images.deleteConfirm", { count })}</p>
            </Modal.Body>
            <Modal.Footer className="justify-end gap-2 border-t px-4 py-3">
              <Button type="button" variant="secondary" disabled={deleting} onClick={onClose}>
                {t("common.cancel")}
              </Button>
              <Button type="button" variant="destructive" disabled={deleting} onClick={onConfirm}>
                {deleting ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
                {t("images.deleteConfirmAction")}
              </Button>
            </Modal.Footer>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
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
  const { job, src } = item;
  const revisedPrompt = item.revisedPrompt;
  const styleLabel = formatImageStyleLabel(job.size, job.quality, t);

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
              <div className="flex items-center gap-2">
                <Button variant="secondary" size="sm" disabled={!src} onClick={handleDownload}>
                  <Download size={15} />
                  {t("images.download")}
                </Button>
                <Button variant="secondary" size="sm" disabled={!src || editing} onClick={() => onEdit(item)}>
                  {editing ? <Loader2 size={15} className="animate-spin" /> : <Pencil size={15} />}
                  {t("images.edit")}
                </Button>
                {job.status === "failed" ? (
                  <Button variant="secondary" size="sm" disabled={retrying} onClick={() => onRetry(item)}>
                    {retrying ? <Loader2 size={15} className="animate-spin" /> : <WandSparkles size={15} />}
                    {t("images.retry")}
                  </Button>
                ) : null}
                <Button variant="destructive" size="sm" disabled={!isSelectableGalleryItem(item) || deleting} onClick={() => onDelete(item)}>
                  {deleting ? <Loader2 size={15} className="animate-spin" /> : <Trash2 size={15} />}
                  {t("images.delete")}
                </Button>
                <Button type="button" variant="ghost" size="icon" aria-label={t("images.closePreview")} onClick={onClose}>
                  <X size={18} />
                </Button>
              </div>
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
                    <Palette size={13} />
                    {t("images.style")}
                  </div>
                  <p className="text-sm leading-6">{styleLabel}</p>
                </div>
                <div>
                  <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">{t("images.prompt")}</div>
                  <p className="whitespace-pre-wrap break-words text-sm leading-6">{job.prompt}</p>
                </div>
                {revisedPrompt ? (
                  <div>
                    <div className="mb-1 text-xs font-semibold uppercase text-muted-foreground">{t("images.revisedPrompt")}</div>
                    <p className="whitespace-pre-wrap break-words text-sm leading-6">{revisedPrompt}</p>
                  </div>
                ) : null}
                {job.references.length ? (
                  <div>
                    <div className="mb-2 text-xs font-semibold uppercase text-muted-foreground">{t("images.references")}</div>
                    <div className="grid grid-cols-2 gap-2">
                      {job.references.map((reference) => (
                        <div key={reference.id} className="overflow-hidden rounded-md border bg-white">
                          <img src={reference.file_url} alt={reference.original_file_name} className="aspect-square w-full object-cover" />
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
                  <div className="rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive">
                    {job.error.message}
                  </div>
                ) : null}
              </div>
            </Modal.Body>
          </Modal.Dialog>
        </Modal.Container>
      </Modal.Backdrop>
    </Modal>
  );
}
