import { useStartJob, useStatus } from "../lib/hooks";
import { Icon } from "./ui";
import { useApp } from "./workbenchContext";

/** Starts a job and opens its live monitor; disabled while another job runs. */
export function RunButton({
  kind,
  options,
  label,
  icon = "play",
  secondary,
  small,
}: {
  kind: string;
  options?: Record<string, unknown>;
  label: string;
  icon?: string;
  secondary?: boolean;
  small?: boolean;
}) {
  const start = useStartJob();
  const status = useStatus();
  const app = useApp();
  const busy = !!status.data?.active_job || start.isPending;
  return (
    <button
      className={`btn ${secondary ? "secondary" : ""} ${small ? "sm" : ""}`}
      disabled={busy}
      title={busy ? "Another run is in progress" : undefined}
      onClick={() =>
        start.mutate(
          { kind, options },
          {
            onSuccess: (j) => app.showJob(j.id),
            onError: (e) => app.toast(e instanceof Error ? e.message : String(e), "error"),
          },
        )
      }
    >
      <Icon name={start.isPending ? "loading" : icon} className={`sm ${start.isPending ? "spin" : ""}`} />
      {label}
    </button>
  );
}
