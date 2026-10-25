// Research labels and the colour each one wears everywhere in the app.

export const LABELS = [
  "Deep value",
  "Undervalued",
  "Fairly valued",
  "Overvalued",
  "Avoid - red flags",
  "Insufficient evidence",
] as const;

export const LABEL_COLOR: Record<string, string> = {
  "Deep value": "var(--c-green)",
  Undervalued: "#a9d9a9",
  "Fairly valued": "var(--c-blue)",
  Overvalued: "var(--c-yellow)",
  "Avoid - red flags": "var(--c-red)",
  "Insufficient evidence": "var(--fg-muted)",
};

// Raw hex for SVG fills where CSS variables are awkward.
export const LABEL_HEX: Record<string, string> = {
  "Deep value": "#86CF86",
  Undervalued: "#A9D9A9",
  "Fairly valued": "#57A3F8",
  Overvalued: "#E0B97F",
  "Avoid - red flags": "#EF8773",
  "Insufficient evidence": "#8C8C8C",
};

export const SERIES = ["#57A3F8", "#86CF86", "#E0B97F", "#AD80D7", "#EF8773", "#CD861A", "#4EC9B0", "#C586C0", "#9CDCFE", "#D7BA7D", "#B5CEA8"];

export const LEAD_SHORT: Record<string, string> = {
  market_news_lead: "News",
  equity_research_lead: "Equity",
  industry_geo_lead: "Industry & Geo",
  market_activity_lead: "Market & Ownership",
  review_lead: "Review",
};

export const LEAD_ICON: Record<string, string> = {
  market_news_lead: "megaphone",
  equity_research_lead: "graph",
  industry_geo_lead: "globe",
  market_activity_lead: "pulse",
  review_lead: "law",
};

export const AGENT_NAME: Record<string, string> = {
  research_analyst: "Research Analyst",
  news_credibility_analyst: "News Credibility",
  sentiment_analyst: "Sentiment",
  stock_movement_analyst: "Stock Movement",
  market_impact_analyst: "Market Impact",
  fundamental_research_analyst: "Fundamental Research",
  financial_forensics_analyst: "Financial Forensics",
  pre_earnings_analyst: "Pre-Earnings Intelligence",
  industry_research_analyst: "Industry Research",
  geopolitical_risk_analyst: "Geopolitical Risk",
  market_volume_analyst: "Market Volume",
  insider_activity_analyst: "Insider Activity",
  fund_holdings_analyst: "Fund Holdings",
  short_seller_analyst: "Short-Seller Research",
  research_validation_analyst: "Research Validation",
  bull_case_analyst: "Bull Case",
  bear_case_analyst: "Bear Case",
};

export const LENSES = ["cash_flow", "earnings_power", "asset", "market", "conservative", "learning"] as const;

export const LENS_NAME: Record<string, string> = {
  cash_flow: "Cash flow",
  earnings_power: "Earnings power",
  asset: "Asset",
  market: "Market",
  conservative: "Conservative",
  learning: "Learning",
};

export const LENS_HINT: Record<string, string> = {
  cash_flow: "Three-stage DCF (lenders: residual income) at the agent-adjusted k and g",
  earnings_power: "What it is worth if it never grows: NOPAT ÷ WACC",
  asset: "Book value × justified P/B, (ROE − g) ÷ (k − g)",
  market: "Peer-regression P/E and EV/EBITDA",
  conservative: "Graham Number",
  learning: "Machine-learning consensus",
};

export const LENS_COLOR: Record<string, string> = {
  cash_flow: "#57A3F8",
  earnings_power: "#4EC9B0",
  asset: "#E0B97F",
  market: "#86CF86",
  conservative: "#CD861A",
  learning: "#AD80D7",
};

export const HM = "HYBRID MODEL";
export const HM_COLOR = "#AD80D7";

export const scoreColor =(s: number | null | undefined) =>
  s == null ? "var(--fg-muted)" : s > 0.1 ? "var(--c-green)" : s < -0.1 ? "var(--c-red)" : "var(--fg-muted)";
