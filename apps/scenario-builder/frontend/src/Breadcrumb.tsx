import type { ReactNode } from "react";

export interface BreadcrumbItem {
  label: ReactNode;
  onClick?: () => void;
}

export function Breadcrumb({
  items,
  className,
}: {
  items: BreadcrumbItem[];
  className?: string;
}) {
  return (
    <nav
      className={className ? `breadcrumb ${className}` : "breadcrumb"}
      aria-label="パンくずリスト"
    >
      <ol>
        {items.map((item, index) => {
          const current = index === items.length - 1;
          return (
            <li key={index}>
              {current || !item.onClick ? (
                <span aria-current={current ? "page" : undefined}>{item.label}</span>
              ) : (
                <button
                  type="button"
                  className="breadcrumb-link"
                  onClick={item.onClick}
                >
                  {item.label}
                </button>
              )}
              {current ? null : (
                <span className="breadcrumb-separator" aria-hidden="true">
                  /
                </span>
              )}
            </li>
          );
        })}
      </ol>
    </nav>
  );
}
