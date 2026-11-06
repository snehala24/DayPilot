import React from "react";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import InboxPage from "@/app/inbox/page";
import ApprovalsPage from "@/app/approvals/page";
import CommitmentsPage from "@/app/commitments/page";
import { api } from "@/lib/api";

// Mock next/navigation
vi.mock("next/navigation", () => ({
  usePathname: () => "/inbox",
  useRouter: () => ({ push: vi.fn() }),
}));

describe("Main User Flow Integrations", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("Inbox Flow: extract note, display candidates, and confirm", async () => {
    vi.spyOn(api, "submitRawInput").mockResolvedValue({
      note_id: "note-123",
      raw_text: "Finish report by Friday",
      captured_at: new Date().toISOString(),
      commitments: [
        {
          title: "Finish report",
          priority: 2,
          due_date: "2026-11-13",
          dependencies: [],
          confidence: 0.95,
          uncertain_fields: [],
        },
      ],
      questions: [],
      overall_confidence: 0.95,
      parse_latency_ms: 10,
    });

    vi.spyOn(api, "confirmCommitments").mockResolvedValue({
      note_id: "note-123",
      confirmed_commitment_ids: ["comm-456"],
      commitments: [
        {
          id: "comm-456",
          title: "Finish report",
          priority: 2,
          status: "open",
          dependencies: [],
        },
      ],
      audit_event_id: "audit-789",
      status: "confirmed",
    });

    render(<InboxPage />);

    // Type text in textarea
    const textarea = screen.getByPlaceholderText(/Prepare client deck/i);
    fireEvent.change(textarea, { target: { value: "Finish report by Friday" } });

    // Click Extract
    const extractBtn = screen.getByRole("button", { name: /Extract Commitments/i });
    fireEvent.click(extractBtn);

    // Wait for candidate to appear
    await waitFor(() => {
      expect(screen.getByDisplayValue("Finish report")).toBeInTheDocument();
    });

    // Click Confirm & Save
    const confirmBtn = screen.getByRole("button", { name: /Confirm & Save All/i });
    fireEvent.click(confirmBtn);

    // Verify success banner appears
    await waitFor(() => {
      expect(screen.getByText(/Confirmed and Saved!/i)).toBeInTheDocument();
    });
  });

  it("Approvals Flow: loads pending proposals and triggers approval", async () => {
    vi.spyOn(api, "listProposals").mockResolvedValue([
      {
        id: "prop-123",
        user_id: "user-1",
        kind: "calendar_create",
        payload: {
          title: "Design Review",
          starts_at: "2026-11-07T10:00:00Z",
          ends_at: "2026-11-07T11:00:00Z",
        },
        reason: "Scheduled block",
        status: "pending",
        idempotency_key: "prop-key-001",
        created_at: new Date().toISOString(),
        updated_at: new Date().toISOString(),
      },
    ]);

    const approveSpy = vi.spyOn(api, "approveProposal").mockResolvedValue({
      id: "prop-123",
      user_id: "user-1",
      kind: "calendar_create",
      payload: { title: "Design Review" },
      status: "verified",
      idempotency_key: "prop-key-001",
      result: { title: "Design Review", external_id: "sim-123", verified_at: new Date().toISOString() },
      created_at: new Date().toISOString(),
      updated_at: new Date().toISOString(),
    });

    render(<ApprovalsPage />);

    // Wait for proposal to load
    await waitFor(() => {
      expect(screen.getByText("Design Review")).toBeInTheDocument();
    });

    // Click Approve
    const approveBtn = screen.getByRole("button", { name: /Approve & Execute/i });
    fireEvent.click(approveBtn);

    await waitFor(() => {
      expect(approveSpy).toHaveBeenCalledWith("prop-123", expect.any(String), undefined);
    });
  });

  it("Commitments Flow: lists commitments and opens reminder modal", async () => {
    vi.spyOn(api, "listCommitments").mockResolvedValue([
      {
        id: "comm-999",
        title: "Submit Budget Analysis",
        priority: 3,
        status: "open",
        due_at: "2026-11-10T17:00:00Z",
        dependencies: [],
      },
    ]);
    vi.spyOn(api, "listReminders").mockResolvedValue([]);

    render(<CommitmentsPage />);

    await waitFor(() => {
      expect(screen.getByText("Submit Budget Analysis")).toBeInTheDocument();
    });

    // Click Set Reminder button
    const setReminderBtn = screen.getByRole("button", { name: /Set Reminder/i });
    fireEvent.click(setReminderBtn);

    // Modal opens
    expect(screen.getByText(/Schedule Reminder/i)).toBeInTheDocument();
  });
});
