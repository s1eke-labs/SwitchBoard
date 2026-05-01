import { useI18n } from "@/i18n";
import { cn } from "@/lib/utils";
import { Pagination } from "@/components/heroui/pagination";

type PageItem = number | "start-ellipsis" | "end-ellipsis";

function getPaginationItems(page: number, totalPages: number): PageItem[] {
  const pageCount = Math.max(1, totalPages);
  const currentPage = Math.min(Math.max(1, page), pageCount);

  if (pageCount <= 7) {
    return Array.from({ length: pageCount }, (_, index) => index + 1);
  }

  const items: PageItem[] = [1];
  const middleStart = Math.max(2, currentPage - 1);
  const middleEnd = Math.min(pageCount - 1, currentPage + 1);

  if (middleStart > 2) {
    items.push("start-ellipsis");
  }

  for (let pageNumber = middleStart; pageNumber <= middleEnd; pageNumber += 1) {
    items.push(pageNumber);
  }

  if (middleEnd < pageCount - 1) {
    items.push("end-ellipsis");
  }

  items.push(pageCount);
  return items;
}

export function PageSelector({
  page,
  totalPages,
  disabled,
  jumping,
  onSelect,
  className,
  size = "md",
}: {
  page: number;
  totalPages: number;
  disabled: boolean;
  jumping: boolean;
  onSelect: (page: number) => void;
  className?: string;
  size?: "sm" | "md" | "lg";
}) {
  const { t } = useI18n();
  const pageCount = Math.max(1, totalPages);
  const currentPage = Math.min(Math.max(1, page), pageCount);
  const items = getPaginationItems(currentPage, pageCount);
  const isDisabled = disabled || jumping;
  const navButtonClassName =
    size === "sm"
      ? "size-8 min-w-0 gap-0 px-0 md:size-7"
      : size === "lg"
        ? "size-10 min-w-0 gap-0 px-0 md:size-9"
        : "size-9 min-w-0 gap-0 px-0 md:size-8";

  function selectPage(targetPage: number) {
    if (isDisabled || targetPage === currentPage || targetPage < 1 || targetPage > pageCount) return;
    onSelect(targetPage);
  }

  return (
    <Pagination className={cn("w-auto", className)} size={size} aria-busy={jumping} aria-label={t("common.selectPage")}>
      <Pagination.Content>
        <Pagination.Item>
          <Pagination.Previous
            aria-label={t("common.previousPage")}
            className={navButtonClassName}
            isDisabled={isDisabled || currentPage === 1}
            onPress={() => selectPage(currentPage - 1)}
          >
            <Pagination.PreviousIcon />
          </Pagination.Previous>
        </Pagination.Item>
        {items.map((item) =>
          typeof item === "number" ? (
            <Pagination.Item key={item}>
              <Pagination.Link
                aria-label={t("common.pageLabel", { page: item, total: pageCount })}
                isActive={item === currentPage}
                isDisabled={isDisabled}
                onPress={() => selectPage(item)}
              >
                {item}
              </Pagination.Link>
            </Pagination.Item>
          ) : (
            <Pagination.Item key={item}>
              <Pagination.Ellipsis />
            </Pagination.Item>
          ),
        )}
        <Pagination.Item>
          <Pagination.Next
            aria-label={t("common.nextPage")}
            className={navButtonClassName}
            isDisabled={isDisabled || currentPage >= pageCount}
            onPress={() => selectPage(currentPage + 1)}
          >
            <Pagination.NextIcon />
          </Pagination.Next>
        </Pagination.Item>
      </Pagination.Content>
    </Pagination>
  );
}
