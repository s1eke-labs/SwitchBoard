import { useEffect, useMemo, useRef, useState } from "react";
import type { ChangeEvent, ClipboardEvent, DragEvent, FormEvent } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "@heroui/react";
import { api, type ImageGalleryJob, type ImageGenerationRequest, type ImageReferenceInput } from "@/lib/api";
import { formatAppError } from "@/lib/errors";
import { useI18n } from "@/i18n";
import {
  GALLERY_CARD_HEIGHT,
  GALLERY_FALLBACK_PAGE_SIZE,
  GALLERY_GRID_GAP,
  GALLERY_MAX_PAGE_SIZE,
  GALLERY_MIN_COLUMN_WIDTH,
  IMAGE_SIZE_BY_RATIO_AND_QUALITY,
  MAX_REFERENCE_IMAGE_BYTES,
  MAX_REFERENCE_IMAGES,
  REFERENCE_IMAGE_TYPES,
} from "@/features/images/constants";
import { ImageGalleryPanel } from "@/features/images/ImageGalleryPanel";
import { ImageStudioControls } from "@/features/images/ImageStudioControls";
import { DeleteConfirmModal, ImagePreviewModal, ReferencePreviewModal } from "@/features/images/ImageStudioModals";
import type {
  GalleryItem,
  ImageAspectRatio,
  ImageCount,
  ImageQuality,
  ImageSize,
  PendingReferenceImage,
} from "@/features/images/types";
import {
  blobToBase64,
  downloadGalleryItem,
  fileToReference,
  galleryApiItemsFromJob,
  galleryItemsFromApiItems,
  isActiveJob,
  isSelectableGalleryItem,
  sourceToReference,
} from "@/features/images/imageUtils";

