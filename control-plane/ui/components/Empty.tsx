import { Icon } from "./Icon";

export function Empty({ icon = "inbox", text }: { icon?: string; text: string }) {
  return (
    <div className="empty">
      <Icon n={icon} />
      <span>{text}</span>
    </div>
  );
}
