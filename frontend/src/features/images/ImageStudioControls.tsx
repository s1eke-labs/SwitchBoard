import {
  useState,
  type ChangeEvent,
  type ClipboardEvent,
  type DragEvent,
  type FormEvent,
  type ReactNode,
  type RefObject,
} from "react";
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

const ASPECT_RATIO_SHAPE_BOUNDS = { width: 24, height: 18 };

const ASPECT_RATIO_SHAPE_SIZE: Record<ImageAspectRatio, { width: number; height: number }> = {
  "1:1": { width: 16, height: 16 },
  "3:4": { width: 12, height: 16 },
  "4:3": { width: 21, height: 15.75 },
  "9:16": { width: 9, height: 16 },
  "16:9": { width: 24, height: 13.5 },
  "21:9": { width: 24, height: 10.25 },
};

const QUALITY_LEVEL_COUNT: Record<ImageQuality, number> = {
  low: 1,
  medium: 2,
  high: 3,
};

function AspectRatioShape({ aspectRatio, selected = false }: { aspectRatio: ImageAspectRatio; selected?: boolean }) {
  const size = ASPECT_RATIO_SHAPE_SIZE[aspectRatio];

  return (
    <span
      aria-hidden="true"
      className="flex shrink-0 items-center justify-center"
      style={{ width: ASPECT_RATIO_SHAPE_BOUNDS.width, height: ASPECT_RATIO_SHAPE_BOUNDS.height }}
    >
      <span
        className={`rounded-[3px] border ${selected ? "border-primary bg-primary/10" : "border-muted-foreground/70 bg-muted/40"}`}
        style={{ width: size.width, height: size.height }}
      />
    </span>
  );
}

function QualityLevelIcon({ quality, selected = false }: { quality: ImageQuality; selected?: boolean }) {
  const activeBars = QUALITY_LEVEL_COUNT[quality];

  return (
    <span aria-hidden="true" className="flex h-4 w-5 shrink-0 items-end justify-center gap-0.5">
      {[1, 2, 3].map((level) => (
        <span
          key={level}
          className={`w-1.5 rounded-sm border ${
            level <= activeBars
              ? selected
                ? "border-primary bg-primary"
                : "border-foreground bg-foreground"
              : "border-muted-foreground/50 bg-transparent"
          }`}
          style={{ height: 6 + level * 3 }}
        />
      ))}
    </span>
  );
}

function ImageCountIcon({ count, selected = false }: { count: ImageCount; selected?: boolean }) {
  const activeSlots = count === 4 ? 4 : count === 2 ? 2 : 1;

  return (
    <span aria-hidden="true" className="grid h-4 w-4 shrink-0 grid-cols-2 grid-rows-2 gap-0.5">
      {[1, 2, 3, 4].map((slot) => (
        <span
          key={slot}
          className={`rounded-[2px] border ${
            slot <= activeSlots
              ? selected
                ? "border-primary bg-primary/15"
                : "border-foreground bg-foreground/10"
              : "border-muted-foreground/35 bg-transparent"
          }`}
        />
      ))}
    </span>
  );
}

