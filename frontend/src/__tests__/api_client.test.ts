import { describe, it, expect, vi, beforeEach } from "vitest";
import { api, API_BASE } from "@/lib/api";

describe("Centralized API Client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("submits raw input to /inputs endpoint", async () => {
    const mockResponse = {
      note_id: "123e4567-e89b-12d3-a456-426614174000",
      raw_text: "Call Rahul tomorrow",
      captured_at: new Date().toISOString(),
      commitments: [],
      questions: [],
      overall_confidence: 0.9,
      parse_latency_ms: 12.5,
    };

    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => mockResponse,
    } as any);

    const result = await api.submitRawInput("Call Rahul tomorrow");

    expect(global.fetch).toHaveBeenCalledWith(
      `${API_BASE}/inputs`,
      expect.objectContaining({
        method: "POST",
        body: JSON.stringify({ raw_text: "Call Rahul tomorrow" }),
      })
    );
    expect(result.note_id).toBe(mockResponse.note_id);
  });

  it("handles backend error response properly", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: async () => ({ detail: "Proposal has expired." }),
    } as any);

    await expect(api.approveProposal("prop-01")).rejects.toThrow("Proposal has expired.");
  });

  it("fetches audit events with entity filter", async () => {
    global.fetch = vi.fn().mockResolvedValue({
      ok: true,
      json: async () => [],
    } as any);

    await api.listAuditEvents("proposal", 50);

    expect(global.fetch).toHaveBeenCalledWith(
      `${API_BASE}/audit-events?entity_type=proposal&limit=50`,
      expect.any(Object)
    );
  });
});
