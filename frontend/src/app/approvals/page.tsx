"use client";

import React, { useEffect, useState } from "react";
import {
  CheckSquare,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Clock,
  Calendar,
  ShieldCheck,
  Edit2,
  ArrowRight,
  ExternalLink,
  History as HistoryIcon,
} from "lucide-react";
import { api, ProposalItem } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";

export default function ApprovalsPage() {
  const [proposals, setProposals] = useState<ProposalItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [activeTab, setActiveTab] = useState<string>("pending");
  const [actingId, setActingId] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<{ text: string; type: "success" | "error" } | null>(null);

  // Edit before approve modal state
  const [editingProposal, setEditingProposal] = useState<ProposalItem | null>(null);
  const [editTitle, setEditTitle] = useState<string>("");
  const [editStartsAt, setEditStartsAt] = useState<string>("");
  const [editEndsAt, setEditEndsAt] = useState<string>("");

  const loadProposals = async () => {
    try {
      setLoading(true);
      const res = await api.listProposals(activeTab === "all" ? undefined : activeTab);
      setProposals(res);
    } catch (err: any) {
      setFeedback({ text: err.message || "Failed to load proposals.", type: "error" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadProposals();
  }, [activeTab]);

  const handleApprove = async (proposalId: string, editedPayload?: Record<string, any>) => {
    try {
      setActingId(proposalId);
      setFeedback(null);

      const approved = await api.approveProposal(
        proposalId,
        "Approved via DayPilot dashboard",
        editedPayload
      );

      setFeedback({
        text: `Proposal approved, executed, and read-back verified! Event created: "${approved.result?.title || approved.payload?.title}"`,
        type: "success",
      });

      // Refresh list
      loadProposals();
      setEditingProposal(null);
    } catch (err: any) {
      setFeedback({ text: err.message || "Approval execution failed.", type: "error" });
    } finally {
      setActingId(null);
    }
  };

  const handleReject = async (proposalId: string) => {
    const reason = prompt("Enter a reason for rejection (optional):") || undefined;
    try {
      setActingId(proposalId);
      setFeedback(null);

      await api.rejectProposal(proposalId, reason);

      setFeedback({
        text: "Proposal rejected. No external calendar action was taken.",
        type: "success",
      });

      loadProposals();
    } catch (err: any) {
      setFeedback({ text: err.message || "Failed to reject proposal.", type: "error" });
    } finally {
      setActingId(null);
    }
  };

  const openEditModal = (p: ProposalItem) => {
    setEditingProposal(p);
    setEditTitle(p.payload?.title || "");
    setEditStartsAt(p.payload?.starts_at || "");
    setEditEndsAt(p.payload?.ends_at || "");
  };

  const handleSaveAndApprove = () => {
    if (!editingProposal) return;
    const editedPayload = {
      ...editingProposal.payload,
      title: editTitle,
      starts_at: editStartsAt,
      ends_at: editEndsAt,
    };
    handleApprove(editingProposal.id, editedPayload);
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "pending":
        return <Badge variant="warning">Pending Approval</Badge>;
      case "approved":
        return <Badge variant="primary">Approved</Badge>;
      case "verified":
        return <Badge variant="success">Executed & Verified</Badge>;
      case "rejected":
        return <Badge variant="neutral">Rejected</Badge>;
      case "failed":
        return <Badge variant="danger">Execution Failed</Badge>;
      case "expired":
        return <Badge variant="neutral">Expired</Badge>;
      default:
        return <Badge>{status}</Badge>;
    }
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-border">
        <div>
          <div className="flex items-center gap-2">
            <CheckSquare className="w-6 h-6 text-primary" />
            <h1 className="text-2xl font-bold tracking-tight text-text">Approval Queue</h1>
          </div>
          <p className="text-sm text-text-muted mt-1">
            The agent proposes. The person approves. The system executes and verifies.
          </p>
        </div>

        {/* Tab Filters */}
        <div className="flex items-center gap-1 p-1 bg-stone-100 dark:bg-stone-800 rounded-lg border border-border">
          {["pending", "verified", "rejected", "all"].map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              className={`px-3 py-1 text-xs font-medium rounded-md capitalize transition-colors ${
                activeTab === tab
                  ? "bg-surface text-text shadow-sm font-semibold"
                  : "text-text-muted hover:text-text"
              }`}
            >
              {tab}
            </button>
          ))}
        </div>
      </div>

      {/* Feedback Banner */}
      {feedback && (
        <div
          className={`p-3.5 rounded-md border text-sm flex items-center justify-between ${
            feedback.type === "success"
              ? "bg-emerald-50 border-emerald-200 text-emerald-800 dark:bg-emerald-950/40 dark:border-emerald-800 dark:text-emerald-300"
              : "bg-rose-50 border-rose-200 text-rose-800 dark:bg-rose-950/40 dark:border-rose-800 dark:text-rose-300"
          }`}
        >
          <span>{feedback.text}</span>
          <button
            onClick={() => setFeedback(null)}
            className="text-xs font-semibold underline ml-4 hover:opacity-75"
          >
            Dismiss
          </button>
        </div>
      )}

      {/* Proposal Cards List */}
      {loading ? (
        <div className="py-12 text-center text-text-muted text-sm animate-pulse">
          Loading proposals from approval queue...
        </div>
      ) : proposals.length === 0 ? (
        <EmptyState
          icon={ShieldCheck}
          title={
            activeTab === "pending"
              ? "No pending approvals"
              : `No proposals found in '${activeTab}' state`
          }
          description="Every consequential calendar write is safely gated behind your review. Generate a plan on the Today screen or resolve a conflict to create proposals."
        />
      ) : (
        <div className="space-y-4">
          {proposals.map((prop) => (
            <Card key={prop.id} className="border-border hover:border-primary/30 transition-all">
              <CardContent className="p-5 space-y-4">
                {/* Header row */}
                <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 border-b border-border/60 pb-3">
                  <div className="flex items-center gap-2.5">
                    <span className="font-mono text-xs px-2 py-0.5 rounded bg-stone-100 dark:bg-stone-800 text-text-muted font-semibold">
                      {prop.kind}
                    </span>
                    <span className="text-xs font-mono text-text-muted">
                      ID: {prop.idempotency_key}
                    </span>
                  </div>

                  <div className="flex items-center gap-2">
                    {getStatusBadge(prop.status)}
                    {prop.expires_at && prop.status === "pending" && (
                      <span className="text-[11px] font-mono text-amber-600 dark:text-amber-400">
                        Expires: {new Date(prop.expires_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </span>
                    )}
                  </div>
                </div>

                {/* Details row */}
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  <div>
                    <h3 className="text-base font-semibold text-text tracking-tight mb-1">
                      {prop.payload?.title || "Calendar Write"}
                    </h3>
                    <p className="text-xs text-text-muted">{prop.reason || "Action proposed by DayPilot agent."}</p>
                  </div>

                  <div className="p-3 rounded-lg bg-stone-50 dark:bg-stone-900/40 border border-border text-xs space-y-1.5 font-mono">
                    <div className="flex justify-between">
                      <span className="text-text-muted">Starts At:</span>
                      <span className="text-text font-medium">{prop.payload?.starts_at}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-text-muted">Ends At:</span>
                      <span className="text-text font-medium">{prop.payload?.ends_at}</span>
                    </div>
                    <div className="flex justify-between">
                      <span className="text-text-muted">Timezone:</span>
                      <span className="text-text font-medium">{prop.payload?.tz || "UTC"}</span>
                    </div>
                  </div>
                </div>

                {/* Verification result (if executed/verified) */}
                {prop.result && (
                  <div className="p-3 rounded-lg bg-emerald-50/60 dark:bg-emerald-950/20 border border-emerald-200 dark:border-emerald-800 text-xs space-y-1">
                    <div className="flex items-center gap-1.5 font-semibold text-emerald-800 dark:text-emerald-300">
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      Read-Back Verification Confirmed
                    </div>
                    <div className="font-mono text-[11px] text-emerald-700 dark:text-emerald-400">
                      External Calendar ID: {prop.result.external_id || prop.result.calendar_event_id} | Verified at: {prop.result.verified_at}
                    </div>
                  </div>
                )}

                {/* Action buttons (only for pending proposals) */}
                {prop.status === "pending" && (
                  <div className="flex items-center justify-end gap-3 pt-2 border-t border-border/60">
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => openEditModal(prop)}
                      disabled={actingId === prop.id}
                    >
                      <Edit2 className="w-3.5 h-3.5" />
                      Edit & Approve
                    </Button>

                    <Button
                      size="sm"
                      variant="danger"
                      onClick={() => handleReject(prop.id)}
                      disabled={actingId === prop.id}
                      loading={actingId === prop.id}
                    >
                      <XCircle className="w-3.5 h-3.5" />
                      Reject
                    </Button>

                    <Button
                      size="sm"
                      variant="primary"
                      onClick={() => handleApprove(prop.id)}
                      disabled={actingId === prop.id}
                      loading={actingId === prop.id}
                    >
                      <CheckCircle2 className="w-3.5 h-3.5" />
                      Approve & Execute
                    </Button>
                  </div>
                )}
              </CardContent>
            </Card>
          ))}
        </div>
      )}

      {/* Edit Before Approve Modal */}
      {editingProposal && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="bg-surface border border-border rounded-xl shadow-xl max-w-lg w-full p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <h3 className="text-base font-semibold text-text">Edit Proposal Before Approving</h3>
              <button
                onClick={() => setEditingProposal(null)}
                className="text-text-muted hover:text-text text-sm"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="font-semibold text-text-muted block mb-1">Event Title</label>
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="w-full px-3 py-2 rounded border border-border bg-bg text-text text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>

              <div>
                <label className="font-semibold text-text-muted block mb-1">Starts At (ISO)</label>
                <input
                  type="text"
                  value={editStartsAt}
                  onChange={(e) => setEditStartsAt(e.target.value)}
                  className="w-full px-3 py-2 rounded border border-border bg-bg text-text text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>

              <div>
                <label className="font-semibold text-text-muted block mb-1">Ends At (ISO)</label>
                <input
                  type="text"
                  value={editEndsAt}
                  onChange={(e) => setEditEndsAt(e.target.value)}
                  className="w-full px-3 py-2 rounded border border-border bg-bg text-text text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-border">
              <Button size="sm" variant="outline" onClick={() => setEditingProposal(null)}>
                Cancel
              </Button>
              <Button size="sm" variant="primary" onClick={handleSaveAndApprove} loading={actingId === editingProposal.id}>
                Approve Adjusted Payload
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
