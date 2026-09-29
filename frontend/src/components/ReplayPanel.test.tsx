import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { HeadersTable } from "./ReplayPanel";

vi.mock("../api/client", () => ({
  api: {
    listReplays: vi.fn().mockResolvedValue([]),
  },
  getStoredToken: () => "test-token",
}));

describe("HeadersTable redaction", () => {
  it("redacts sensitive headers by default", () => {
    render(
      <HeadersTable
        headers={{
          Authorization: "Bearer sk_live_never_show",
          "Content-Type": "application/json",
          "X-Api-Key": "key-123",
        }}
      />,
    );
    expect(screen.getAllByText("[REDACTED]")).toHaveLength(2);
    expect(screen.queryByText(/sk_live_never_show/)).toBeNull();
    expect(screen.getByText("application/json")).toBeInTheDocument();
  });

  it("reveals a sensitive value only after explicit user action", async () => {
    const user = (await import("@testing-library/user-event")).default.setup();
    render(<HeadersTable headers={{ "Private-Token": "abc123" }} />);
    expect(screen.queryByText("abc123")).toBeNull();
    await user.click(screen.getByRole("button", { name: /reveal private-token/i }));
    expect(screen.getByText("abc123")).toBeInTheDocument();
  });

  it("offers copy for every row", () => {
    render(<HeadersTable headers={{ "X-One": "1", "X-Two": "2" }} />);
    expect(screen.getAllByRole("button", { name: /copy/i })).toHaveLength(2);
  });
});
