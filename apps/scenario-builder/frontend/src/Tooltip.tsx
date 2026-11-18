import {
  cloneElement,
  useId,
  type ReactElement,
  type ReactNode,
} from "react";

export function Tooltip({
  content,
  align = "start",
  children,
}: {
  content?: ReactNode;
  align?: "start" | "end";
  children: ReactElement<{ "aria-describedby"?: string }>;
}) {
  const id = useId();
  if (!content) {
    return children;
  }
  const existing = children.props["aria-describedby"];
  const describedBy = [existing, id].filter(Boolean).join(" ");
  return (
    <span className="tooltip-anchor">
      {cloneElement(children, { "aria-describedby": describedBy })}
      <span id={id} role="tooltip" className={`tooltip-bubble align-${align}`}>
        {content}
      </span>
    </span>
  );
}
