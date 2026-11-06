import React from "react";
import clsx from "clsx";
import { LucideIcon } from "lucide-react";

export interface EmptyStateProps {
  icon: LucideIcon;
  title: string;
  description: string;
  action?: React.ReactNode;
  className?: string;
}

export const EmptyState: React.FC<EmptyStateProps> = ({
  icon: Icon,
  title,
  description,
  action,
  className,
}) => {
  return (
    <div
      className={clsx(
        "flex flex-col items-center justify-center p-8 md:p-12 text-center rounded-lg border border-dashed border-border bg-stone-50/50 dark:bg-stone-900/20",
        className
      )}
    >
      <div className="w-12 h-12 rounded-full bg-surface border border-border flex items-center justify-center mb-4 text-text-muted shadow-sm">
        <Icon className="w-6 h-6" />
      </div>
      <h4 className="text-base font-semibold text-text mb-1">{title}</h4>
      <p className="text-sm text-text-muted max-w-sm mb-6">{description}</p>
      {action && <div>{action}</div>}
    </div>
  );
};
