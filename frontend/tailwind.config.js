/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: { DEFAULT: "#0B0D0C", panel: "#111513", raised: "#161B18", line: "rgba(245,247,245,0.08)" },
        fg: { DEFAULT: "#F5F7F5", muted: "#A3ADA6", faint: "#6B756E" },
        neon: { DEFAULT: "#D9FF00", dim: "rgba(217,255,0,0.12)" },
        up: { DEFAULT: "#4ADE80", dim: "rgba(74,222,128,0.12)" },
        down: { DEFAULT: "#E5736B", dim: "rgba(229,115,107,0.12)" },
        warn: { DEFAULT: "#E7C26A", dim: "rgba(231,194,106,0.12)" },
      },
      fontFamily: {
        sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "sans-serif"],
        mono: ["JetBrains Mono", "ui-monospace", "SFMono-Regular", "Menlo", "monospace"],
      },
      borderRadius: { xl: "14px" },
      boxShadow: { panel: "0 1px 0 rgba(255,255,255,0.03) inset, 0 12px 32px -16px rgba(0,0,0,0.6)", glow: "0 0 0 1px rgba(217,255,0,0.5), 0 0 18px -6px rgba(217,255,0,0.45)" },
    },
  },
  plugins: [],
};
