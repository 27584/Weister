"use client";

import { KeyRound } from "lucide-react";

export function FieldLabel({
  icon: Icon,
  children,
}: {
  icon?: typeof KeyRound;
  children: React.ReactNode;
}) {
  return (
    <span className="mb-1 flex items-center gap-1.5 text-[14px] text-base-content/90">
      {Icon && <Icon className="h-3 w-3" />}
      {children}
    </span>
  );
}
