"use client";

import React, { useEffect, useState } from "react";
import {
  History as HistoryIcon,
  ShieldCheck,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  RotateCcw,
  Clock,
  User,
  Bot,
  Cpu,
  Layers,
  ChevronDown,
  ChevronUp,
} from "lucide-react";
import { api, AuditEventItem } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";

export default function HistoryPage() {
  const [events, setEvents] = useState<AuditEventItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [entityFilter, setEntityFilter] = useState<string>("all");
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const loadEvents = async () => {
    try {
      setLoading(true);
      const res = await api.listAuditEvents(
        entityFilter === "all" ? undefined : entityFilter,
        150
      );
      setEvents(res);
    } catch {
      // ignore
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadEvents();
  }, [entityFilter]);

  const toggleExpand = (id: string) => {
    setExpandedId(expandedId === id ? null : id);
  };

  const getActorBadge = (actor: string) => {
    switch (actor) {
      case "person":
        return (
          <Badge size="sm" variant="primary">
            <User className="w-2.5 h-2.5" /> Person
          </Badge>
        );
      case "agent":
        return (
          <Badge size="sm" variant="warning">
            <Bot className="w-2.5 h-2.5" /> Agent
          </Badge>
        );
      default:
        return (
          <Badge size="sm" variant="neutral">
            <Cpu className="w-2.5 h-2.5" /> System
          </Badge>
        );
    }
  };

  const getActionBadge = (action: string, recoveryStatus?: string | null) => {
    if (action.includes("verify") || action.includes("success") || action === "confirm_extraction") {
      return <Badge size="sm" variant="success">{action}</Badge>;
    }
    if (action.includes("fail") || action.includes("reject")) {
      return <Badge size="sm" variant="danger">{action}</Badge>;
    }
    if (action.includes("retry") || action.includes("recover") || recoveryStatus === "needs_attention") {
      return <Badge size="sm" variant="warning">{action}</Badge>;
    }
    return <Badge size="sm" variant="neutral">{action}</Badge>;
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-border">
        <div>
          <div className="flex items-center gap-2">
            <HistoryIcon className="w-6 h-6 text-primary" />
            <h1 className="text-2xl font-bold tracking-tight text-text">Audit & History Timeline</h1>
          </div>
          <p className="text-sm text-text-muted mt-1">
            Immutable append-only record of all extractions, proposals, approval decisions, execution verifications, and delivery attempts.
          </p>
        </div>

        {/* Entity filter */}
        <div className="flex items-center gap-1 p-1 bg-stone-100 dark:bg-stone-800 rounded-lg border border-border">
          {["all", "proposal", "commitment", "reminder", "plan"].map((type) => (
            <button
              key={type}
              onClick={() => setEntityFilter(type)}
              className={`px-3 py-1 text-xs font-medium rounded-md capitalize transition-colors ${
                entityFilter === type
                  ? "bg-surface text-text shadow-sm font-semibold"
                  : "text-text-muted hover:text-text"
              }`}
            >
              {type}
            </button>
          ))}
        </div>
      </div>

      {/* Audit Log Entries */}
      {loading ? (
        <div className="py-12 text-center text-text-muted text-sm animate-pulse">
          Loading audit trail...
        </div>
      ) : events.length === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title="No audit events found"
          description="Every consequential event will be recorded here with full provenance and read-back details."
        />
      ) : (
        <div className="relative border-l-2 border-border ml-4 space-y-4">
          {events.map((event) => {
            const isExpanded = expandedId === event.id;

            return (
              <div key={event.id} className="relative pl-6">
                {/* Node indicator */}
                <div className="absolute -left-[9px] top-3 w-4 h-4 rounded-full border-2 border-primary bg-surface" />

                <div className="p-4 rounded-lg border border-border bg-surface hover:border-primary/30 transition-all shadow-sm">
                  {/* Top row */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 mb-2">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="font-mono text-xs font-bold text-text uppercase">
                        [{event.entity_type}]
                      </span>
                      {getActionBadge(event.action, event.recovery_status)}
                      {getActorBadge(event.actor)}
                    </div>

                    <div className="flex items-center gap-2 font-mono text-xs text-text-muted">
                      <Clock className="w-3.5 h-3.5" />
                      <span>{new Date(event.created_at).toLocaleString()}</span>
                    </div>
                  </div>

                  {/* Summary / ID */}
                  <div className="flex items-center justify-between text-xs text-text-muted">
                    <span className="font-mono">
                      Entity ID: {event.entity_id || "None"}
                    </span>
                    <button
                      onClick={() => toggleExpand(event.id)}
                      className="text-primary hover:underline flex items-center gap-1 font-medium text-xs"
                    >
                      {isExpanded ? (
                        <>
                          Hide Payload <ChevronUp className="w-3.5 h-3.5" />
                        </>
                      ) : (
                        <>
                          View Payload & Result <ChevronDown className="w-3.5 h-3.5" />
                        </>
                      )}
                    </button>
                  </div>

                  {/* Expanded JSON details */}
                  {isExpanded && (
                    <div className="mt-3 pt-3 border-t border-border/60 space-y-3 font-mono text-xs">
                      {event.payload && (
                        <div>
                          <div className="text-[11px] text-text-muted font-bold uppercase mb-1">
                            Action Payload:
                          </div>
                          <pre className="p-2.5 rounded bg-stone-50 dark:bg-stone-900 border border-border overflow-x-auto text-text">
                            {JSON.stringify(event.payload, null, 2)}
                          </pre>
                        </div>
                      )}

                      {event.result && (
                        <div>
                          <div className="text-[11px] text-text-muted font-bold uppercase mb-1">
                            Execution Result & Read-Back:
                          </div>
                          <pre className="p-2.5 rounded bg-stone-50 dark:bg-stone-900 border border-border overflow-x-auto text-text">
                            {JSON.stringify(event.result, null, 2)}
                          </pre>
                        </div>
                      )}

                      {event.recovery_status && (
                        <div className="flex items-center gap-2 text-amber-700 dark:text-amber-400">
                          <AlertTriangle className="w-4 h-4" />
                          <span>Recovery Status: {event.recovery_status}</span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
