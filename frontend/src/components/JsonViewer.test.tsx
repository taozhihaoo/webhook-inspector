import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { JsonViewer } from "./JsonViewer";

describe("JsonViewer", () => {
  it("renders nested json values as text", () => {
    render(<JsonViewer data={{ event: "order.created", order: { id: 42, total: 19.99 } }} />);
    expect(screen.getByText(/order\.created/)).toBeInTheDocument();
    expect(screen.getByText(/19\.99/)).toBeInTheDocument();
  });

  it("renders injected markup as inert text (no HTML execution)", () => {
    render(<JsonViewer data={{ evil: "<script>alert(1)</script>" }} />);
    // The payload appears as text content, not as an actual script element.
    expect(screen.getByText(/alert\(1\)/)).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });

  it("collapses deep nodes and expands on click", async () => {
    const user = userEvent.setup();
    const deep = { l1: { l2: { a: { x: 1 }, b: { y: 2 } } } };
    render(<JsonViewer data={deep} />);
    // depth 3 is beyond COLLAPSE_DEPTH -> rendered collapsed by default
    const collapsed = screen
      .getAllByRole("button")
      .filter((button) => button.getAttribute("aria-expanded") === "false");
    expect(collapsed.length).toBeGreaterThan(0);
    await user.click(collapsed[0]);
    expect(collapsed[0].getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("1")).toBeInTheDocument();
  });

  it("renders event-handler payloads as inert text (img onerror)", () => {
    render(<JsonViewer data={{ payload: '<img src=x onerror=alert(2)>' }} />);
    expect(screen.getByText(/onerror=alert\(2\)/)).toBeInTheDocument();
    // No img element may exist anywhere in the rendered viewer.
    expect(document.querySelector("img")).toBeNull();
  });

  it("renders malformed json fragments as data", () => {
    render(<JsonViewer data={{ note: '{"truncated', other: [null, true] }} />);
    expect(screen.getByText(/truncated/)).toBeInTheDocument();
    expect(document.querySelector("script")).toBeNull();
  });

  it("renders empty containers", () => {
    render(<JsonViewer data={{ empty_object: {}, empty_array: [] }} />);
    expect(screen.getByText("{}")).toBeInTheDocument();
    expect(screen.getByText("[]")).toBeInTheDocument();
  });

  it("renders null and booleans", () => {
    render(<JsonViewer data={{ a: null, b: true, c: false }} />);
    expect(screen.getByText("null")).toBeInTheDocument();
    expect(screen.getByText("true")).toBeInTheDocument();
  });
});
