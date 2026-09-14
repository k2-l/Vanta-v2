import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Tailwind 友好的类名合并。 */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}
