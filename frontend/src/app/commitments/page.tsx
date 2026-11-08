"use client";

import React, { useEffect, useState } from "react";
import {
  ListTodo,
  Clock,
  Calendar,
  Bell,
  AlertTriangle,
  CheckCircle2,
  Tag,
  ArrowRight,
  Filter,
  Plus,
  Send,
  Edit2,
} from "lucide-react";
import { api, ConfirmedCommitmentItem, ReminderItem } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";

export default function CommitmentsPage() {
  const [commitments, setCommitments] = useState<ConfirmedCommitmentItem[]>([]);
  const [reminders, setReminders] = useState<ReminderItem[]>([]);
  const [loading, setLoading] = useState<boolean>(true);
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [feedback, setFeedback] = useState<{ text: string; type: "success" | "error" } | null>(null);

  // Reminder creation modal
  const [selectedCommitment, setSelectedCommitment] = useState<ConfirmedCommitmentItem | null>(null);
  const [reminderDueAt, setReminderDueAt] = useState<string>("");
  const [reminderChannel, setReminderChannel] = useState<string>("in_app");
  const [creatingReminder, setCreatingReminder] = useState<boolean>(false);
  const [dispatching, setDispatching] = useState<boolean>(false);

  // Commitment edit modal
  const [editingCommitment, setEditingCommitment] = useState<ConfirmedCommitmentItem | null>(null);
  const [editTitle, setEditTitle] = useState<string>("");
  const [editStatus, setEditStatus] = useState<string>("open");
  const [editPriority, setEditPriority] = useState<number>(2);
  const [editDuration, setEditDuration] = useState<string>("");
  const [updatingCommitment, setUpdatingCommitment] = useState<boolean>(false);

  const loadData = async () => {
    try {
      setLoading(true);
      const comms = await api.listCommitments(statusFilter === "all" ? undefined : statusFilter);
      setCommitments(comms);

      const rems = await api.listReminders();
      setReminders(rems);
    } catch (err: any) {
      setFeedback({ text: err.message || "Failed to load commitments.", type: "error" });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
  }, [statusFilter]);

  const handleCreateReminder = async () => {
    if (!selectedCommitment || !reminderDueAt) return;

    try {
      setCreatingReminder(true);
      setFeedback(null);

      const dueIso = new Date(reminderDueAt).toISOString();
      const newRem = await api.createReminder({
        commitment_id: selectedCommitment.id,
        due_at: dueIso,
        channel: reminderChannel,
        idempotency_key: `rem-ui-${Date.now()}`,
      });

      setFeedback({
        text: `Reminder scheduled (#${newRem.idempotency_key}) for ${selectedCommitment.title}`,
        type: "success",
      });

      setSelectedCommitment(null);
      setReminderDueAt("");
      loadData();
    } catch (err: any) {
      setFeedback({ text: err.message || "Failed to schedule reminder.", type: "error" });
    } finally {
      setCreatingReminder(false);
    }
  };

  const handleUpdateCommitment = async () => {
    if (!editingCommitment) return;
    try {
      setUpdatingCommitment(true);
      setFeedback(null);
      await api.updateCommitment(editingCommitment.id, {
        title: editTitle,
        status: editStatus,
        priority: editPriority,
        estimate_minutes: editDuration ? parseInt(editDuration) : undefined,
      });
      setFeedback({ text: `Commitment "${editTitle}" updated successfully.`, type: "success" });
      setEditingCommitment(null);
      loadData();
    } catch (err: any) {
      setFeedback({ text: err.message || "Failed to update commitment.", type: "error" });
    } finally {
      setUpdatingCommitment(false);
    }
  };

  const handleTriggerDispatch = async () => {
    try {
      setDispatching(true);
      setFeedback(null);
      const res = await api.dispatchReminders("success");
      setFeedback({
        text: `Worker dispatch complete: ${res.processed_count} processed, ${res.delivered_count} delivered, ${res.retried_count} retried, ${res.failed_count} failed.`,
        type: "success",
      });
      loadData();
    } catch (err: any) {
      setFeedback({ text: err.message || "Dispatch failed.", type: "error" });
    } finally {
      setDispatching(false);
    }
  };

  const getRemindersForCommitment = (commitmentId: string) => {
    return reminders.filter((r) => r.commitment_id === commitmentId);
  };

  const getPriorityBadge = (p: number) => {
    switch (p) {
      case 4:
        return <Badge variant="danger">P4 - Urgent</Badge>;
      case 3:
        return <Badge variant="warning">P3 - High</Badge>;
      case 2:
        return <Badge variant="primary">P2 - Normal</Badge>;
      default:
        return <Badge variant="neutral">P1 - Low</Badge>;
    }
  };

  const getStatusBadge = (s: string) => {
    switch (s) {
      case "open":
        return <Badge variant="neutral">Open</Badge>;
      case "scheduled":
        return <Badge variant="primary">Scheduled</Badge>;
      case "in_progress":
        return <Badge variant="warning">In Progress</Badge>;
      case "done":
        return <Badge variant="success">Done</Badge>;
      case "dropped":
        return <Badge variant="danger">Dropped</Badge>;
      default:
        return <Badge>{s}</Badge>;
    }
  };

  return (
    <div className="space-y-6 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 pb-2 border-b border-border">
        <div>
          <div className="flex items-center gap-2">
            <ListTodo className="w-6 h-6 text-primary" />
            <h1 className="text-2xl font-bold tracking-tight text-text">Tracked Commitments</h1>
          </div>
          <p className="text-sm text-text-muted mt-1">
            First-class commitments with due dates, dependencies, provenance, status, and reminder rules.
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Button
            size="sm"
            variant="outline"
            onClick={handleTriggerDispatch}
            loading={dispatching}
            title="Trigger background reminder worker to deliver due notifications"
          >
            <Send className="w-3.5 h-3.5" />
            Dispatch Due Reminders
          </Button>

          {/* Filter tabs */}
          <div className="flex items-center gap-1 p-1 bg-stone-100 dark:bg-stone-800 rounded-lg border border-border">
            {["all", "open", "scheduled", "in_progress", "done"].map((status) => (
              <button
                key={status}
                onClick={() => setStatusFilter(status)}
                className={`px-3 py-1 text-xs font-medium rounded-md capitalize transition-colors ${
                  statusFilter === status
                    ? "bg-surface text-text shadow-sm font-semibold"
                    : "text-text-muted hover:text-text"
                }`}
              >
                {status}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Feedback Alert */}
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

      {/* Commitments Table */}
      {loading ? (
        <div className="py-12 text-center text-text-muted text-sm animate-pulse">
          Loading commitments...
        </div>
      ) : commitments.length === 0 ? (
        <EmptyState
          icon={ListTodo}
          title="No commitments found"
          description="Capture thoughts and to-dos in your Inbox to generate structured commitments."
        />
      ) : (
        <div className="border border-border rounded-lg bg-surface overflow-hidden shadow-sm">
          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse text-sm">
              <thead>
                <tr className="border-b border-border bg-stone-50 dark:bg-stone-900/40 text-xs font-semibold text-text-muted uppercase tracking-wider">
                  <th className="py-3 px-4">Title</th>
                  <th className="py-3 px-4">Priority</th>
                  <th className="py-3 px-4">Status</th>
                  <th className="py-3 px-4">Due Date</th>
                  <th className="py-3 px-4">Duration</th>
                  <th className="py-3 px-4">Reminders</th>
                  <th className="py-3 px-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border font-sans">
                {commitments.map((c) => {
                  const commReminders = getRemindersForCommitment(c.id);

                  return (
                    <tr key={c.id} className="hover:bg-stone-50/50 dark:hover:bg-stone-800/40 transition-colors">
                      <td className="py-3.5 px-4">
                        <div className="font-semibold text-text">{c.title}</div>
                        {c.description && (
                          <div className="text-xs text-text-muted mt-0.5 line-clamp-1">
                            {c.description}
                          </div>
                        )}
                        {c.dependencies.length > 0 && (
                          <div className="flex items-center gap-1 text-[11px] text-text-muted mt-1 font-mono">
                            <Tag className="w-3 h-3" />
                            <span>{c.dependencies.length} prerequisite(s)</span>
                          </div>
                        )}
                      </td>

                      <td className="py-3.5 px-4 whitespace-nowrap">
                        {getPriorityBadge(c.priority)}
                      </td>

                      <td className="py-3.5 px-4 whitespace-nowrap">
                        {getStatusBadge(c.status)}
                      </td>

                      <td className="py-3.5 px-4 whitespace-nowrap text-xs font-mono text-text">
                        {c.due_at ? (
                          new Date(c.due_at).toLocaleDateString([], {
                            month: "short",
                            day: "numeric",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        ) : (
                          <span className="text-text-muted italic">No deadline</span>
                        )}
                      </td>

                      <td className="py-3.5 px-4 whitespace-nowrap text-xs font-mono text-text">
                        {c.estimate_minutes ? `${c.estimate_minutes} min` : "—"}
                      </td>

                      <td className="py-3.5 px-4 whitespace-nowrap">
                        {commReminders.length === 0 ? (
                          <span className="text-xs text-text-muted italic">None</span>
                        ) : (
                          <div className="flex flex-wrap gap-1">
                            {commReminders.map((r) => (
                              <Badge
                                key={r.id}
                                size="sm"
                                variant={
                                  r.status === "delivered"
                                    ? "success"
                                    : r.status === "needs_attention"
                                    ? "danger"
                                    : "primary"
                                }
                              >
                                <Bell className="w-2.5 h-2.5" />
                                {r.status}
                              </Badge>
                            ))}
                          </div>
                        )}
                      </td>

                      <td className="py-3.5 px-4 text-right whitespace-nowrap">
                        <div className="flex items-center justify-end gap-1.5">
                          <Button
                            size="sm"
                            variant="ghost"
                            onClick={() => {
                              setEditingCommitment(c);
                              setEditTitle(c.title);
                              setEditStatus(c.status);
                              setEditPriority(c.priority);
                              setEditDuration(c.estimate_minutes ? c.estimate_minutes.toString() : "");
                            }}
                          >
                            <Edit2 className="w-3.5 h-3.5" />
                            Edit
                          </Button>
                          <Button
                            size="sm"
                            variant="outline"
                            onClick={() => {
                              setSelectedCommitment(c);
                              // Default reminder: 1 hour before due or 1 hour from now
                              const defaultTime = c.due_at
                                ? new Date(new Date(c.due_at).getTime() - 60 * 60 * 1000)
                                : new Date(Date.now() + 60 * 60 * 1000);
                              setReminderDueAt(defaultTime.toISOString().slice(0, 16));
                            }}
                          >
                            <Bell className="w-3.5 h-3.5" />
                            Set Reminder
                          </Button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Set Reminder Modal */}
      {selectedCommitment && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="bg-surface border border-border rounded-xl shadow-xl max-w-md w-full p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div className="flex items-center gap-2">
                <Bell className="w-5 h-5 text-primary" />
                <h3 className="text-base font-semibold text-text">Schedule Reminder</h3>
              </div>
              <button
                onClick={() => setSelectedCommitment(null)}
                className="text-text-muted hover:text-text text-sm"
              >
                ✕
              </button>
            </div>

            <div className="text-xs text-text-muted">
              Configure an idempotent notification for{" "}
              <strong className="text-text">"{selectedCommitment.title}"</strong>.
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="font-semibold text-text-muted block mb-1">Reminder Time</label>
                <input
                  type="datetime-local"
                  value={reminderDueAt}
                  onChange={(e) => setReminderDueAt(e.target.value)}
                  className="w-full px-3 py-2 rounded border border-border bg-bg text-text text-sm font-mono focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>

              <div>
                <label className="font-semibold text-text-muted block mb-1">Delivery Channel</label>
                <select
                  value={reminderChannel}
                  onChange={(e) => setReminderChannel(e.target.value)}
                  className="w-full px-3 py-2 rounded border border-border bg-bg text-text text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                >
                  <option value="in_app">In-App Notification</option>
                  <option value="simulated_email">Simulated Email</option>
                  <option value="simulated_sms">Simulated SMS</option>
                </select>
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-border">
              <Button size="sm" variant="outline" onClick={() => setSelectedCommitment(null)}>
                Cancel
              </Button>
              <Button
                size="sm"
                variant="primary"
                onClick={handleCreateReminder}
                loading={creatingReminder}
                disabled={!reminderDueAt}
              >
                Save Scheduled Reminder
              </Button>
            </div>
          </div>
        </div>
      )}

      {/* Edit Commitment Modal */}
      {editingCommitment && (
        <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-sm">
          <div className="bg-surface border border-border rounded-xl shadow-xl max-w-md w-full p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div className="flex items-center gap-2">
                <Edit2 className="w-5 h-5 text-primary" />
                <h3 className="text-base font-semibold text-text">Edit Commitment</h3>
              </div>
              <button
                onClick={() => setEditingCommitment(null)}
                className="text-text-muted hover:text-text text-sm"
              >
                ✕
              </button>
            </div>

            <div className="space-y-3 text-xs">
              <div>
                <label className="font-semibold text-text-muted block mb-1">Title</label>
                <input
                  type="text"
                  value={editTitle}
                  onChange={(e) => setEditTitle(e.target.value)}
                  className="w-full px-3 py-2 rounded border border-border bg-bg text-text text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="font-semibold text-text-muted block mb-1">Status</label>
                  <select
                    value={editStatus}
                    onChange={(e) => setEditStatus(e.target.value)}
                    className="w-full px-3 py-2 rounded border border-border bg-bg text-text text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                  >
                    <option value="open">Open</option>
                    <option value="scheduled">Scheduled</option>
                    <option value="in_progress">In Progress</option>
                    <option value="done">Done</option>
                    <option value="dropped">Dropped</option>
                  </select>
                </div>

                <div>
                  <label className="font-semibold text-text-muted block mb-1">Priority</label>
                  <select
                    value={editPriority}
                    onChange={(e) => setEditPriority(parseInt(e.target.value))}
                    className="w-full px-3 py-2 rounded border border-border bg-bg text-text text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                  >
                    <option value={1}>P1 - Low</option>
                    <option value={2}>P2 - Normal</option>
                    <option value={3}>P3 - High</option>
                    <option value={4}>P4 - Urgent</option>
                  </select>
                </div>
              </div>

              <div>
                <label className="font-semibold text-text-muted block mb-1">Estimate (Minutes)</label>
                <input
                  type="number"
                  value={editDuration}
                  onChange={(e) => setEditDuration(e.target.value)}
                  placeholder="e.g. 60"
                  className="w-full px-3 py-2 rounded border border-border bg-bg text-text text-sm focus:outline-none focus:ring-1 focus:ring-primary"
                />
              </div>
            </div>

            <div className="flex items-center justify-end gap-3 pt-3 border-t border-border">
              <Button size="sm" variant="outline" onClick={() => setEditingCommitment(null)}>
                Cancel
              </Button>
              <Button
                size="sm"
                variant="primary"
                onClick={handleUpdateCommitment}
                loading={updatingCommitment}
                disabled={!editTitle.trim()}
              >
                Save Changes
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
