import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { createBrowserRouter, Navigate, RouterProvider, useParams } from "react-router-dom";
import "@fontsource-variable/inter";
import "@fontsource/jetbrains-mono/400.css";
import "@fontsource/jetbrains-mono/500.css";
import "@vscode/codicons/dist/codicon.css";
import "./styles/system.css";
import "./styles/views.css";
import "./styles/agents.css";
import "./styles/network.css";
import { Shell } from "./components/Shell";
import { Empty, Panel } from "./components/ui";
import { CommandCenter } from "./views/CommandCenter";
import { CompanyByName, CompanyInList } from "./views/Profile";
import { Studio } from "./views/Studio";
import { Performance } from "./views/Performance";
import { Operations } from "./views/Operations";
import { Configuration } from "./views/Configuration";
import { Markets } from "./views/Markets";
import { WatchlistDetail } from "./views/Watchlist";
import { Watchlist } from "./views/WatchlistLibrary";
import { AgentChat } from "./views/AgentChat";
import { AgentNetwork } from "./views/AgentNetwork";
import { AgentsOverview } from "./views/AgentsOverview";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1, staleTime: 15_000, refetchOnWindowFocus: true } } });

function OldCompany() {
  const { company = "" } = useParams();
  return <Navigate to={`/company/${company}`} replace />;
}

const NotFound = (
  <div className="page"><Panel><Empty icon="question" title="Page not found"><a href="/">Go to the Command Center</a></Empty></Panel></div>
);

const router = createBrowserRouter([
  {
    path: "/",
    element: <Shell />,
    errorElement: NotFound,
    children: [
      { index: true, element: <CommandCenter /> },
      { path: "markets", element: <Markets /> },
      { path: "watchlist", element: <Watchlist /> },
      { path: "watchlist/:id", element: <WatchlistDetail /> },
      { path: "watchlist/:id/:ticker", element: <CompanyInList /> },
      { path: "company/:company", element: <CompanyByName /> },
      { path: "agents/network", element: <AgentNetwork /> },
      { path: "agents/chat", element: <AgentChat /> },
      { path: "agents", element: <AgentsOverview /> },
      { path: "studio", element: <Studio /> },
      { path: "performance", element: <Performance /> },
      { path: "operations", element: <Operations /> },
      { path: "configuration", element: <Configuration /> },
      // addresses from earlier versions of the app
      // Coverage and Universe are folded into the watchlists
      { path: "coverage", element: <Navigate to="/watchlist" replace /> },
      { path: "coverage/:company", element: <OldCompany /> },
      { path: "universe", element: <Navigate to="/watchlist" replace /> },
      { path: "research", element: <Navigate to="/watchlist" replace /> },
      { path: "research/:company", element: <OldCompany /> },
      { path: "intel/:company", element: <OldCompany /> },
      { path: "lab", element: <Navigate to="/studio" replace /> },
      { path: "models", element: <Navigate to="/performance" replace /> },
      { path: "learning", element: <Navigate to="/performance?tab=training" replace /> },
      { path: "run", element: <Navigate to="/operations" replace /> },
      { path: "companies", element: <Navigate to="/watchlist" replace /> },
      { path: "settings", element: <Navigate to="/configuration" replace /> },
      { path: "*", element: NotFound },
    ],
  },
]);

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={queryClient}><RouterProvider router={router} /></QueryClientProvider>
  </React.StrictMode>,
);
