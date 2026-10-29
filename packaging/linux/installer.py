# FILE: packaging/linux/installer.py
"""
INTVAL Setup for Linux: a graphical installer wizard (Tk), frozen into one
executable together with the app (packaging/linux/build_linux.sh).

    ./INTVAL-Setup-<version>-linux-x86_64              the wizard
    ./INTVAL-Setup-<version>-linux-x86_64 --silent [--dir PATH] [--no-desktop] [--no-menu] [--launch]

Pages: welcome -> destination folder -> options (desktop shortcut,
applications-menu entry, launch when finished) -> installing -> finished.
It writes an uninstall script into the install folder and a menu entry for it.
Without a display it falls back to the --silent path.

The same program is also the UPDATER: named INTVAL-Update-<version>-... (the
build ships both names) or run with --update, it finds the existing install,
backs up the user's data into backups/<date>-<old>-to-<new>/, replaces only
the program and runs "INTVAL --migrate" (src/migrate.py), which adds the new
version's training companies and settings sections without changing the
user's own. Shortcuts and the uninstaller are left as they are.
"""

import argparse
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
from pathlib import Path

APP = "INTVAL"
FULL = "INTVAL - Intrinsic Value Calculator"
HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
PAYLOAD = HERE / "payload.tar.gz"
VERSION = (HERE / "VERSION").read_text().strip() if (HERE / "VERSION").exists() else "dev"
KEEP = ("agent_settings.yaml", "data/companies.csv", "data/training_universe.csv",
        "data/auto_training_universe.csv", "data/fundamentals_override.csv")  # the user's own copies survive an upgrade
XDG_DATA = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
RECORD = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "intval" / "install.json"
UPDATE = "update" in Path(sys.argv[0]).name.lower() or "--update" in sys.argv
BG, PANEL, FG, MUTED, ACCENT = "#191a1b", "#202122", "#e6e6e6", "#9aa0a6", "#3994bc"
USER_DATA = ("data", "output/intel", "agent_settings.yaml", ".env", "llm_providers.json", "VERSION")  # backed up before an update


def default_dir():
    return Path("/opt/intval") if os.geteuid() == 0 else XDG_DATA / "intval"


def desktop_dir():
    try:
        out = subprocess.run(["xdg-user-dir", "DESKTOP"], capture_output=True, text=True, timeout=5).stdout.strip()
        if out and Path(out).is_dir():
            return Path(out)
    except (OSError, subprocess.SubprocessError):
        pass
    return Path.home() / "Desktop"


def menu_dir():
    return Path("/usr/share/applications") if os.geteuid() == 0 else XDG_DATA / "applications"


def entry(target, name, comment, exe, icon, terminal):
    return (f"[Desktop Entry]\nType=Application\nName={name}\nComment={comment}\n"
            f'Exec="{exe}"\nPath={target}\nIcon={icon}\nTerminal={"true" if terminal else "false"}\n'
            "Categories=Office;Finance;\n")


def find_install():
    """The folder an earlier INTVAL was installed in, or None."""
    import json

    tries = []
    try:
        tries.append(Path(json.loads(RECORD.read_text())["dir"]))
    except (OSError, ValueError, KeyError, TypeError):
        pass
    tries += [default_dir(), Path("/opt/intval"), XDG_DATA / "intval"]
    for d in tries:
        if (d / APP).exists() and (d / "_internal").is_dir():
            return d
    return None


def installed_version(target):
    try:
        return (Path(target) / "VERSION").read_text().strip() or "earlier version"
    except OSError:
        return "earlier version"


def backup(target, old):
    """Copy the user's own files to target/backups/<stamp>-<old>-to-<new>/. -> that folder."""
    import time

    dest = Path(target) / "backups" / f"{time.strftime('%Y%m%d-%H%M%S')}-{old}-to-{VERSION}".replace(" ", "-")
    dest.mkdir(parents=True, exist_ok=True)
    for item in USER_DATA:
        src = Path(target) / item
        if src.is_dir():
            shutil.copytree(src, dest / item, dirs_exist_ok=True)
        elif src.is_file():
            (dest / item).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest / item)
    return dest


