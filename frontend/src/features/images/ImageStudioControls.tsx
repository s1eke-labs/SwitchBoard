import { useState, type ChangeEvent, type DragEvent, type FormEvent, type RefObject } from "react";
import { ChevronDown, Plus, WandSparkles, X } from "lucide-react";
import { Button } from "@/components/heroui/button";
import { Card, CardContent, CardHeader } from "@/components/heroui/card";
import { Form } from "@/components/heroui/form";
import { Spinner } from "@/components/heroui/spinner";
import { TextArea } from "@/components/heroui/textarea";
import { useI18n } from "@/i18n";
import { ASPECT_RATIO_OPTIONS, IMAGE_COUNT_OPTIONS, MAX_REFERENCE_IMAGES, QUALITY_OPTIONS } from "@/features/images/constants";
import type { ImageAspectRatio, ImageCount, ImageQuality, PendingReferenceImage } from "@/features/images/types";

type ImageOptionMenuKey = "aspectRatio" | "quality" | "imageCount";

function ImageOptionMenu<T extends string | number>({
  menuKey,
  label,
  value,
  options,
  open,
  formatOption = String,
  onOpenChange,
  onChange,
}: {
  menuKey: ImageOptionMenuKey;
  label: string;
  value: T;
  options: readonly T[];
  open: boolean;
  formatOption?: (value: T) => string;
  onOpenChange: (menu: ImageOptionMenuKey | null) => void;
  onChange: (value: T) => void;
}) {
  return (
    <div className="relative">
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        onClick={() => onOpenChange(open ? null : menuKey)}
        className="flex h-9 w-full items-center justify-between gap-2 rounded-md border bg-white px-3 text-left text-sm font-semibold leading-none transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
      >
        <span className="min-w-0 truncate whitespace-nowrap">
          <span className="text-muted-foreground">{label}</span>
          <span className="text-muted-foreground"> · </span>
          <span>{formatOption(value)}</span>
        </span>
        <ChevronDown size={16} className={`shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open ? (
        <div className="absolute bottom-10 left-0 right-0 z-20 overflow-hidden rounded-md border bg-white py-1 shadow-lg" role="listbox" aria-label={label}>
          {options.map((option) => (
            <button
              key={String(option)}
              type="button"
              role="option"
              aria-selected={option === value}
              onClick={() => {
                onChange(option);
                onOpenChange(null);
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
  referenceImages,
  queueing,
  onPromptChange,
  onAspectRatioChange,
  onQualityChange,
  onImageCountChange,
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
  referenceImages: PendingReferenceImage[];
  queueing: boolean;
  onPromptChange: (prompt: string) => void;
  onAspectRatioChange: (aspectRatio: ImageAspectRatio) => void;
  onQualityChange: (quality: ImageQuality) => void;
  onImageCountChange: (imageCount: ImageCount) => void;
  onReferenceChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onReferenceDrop: (event: DragEvent<HTMLDivElement>) => void;
  onPreviewReference: (id: string) => void;
  onRemoveReference: (id: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  const { t } = useI18n();
  const [openMenu, setOpenMenu] = useState<ImageOptionMenuKey | null>(null);

  return (
    <Card className="flex h-full min-h-0 flex-col overflow-hidden">
      <CardHeader>
        <div className="flex items-center gap-2">
          <WandSparkles size={18} className="text-primary" />
          <h2 className="text-base font-bold">{t("images.title")}</h2>
        </div>
      </CardHeader>
      <CardContent className="flex min-h-0 flex-1 flex-col p-0">
        <Form className="flex min-h-0 flex-1 flex-col gap-3 p-4" onSubmit={onSubmit}>
          <div
            onDragOver={(event) => event.preventDefault()}
            onDrop={onReferenceDrop}
            className="flex min-h-[360px] flex-1 flex-col rounded-md border bg-white p-3 focus-within:ring-2 focus-within:ring-ring"
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-sm font-semibold">{t("images.prompt")}</span>
              <Button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                aria-label={t("images.addReference")}
                size="icon"
                variant="secondary"
                className="h-8 w-8 text-muted-foreground"
              >
                <Plus size={16} />
              </Button>
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
            <TextArea
              ref={textareaRef}
              value={prompt}
              onChange={(event) => onPromptChange(event.target.value)}
              placeholder={t("images.promptPlaceholder")}
              className="min-h-[190px] flex-1 border-0 bg-transparent p-0 shadow-none"
            />
          </div>

          <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
            <ImageOptionMenu
              menuKey="aspectRatio"
              label={t("images.size")}
              value={aspectRatio}
              options={ASPECT_RATIO_OPTIONS}
              open={openMenu === "aspectRatio"}
              formatOption={(option) => option}
              onOpenChange={setOpenMenu}
              onChange={onAspectRatioChange}
            />
            <ImageOptionMenu
              menuKey="quality"
              label={t("images.quality")}
              value={quality}
              options={QUALITY_OPTIONS}
              open={openMenu === "quality"}
              formatOption={(option) => t(`images.quality.${option}`)}
              onOpenChange={setOpenMenu}
              onChange={onQualityChange}
            />
            <ImageOptionMenu
              menuKey="imageCount"
              label={t("images.count")}
              value={imageCount}
              options={IMAGE_COUNT_OPTIONS}
              open={openMenu === "imageCount"}
              onOpenChange={setOpenMenu}
              onChange={onImageCountChange}
            />
          </div>

          <Button type="submit" className="w-full" disabled={!trimmedPrompt || queueing}>
            {queueing ? <Spinner /> : <WandSparkles size={16} />}
            {queueing ? t("images.queueing") : t("images.generate")}
          </Button>
        </Form>
      </CardContent>
    </Card>
  );
}