export function ImageStudioPage() {
  const { t } = useI18n();
  const queryClient = useQueryClient();
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const galleryBodyRef = useRef<HTMLDivElement | null>(null);
  const referenceImagesRef = useRef<PendingReferenceImage[]>([]);
  const [galleryLayout, setGalleryLayout] = useState({
    width: 0,
    top: 0,
    viewportHeight: typeof window === "undefined" ? 0 : window.innerHeight,
  });
  const [prompt, setPrompt] = useState("");
  const [aspectRatio, setAspectRatio] = useState<ImageAspectRatio>("1:1");
  const [quality, setQuality] = useState<ImageQuality>("low");
  const [imageCount, setImageCount] = useState<ImageCount>(1);
  const [referenceImages, setReferenceImages] = useState<PendingReferenceImage[]>([]);
  const [previewReferenceId, setPreviewReferenceId] = useState<string | null>(null);
  const [selectedItemKey, setSelectedItemKey] = useState<string | null>(null);
  const [galleryPage, setGalleryPage] = useState(1);
  const [editingItemKey, setEditingItemKey] = useState<string | null>(null);
  const [selectingGallery, setSelectingGallery] = useState(false);
  const [selectedGalleryKeys, setSelectedGalleryKeys] = useState<Set<string>>(() => new Set());
  const [pendingDeleteItems, setPendingDeleteItems] = useState<GalleryItem[] | null>(null);
  const trimmedPrompt = prompt.trim();
  const galleryPageSize = useMemo(() => {
    if (!galleryLayout.width || !galleryLayout.viewportHeight) return GALLERY_FALLBACK_PAGE_SIZE;
    const columns = Math.max(
      1,
      Math.floor((galleryLayout.width + GALLERY_GRID_GAP) / (GALLERY_MIN_COLUMN_WIDTH + GALLERY_GRID_GAP)),
    );
    const availableHeight = Math.max(GALLERY_CARD_HEIGHT, galleryLayout.viewportHeight - galleryLayout.top - 24);
    const rows = Math.max(1, Math.floor((availableHeight + GALLERY_GRID_GAP) / (GALLERY_CARD_HEIGHT + GALLERY_GRID_GAP)));
    return Math.max(1, Math.min(GALLERY_MAX_PAGE_SIZE, columns * rows));
  }, [galleryLayout]);

  const gallery = useQuery({
    queryKey: ["imageGallery", galleryPage, galleryPageSize],
    queryFn: () => api.imageGalleryItems({ page: galleryPage, limit: galleryPageSize }),
    placeholderData: (previousData) => previousData,
    refetchInterval: (query) => {
      const data = query.state.data?.items;
      return data?.some((item) => isActiveJob(item.job)) ? 3000 : false;
    },
  });
  const galleryItems = useMemo(() => galleryItemsFromApiItems(gallery.data?.items ?? []), [gallery.data?.items]);
  const galleryTotalPages = Math.max(1, Math.ceil((gallery.data?.total_count ?? 0) / galleryPageSize));
  const selectedItem = useMemo(
    () => galleryItems.find((item) => item.key === selectedItemKey) ?? null,
    [galleryItems, selectedItemKey],
  );
  const selectedGalleryItems = useMemo(
    () => galleryItems.filter((item) => selectedGalleryKeys.has(item.key) && isSelectableGalleryItem(item)),
    [galleryItems, selectedGalleryKeys],
  );
  const selectedDownloadableCount = selectedGalleryItems.filter((item) => item.fullSrc).length;
  const previewReference = useMemo(
    () => referenceImages.find((reference) => reference.id === previewReferenceId) ?? null,
    [previewReferenceId, referenceImages],
  );

  useEffect(() => {
    referenceImagesRef.current = referenceImages;
  }, [referenceImages]);

  useEffect(() => {
    return () => {
      for (const reference of referenceImagesRef.current) {
        URL.revokeObjectURL(reference.previewUrl);
      }
    };
  }, []);

  useEffect(() => {
    function measureGallery() {
      const rect = galleryBodyRef.current?.getBoundingClientRect();
      setGalleryLayout((current) => {
        const next = {
          width: Math.floor(rect?.width ?? 0),
          top: Math.floor(rect?.top ?? 0),
          viewportHeight: window.innerHeight,
        };
        return current.width === next.width && current.top === next.top && current.viewportHeight === next.viewportHeight
          ? current
          : next;
      });
    }

    measureGallery();
    const observer = new ResizeObserver(measureGallery);
    if (galleryBodyRef.current) observer.observe(galleryBodyRef.current);
    window.addEventListener("resize", measureGallery);
    window.addEventListener("orientationchange", measureGallery);
    return () => {
      observer.disconnect();
      window.removeEventListener("resize", measureGallery);
      window.removeEventListener("orientationchange", measureGallery);
    };
  }, []);

  useEffect(() => {
    if (!gallery.isFetching && galleryPage > galleryTotalPages) {
      setGalleryPage(galleryTotalPages);
    }
  }, [galleryPage, galleryTotalPages, gallery.isFetching]);

  useEffect(() => {
    setSelectedGalleryKeys((current) => {
      const available = new Set(galleryItems.filter(isSelectableGalleryItem).map((item) => item.key));
      const next = new Set([...current].filter((key) => available.has(key)));
      return next.size === current.size ? current : next;
    });
  }, [galleryItems]);

  const createJob = useMutation({
    mutationFn: (payload: ImageGenerationRequest) => api.createImageJob(payload),
    onSuccess: (job) => {
      setGalleryPage(1);
      queryClient.setQueryData(["imageGallery", 1, galleryPageSize], (current: typeof gallery.data | undefined) => {
        if (!current) return current;
        const existingSlots = current.items.filter((item) => item.job.id === job.id).length;
        const incomingSlots = galleryApiItemsFromJob(job);
        return {
          ...current,
          items: [...incomingSlots, ...current.items.filter((item) => item.job.id !== job.id)].slice(0, galleryPageSize),
          total_count: current.total_count + Math.max(incomingSlots.length - existingSlots, 0),
        };
      });
      queryClient.invalidateQueries({ queryKey: ["imageGallery"] });
      queryClient.invalidateQueries({ queryKey: ["imageJobs"] });
      for (const reference of referenceImagesRef.current) {
        URL.revokeObjectURL(reference.previewUrl);
      }
      setReferenceImages([]);
      toast.success(t("images.jobQueued"));
    },
    onError: (error) => {
      toast.danger(t("images.generateFailed"), {
        description: formatAppError(error),
      });
    },
  });

  const retryJob = useMutation({
    mutationFn: async (job: ImageGalleryJob) => {
      const references: ImageReferenceInput[] = [];
      for (const reference of job.references) {
        const response = await fetch(reference.file_url);
        if (!response.ok) throw new Error("fetch failed");
        references.push({
          file_name: reference.original_file_name,
          mime_type: reference.mime_type,
          b64_json: await blobToBase64(await response.blob()),
        });
      }
      const retry = await api.createImageJob({
        prompt: job.prompt,
        size: job.size as ImageGenerationRequest["size"],
        quality: "auto",
        n: job.n,
        response_format: "b64_json",
        reference_images: references,
      });
      await api.deleteImageJob(job.id);
      return retry;
    },
    onSuccess: () => {
      setGalleryPage(1);
      setSelectedItemKey(null);
      queryClient.invalidateQueries({ queryKey: ["imageGallery"] });
      queryClient.invalidateQueries({ queryKey: ["imageJobs"] });
      toast.success(t("images.jobQueued"));
    },
    onError: (error) => {
      toast.danger(t("images.retryFailed"), {
        description: formatAppError(error),
      });
    },
  });

  const deleteImages = useMutation({
    mutationFn: async (items: GalleryItem[]) => {
      const orderedItems = [...items].sort((first, second) => {
        const jobOrder = first.job.id.localeCompare(second.job.id);
        return jobOrder || second.index - first.index;
      });
      for (const item of orderedItems) {
        if (item.fullSrc) {
          await api.deleteImageJobResult(item.job.id, item.index);
        } else {
          await api.deleteImageJob(item.job.id);
        }
      }
    },
    onSuccess: () => {
      setPendingDeleteItems(null);
      setSelectedItemKey(null);
      setSelectedGalleryKeys(new Set());
      setSelectingGallery(false);
      queryClient.invalidateQueries({ queryKey: ["imageGallery"] });
      queryClient.invalidateQueries({ queryKey: ["imageJobs"] });
      toast.success(t("images.deleted"));
    },
    onError: (error) => {
      toast.danger(t("images.deleteFailed"), {
        description: formatAppError(error),
      });
    },
  });

  async function addReferenceFiles(files: FileList | File[]) {
    const incoming = Array.from(files);
    const slots = MAX_REFERENCE_IMAGES - referenceImages.length;
    if (incoming.length > slots) {
      toast.danger(t("images.referenceTooMany"));
    }
    const accepted = incoming.slice(0, Math.max(0, slots));
    const nextReferences: PendingReferenceImage[] = [];
    for (const file of accepted) {
      if (!REFERENCE_IMAGE_TYPES.has(file.type)) {
        toast.danger(t("images.referenceUnsupported", { name: file.name }));
        continue;
      }
      if (file.size > MAX_REFERENCE_IMAGE_BYTES) {
        toast.danger(t("images.referenceTooLarge", { name: file.name }));
        continue;
      }
      try {
        nextReferences.push(await fileToReference(file));
      } catch {
        toast.danger(t("images.referenceReadFailed", { name: file.name }));
      }
    }
    if (nextReferences.length > 0) {
      setReferenceImages((current) => [...current, ...nextReferences]);
    }
  }

  function handleReferenceChange(event: ChangeEvent<HTMLInputElement>) {
    const files = event.currentTarget.files;
    if (files) void addReferenceFiles(files);
    event.currentTarget.value = "";
  }

  function handleReferenceDrop(event: DragEvent<HTMLDivElement>) {
    event.preventDefault();
    void addReferenceFiles(event.dataTransfer.files);
  }

  function handleReferencePaste(event: ClipboardEvent<HTMLElement>) {
    const imageFiles: File[] = [];
    for (const item of Array.from(event.clipboardData.items)) {
      if (item.kind !== "file" || !item.type.startsWith("image/")) continue;
      const file = item.getAsFile();
      if (file) imageFiles.push(file);
    }
    if (imageFiles.length === 0) {
      imageFiles.push(...Array.from(event.clipboardData.files).filter((file) => file.type.startsWith("image/")));
    }
    if (imageFiles.length === 0) return;
    event.preventDefault();
    void addReferenceFiles(imageFiles);
  }

  function removeReference(id: string) {
    setReferenceImages((current) => {
      const removed = current.find((reference) => reference.id === id);
      if (removed) URL.revokeObjectURL(removed.previewUrl);
      return current.filter((reference) => reference.id !== id);
    });
  }

  async function handleEditItem(item: GalleryItem) {
    if (!item.fullSrc) return;
    setEditingItemKey(item.key);
    try {
      const reference = await sourceToReference(item.fullSrc, item.job, item.index);
      setReferenceImages((current) => {
        for (const existing of current) {
          URL.revokeObjectURL(existing.previewUrl);
        }
        return [reference];
      });
      setSelectedItemKey(null);
      window.setTimeout(() => textareaRef.current?.focus(), 0);
      toast.success(t("images.editReady"));
    } catch {
      toast.danger(t("images.editReferenceFailed"));
    } finally {
      setEditingItemKey(null);
    }
  }

  function toggleGallerySelection(key: string) {
    setSelectedGalleryKeys((current) => {
      const next = new Set(current);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }

  function toggleSelectingGallery() {
    setSelectingGallery((current) => {
      if (current) setSelectedGalleryKeys(new Set());
      return !current;
    });
  }

  function downloadSelectedImages() {
    for (const item of selectedGalleryItems) {
      downloadGalleryItem(item);
    }
  }

  function deleteSelectedImages() {
    if (selectedGalleryItems.length === 0 || deleteImages.isPending) return;
    setPendingDeleteItems(selectedGalleryItems);
  }

  function deletePreviewImage(item: GalleryItem) {
    if (!isSelectableGalleryItem(item) || deleteImages.isPending) return;
    setPendingDeleteItems([item]);
  }

  function retryPreviewJob(item: GalleryItem) {
    if (item.job.status !== "failed" || retryJob.isPending) return;
    retryJob.mutate(item.job);
  }

  function confirmDeleteImages() {
    if (!pendingDeleteItems?.length || deleteImages.isPending) return;
    deleteImages.mutate(pendingDeleteItems);
  }

  async function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!trimmedPrompt || createJob.isPending) return;
    const references: ImageReferenceInput[] = referenceImages.map((reference) => ({
      file_name: reference.fileName,
      mime_type: reference.mimeType,
      b64_json: reference.b64Json,
    }));
    const selectedSize: ImageSize = IMAGE_SIZE_BY_RATIO_AND_QUALITY[aspectRatio][quality];
    createJob.mutate({
      prompt: trimmedPrompt,
      size: selectedSize,
      quality: "auto",
      n: imageCount,
      response_format: "b64_json",
      reference_images: references,
    });
    setPrompt("");
  }

  function selectGalleryPage(targetPage: number) {
    if (targetPage === galleryPage || targetPage < 1 || targetPage > galleryTotalPages || gallery.isFetching) return;
    setGalleryPage(targetPage);
    setSelectedItemKey(null);
  }

  return (
    <>
      <div className="grid min-h-[760px] w-full flex-1 grid-cols-1 gap-4 lg:grid-cols-[380px_minmax(0,1fr)]">
        <ImageStudioControls
          fileInputRef={fileInputRef}
          textareaRef={textareaRef}
          prompt={prompt}
          trimmedPrompt={trimmedPrompt}
          aspectRatio={aspectRatio}
          quality={quality}
          imageCount={imageCount}
          referenceImages={referenceImages}
          queueing={createJob.isPending}
          onPromptChange={setPrompt}
          onAspectRatioChange={setAspectRatio}
          onQualityChange={setQuality}
          onImageCountChange={setImageCount}
          onReferenceChange={handleReferenceChange}
          onReferenceDrop={handleReferenceDrop}
          onReferencePaste={handleReferencePaste}
          onPreviewReference={setPreviewReferenceId}
          onRemoveReference={removeReference}
          onSubmit={handleSubmit}
        />

        <ImageGalleryPanel
          bodyRef={galleryBodyRef}
          items={galleryItems}
          loading={gallery.isPending}
          fetching={gallery.isFetching}
          page={galleryPage}
          totalPages={galleryTotalPages}
          selecting={selectingGallery}
          selectedItems={selectedGalleryItems}
          selectedKeys={selectedGalleryKeys}
          selectedDownloadableCount={selectedDownloadableCount}
          deleting={deleteImages.isPending}
          onDownloadSelected={downloadSelectedImages}
          onDeleteSelected={deleteSelectedImages}
          onToggleSelecting={toggleSelectingGallery}
          onSelectPage={selectGalleryPage}
          onOpenPreview={setSelectedItemKey}
          onToggleSelected={toggleGallerySelection}
        />
      </div>

      {selectedItem ? (
        <ImagePreviewModal
          item={selectedItem}
          editing={editingItemKey === selectedItem.key}
          deleting={deleteImages.isPending}
          retrying={retryJob.isPending}
          onEdit={handleEditItem}
          onDelete={deletePreviewImage}
          onRetry={retryPreviewJob}
          onClose={() => setSelectedItemKey(null)}
        />
      ) : null}
      {pendingDeleteItems ? (
        <DeleteConfirmModal
          count={pendingDeleteItems.length}
          deleting={deleteImages.isPending}
          onConfirm={confirmDeleteImages}
          onClose={() => setPendingDeleteItems(null)}
        />
      ) : null}
      {previewReference ? <ReferencePreviewModal reference={previewReference} onClose={() => setPreviewReferenceId(null)} /> : null}
    </>
  );
}
