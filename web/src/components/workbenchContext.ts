import { createContext, useContext } from "react";

export interface Toast {
  id: number;
  text: string;
  tone: "info" | "error" | "ok";
}

export interface AppApi {
  /** open the run drawer on a job */
  showJob: (id: string) => void;
  openHelp: () => void;
  toast: (text: string, tone?: Toast["tone"]) => void;
}

export const AppContext = createContext<AppApi>({ showJob: () => {}, openHelp: () => {}, toast: () => {} });

export const useApp = () => useContext(AppContext);
