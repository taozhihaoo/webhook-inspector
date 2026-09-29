import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { EmptyState, ErrorState, LoadingState } from "./States";
import { AuthChip, MethodBadge, SignatureChip, StatusPill } from "./Badges";

describe("States", () => {
  it("renders empty state with hint", () => {
    render(<EmptyState title="No requests" hint="Send a webhook." />);
    expect(screen.getByText("No requests")).toBeInTheDocument();
    expect(screen.getByText("Send a webhook.")).toBeInTheDocument();
  });
  it("renders error state", () => {
    render(<ErrorState message="backend down" />);
    expect(screen.getByText("backend down")).toBeInTheDocument();
  });
  it("renders loading state", () => {
    render(<LoadingState label="Loading requests…" />);
    expect(screen.getByText("Loading requests…")).toBeInTheDocument();
  });
});

describe("Badges (status must not rely on color alone)", () => {
  it("method badge shows the method name", () => {
    render(<MethodBadge method="POST" />);
    expect(screen.getByText("POST")).toBeInTheDocument();
  });
  it("status pill shows the numeric status", () => {
    render(<StatusPill status={200} />);
    expect(screen.getByText("200")).toBeInTheDocument();
  });
  it("signature chip text differs per state", () => {
    const { rerender } = render(<SignatureChip status="verified" />);
    expect(screen.getByText(/verified/)).toBeInTheDocument();
    rerender(<SignatureChip status="invalid" />);
    expect(screen.getByText(/invalid/)).toBeInTheDocument();
  });
  it("auth chip text differs per state", () => {
    const { rerender } = render(<AuthChip status="valid" />);
    expect(screen.getByText(/token valid/)).toBeInTheDocument();
    rerender(<AuthChip status="invalid" />);
    expect(screen.getByText(/token invalid/)).toBeInTheDocument();
  });
});
