import { cva, type VariantProps } from "class-variance-authority";
import { forwardRef, type ButtonHTMLAttributes } from "react";
import { cn } from "@/lib/cn";

const button = cva(
  "inline-flex items-center justify-center gap-2 rounded-md text-sm font-medium transition-colors disabled:opacity-50 disabled:pointer-events-none focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
  {
    variants: {
      variant: {
        primary: "text-[var(--accent-fg)] bg-[var(--accent)] hover:bg-[var(--accent-hover)]",
        secondary: "border bg-[var(--bg-elevated)] hover:bg-[var(--bg-inset)]",
        ghost: "hover:bg-[var(--bg-inset)]",
        danger: "text-white bg-[var(--danger)] hover:opacity-90",
      },
      size: {
        sm: "h-8 px-3",
        md: "h-10 px-4",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & VariantProps<typeof button>;

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { className, variant, size, ...props },
  ref,
) {
  return (
    <button
      ref={ref}
      className={cn(button({ variant, size }), className)}
      style={{ borderColor: "var(--border)", color: variant === "secondary" || variant === "ghost" ? "var(--fg)" : undefined }}
      {...props}
    />
  );
});
