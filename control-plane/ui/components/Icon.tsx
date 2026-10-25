export function Icon({ n, fill, size, className = "" }: { n: string; fill?: boolean; size?: "sm" | "xs"; className?: string }) {
  return (
    <span className={`ms ${fill ? "fill" : ""} ${size ?? ""} ${className}`.trim()} aria-hidden="true">
      {n}
    </span>
  );
}
