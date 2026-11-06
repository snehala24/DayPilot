import React from "react";
import { render, screen, fireEvent } from "@testing-library/react";
import { describe, it, expect, vi } from "vitest";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/Card";
import { EmptyState } from "@/components/ui/EmptyState";
import { ShieldCheck } from "lucide-react";

describe("Design System UI Components", () => {
  it("renders Badge with appropriate variant classes", () => {
    const { rerender } = render(<Badge variant="success">Verified</Badge>);
    expect(screen.getByText("Verified")).toBeInTheDocument();

    rerender(<Badge variant="danger">Failed</Badge>);
    expect(screen.getByText("Failed")).toBeInTheDocument();

    rerender(<Badge variant="warning">Conflict</Badge>);
    expect(screen.getByText("Conflict")).toBeInTheDocument();
  });

  it("renders Button and handles clicks", () => {
    const handleClick = vi.fn();
    render(<Button onClick={handleClick}>Approve Action</Button>);

    const btn = screen.getByRole("button", { name: "Approve Action" });
    fireEvent.click(btn);
    expect(handleClick).toHaveBeenCalledTimes(1);
  });

  it("disables Button when loading or disabled", () => {
    render(<Button loading>Processing</Button>);
    const btn = screen.getByRole("button");
    expect(btn).toBeDisabled();
  });

  it("renders Card container with header and content", () => {
    render(
      <Card>
        <CardHeader>
          <CardTitle>Daily Schedule</CardTitle>
        </CardHeader>
        <CardContent>
          <p>Schedule details</p>
        </CardContent>
      </Card>
    );

    expect(screen.getByText("Daily Schedule")).toBeInTheDocument();
    expect(screen.getByText("Schedule details")).toBeInTheDocument();
  });

  it("renders EmptyState component properly", () => {
    render(
      <EmptyState
        icon={ShieldCheck}
        title="No pending approvals"
        description="All proposals have been evaluated."
        action={<Button size="sm">Refresh</Button>}
      />
    );

    expect(screen.getByText("No pending approvals")).toBeInTheDocument();
    expect(screen.getByText("All proposals have been evaluated.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Refresh" })).toBeInTheDocument();
  });
});
