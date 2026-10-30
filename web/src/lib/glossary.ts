// The in-app glossary (press ?), grouped by topic. `sym` is the short name a
// term goes by in tables and formulas; `where` is the page it is seen on.

export interface Term { term: string; sym?: string; where?: string; text: string }
export interface Topic { id: string; title: string; icon: string; blurb: string; terms: Term[] }

export const GLOSSARY: Topic[] = [
  {
    id: "basics", title: "The basics", icon: "book", blurb: "The words every page uses.",
    terms: [
      { term: "Onboarding", text: "A guided tour of the whole workbench, page by page. Search “onboarding” in the top bar to start it, jump to a chapter, or pick up where you left off." },
      { term: "Intrinsic value", text: "What the business is estimated to be worth from its published accounts, as opposed to what people are paying for the shares today. A gap means either the market knows something the accounts do not, or the shares are mispriced — the app does not say which." },
      { term: "Price", where: "/markets", text: "The latest share price. Live while the market is open (polled every 30 seconds for watched companies); otherwise the last close." },
      { term: "Upside", text: "How far the HYBRID MODEL value sits above (or below, when negative) today's price: value ÷ price − 1." },
      { term: "Margin of safety", text: "The discount to value asked for before buying. It widens as confidence falls and red flags rise." },
      { term: "Buy-below", text: "The HYBRID MODEL value less the margin of safety. A research reference point, not an instruction." },
      { term: "Comparison price", text: "Everything is scored against the close nearest 1 May after each financial year — a month after the accounts appear — so nothing can peek at information it should not have had." },
      { term: "Financial year", sym: "FY", text: "Indian companies report April to March; “2024-25” is the year ending 31 March 2025." },
      { term: "The asterisk", text: "At least one input was estimated from the company's own history or its sector rather than read from a published statement." },
      { term: "A word of caution", text: "Every number here is an estimate from past accounts and public information. Methods disagree for good reasons and can all be wrong at once. Treat the output as a starting point for your own research, not a recommendation." },
    ],
  },
  {
    id: "labels", title: "Research labels", icon: "tag", blurb: "The verdict each company gets after research.",
    terms: [
      { term: "Deep value", text: "The price is well below even the cautious end of the value range, and the evidence holds up." },
      { term: "Undervalued", text: "The price is below the value with a reasonable margin." },
      { term: "Fairly valued", text: "The price sits inside the value range." },
      { term: "Overvalued", text: "The price is above the value range." },
      { term: "Avoid - red flags", text: "Validated red flags outweigh whatever the valuation says." },
      { term: "Insufficient evidence", text: "Too little usable data or too much disagreement to call it." },
    ],
  },
  {
    id: "models", title: "Valuation models", icon: "symbol-operator", blurb: "Each model is a different way of putting a number on a company.",
    terms: [
      { term: "DCF", text: "Discounted cash flow: future free cash flows brought back to today at the cost of capital." },
      { term: "P/E Relative", text: "Earnings per share times the price-to-earnings multiple peers in the sector trade on." },
      { term: "EV/EBITDA", text: "Operating earnings times the peers' enterprise-value multiple, less debt, per share." },
      { term: "Graham Number", text: "Benjamin Graham's cautious ceiling: √(22.5 × earnings per share × book value per share)." },
      { term: "Residual Income", text: "Book value plus the present value of profits earned above the cost of equity. Used for banks and lenders, where cash flow is hard to define." },
      { term: "XGBoost · Random Forest · LightGBM", text: "Tree-based machine-learning models trained on earlier years' accounts and prices, never on the year they value." },
      { term: "MLP Neural Network", text: "A small neural network trained the same way as the tree models." },
      { term: "Ensemble", text: "The calculator's earlier blend (formerly “Hybrid”): improved versions of every model weighted by past accuracy. Its components feed the HYBRID MODEL." },
      { term: "HYBRID MODEL", sym: "HM", where: "/studio", text: "The headline value: six lenses, each calibrated against its own earlier misses, blended by company type, adjusted for quality and governance, then run through bull, base and bear scenarios. Every constant is editable in the Studio." },
    ],
  },
  {
    id: "parameters", title: "HYBRID MODEL parameters", icon: "settings", blurb: "The dials behind the headline value, all editable in the Studio.",
    terms: [
      { term: "Lenses", text: "The six views the HYBRID MODEL blends: cash flow (three-stage DCF), earnings power (no-growth value, NOPAT ÷ WACC), asset (book × justified P/B), market (peer P/E and EV/EBITDA), conservative (Graham Number) and learning (machine-learning consensus)." },
      { term: "Lens weights", text: "How much each lens counts, set by company type (lender, asset-heavy, growth…) and by how well it has priced before." },
      { term: "Cost of equity", sym: "k", text: "The yearly return shareholders need: CAPM (risk-free rate + beta × market premium) plus premia for size, governance and the agents' risk findings." },
      { term: "Premia", text: "Additions to the cost of equity for specific risks the research turned up." },
      { term: "Growth", sym: "g", text: "Growth from the accounts, tilted up or down by research findings, fading to a terminal rate." },
      { term: "Terminal growth", text: "The rate the business is assumed to grow at forever after the explicit forecast years." },
      { term: "Growth-credibility gate", text: "Growth is only paid for when returns on capital earn it. If too much of the cash-flow lens comes from future growth rather than today's earning power, the lens is cut back; a wider moat allows more." },
      { term: "PVGO", text: "Present value of growth opportunities: the part of a value that depends on growth rather than today's earnings." },
      { term: "Quality multiplier", text: "A small adjustment (typically within ±10%) for return on capital, earnings quality and governance." },
      { term: "Calibration", text: "Each lens's typical miss against the 1-May price in earlier years is removed, and lenses that have priced well count for more. A year never learns from itself." },
      { term: "Scenarios", text: "Bull, base and bear values, each with a probability; their weighted sum is the HYBRID MODEL value." },
      { term: "Sigma", sym: "σ", text: "The spread of the lenses around the blend — the source of the value range." },
      { term: "Confidence", text: "The modelled chance the price lands within 20% of the value, from the lenses' disagreement — blended, after research, with evidence coverage, validation and the team's agreement." },
    ],
  },
  {
    id: "accuracy", title: "Accuracy metrics", icon: "graph", blurb: "How Model Performance scores every model against the market.",
    terms: [
      { term: "MedAPE", sym: "MedAPE %", where: "/performance", text: "Median absolute percentage error: the typical miss against the comparison price, ignoring direction. Lower is better." },
      { term: "Hit rate", sym: "Hit ±20%", text: "Share of company-years where the value landed within 20% of the price." },
      { term: "Bias", sym: "Bias %", text: "Average signed error. Positive means the model tends to value above the price." },
      { term: "Spearman", text: "Rank correlation between values and prices: does the model order companies the way the market does? 1 is perfect." },
      { term: "Win rate", text: "How often a model was the closest to the price among all models that answered for that company-year." },
      { term: "N", text: "How many company-years a figure is based on." },
      { term: "Excluded", text: "Company-years left out of scoring because an input was missing or implausible, with the reason." },
    ],
  },
  {
    id: "forecasts", title: "Model forecasts", icon: "graph-line", blurb: "The predicted price paths on each company's profile.",
    terms: [
      { term: "Forecast path", text: "Starts at today's price and moves toward a model's value as fast as the market has historically followed that model, while the value itself grows at the company's long-run growth rate." },
      { term: "Gap closed per year", sym: "β", text: "Learned from the valuation report: the share of the gap between a model's value and the price that next year's price closed, across every company." },
      { term: "Spread", text: "How far prices strayed from that line in the past; the range shown when you hover a forecast." },
      { term: "Conviction", text: "0–100, how strongly a model believes its prediction: how well its gaps foretold the next move (35%), its hit rate (25%), how steady its view of this company has been (20%) and how close it sits to the other models (20%)." },
      { term: "Horizons", text: "1 week, 1 month, 1 quarter, 6 months, 1 year, 3 and 5 years. The further out, the wider the range." },
    ],
  },
  {
    id: "workforce", title: "Research workforce", icon: "organization", blurb: "The agents that research each company.",
    terms: [
      { term: "Agents", where: "/agents", text: "Specialist analysts (news credibility, forensics, insider activity, short-seller research and more), each reading its own sources and reporting findings with citations." },
      { term: "Teams", text: "CMD command, NWS market news, EQR equity research, IGR industry & geopolitics, MAO market activity & ownership, IRV investment review. Each team has a lead who summarises it." },
      { term: "Lead score", text: "Each lead's overall reading for a company, from −1 (strongly negative) to +1 (strongly positive)." },
      { term: "Research score", text: "The team's combined reading, which tilts growth, premia and confidence." },
      { term: "Red flag", text: "A serious concern that survived the review team's validation — accounting, governance or legal." },
      { term: "Verdict", text: "The chief agent's final call: label, value, range and a cited research note." },
      { term: "Quick sweep", text: "News and market agents only: fast and cheap, for a daily check." },
      { term: "Full research", text: "Every agent, including fundamentals, forensics and the bull and bear cases." },
      { term: "Research Room", where: "/agents/chat", text: "The workforce's chat. Agents post as they work; you can ask them questions or give commands like /research." },
      { term: "Agent Network", where: "/agents/network", text: "A live map of who is talking to whom, with replay of past runs." },
      { term: "Auto-start", text: "Lets the workforce begin a run when the web app starts, on the schedule you set." },
    ],
  },
  {
    id: "watchlists", title: "Watchlists & data", icon: "eye", blurb: "Where companies come from and how they are followed.",
    terms: [
      { term: "Watchlists", where: "/watchlist", text: "Your named lists of companies, tracked live. Each company opens to its full analysis: live chart and forecast, research, valuation and model forecasts." },
      { term: "Live forecast", text: "A company's likely price in 15 minutes, an hour, a day … five years: a median with a band holding 8 in 10 outcomes, recomputed with every price update. Short horizons follow its own volatility and recent moves; long ones are pulled towards the HYBRID MODEL value." },
      { term: "Watchlist library", where: "/watchlist", text: "Named lists of companies, each with a description and colour. A company can be on several lists; up to 100 companies are tracked across all of them." },
      { term: "Focus", text: "Choose a watchlist in the top bar and the Command Center, Model Performance and the research workforce show only its companies. “All companies” brings everything back." },
      { term: "Tracker", text: "While the market is open, polls watched companies every 30 seconds, stores every minute bar on this computer, re-values every valued company at the live price, and raises your alerts." },
      { term: "Ticker", text: "NSE symbol plus .NS (BSE: .BO), for example TCS.NS." },
    ],
  },
  {
    id: "settings", title: "AI & exports", icon: "plug", blurb: "Language models and getting data out.",
    terms: [
      { term: "AI provider", where: "/configuration", text: "Any service that runs language models: OpenAI-style APIs (Groq, Gemini, OpenRouter, Mistral, local Ollama…) or Anthropic. Add as many as you like." },
      { term: "Several keys", text: "Each provider can hold several API keys. When one hits a rate limit the next is used; a rejected key is skipped." },
      { term: "Fast and smart models", text: "Each provider names a quick model for routine reading and a stronger one for judgement calls." },
      { term: "Routes", text: "The order providers are tried in, so a failing service hands over to the next." },
      { term: "Export", text: "Every export button offers the formats that suit what it holds — data as Excel, CSV, Word, Markdown or PDF; charts as PNG, PDF or Word; whole pages as PDF or Word — with a short editor before the file is saved." },
    ],
  },
];
