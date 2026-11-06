"use client";

import React, { useState } from "react";
import Link from "next/link";
import {
  Inbox as InboxIcon,
  Sparkles,
  CheckCircle2,
  AlertCircle,
  HelpCircle,
  Clock,
  ArrowRight,
  FileText,
  User,
  Tag,
  Calendar,
} from "lucide-react";
import { api, RawInputResponse, ExtractedCandidate, ConfirmCommitmentsResponse } from "@/lib/api";
import { Button } from "@/components/ui/Button";
import { Badge } from "@/components/ui/Badge";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card";

const SAMPLE_NOTES = [
  "Finish the Q3 budget report by tomorrow 5pm. Sync with Rahul before submitting. Need about 90 mins for the report.",
  "Submit assignment next Friday. Call Dr. Kumar regarding lab equipment on Monday morning.",
  "Prepare presentation slides for team demo on Thursday 2pm. Need 45 mins. Prerequisite is completing user feedback analysis.",
];

export default function InboxPage() {
  const [inputText, setInputText] = useState<string>("");
  const [extracting, setExtracting] = useState<boolean>(false);
  const [extractionResult, setExtractionResult] = useState<RawInputResponse | null>(null);
  const [candidates, setCandidates] = useState<ExtractedCandidate[]>([]);
  const [confirming, setConfirming] = useState<boolean>(false);
  const [confirmedResult, setConfirmedResult] = useState<ConfirmCommitmentsResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleExtract = async () => {
    if (!inputText.trim()) return;

    try {
      setExtracting(true);
      setError(null);
      setConfirmedResult(null);

      const res = await api.submitRawInput(inputText);
      setExtractionResult(res);
      setCandidates(res.commitments);
    } catch (err: any) {
      setError(err.message || "Failed to extract commitments.");
    } finally {
      setExtracting(false);
    }
  };

  const handleCandidateChange = (
    index: number,
    field: keyof ExtractedCandidate,
    value: any
  ) => {
    const updated = [...candidates];
    updated[index] = { ...updated[index], [field]: value };
    setCandidates(updated);
  };

  const handleConfirm = async () => {
    if (!extractionResult) return;

    try {
      setConfirming(true);
      setError(null);

      const res = await api.confirmCommitments(
        extractionResult.note_id,
        candidates,
        `confirm-${Date.now()}`
      );
      setConfirmedResult(res);
    } catch (err: any) {
      setError(err.message || "Failed to confirm commitments.");
    } finally {
      setConfirming(false);
    }
  };

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Header */}
      <div className="pb-2 border-b border-border">
        <div className="flex items-center gap-2">
          <InboxIcon className="w-6 h-6 text-primary" />
          <h1 className="text-2xl font-bold tracking-tight text-text">Capture & Ingest Notes</h1>
        </div>
        <p className="text-sm text-text-muted mt-1">
          Paste messy thoughts, chat requests, or to-dos. The extraction engine extracts structured commitments with explicit provenance.
        </p>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="p-3.5 rounded-md border border-rose-200 bg-rose-50 text-rose-800 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300 text-sm flex items-center gap-2">
          <AlertCircle className="w-4 h-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Success Banner */}
      {confirmedResult && (
        <div className="p-5 rounded-lg border border-emerald-200 bg-emerald-50 text-emerald-900 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300 space-y-3">
          <div className="flex items-center gap-2">
            <CheckCircle2 className="w-5 h-5 text-emerald-600 dark:text-emerald-400" />
            <h3 className="font-semibold text-base">
              {confirmedResult.commitments.length} Commitment{confirmedResult.commitments.length > 1 ? "s" : ""} Confirmed and Saved!
            </h3>
          </div>
          <p className="text-xs text-emerald-800 dark:text-emerald-400">
            Commitments are persisted in the database with immutable audit trail ({confirmedResult.audit_event_id}). Nothing has been written to your calendar yet until a proposal is generated and approved.
          </p>
          <div className="flex items-center gap-3 pt-1">
            <Link href="/">
              <Button size="sm" variant="primary">
                View in Today's Plan <ArrowRight className="w-4 h-4 ml-1" />
              </Button>
            </Link>
            <Link href="/commitments">
              <Button size="sm" variant="outline">
                Browse Commitments
              </Button>
            </Link>
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setInputText("");
                setExtractionResult(null);
                setConfirmedResult(null);
              }}
            >
              Capture New Note
            </Button>
          </div>
        </div>
      )}

      {/* Input Section */}
      {!confirmedResult && (
        <Card>
          <CardHeader>
            <CardTitle>Raw Input</CardTitle>
            <span className="text-xs font-mono text-text-muted">Passive Data Sandboxed</span>
          </CardHeader>
          <CardContent className="space-y-4">
            <textarea
              className="w-full h-32 p-3 text-sm rounded-md border border-border bg-bg text-text focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent transition-all resize-none font-sans"
              placeholder="e.g. Prepare client deck for tomorrow 3pm. Rahul needs to review it first. Takes about 45 mins."
              value={inputText}
              onChange={(e) => setInputText(e.target.value)}
            />

            {/* Quick sample chips */}
            <div className="space-y-1.5">
              <span className="text-xs font-medium text-text-muted">Or try a sample note:</span>
              <div className="flex flex-wrap gap-2">
                {SAMPLE_NOTES.map((sample, i) => (
                  <button
                    key={i}
                    onClick={() => setInputText(sample)}
                    className="text-xs px-2.5 py-1 rounded border border-border bg-stone-50 dark:bg-stone-800 text-text-muted hover:text-text hover:border-primary/40 text-left transition-colors truncate max-w-xs"
                    title={sample}
                  >
                    Sample {i + 1}: "{sample.slice(0, 35)}..."
                  </button>
                ))}
              </div>
            </div>

            <div className="flex items-center justify-between pt-2">
              <span className="text-xs font-mono text-text-muted">
                {inputText.length} characters
              </span>
              <Button
                onClick={handleExtract}
                loading={extracting}
                disabled={!inputText.trim()}
              >
                <Sparkles className="w-4 h-4" />
                Extract Commitments
              </Button>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Extraction Review Section */}
      {extractionResult && !confirmedResult && (
        <div className="space-y-6">
          {/* Ambiguity Questions (if any) */}
          {extractionResult.questions && extractionResult.questions.length > 0 && (
            <Card className="border-amber-200 dark:border-amber-900/50 bg-amber-50/20 dark:bg-amber-950/10">
              <CardHeader className="border-b border-amber-200 dark:border-amber-900/50">
                <div className="flex items-center gap-2">
                  <HelpCircle className="w-4 h-4 text-warning" />
                  <CardTitle className="text-amber-900 dark:text-amber-300">
                    Clarification Questions ({extractionResult.questions.length})
                  </CardTitle>
                </div>
                <span className="text-xs text-amber-700 dark:text-amber-400 font-mono">
                  Never Guess Policy
                </span>
              </CardHeader>
              <CardContent className="space-y-3">
                <p className="text-xs text-text-muted">
                  The model identified missing or ambiguous information. Instead of silently fabricating timestamps or owners, DayPilot asks directly:
                </p>
                <div className="space-y-2">
                  {extractionResult.questions.map((q, idx) => (
                    <div
                      key={idx}
                      className="p-3 rounded bg-surface border border-border text-xs space-y-1"
                    >
                      <div className="font-semibold text-text flex items-center justify-between">
                        <span>{q.question}</span>
                        <Badge size="sm" variant="warning">
                          {q.field}
                        </Badge>
                      </div>
                      <p className="text-text-muted text-[11px]">{q.reason}</p>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}

          {/* Candidate Commitments Review */}
          <div className="space-y-4">
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-base font-semibold text-text">
                  Extracted Candidates ({candidates.length})
                </h3>
                <p className="text-xs text-text-muted">
                  Review and edit before saving. The agent will never confirm commitments without your explicit instruction.
                </p>
              </div>
              <Badge variant="success">
                Confidence: {Math.round(extractionResult.overall_confidence * 100)}%
              </Badge>
            </div>

            {candidates.map((cand, idx) => (
              <Card key={idx} className="border-border">
                <CardContent className="p-4 space-y-4">
                  {/* Top row: Title and Priority */}
                  <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
                    <div className="sm:col-span-3">
                      <label className="text-xs font-semibold text-text-muted block mb-1">
                        Title
                      </label>
                      <input
                        type="text"
                        value={cand.title}
                        onChange={(e) => handleCandidateChange(idx, "title", e.target.value)}
                        className="w-full px-3 py-1.5 text-sm rounded border border-border bg-bg text-text focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    </div>
                    <div>
                      <label className="text-xs font-semibold text-text-muted block mb-1">
                        Priority (1-4)
                      </label>
                      <select
                        value={cand.priority}
                        onChange={(e) =>
                          handleCandidateChange(idx, "priority", parseInt(e.target.value))
                        }
                        className="w-full px-3 py-1.5 text-sm rounded border border-border bg-bg text-text focus:outline-none focus:ring-1 focus:ring-primary"
                      >
                        <option value={1}>P1 - Low</option>
                        <option value={2}>P2 - Normal</option>
                        <option value={3}>P3 - High</option>
                        <option value={4}>P4 - Urgent</option>
                      </select>
                    </div>
                  </div>

                  {/* Second row: Due date, time, duration */}
                  <div className="grid grid-cols-1 sm:grid-cols-3 gap-3">
                    <div>
                      <label className="text-xs font-semibold text-text-muted block mb-1">
                        Due Date
                      </label>
                      <input
                        type="date"
                        value={cand.due_date || ""}
                        onChange={(e) =>
                          handleCandidateChange(idx, "due_date", e.target.value || null)
                        }
                        className="w-full px-3 py-1.5 text-sm rounded border border-border bg-bg text-text focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    </div>

                    <div>
                      <label className="text-xs font-semibold text-text-muted block mb-1">
                        Due Time
                      </label>
                      <input
                        type="time"
                        value={cand.due_time || ""}
                        onChange={(e) =>
                          handleCandidateChange(idx, "due_time", e.target.value || null)
                        }
                        className="w-full px-3 py-1.5 text-sm rounded border border-border bg-bg text-text focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    </div>

                    <div>
                      <label className="text-xs font-semibold text-text-muted block mb-1">
                        Estimate (Minutes)
                      </label>
                      <input
                        type="number"
                        value={cand.estimate_minutes || ""}
                        placeholder="e.g. 60"
                        onChange={(e) =>
                          handleCandidateChange(
                            idx,
                            "estimate_minutes",
                            e.target.value ? parseInt(e.target.value) : null
                          )
                        }
                        className="w-full px-3 py-1.5 text-sm rounded border border-border bg-bg text-text focus:outline-none focus:ring-1 focus:ring-primary"
                      />
                    </div>
                  </div>

                  {/* Third row: Dependencies & Provenance */}
                  <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2 pt-2 border-t border-border/60 text-xs">
                    <div className="flex items-center gap-2 text-text-muted">
                      <Tag className="w-3.5 h-3.5" />
                      <span>
                        Dependencies:{" "}
                        <strong className="text-text">
                          {cand.dependencies.length > 0 ? cand.dependencies.join(", ") : "None"}
                        </strong>
                      </span>
                    </div>

                    {cand.source_span && (
                      <div className="flex items-center gap-1.5 text-text-muted font-mono text-[11px]">
                        <FileText className="w-3.5 h-3.5" />
                        <span>Source text: "{cand.source_span.text}"</span>
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            ))}

            {/* Confirm Actions */}
            <div className="flex items-center justify-between pt-4 border-t border-border">
              <Button
                variant="outline"
                onClick={() => {
                  setExtractionResult(null);
                  setCandidates([]);
                }}
              >
                Discard & Re-type
              </Button>

              <Button
                variant="primary"
                onClick={handleConfirm}
                loading={confirming}
                disabled={candidates.length === 0}
              >
                <CheckCircle2 className="w-4 h-4" />
                Confirm & Save All ({candidates.length}) Commitments
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