def update(target, progress=lambda f, msg: None):
    """Update an existing install in place. -> (program path, backup folder)."""
    target = Path(target)
    old = installed_version(target)
    progress(0.0, "backing up your data")
    saved = backup(target, old)
    exe = install(target, desktop=False, menu=False, progress=lambda f, m: progress(0.05 + 0.85 * f, m), keep_uninstaller=True)
    progress(0.92, "bringing your data up to date")
    subprocess.run([str(exe), "--migrate", "--no-backup", "--previous-version", old], cwd=str(target), check=False,
                   stdin=subprocess.DEVNULL, capture_output=True, timeout=600)
    progress(1.0, "done")
    return exe, saved


def install(target, desktop=True, menu=True, progress=lambda f, msg: None, keep_uninstaller=False):
    """Copy the app into target and add shortcuts. -> path of the program."""
    target = Path(target).expanduser().resolve()
    target.mkdir(parents=True, exist_ok=True)
    if not os.access(target, os.W_OK):
        raise PermissionError(f"cannot write to {target} - choose a folder you own, or run the installer with sudo")
    for old in ("_internal", "web/dist"):  # an upgrade replaces the program wholesale
        shutil.rmtree(target / old, ignore_errors=True)
    with tarfile.open(PAYLOAD, "r:gz") as tar:
        members = tar.getmembers()
        for i, m in enumerate(members, 1):
            if m.name in KEEP and (target / m.name).exists():
                continue
            tar.extract(m, target, filter="tar") if hasattr(tarfile, "data_filter") else tar.extract(m, target)
            if i % 25 == 0 or i == len(members):
                progress(i / len(members), m.name)
    exe = target / APP
    exe.chmod(exe.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    icon = target / "assets" / "intval.png"

    made = []
    app_entry = entry(target, APP, "Open the INTVAL workbench", exe, icon, terminal=True)
    if menu:
        md = menu_dir()
        md.mkdir(parents=True, exist_ok=True)
        (md / "intval.desktop").write_text(app_entry)
        (md / "intval-uninstall.desktop").write_text(entry(target, "Uninstall INTVAL", "Remove INTVAL", target / "uninstall.sh", icon, terminal=True))
        made += [md / "intval.desktop", md / "intval-uninstall.desktop"]
        subprocess.run(["update-desktop-database", str(md)], capture_output=True, check=False) if shutil.which("update-desktop-database") else None
    if desktop:
        dd = desktop_dir()
        dd.mkdir(parents=True, exist_ok=True)
        f = dd / "intval.desktop"
        f.write_text(app_entry)
        f.chmod(0o755)
        if shutil.which("gio"):  # GNOME asks before running an untrusted launcher
            subprocess.run(["gio", "set", str(f), "metadata::trusted", "true"], capture_output=True, check=False)
        made.append(f)

    _record(target)
    if keep_uninstaller and (target / "uninstall.sh").exists():
        progress(1.0, "done")
        return exe

    lines = ["#!/bin/sh", f"# Removes {FULL}.", "set -e"]
    lines += [f'rm -f "{p}"' for p in made]
    lines += [
        f'printf "Also delete your INTVAL data (reports, settings, API keys)? [y/N] "',
        "read ans",
        'case "$ans" in',
        f'  [yY]*) rm -rf "{target}" ;;',
        f'  *) rm -rf "{target}/_internal" "{target}/{APP}" "{target}/web" "{target}/uninstall.sh"; echo "Your data is kept in {target}" ;;',
        "esac",
        f'echo "{APP} removed."',
    ]
    (target / "uninstall.sh").write_text("\n".join(lines) + "\n")
    (target / "uninstall.sh").chmod(0o755)
    progress(1.0, "done")
    return exe


def _record(target):
    import json

    try:
        RECORD.parent.mkdir(parents=True, exist_ok=True)
        RECORD.write_text(json.dumps({"dir": str(target), "version": VERSION}))
    except OSError:
        pass


def launch(exe):
    term = next((t for t in ("x-terminal-emulator", "gnome-terminal", "konsole", "xfce4-terminal", "xterm") if shutil.which(t)), None)
    cmd = [term, "-e", str(exe)] if term and term != "gnome-terminal" else ([term, "--", str(exe)] if term else [str(exe)])
    subprocess.Popen(cmd, cwd=str(exe.parent), start_new_session=True,
                     stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


# ------------------------------------------------------------------ the wizard
def _window(heading):
    """The wizard's window: dark theme, banner, a body and a button row. -> (tk, ttk, messagebox, root, body, nav, title, clear)"""
    import tkinter as tk
    from tkinter import messagebox, ttk

    root = tk.Tk()
    root.title(heading)
    root.geometry("640x470")
    root.resizable(False, False)
    root.configure(bg=BG)
    try:
        root.iconphoto(True, tk.PhotoImage(file=str(HERE / "icon.png")))
    except tk.TclError:
        pass
    style = ttk.Style(root)
    style.theme_use("clam")
    style.configure(".", background=BG, foreground=FG, fieldbackground=PANEL)
    style.configure("TLabel", background=BG, foreground=FG, font=("DejaVu Sans", 10))
    style.configure("Muted.TLabel", foreground=MUTED)
    style.configure("Title.TLabel", font=("DejaVu Sans", 14, "bold"))
    style.configure("TCheckbutton", background=BG, foreground=FG, font=("DejaVu Sans", 10))
    style.map("TCheckbutton", background=[("active", BG)])
    style.configure("TButton", background=PANEL, foreground=FG, padding=(14, 6), borderwidth=1)
    style.map("TButton", background=[("active", "#2a2c2e"), ("disabled", BG)], foreground=[("disabled", "#555")])
    style.configure("Accent.TButton", background=ACCENT, foreground="white")
    style.map("Accent.TButton", background=[("active", "#4aa6cf"), ("disabled", "#2b4a58")])
    style.configure("TEntry", foreground=FG, insertcolor=FG)
    style.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=PANEL, bordercolor=BG)
    try:
        root.banner = tk.PhotoImage(file=str(HERE / "banner.png"))
        tk.Label(root, image=root.banner, bd=0, bg=BG).pack(fill="x")
    except tk.TclError:
        ttk.Label(root, text=f"{APP} Setup", style="Title.TLabel").pack(anchor="w", padx=20, pady=16)
    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True, padx=28, pady=(18, 8))
    nav = tk.Frame(root, bg=BG)
    nav.pack(fill="x", padx=20, pady=(0, 16))

    def clear():
        for w in body.winfo_children():
            w.destroy()

    def title(text, sub=None):
        ttk.Label(body, text=text, style="Title.TLabel").pack(anchor="w")
        if sub:
            ttk.Label(body, text=sub, style="Muted.TLabel", wraplength=580, justify="left").pack(anchor="w", pady=(6, 14))
    return tk, ttk, messagebox, root, body, nav, title, clear


