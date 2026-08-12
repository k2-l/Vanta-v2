import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

/** Tailwind 类名合并（shadcn 风格的 cn 助手） */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
