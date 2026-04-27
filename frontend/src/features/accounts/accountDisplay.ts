export type AccountDensity = "large" | "medium" | "small";

export const accountDensityOrder: AccountDensity[] = ["large", "medium", "small"];
export const accountDensityLabels: Record<AccountDensity, string> = {
  large: "large",
  medium: "medium",
  small: "small",
};
export const accountGridClasses: Record<AccountDensity, string> = {
  large: "grid-cols-2",
  medium: "grid-cols-3",
  small: "grid-cols-4",
};
export const collapsedRowsByDensity: Record<AccountDensity, number> = {
  large: 1,
  medium: 1,
  small: 2,
};
