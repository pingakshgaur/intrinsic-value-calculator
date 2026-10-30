// The onboarding tour: chapters of steps that walk across the app. Each step
// may open a page (`route`) and point at something on it (`target`, a CSS
// selector, or a panel's title as "panel:Title"). A step whose target cannot be
// found still shows, centred, so the tour never stalls on an empty page.
import { ReactNode } from "react";

/** `company`: the first researched company, already slugged for a URL */
export interface TourCtx { company: string | null }

export interface TourStep {
  route?: string | ((c: TourCtx) => string | null);
  target?: string;
  title: string;
  body: ReactNode;
  /** a small nudge to try something while the step is open */
  try?: ReactNode;
  side?: "auto" | "right" | "left" | "bottom" | "top";
}

export interface Chapter { id: string; title: string; icon: string; color: string; blurb: string; steps: TourStep[] }

const K = ({ children }: { children: ReactNode }) => <kbd>{children}</kbd>;
const company = (path: string) => (c: TourCtx) => (c.company ? `/company/${c.company}${path}` : null);

export const CHAPTERS: Chapter[] = [
  {
    id: "frame", title: "Find your way", icon: "compass", color: "#57A3F8", blurb: "The frame around every page",
    steps: [
      { route: "/", target: ".sidebar", side: "right", title: "The sidebar",
        body: <>Every page lives here, in three groups: <b>Analysis</b> (the dashboard, markets, watchlists, the Studio), the <b>Research workforce</b> (the AI agents) and <b>Operations</b>, which runs jobs, scores the models and holds the settings.</>,
        try: <>Press <K>Alt</K> + <K>1</K>…<K>9</K> to jump between pages, or <K>Ctrl</K> + <K>\</K> to fold the sidebar.</> },
      { target: ".sb-foot", side: "right", title: "System status",
        body: <>A live health check: is the local server up, how many AI providers have working keys, when the valuation report and the last research were made, and whether the market tracker is running. Click it for the details.</> },
      { target: ".tape", side: "bottom", title: "The market tape",
        body: <>Nifty 50, India VIX, the rupee, oil, US yields and gold, each with its one-month change. Hover any of them for the 1-year move.</> },
      { target: ".scope-btn", side: "bottom", title: "Focus on a watchlist",
        body: <>Pick one of your watchlists here and the whole app narrows to its companies: the Command Center, Model Performance and the agents. <b>All companies</b> brings everything back.</> },
      { target: ".cmdk", side: "bottom", title: "Search everything",
        body: <>Companies, pages and actions in one box. Type a company to open its profile, its live chart or the Studio; type <i>research</i> or <i>valuation</i> to start a run. This tour lives here too: search <b>onboarding</b> any time.</>,
        try: <><K>Ctrl</K> + <K>K</K> opens it from anywhere.</> },
      { target: ".topbar .tool[title^='Glossary']", side: "bottom", title: "The glossary",
        body: <>Seventy-odd terms in nine topics, searchable: the valuation models, the HYBRID MODEL's dials, accuracy metrics, research labels, the agents. Press <K>?</K> on any page.</> },
      { target: ".runchip", side: "bottom", title: "Runs",
        body: <>Valuation reports, research runs and data jobs run in the background. This chip shows the one in progress; click it for the live log and recent runs.</> },
      { target: ".themer", side: "bottom", title: "Light or dark",
        body: <>Switch themes here. Every chart, export and the agent map follow along.</> },
    ],
  },
  {
    id: "dashboard", title: "Dashboard", icon: "dashboard", color: "#4EC9B0", blurb: "Everything worth watching, on one page",
    steps: [
      { route: "/dashboard", target: ".dash-grid", side: "top", title: "Your dashboard",
        body: <>The market, your watchlists, the buy zone, alerts, the agents' best ideas and red flags, running jobs and how accurate the models are — each widget links to the page with the detail.</> },
      { target: ".ph .acts", side: "bottom", title: "Make it yours",
        body: <><b>Customise</b> shows, hides and reorders the widgets; this browser remembers the layout. Pick a watchlist in the top bar and every widget narrows to its companies.</> },
    ],
  },
  {
    id: "command", title: "Command Center", icon: "pulse", color: "#AD80D7", blurb: "Research verdicts at a glance",
    steps: [
      { route: "/", target: ".page > .band", side: "bottom", title: "The headline numbers",
        body: <>How many companies are researched, how many sit below or above their value, the median upside, red flags and how accurate the HYBRID MODEL has been against the market.</> },
      { target: "panel:Research map", title: "Research map",
        body: <>Every researched company as a tile: size is market value, colour is upside to the HYBRID MODEL value. Click a tile to open the company.</> },
      { target: "panel:Signals", title: "Signals",
        body: <>What changed since the last run: new red flags, label changes and moves in value, newest first.</> },
      { target: "panel:Upside vs confidence", title: "Upside against confidence",
        body: <>The interesting corner is top-right: a big gap to value <i>and</i> a model that is confident about it.</> },
      { target: "panel:Model leaderboard", title: "Which models price best",
        body: <>Every valuation model ranked by its typical miss against the market price. Model Performance has the full story.</> },
    ],
  },
  {
    id: "markets", title: "Markets & watchlists", icon: "graph", color: "#86CF86", blurb: "Live prices and the lists you follow",
    steps: [
      { route: "/markets", target: ".radar", side: "bottom", title: "Research radar",
        body: <>What deserves a look right now, refreshed with every price update: companies that have just dropped under their HYBRID MODEL buy-below price, the biggest gaps to value, what the live forecast leans towards for today, and today's unusual moves. Click one to chart it below.</> },
      { target: ".mkt", title: "Charts and the scanner",
        body: <>Candles or lines from one day to the full history, with the HYBRID MODEL value and buy-below drawn on the chart. The scanner finds gainers, losers, volume spikes, 52-week extremes, RSI extremes, and valued companies trading below their buy-below price.</>,
        try: <>Every chart has an <b>Export</b> menu: PNG, PDF or Word.</> },
      { route: "/watchlist", target: ".wl-lib", title: "Your watchlist library",
        body: <>Named lists, each with a description and colour: a theme, a sector, a strategy, a shortlist. Cards show today's movers and who is in the buy zone. A company can sit on several lists.</> },
      { target: ".ph .acts", side: "bottom", title: "Make a list",
        body: <>Fill it as you create it, or later with <b>Add companies</b>: search for names, type an index (NIFTY 50, NIFTY 500, Bank Nifty, Large cap…) to take all of it, pick whole sectors, import a spreadsheet (Excel, CSV or pasted text), or copy another list. Open any list for live tiles, search, charts, forecasts, price alerts and notes, and research it in one click.</> },
    ],
  },
  {
    id: "coverage", title: "Company analysis", icon: "go-to-file", color: "#E0B97F", blurb: "Everything on one company",
    steps: [
      { route: company(""), target: ".profile-bar", side: "bottom", title: "A company profile",
        body: <>Open any company on a watchlist with <b>Full analysis</b>. The sticky bar keeps the essentials in view: the live price, the HYBRID MODEL value, upside, buy-below and confidence. <b>Studio</b> opens the valuation to tinker with; <b>Re-check</b> sends the agents back to it.</> },
      { target: "nav.anchors", side: "right", title: "Sections",
        body: <>Live (chart, forecast from 15 minutes to 5 years, alerts), then the research: summary, valuation, model forecasts, drivers and risk, the agents' evidence, bull versus bear and history. The index follows you as you scroll.</> },
      { target: "#summary", title: "The research note",
        body: <>The chief agent's note, with every point traced to a cited finding, and each research lead's score from −1 to +1.</> },
      { target: "#forecast", title: "Model forecasts",
        body: <>Every model's predicted price over days, months and years, learned from how fast prices have followed that model in the past. <b>Conviction</b> (0–100) says how strongly each model believes its own prediction.</>,
        try: <>Switch between Days, Months and Years, and hover a conviction bar for what it is made of.</> },
      { target: "#cases", title: "Bull against bear",
        body: <>Two agents argue opposite sides with evidence; their probabilities set the scenario weights behind the value.</> },
    ],
  },
  {
    id: "studio", title: "HYBRID MODEL Studio", icon: "beaker", color: "#4EC9B0", blurb: "Tune the model and see the effect",
    steps: [
      { route: "/studio", target: ".studio > section:first-child", side: "right", title: "Every dial",
        body: <>Every constant of the HYBRID MODEL as a tree: discount rates, growth, the lenses and their weights, quality, scenarios, margins of safety. Search it, change a value, reset one, or load the shipped defaults.</> },
      { target: ".studio .canvas", title: "The live canvas",
        body: <>Change a dial and the value, its range, the bridge from each lens and the lens contributions update instantly for the company you pick.</> },
      { target: ".studio .insp-pane", side: "left", title: "The inspector",
        body: <>Sensitivity to each input, the list of your changes, and the raw inputs. Nothing is saved until you press <b>Commit</b>; <b>Discard</b> drops your edits. Named scenario sets and a portfolio view let you compare across companies.</> },
    ],
  },
  {
    id: "agents", title: "The research workforce", icon: "organization", color: "#EF8773", blurb: "23 AI agents in six teams",
    steps: [
      { route: "/agents", target: ".page > .wo-figs", side: "bottom", title: "The workforce",
        body: <>Twenty-three specialist agents in six teams read news, filings, prices, ownership and more, then argue a verdict for each company. These figures show the latest run — companies researched, verdicts, red flags — counted on the watchlist picked in the top bar.</> },
      { target: ".wo-teams", title: "Teams and agents",
        body: <>News, equity research, industry &amp; geopolitics, market activity &amp; ownership, and review, led by a chief. Click any agent for its profile and its settings: stance, weight, AI use and standing instructions.</> },
      { target: ".ph .acts", side: "bottom", title: "Starting research",
        body: <><b>Research</b> starts a run on every watchlist or on the one you pick — a <b>quick sweep</b> (news and markets) or <b>full research</b> (every agent). <b>Auto-start</b> sets whether the workforce begins by itself when the app opens.</> },
      { route: "/agents/network", target: ".net-body", title: "Agent Network",
        body: <>The agents as a live map. Pulses travel along the lines as they hand work to each other; replay any past run at any speed.</> },
      { target: ".net-rail", side: "right", title: "Map tools",
        body: <>Select, pan, connect, annotate and focus. Zoom, fit, and the mini-map live here too.</>,
        try: <>Press <K>M</K> for the mini-map: click it to glide there, or drag its box.</> },
      { target: ".net-top", side: "bottom", title: "Views and layers",
        body: <>Switch between live and past runs, save views, and turn layers on or off: traffic, labels, the inspector and more.</> },
      { route: "/agents/chat", target: ".rr-side", side: "right", title: "The Research Room",
        body: <>The agents' chat: a channel per team, direct exchanges, and who is typing right now.</> },
      { target: ".rr-main textarea", side: "top", title: "Talk to them",
        body: <>Ask a question, give an instruction (“focus on debt”) or a task (“re-check HAL”). Mention <b>@EQR-02</b> to address one agent, or type <b>/</b> for commands.</> },
    ],
  },
  {
    id: "models", title: "Model Performance", icon: "graph-line", color: "#CD861A", blurb: "How well it all works",
    steps: [
      { route: "/performance", target: ".page > .tabs", side: "bottom", title: "Model Performance",
        body: <>Every model scored against the market for every financial year: the typical miss, the hit rate within ±20%, bias and rank correlation. <b>Sectors</b> shows which model suits each sector and what each model forecasts for it; <b>Learning pool</b> shows every company the models learn from and whether more of it helps.</> },
      { route: "/performance?tab=sectors", target: ".page > .band", side: "bottom", title: "Sectors",
        body: <>The most accurate model in every sector, each model's view of every sector against today's price with a one-year projection, and how each sector splits into companies below, near and above value.</> },
    ],
  },
  {
    id: "ops", title: "Operations & settings", icon: "server-process", color: "#C586C0", blurb: "Runs, keys and preferences",
    steps: [
      { route: "/operations", target: ".op-new", side: "bottom", title: "Operations",
        body: <>Start any job from one row: the valuation report, research, a learning-pool refresh or a data check — on every watchlist or on one of them. The job detail below shows its stages and full log as it runs; recent jobs sit under it.</> },
      { route: "/configuration", target: ".cfg-nav", side: "right", title: "Configuration",
        body: <>Run settings, data sources (Yahoo, Screener.in, NSE, BSE and key-based providers, in the order you trust them), AI providers, the research agents, notifications, macro inputs and the raw settings file.</> },
      { route: "/configuration?section=ai", target: ".cfg .col", side: "left", title: "AI providers",
        body: <>Connect any language-model service: OpenAI-style APIs like Groq, Gemini or OpenRouter, Anthropic's Claude, or a local Ollama. Give each provider several keys; when one hits its limit the next takes over. Pick models from the live list and press <b>Test</b>.</> },
    ],
  },
  {
    id: "tips", title: "Power tips", icon: "zap", color: "#9CDCFE", blurb: "Small things that save time",
    steps: [
      { title: "Keyboard first",
        body: <><K>Ctrl</K>+<K>K</K> search · <K>Alt</K>+<K>1–9</K> pages · <K>?</K> glossary · <K>Ctrl</K>+<K>\</K> sidebar · <K>↑</K><K>↓</K> rows in grids · <K>Esc</K> closes anything.</> },
      { title: "Export anything",
        body: <>Every panel, grid, chart and page has an <b>Export</b> menu with the formats that suit it, and a short editor to set the title, columns, page size and colours before the file is saved.</> },
      { title: "A word of caution",
        body: <>Every number here is an estimate from past accounts and public information. Methods disagree for good reasons and can all be wrong at once. Treat it as a starting point for your own research, not a recommendation.</> },
    ],
  },
];

export const TOUR_STEPS = CHAPTERS.flatMap((c, ci) => c.steps.map((s, si) => ({ ...s, chapter: ci, inChapter: si })));