def update_wizard(target):
    """Welcome (what is found, what is kept) -> updating -> finished."""
    import threading as th

    tk, ttk, messagebox, root, body, nav, title, clear = _window(f"Update {FULL} to {VERSION}")
    want_launch = tk.BooleanVar(value=True)
    state = {"exe": None, "saved": None}
    old = installed_version(target)

    def welcome():
        clear()
        title(f"Update INTVAL to {VERSION}",
              f"INTVAL {old} was found in:\n{target}\n\nOnly the program is replaced. Your companies, watchlists, research "
              "history, the agents' memory, training data, settings and API keys stay exactly as they are, and are "
              "backed up first.\n\nClose INTVAL, then click Update.")
        go_btn.config(text="Update", state="normal", command=run)

    def run():
        clear()
        title("Updating…", "Backing up your data, then replacing the program.")
        bar = ttk.Progressbar(body, mode="determinate", maximum=1.0, length=580)
        bar.pack(anchor="w", pady=(6, 6))
        msg = ttk.Label(body, style="Muted.TLabel")
        msg.pack(anchor="w")
        go_btn.config(state="disabled")
        cancel.config(state="disabled")

        def report(f, m):
            root.after(0, lambda: (bar.config(value=f), msg.config(text=m[-80:])))

        def work():
            try:
                state["exe"], state["saved"] = update(target, report)
                root.after(0, done)
            except Exception as e:  # shown to the user; the backup is already on disk
                root.after(0, lambda err=e: (messagebox.showerror("INTVAL Update", f"The update failed:\n\n{err}\n\nYour data is untouched."), root.destroy()))
        th.Thread(target=work, daemon=True).start()

    def done():
        clear()
        title("INTVAL is up to date", f"Updated to {VERSION}. All of your data was kept; a backup of it is in\n{state['saved']}.")
        ttk.Checkbutton(body, text="Open INTVAL now", variable=want_launch).pack(anchor="w", pady=4)
        go_btn.config(text="Finish", state="normal", command=finish)

    def finish():
        if want_launch.get() and state["exe"]:
            launch(state["exe"])
        root.destroy()

    cancel = ttk.Button(nav, text="Cancel", command=root.destroy)
    go_btn = ttk.Button(nav, text="Update", style="Accent.TButton")
    cancel.pack(side="right")
    go_btn.pack(side="right", padx=8)
    welcome()
    root.mainloop()


