import type { ChangeEvent, DragEvent, FormEvent, RefObject } from "react";
import { ChevronDown, Loader2, Plus, WandSparkles, X } from "lucide-react";
import { Button } from "@/components/heroui/button";
import { Card, CardContent, CardHeader } from "@/components/heroui/card";
import { useI18n } from "@/i18n";
import { ASPECT_RATIO_OPTIONS, IMAGE_COUNT_OPTIONS, MAX_REFERENCE_IMAGES, QUALITY_OPTIONS } from "@/features/images/constants";
import type { ImageAspectRatio, ImageCount, ImageOptionMenuKey, ImageQuality, PendingReferenceImage } from "@/features/images/types";

function ImageOptionMenu<T extends string | number>({
  label,
  value,
  options,
  formatOption = String,
  open,
  placement = "down",
  onOpenChange,
  onChange,
}: {
  label: string;
  value: T;
  options: readonly T[];
  formatOption?: (value: T) => string;
  open: boolean;
  placement?: "up" | "down";
  onOpenChange: (open: boolean) => void;
  onChange: (value: T) => void;
}) {
  const menuPosition = placement === "up" ? "bottom-10" : "top-10";
  return (
    <div className="relative">
      <button
        type="button"
        onClick={() => onOpenChange(!open)}
        className="flex h-9 w-full items-center justify-between gap-2 rounded-md border bg-white px-3 text-left text-sm font-semibold transition-colors hover:bg-muted"
      >
        <span className="truncate">
          <span className="text-muted-foreground">{label}</span>
          <span className="mx-1">·</span>
          {formatOption(value)}
        </span>
        <ChevronDown size={15} className={`shrink-0 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open ? (
        <div className={`absolute left-0 right-0 ${menuPosition} z-20 overflow-hidden rounded-md border bg-white shadow-lg`}>
          {options.map((option) => (
            <button
              key={option}
              type="button"
              onClick={() => {
                onChange(option);
                onOpenChange(false);
              }}
              className={`flex h-9 w-full items-center px-3 text-left text-sm transition-colors hover:bg-muted ${
                option === value ? "font-semibold text-primary" : "text-foreground"
              }`}
            >
              {formatOption(option)}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function ImageStudioControls({
  fileInputRef,
  textareaRef,
  prompt,
  trimmedPrompt,
  aspectRatio,
  quality,
  imageCount,
  openMenu,
  referenceImages,
  queueing,
  onPromptChange,
  onAspectRatioChange,
  onQualityChange,
  onImageCountChange,
  onOpenMenuChange,
  onReferenceChange,
  onReferenceDrop,
  onPreviewReference,
  onRemoveReference,
  onSubmit,
}: {
  fileInputRef: RefObject<HTMLInputElement | null>;
  textareaRef: RefObject<HTMLTextAreaElement | null>;
  prompt: string;
  trimmedPrompt: string;
  aspectRatio: ImageAspectRatio;
  quality: ImageQuality;
  imageCount: ImageCount;
  openMenu: ImageOptionMenuKey | null;
  referenceImages: PendingReferenceImage[];
  queueing: boolean;
  onPromptChange: (prompt: string) => void;
  onAspectRatioChange: (aspectRatio: ImageAspectRatio) => void;
  onQualityChange: (quality: ImageQuality) => void;
  onImageCountChange: (imageCount: ImageCount) => void;
  onOpenMenuChange: (menu: ImageOptionMenuKey | null) => void;
  onReferenceChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onReferenceDrop: (event: DragEvent<HTMLDivElement>) => void;
  onPreviewReference: (id: string) => void;
  onRemoveReference: (id: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const { t } = useI18n();

  return (
    <Card className="flex h-full min-h-0 flex-col overflow-hidden">
      <CardHeader>
        <div className="flex items-center gap-2">
          <WandSparkles size={18} className="text-primary" />
          <h2 className="text-base font-bold">{t("images.title")}</h2>
        </div>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col p-0">
        <form className="flex min-h-0 flex-1 flex-col gap-3 p-4" onSubmit={onSubmit}>
          <div
            onDragOver={(event) => event.preventDefault()}
            onDrop={onReferenceDrop}
            className="flex min-h-[360px] flex-1 flex-col rounded-md border bg-white p-3 focus-within:ring-2 focus-within:ring-ring"
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-sm font-semibold">{t("images.prompt")}</span>
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                aria-label={t("images.addReference")}
                className="flex h-8 w-8 items-center justify-center rounded-md border bg-white text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
              >
                <Plus size={16} />
              </button>
            </div>
            <input
              ref={fileInputRef}
              type="file"
              accept="image/png,image/jpeg,image/webp"
              multiple
              className="hidden"
              onChange={onReferenceChange}
            />
            <div className="mb-3 grid h-16 grid-cols-4 gap-2">
              {Array.from({ length: MAX_REFERENCE_IMAGES }, (_, index) => {
                const reference = referenceImages[index];
                return reference ? (
                  <div key={reference.id} className="relative overflow-hidden rounded-md border bg-muted">
                    <button type="button" onClick={() => onPreviewReference(reference.id)} className="h-full w-full">
                      <img src={reference.previewUrl} alt={reference.fileName} className="h-full w-full object-cover" />
                    </button>
                    <button
                      type="button"
                      onClick={() => onRemoveReference(reference.id)}
                      aria-label={t("images.referenceRemove")}
                      className="absolute right-1 top-1 flex h-5 w-5 items-center justify-center rounded bg-white/90 text-foreground shadow-soft hover:bg-white"
                    >
                      <X size={11} />
                    </button>
                  </div>
                ) : (
                  <button
                    key={`reference-slot-${index}`}
                    type="button"
                    onClick={() => fileInputRef.current?.click()}
                    aria-label={t("images.addReference")}
                    className="flex h-full items-center justify-center rounded-md border border-dashed bg-muted/40 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                  >
                    {index === 0 && referenceImages.length === 0 ? <Plus size={15} /> : null}
                  </button>
                );
              })}
            </div>
            <textarea
              ref={textareaRef}
              value={prompt}
              onChange={(event) => onPromptChange(event.target.value)}
              placeholder={t("images.promptPlaceholder")}
              className="min-h-[190px] flex-1 resize-none border-0 bg-transparent p-0 text-sm leading-6 outline-none placeholder:text-muted-foreground"
            />
          </div>

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <ImageOptionMenu
              label={t("images.size")}
              value={aspectRatio}
              options={ASPECT_RATIO_OPTIONS}
              formatOption={(option) => option}
              open={openMenu === "aspectRatio"}
              placement="up"
              onOpenChange={(open) => onOpenMenuChange(open ? "aspectRatio" : null)}
              onChange={onAspectRatioChange}
            />
            <ImageOptionMenu
              label={t("images.quality")}
              value={quality}
              options={QUALITY_OPTIONS}
              formatOption={(option) => t(`images.quality.${option}`)}
              open={openMenu === "quality"}
              placement="up"
              onOpenChange={(open) => onOpenMenuChange(open ? "quality" : null)}
              onChange={onQualityChange}
            />
            <ImageOptionMenu
              label={t("images.count")}
              value={imageCount}
              options={IMAGE_COUNT_OPTIONS}
              open={openMenu === "imageCount"}
              placement="up"
              onOpenChange={(open) => onOpenMenuChange(open ? "imageCount" : null)}
              onChange={onImageCountChange}
            />
          </div>

          <Button type="submit" className="w-full" disabled={!trimmedPrompt || queueing}>
            {queueing ? <Loader2 size={16} className="animate-spin" /> : <WandSparkles size={16} />}
            {queueing ? t("images.queueing") : t("images.generate")}
          </Button>
        </form>
      </CardContent>
    </Card>
  );
}
