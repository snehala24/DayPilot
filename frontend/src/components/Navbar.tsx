"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import clsx from "clsx";
import {
  Calendar,
  Inbox,
  CheckSquare,
  ListTodo,
  History,
  ShieldCheck,
  Moon,
  Sun,
  Activity,
} from "lucide-react";
import { api } from "@/lib/api";

export const Navbar: React.FC = () => {
  const pathname = usePathname();
  const [pendingCount, setPendingCount] = useState<number>(0);
  const [isDark, setIsDark] = useState<boolean>(false);
  const [isOnline, setIsOnline] = useState<boolean>(true);

  useEffect(() => {
    // Check initial dark mode
    if (
      localStorage.theme === "dark" ||
      (!("theme" in localStorage) &&
        window.matchMedia("(prefers-color-scheme: dark)").matches)
    ) {
      document.documentElement.classList.add("dark");
      setIsDark(true);
    } else {
      document.documentElement.classList.remove("dark");
      setIsDark(false);
    }

    // Fetch pending proposal count & health
    const fetchStatus = async () => {
      try {
        const proposals = await api.listProposals("pending");
        setPendingCount(proposals.length);
        setIsOnline(true);
      } catch {
        setIsOnline(false);
      }
    };

    fetchStatus();
    const interval = setInterval(fetchStatus, 15000);
    return () => clearInterval(interval);
  }, [pathname]);

  const toggleTheme = () => {
    if (isDark) {
      document.documentElement.classList.remove("dark");
      localStorage.theme = "light";
      setIsDark(false);
    } else {
      document.documentElement.classList.add("dark");
      localStorage.theme = "dark";
      setIsDark(true);
    }
  };

  const navItems = [
    { label: "Today", href: "/", icon: Calendar },
    { label: "Inbox", href: "/inbox", icon: Inbox },
    {
      label: "Approvals",
      href: "/approvals",
      icon: CheckSquare,
      badge: pendingCount > 0 ? pendingCount : null,
    },
    { label: "Commitments", href: "/commitments", icon: ListTodo },
    { label: "History", href: "/history", icon: History },
  ];

  return (
    <header className="sticky top-0 z-40 w-full border-b border-border bg-surface/90 backdrop-blur">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Brand */}
        <div className="flex items-center gap-6">
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center text-white shadow-sm transition-transform group-hover:scale-105">
              <ShieldCheck className="w-5 h-5" />
            </div>
            <div>
              <span className="font-semibold text-base text-text tracking-tight flex items-center gap-1.5">
                DayPilot
                <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-blue-50 text-blue-700 dark:bg-blue-950 dark:text-blue-300 font-bold border border-blue-200 dark:border-blue-800">
                  MVP
                </span>
              </span>
            </div>
          </Link>

          {/* Navigation tabs */}
          <nav className="hidden md:flex items-center gap-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive =
                item.href === "/"
                  ? pathname === "/" || pathname === "/today"
                  : pathname?.startsWith(item.href);

              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={clsx(
                    "flex items-center gap-2 px-3.5 py-2 rounded-md text-sm font-medium transition-colors relative",
                    isActive
                      ? "text-primary bg-blue-50/70 dark:bg-blue-950/40"
                      : "text-text-muted hover:text-text hover:bg-stone-100 dark:hover:bg-stone-800/60"
                  )}
                >
                  <Icon className="w-4 h-4" />
                  <span>{item.label}</span>
                  {item.badge !== null && item.badge !== undefined && (
                    <span className="ml-0.5 px-1.5 py-0.2 rounded-full text-[10px] font-mono font-bold bg-amber-500 text-white animate-pulse">
                      {item.badge}
                    </span>
                  )}
                </Link>
              );
            })}
          </nav>
        </div>

        {/* Right utility items */}
        <div className="flex items-center gap-3">
          {/* Health indicator */}
          <div
            className="flex items-center gap-1.5 px-2.5 py-1 rounded-full border border-border bg-stone-50 dark:bg-stone-900 text-xs font-mono text-text-muted"
            title={isOnline ? "Backend Connected (Healthy)" : "Backend Disconnected"}
          >
            <span
              className={clsx(
                "w-2 h-2 rounded-full",
                isOnline ? "bg-emerald-500 animate-pulse" : "bg-rose-500"
              )}
            />
            <span className="hidden sm:inline">
              {isOnline ? "ONLINE" : "OFFLINE"}
            </span>
          </div>

          {/* Dark mode toggle */}
          <button
            onClick={toggleTheme}
            className="p-2 rounded-md border border-border text-text-muted hover:text-text hover:bg-stone-100 dark:hover:bg-stone-800 transition-colors"
            aria-label="Toggle theme"
          >
            {isDark ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
        </div>
      </div>

      {/* Mobile nav bar */}
      <div className="flex md:hidden border-t border-border px-2 py-1.5 overflow-x-auto justify-around bg-surface">
        {navItems.map((item) => {
          const Icon = item.icon;
          const isActive =
            item.href === "/"
              ? pathname === "/" || pathname === "/today"
              : pathname?.startsWith(item.href);

          return (
            <Link
              key={item.href}
              href={item.href}
              className={clsx(
                "flex flex-col items-center gap-1 px-3 py-1 text-xs font-medium rounded-md relative",
                isActive
                  ? "text-primary font-semibold"
                  : "text-text-muted hover:text-text"
              )}
            >
              <div className="relative">
                <Icon className="w-4 h-4" />
                {item.badge !== null && item.badge !== undefined && (
                  <span className="absolute -top-1 -right-2 px-1 py-0.2 rounded-full text-[9px] font-mono font-bold bg-amber-500 text-white">
                    {item.badge}
                  </span>
                )}
              </div>
              <span>{item.label}</span>
            </Link>
          );
        })}
      </div>
    </header>
  );
};