def wizard():
    from tkinter import filedialog

    tk, ttk, messagebox, root, body, nav, title, clear = _window(f"{FULL} {VERSION} - Setup")
    dest = tk.StringVar(value=str(default_dir()))
    want_desktop, want_menu, want_launch = tk.BooleanVar(value=True), tk.BooleanVar(value=True), tk.BooleanVar(value=True)
    state = {"page": 0, "exe": None}

    def free_space(path):
        p = Path(path).expanduser()
        while not p.exists() and p != p.parent:
            p = p.parent
        try:
            return shutil.disk_usage(p).free
        except OSError:
            return None

    need = sum(m.size for m in tarfile.open(PAYLOAD, "r:gz").getmembers()) if PAYLOAD.exists() else 0

    def page_welcome():
        title(f"Welcome to {APP} {VERSION}",
              "INTVAL values Indian listed companies with eight models and a 23-agent research team, "
              "in a workbench that opens in your browser.\n\nIt runs entirely on this computer. AI providers and "
              "Ollama (local models) are optional and are set up inside the app.\n\nClick Next to continue.")

    def page_folder():
        title("Choose the install folder", "INTVAL keeps its reports and settings in this folder, so pick one you can write to.")
        row = tk.Frame(body, bg=BG)
        row.pack(fill="x")
        e = ttk.Entry(row, textvariable=dest)
        e.pack(side="left", fill="x", expand=True, ipady=4)

        def browse():
            d = filedialog.askdirectory(initialdir=str(Path(dest.get()).expanduser().parent), title="Install INTVAL in")
            if d:
                dest.set(str(Path(d) / "intval") if Path(d).name.lower() != "intval" else d)
        ttk.Button(row, text="Browse…", command=browse).pack(side="left", padx=(8, 0))
        info = ttk.Label(body, style="Muted.TLabel")
        info.pack(anchor="w", pady=(12, 0))

        def refresh(*_):
            free = free_space(dest.get())
            info.config(text=f"Needs {need / 1024**2:,.0f} MB" + (f" · {free / 1024**3:,.1f} GB free there" if free is not None else ""))
        dest.trace_add("write", refresh)
        refresh()

    def page_options():
        title("Choose additional options")
        ttk.Checkbutton(body, text="Create a desktop shortcut", variable=want_desktop).pack(anchor="w", pady=4)
        ttk.Checkbutton(body, text="Add INTVAL to the applications menu", variable=want_menu).pack(anchor="w", pady=4)
        ttk.Checkbutton(body, text="Launch INTVAL when setup finishes", variable=want_launch).pack(anchor="w", pady=4)
        ttk.Label(body, text=f"\nInstalling to:  {Path(dest.get()).expanduser()}", style="Muted.TLabel", wraplength=580).pack(anchor="w")

    def page_install():
        title("Installing…", "Copying INTVAL to your computer. This takes a minute.")
        bar = ttk.Progressbar(body, mode="determinate", maximum=1.0, length=580)
        bar.pack(anchor="w", pady=(6, 6))
        msg = ttk.Label(body, style="Muted.TLabel")
        msg.pack(anchor="w")

        def report(f, m):
            root.after(0, lambda: (bar.config(value=f), msg.config(text=m[-80:])))

        def work():
            try:
                state["exe"] = install(dest.get(), want_desktop.get(), want_menu.get(), report)
                root.after(0, lambda: go(4))
            except Exception as e:  # shown to the user; nothing half-done is left running
                root.after(0, lambda err=e: (messagebox.showerror("INTVAL Setup", f"Installation failed:\n\n{err}"), go(2)))
        threading.Thread(target=work, daemon=True).start()

    def page_done():
        title("INTVAL is installed", f"Installed in {state['exe'].parent}.\n\nOpen it from the applications menu or the "
              "desktop shortcut: a terminal window shows its log, and the workbench opens in your browser. "
              f"To remove it, run {state['exe'].parent / 'uninstall.sh'}.")
        ttk.Checkbutton(body, text="Launch INTVAL now", variable=want_launch).pack(anchor="w", pady=4)

    pages = [page_welcome, page_folder, page_options, page_install, page_done]
    back = ttk.Button(nav, text="< Back", command=lambda: go(state["page"] - 1))
    cancel = ttk.Button(nav, text="Cancel", command=lambda: messagebox.askyesno("INTVAL Setup", "Quit setup?") and root.destroy())
    nxt = ttk.Button(nav, text="Next >", style="Accent.TButton", command=lambda: go(state["page"] + 1))
    cancel.pack(side="right")
    nxt.pack(side="right", padx=8)
    back.pack(side="right")

    def finish():
        if want_launch.get() and state["exe"]:
            launch(state["exe"])
        root.destroy()

    def go(i):
        if state["page"] == 1 and i == 2:
            free = free_space(dest.get())
            if free is not None and free < need:
                messagebox.showerror("INTVAL Setup", "There is not enough free space in that folder.")
                return
        state["page"] = i
        clear()
        pages[i]()
        back.config(state="normal" if i in (1, 2) else "disabled")
        nxt.config(text="Install" if i == 2 else "Finish" if i == 4 else "Next >",
                   state="disabled" if i == 3 else "normal", command=finish if i == 4 else (lambda: go(state["page"] + 1)))
        cancel.config(state="disabled" if i in (3, 4) else "normal")

    go(0)
    root.mainloop()


