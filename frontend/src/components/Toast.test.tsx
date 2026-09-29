import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { ToastProvider, useToast } from "./Toast";

function Probe() {
  const { showToast } = useToast();
  return (
    <button type="button" onClick={() => showToast("saved successfully", "success")}>
      trigger
    </button>
  );
}

describe("ToastProvider", () => {
  it("shows toasts and auto-dismisses them", async () => {
    const user = userEvent.setup();
    render(
      <ToastProvider>
        <Probe />
      </ToastProvider>,
    );
    await user.click(screen.getByRole("button", { name: "trigger" }));
    expect(screen.getByText("saved successfully")).toBeInTheDocument();
    // Toasts disappear after ~4.5s; use real timers to avoid fake-timer coupling.
    await waitFor(
      () => expect(screen.queryByText("saved successfully")).toBeNull(),
      { timeout: 6000 },
    );
  }, 8000);
});