function ImageOptionMenu<T extends string | number>({
  menuKey,
  label,
  value,
  options,
  open,
  displayValue = true,
  formatOption = String,
  renderSelectedValue,
  renderOptionContent,
  renderSelectedAccessory,
  renderOptionAccessory,
  onOpenChange,
  onChange,
}: {
  menuKey: ImageOptionMenuKey;
  label: string;
  value: T;
  options: readonly T[];
  open: boolean;
  displayValue?: boolean;
  formatOption?: (value: T) => string;
  renderSelectedValue?: (value: T) => ReactNode;
  renderOptionContent?: (value: T, selected: boolean) => ReactNode;
  renderSelectedAccessory?: (value: T) => ReactNode;
  renderOptionAccessory?: (value: T, selected: boolean) => ReactNode;
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
        <span className="flex min-w-0 items-center gap-2 whitespace-nowrap">
          {renderSelectedValue ? (
            renderSelectedValue(value)
          ) : (
            <>
              <span className="min-w-0 truncate">
                <span className="text-muted-foreground">{label}</span>
                {displayValue ? (
                  <>
                    <span className="text-muted-foreground"> · </span>
                    <span>{formatOption(value)}</span>
                  </>
                ) : null}
              </span>
              {renderSelectedAccessory ? renderSelectedAccessory(value) : null}
            </>
          )}
        </span>
        <ChevronDown size={16} className={`shrink-0 text-muted-foreground transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open ? (
        <div className="absolute bottom-10 left-0 right-0 z-20 overflow-hidden rounded-md border bg-white py-1 shadow-lg" role="listbox" aria-label={label}>
          {options.map((option) => {
            const selected = option === value;

            return (
              <button
                key={String(option)}
                type="button"
                role="option"
                aria-selected={selected}
                onClick={() => {
                  onChange(option);
                  onOpenChange(null);
                }}
                className={`flex h-9 w-full items-center justify-between gap-3 px-3 text-left text-sm transition-colors hover:bg-muted ${
                  selected ? "font-semibold text-primary" : "text-foreground"
                }`}
              >
                {renderOptionContent ? renderOptionContent(option, selected) : <span className="min-w-0 truncate">{formatOption(option)}</span>}
                {renderOptionAccessory ? renderOptionAccessory(option, selected) : null}
              </button>
            );
          })}
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
  onReferencePaste,
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
  onReferencePaste: (event: ClipboardEvent<HTMLElement>) => void;
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
            onPaste={onReferencePaste}
            className="flex min-h-[360px] flex-1 flex-col rounded-md border bg-white p-3"
          >
            <div className="mb-2 flex items-center justify-between gap-2">
              <span className="text-sm font-semibold">{t("images.prompt")}</span>
              <Button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                aria-label={t("images.addReference")}
                size="icon"
                variant="secondary"
                disabled={referenceImages.length >= MAX_REFERENCE_IMAGES}
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
            {referenceImages.length > 0 ? (
              <div className="mb-3 flex h-16 gap-2 overflow-x-auto">
                {referenceImages.map((reference) => (
                  <div key={reference.id} className="relative aspect-[4/3] h-full shrink-0 overflow-hidden rounded-md border bg-muted">
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
                ))}
              </div>
            ) : null}
            <TextArea
              ref={textareaRef}
              value={prompt}
              onChange={(event) => onPromptChange(event.target.value)}
              placeholder={t("images.promptPlaceholder")}
              className="min-h-[190px] flex-1 border-0 bg-transparent p-0 shadow-none focus:ring-0 data-[focused=true]:ring-0"
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
              displayValue={false}
              renderSelectedValue={(option) => (
                <>
                  <AspectRatioShape aspectRatio={option} selected />
                  <span>{option}</span>
                </>
              )}
              renderOptionAccessory={(option, selected) => <AspectRatioShape aspectRatio={option} selected={selected} />}
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
              displayValue={false}
              renderSelectedValue={(option) => (
                <>
                  <QualityLevelIcon quality={option} selected />
                  <span>{t(`images.quality.${option}`)}</span>
                </>
              )}
              renderOptionContent={(option, selected) => (
                <span className="flex min-w-0 items-center gap-2">
                  <QualityLevelIcon quality={option} selected={selected} />
                  <span className="truncate">{t(`images.quality.${option}`)}</span>
                </span>
              )}
              onOpenChange={setOpenMenu}
              onChange={onQualityChange}
            />
            <ImageOptionMenu
              menuKey="imageCount"
              label={t("images.count")}
              value={imageCount}
              options={IMAGE_COUNT_OPTIONS}
              open={openMenu === "imageCount"}
              displayValue={false}
              renderSelectedValue={(option) => (
                <>
                  <ImageCountIcon count={option} selected />
                  <span>{option}</span>
                </>
              )}
              renderOptionContent={(option, selected) => (
                <span className="flex min-w-0 items-center gap-2">
                  <ImageCountIcon count={option} selected={selected} />
                  <span className="truncate">{option}</span>
                </span>
              )}
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
