import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api } from "../api/client";
import { PAPER_BANNER, PaperBadge } from "../components/PaperBadge";
import { Layout } from "../components/Layout";
import { money, pct, rr } from "../lib/format";

describe("format helpers", () => {
  it("formats INR and percentages", () => {
    expect(money(100000, 0)).toBe("₹1,00,000");
    expect(money(null)).toBe("—");
    expect(pct(1.234)).toBe("+1.23%");
    expect(pct(-0.5)).toBe("-0.50%");
  });
  it("mirrors the reward:risk formula", () => {
    expect(rr(100, 95, 115)).toBe(3);
    expect(Number.isNaN(rr(100, 101, 120))).toBe(true);
  });
});

describe("paper-only indicator", () => {
  it("renders the exact banner text", () => {
    render(<PaperBadge />);
    expect(screen.getByRole("status").textContent).toContain("PAPER TRADING ONLY — NO LIVE ORDERS");
    expect(PAPER_BANNER).toBe("PAPER TRADING ONLY — NO LIVE ORDERS");
  });
});

describe("api client", () => {
  afterEach(() => vi.restoreAllMocks());
  it("surfaces backend error lists", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ detail: { errors: ["Allocation exceeds available paper cash"] } }), { status: 422 }));
    await expect(api("/api/d1/trades", { body: {} })).rejects.toThrow("Allocation exceeds available paper cash");
  });
  it("reports an unreachable backend honestly", async () => {
    vi.spyOn(globalThis, "fetch").mockRejectedValue(new TypeError("Failed to fetch"));
    const err = await api("/api/health").catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err.message).toContain("Backend unreachable");
  });
});

describe("layout", () => {
  beforeEach(() => {
    vi.spyOn(globalThis, "fetch").mockImplementation(async (url: any) => {
      const u = String(url);
      const body = u.includes("/api/system/status")
        ? { banner: PAPER_BANNER, dhan: { status: "NOT_CONFIGURED" }, market_data: { state: "NO_DATA" }, market_open: false }
        : { accounts: [{ code: "D1_MTF", available_cash: 100000 }] };
      return new Response(JSON.stringify(body), { status: 200 });
    });
  });
  afterEach(() => vi.restoreAllMocks());
  it("always shows the paper banner and real connection status", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <MemoryRouter><Layout /></MemoryRouter>
      </QueryClientProvider>,
    );
    expect(screen.getByRole("status").textContent).toContain("NO LIVE ORDERS");
    await waitFor(() => expect(screen.getAllByText("NOT CONFIGURED").length).toBeGreaterThan(0));
  });
});
