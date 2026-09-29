import { describe, expect, it } from "vitest";
import { formatBytes, formatDuration, formatRelative, statusClass } from "./format";

describe("formatBytes", () => {
  it("formats bytes", () => {
    expect(formatBytes(0)).toBe("0 B");
    expect(formatBytes(512)).toBe("512 B");
  });
  it("formats kilobytes", () => {
    expect(formatBytes(2048)).toBe("2.0 KB");
  });
  it("formats megabytes", () => {
    expect(formatBytes(1024 * 1024 * 1.5)).toBe("1.50 MB");
  });
  it("handles null", () => {
    expect(formatBytes(null)).toBe("—");
  });
});

describe("formatDuration", () => {
  it("shows milliseconds below a second", () => {
    expect(formatDuration(250)).toBe("250 ms");
  });
  it("shows seconds above a second", () => {
    expect(formatDuration(1500)).toBe("1.50 s");
  });
  it("handles null", () => {
    expect(formatDuration(null)).toBe("—");
  });
});

describe("formatRelative", () => {
  it("returns just now for very recent", () => {
    expect(formatRelative(new Date().toISOString())).toBe("just now");
  });
  it("returns minutes ago", () => {
    // 5.5 minutes: floor(330s / 60) = 5, tolerant of slow CI clocks.
    const ago = new Date(Date.now() - 5.5 * 60 * 1000).toISOString();
    expect(formatRelative(ago)).toBe("5m ago");
  });
  it("marks future times", () => {
    // 2.5 hours out: floor(8999s / 3600) = 2, tolerant of slow CI clocks.
    const soon = new Date(Date.now() + 2.5 * 3600 * 1000).toISOString();
    expect(formatRelative(soon)).toBe("in 2h");
  });
  it("handles null", () => {
    expect(formatRelative(null)).toBe("—");
  });
});

describe("statusClass", () => {
  it("maps 2xx to success", () => {
    expect(statusClass(200)).toBe("status-2xx");
    expect(statusClass(201)).toBe("status-2xx");
  });
  it("maps 4xx to warning", () => {
    expect(statusClass(429)).toBe("status-4xx");
  });
  it("maps 5xx to error", () => {
    expect(statusClass(500)).toBe("status-5xx");
  });
  it("handles null", () => {
    expect(statusClass(null)).toBe("status-5xx");
  });
});
