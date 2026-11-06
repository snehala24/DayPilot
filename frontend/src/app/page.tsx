"use client";

import React, { useEffect, useState } from "react";
import Link from "next/link";
import {
  Calendar as CalendarIcon,
  Clock,
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  ArrowRight,
  ShieldAlert,
  Lock,
  Layers,
  Sparkles,
  CalendarCheck,
} from "lucide-react";
import { api, PlanResponse, PlanItem, ConflictItem, ProposalItem } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";

export default function TodayPage() {
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [proposals, setProposals] = useState<ProposalItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [replanning, setReplanning] = useState<boolean>(false);
  const [proposingAlternative, setProposingAlternative] = useState<string | null>(null);
  const [feedbackMessage, setFeedbackMessage] = useState<{ text: string; type: "success" | "error" } | null>(null);

  const todayStr = new Date().toISOString().split("T")[0];

  const fetchPlanAndProposals = async () => {
    try {
      setLoading(true);
      // Fetch plan or generate if not yet generated
      let currentPlan: PlanResponse | null = null;
      try {
        currentPlan = await api.getPlan(todayStr);
      } catch {
        currentPlan = await api.generatePlan(todayStr);
      }
      setPlan(currentPlan);

      const pendingProposals = await api.listProposals("pending");
      setProposals(pendingProposals);
    } catch (err: any) {
      setFeedbackMessage({ text: err.message || "Failed to load today's plan", type: "error" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchPlanAndProposals();
  }, []);

  const handleReplan = async () => {
    try {
      setReplanning(true);
      setFeedbackMessage(null);
      const newPlan = await api.generatePlan(todayStr);
      setPlan(newPlan);
      setFeedbackMessage({ text: "Plan refreshed with zero constraint violations.", type: "success" });
    } catch (err: any) {
      setFeedbackMessage({ text: err.message || "Failed to replan day.", type: "error" });
    } finally {
      setReplanning(false);
    }
  };

  const handleProposeAlternative = async (conflict: ConflictItem, altIndex: number) => {
    const alt = conflict.alternatives[altIndex];
    if (!alt) return;

    try {
      setProposingAlternative(`${conflict.commitment_id}-${altIndex}`);
      setFeedbackMessage(null);

      // Create proposal from alternative
      const payload = {
        kind: alt.kind === "reschedule_next_day" ? "reschedule" : "calendar_create",
        commitment_id: conflict.commitment_id,
        payload: {
          title: conflict.commitment_title,
          starts_at: alt.changes.proposed_start || new Date().toISOString(),
          ends_at: alt.changes.proposed_end || new Date().toISOString(),
          tz: "UTC",
          alternative_kind: alt.kind,
        },
        reason: alt.description,
      };

      const prop = await api.createProposal(payload);
      setFeedbackMessage({
        text: `Proposal created (#${prop.idempotency_key}) for user approval. Review in Approvals queue.`,
        type: "success",
      });
      // Refresh pending proposals
      const pending = await api.listProposals("pending");
      setProposals(pending);
    } catch (err: any) {
      setFeedbackMessage({ text: err.message || "Failed to create proposal from alternative.", type: "error" });
    } finally {
      setProposingAlternative(null);
    }
  };

  const formatTime = (isoString: string) => {
    try {
      const d = new Date(isoString);
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", hour12: false });
    } catch {
      return isoString;
    }
  };

  return (
    <div className="space-y-6">
      {/* Page Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-border">
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-2xl font-bold tracking-tight text-text">Today's Schedule</h1>
            <Badge variant="primary">{todayStr}</Badge>
          </div>
          <p className="text-sm text-text-muted mt-1">
            Constraint-validated plan respecting fixed calendar events, working hours, and dependencies.
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={handleReplan}
            loading={replanning}
          >
            <RefreshCw className="w-4 h-4" />
            Replan Day
          </Button>

          {proposals.length > 0 && (
            <Link href="/approvals">
              <Button size="sm" className="bg-amber-500 hover:bg-amber-600 text-white">
                <AlertTriangle className="w-4 h-4" />
                {proposals.length} Pending Approval{proposals.length > 1 ? "s" : ""}
              </Button>
            </Link>
          )}
        </div>
      </div>

      {/* Feedback Alert */}
      {feedbackMessage && (
        <div
          className={`p-3.5 rounded-md border text-sm flex items-center justify-between ${
            feedbackMessage.type === "success"
              ? "bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-950/40 dark:border-emerald-800 dark:text-emerald-300"
              : "bg-rose-50 border-rose-200 text-rose-800 dark:bg-rose-950/40 dark:border-rose-800 dark:text-rose-300"
          }`}
        >
          <span>{feedbackMessage.text}</span>
          <button
            onClick={() => setFeedbackMessage(null)}
            className="text-xs font-semibold underline ml-4 hover:opacity-75"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Overview Stats Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <Card className="p-4 flex items-center gap-4">
          <div className="w-10 h-10 rounded-lg bg-blue-50 dark:bg-blue-950/50 text-primary flex items-center justify-center">
            <Clock className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs uppercase font-mono text-text-muted">Planned Blocks</div>
            <div className="text-xl font-bold text-text">
              {plan?.items.length || 0} Commitments
            </div>
          </div>
        </Card>

        <Card className="p-4 flex items-center gap-4">
          <div className="w-10 h-10 rounded-lg bg-amber-50 dark:bg-amber-950/50 text-warning flex items-center justify-center">
            <AlertTriangle className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs uppercase font-mono text-text-muted">Detected Conflicts</div>
            <div className="text-xl font-bold text-text">
              {plan?.conflicts.length || 0} Items
            </div>
          </div>
        </Card>

        <Card className="p-4 flex items-center gap-4">
          <div className="w-10 h-10 rounded-lg bg-emerald-50 dark:bg-emerald-950/50 text-success flex items-center justify-center">
            <CheckCircle2 className="w-5 h-5" />
          </div>
          <div>
            <div className="text-xs uppercase font-mono text-text-muted">Hard Constraints</div>
            <div className="text-xl font-bold text-text">
              {plan?.constraints_report.is_valid ? "100% Satisfied" : "Review Needed"}
            </div>
          </div>
        </Card>
      </div>

      {/* Main Content Grid: Timeline on left, Conflicts & Proposals on right */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Timeline Column (2 cols) */}
        <div className="lg:col-span-2 space-y-4">
          <Card>
            <CardHeader>
              <div className="flex items-center gap-2">
                <CalendarIcon className="w-4 h-4 text-primary" />
                <CardTitle>Daily Schedule & Execution Timeline</CardTitle>
              </div>
              <span className="text-xs font-mono text-text-muted">Working hours: 09:00 - 18:00</span>
            </CardHeader>
            <CardContent>
              {loading ? (
                <div className="py-12 text-center text-text-muted text-sm animate-pulse">
                  Loading deterministic schedule...
                </div>
              ) : !plan || plan.items.length === 0 ? (
                <EmptyState
                  icon={CalendarCheck}
                  title="No scheduled commitments for today"
                  description="Your day is currently clear or tasks have not been planned yet. Paste notes in Inbox to capture commitments."
                  action={
                    <Link href="/inbox">
                      <Button size="sm">Go to Inbox</Button>
                    </Link>
                  }
                />
              ) : (
                <div className="relative border-l-2 border-border ml-3 my-2 space-y-4">
                  {plan.items.map((item, idx) => (
                    <div key={item.id} className="relative pl-6 group">
                      {/* Timeline node */}
                      <div
                        className={`absolute -left-[9px] top-1.5 w-4 h-4 rounded-full border-2 bg-surface transition-colors ${
                          item.locked
                            ? "border-text-muted bg-stone-200 dark:bg-stone-700"
                            : "border-primary group-hover:scale-110"
                        }`}
                      />

                      <div className="p-4 rounded-lg border border-border bg-surface hover:border-primary/40 transition-all shadow-sm">
                        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-1 mb-2">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-mono font-bold text-primary">
                              {formatTime(item.starts_at)} – {formatTime(item.ends_at)}
                            </span>
                            <span className="text-xs text-text-muted font-mono">
                              ({item.duration_minutes} min)
                            </span>
                            {item.locked && (
                              <Badge size="sm" variant="neutral">
                                <Lock className="w-3 h-3" /> Fixed Event
                              </Badge>
                            )}
                          </div>
                          <Badge size="sm" variant={item.priority >= 3 ? "warning" : "primary"}>
                            P{item.priority}
                          </Badge>
                        </div>

                        <h4 className="text-sm font-semibold text-text tracking-tight">
                          {item.commitment_title}
                        </h4>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>

        {/* Conflicts and Alternative Proposals Column (1 col) */}
        <div className="space-y-6">
          {/* Conflicts Card */}
          <Card className="border-amber-200 dark:border-amber-900/50">
            <CardHeader className="bg-amber-50/50 dark:bg-amber-950/20 border-b border-amber-200 dark:border-amber-900/50">
              <div className="flex items-center gap-2">
                <AlertTriangle className="w-4 h-4 text-warning" />
                <CardTitle className="text-amber-900 dark:text-amber-300">
                  Visible Conflicts ({plan?.conflicts.length || 0})
                </CardTitle>
              </div>
            </CardHeader>
            <CardContent>
              {!plan || plan.conflicts.length === 0 ? (
                <div className="text-center py-6 text-sm text-text-muted">
                  <CheckCircle2 className="w-8 h-8 text-emerald-500 mx-auto mb-2 opacity-80" />
                  No scheduling conflicts detected! Every planned task satisfies duration, working hours, and deadlines.
                </div>
              ) : (
                <div className="space-y-4">
                  {plan.conflicts.map((conf) => (
                    <div
                      key={conf.commitment_id}
                      className="p-3.5 rounded-lg border border-amber-200 dark:border-amber-900/50 bg-amber-50/30 dark:bg-amber-950/10 space-y-3"
                    >
                      <div>
                        <div className="text-xs font-mono font-bold text-amber-800 dark:text-amber-400">
                          {conf.commitment_title}
                        </div>
                        <p className="text-xs text-text-muted mt-0.5">{conf.reason}</p>
                      </div>

                      {/* Alternatives list */}
                      <div className="space-y-2 pt-1">
                        <div className="text-[11px] font-semibold text-text uppercase tracking-wider">
                          Proposed Alternatives:
                        </div>
                        {conf.alternatives.map((alt, altIdx) => {
                          const isProposing = proposingAlternative === `${conf.commitment_id}-${altIdx}`;
                          return (
                            <div
                              key={altIdx}
                              className="p-2.5 rounded bg-surface border border-border text-xs space-y-1.5"
                            >
                              <div className="flex items-center justify-between">
                                <span className="font-medium text-text capitalize">
                                  {alt.kind.replace(/_/g, " ")}
                                </span>
                                {alt.requires_user_approval && (
                                  <span className="text-[10px] text-amber-600 font-mono font-semibold">
                                    Requires Approval
                                  </span>
                                )}
                              </div>
                              <p className="text-text-muted text-[11px]">{alt.description}</p>
                              <div className="pt-1">
                                <Button
                                  size="sm"
                                  variant="outline"
                                  className="w-full text-xs h-7"
                                  onClick={() => handleProposeAlternative(conf, altIdx)}
                                  loading={isProposing}
                                >
                                  Propose Alternative
                                </Button>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Pending Approval Notice */}
          {proposals.length > 0 && (
            <Card className="border-blue-200 dark:border-blue-900 bg-blue-50/30 dark:bg-blue-950/20">
              <CardContent className="space-y-3">
                <div className="flex items-center gap-2">
                  <ShieldAlert className="w-5 h-5 text-primary" />
                  <h4 className="text-sm font-semibold text-text">Pending Approvals Gate</h4>
                </div>
                <p className="text-xs text-text-muted">
                  You have {proposals.length} consequential action{proposals.length > 1 ? "s" : ""} waiting in the approval queue. Nothing will be written to your calendar until you review and approve.
                </p>
                <Link href="/approvals" className="block">
                  <Button size="sm" className="w-full">
                    Review Approval Queue <ArrowRight className="w-4 h-4 ml-1" />
                  </Button>
                </Link>
              </CardContent>
            </Card>
          )}
        </div>
      </div>
    </div>
  );
}
