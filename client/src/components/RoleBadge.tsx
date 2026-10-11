import type { Role } from "../lib/types";

const LABELS: Record<Role, string> = {
  host: "Host",
  moderator: "Mod",
  participant: "",
};

/** Host is filled gold; moderator is outlined gold; participant is unbadged. */
export default function RoleBadge({ role }: { role: Role }) {
  const label = LABELS[role];
  if (!label) {
    return null;
  }
  return (
    <span className={`badge badge-${role}`} data-testid={`badge-${role}`}>
      {label}
    </span>
  );
}