def main():
    ap = argparse.ArgumentParser(description=f"{FULL} {VERSION} installer")
    ap.add_argument("--silent", action="store_true", help="install without the wizard")
    ap.add_argument("--dir", default=None, help=f"install folder (default {default_dir()})")
    ap.add_argument("--no-desktop", action="store_true", help="no desktop shortcut")
    ap.add_argument("--no-menu", action="store_true", help="no applications-menu entry")
    ap.add_argument("--launch", action="store_true", help="start INTVAL afterwards")
    ap.add_argument("--update", action="store_true", help="update an existing install in place, keeping every bit of data")
    args = ap.parse_args()
    if UPDATE or args.update:
        target = Path(args.dir).expanduser().resolve() if args.dir else find_install()
        if not target or not (target / APP).exists():
            sys.exit("INTVAL is not installed here, so there is nothing to update - run the Setup (INTVAL-Setup-...) instead"
                     + ("" if args.dir else ", or point the updater at the install folder with --dir PATH") + ".")
        if not args.silent and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
            try:
                return update_wizard(target)
            except Exception as e:  # no Tk display after all: fall through to the text update
                print(f"(graphical updater unavailable: {e}; updating in text mode)")
        print(f"Updating INTVAL {installed_version(target)} in {target} to {VERSION} (your data is kept) ...")
        exe, saved = update(target, lambda f, m: print(f"\r  {f:5.0%}  {m[:50]:50}", end="", flush=True))
        print(f"\nDone. A backup of your data is in {saved}\nStart INTVAL with: {exe}")
        if args.launch:
            launch(exe)
        return
    if not args.silent and (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        try:
            return wizard()
        except Exception as e:  # no Tk display after all: fall through to the text install
            print(f"(graphical setup unavailable: {e}; installing in text mode)")
    target = args.dir or str(default_dir())
    print(f"Installing {FULL} {VERSION} to {target} ...")
    exe = install(target, not args.no_desktop, not args.no_menu,
                  lambda f, m: print(f"\r  {f:5.0%}", end="", flush=True))
    print(f"\nDone. Start it with: {exe}\nRemove it with: {exe.parent / 'uninstall.sh'}")
    if args.launch:
        launch(exe)


if __name__ == "__main__":
    main()
