"""demoforge control panel — double-click, no console, no PowerShell.

The .pyw extension makes Windows run this with pythonw.exe (no console
window). It owns the workbench server and gives you the controls: start/
stop, open the workbench dashboard in your browser, copy the URL, open the
repo folder, and a live request log.
"""

from __future__ import annotations

import os
import sys
import tkinter as tk
import webbrowser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from launcher_core import REPO, WorkbenchServer  # noqa: E402

BG, PANEL, FG, MUTED = "#14171b", "#1d2228", "#e8eaed", "#9aa0a6"
ACCENT, OK, BAD = "#4cc2ff", "#57d9a3", "#ff6b57"


def main() -> None:
    root = tk.Tk()
    root.title("demoforge control panel")
    root.configure(bg=BG)
    root.geometry("520x360")
    root.minsize(460, 300)

    tk.Label(root, text="demoforge", bg=BG, fg=FG,
             font=("Segoe UI", 14, "bold")).pack(anchor="w", padx=16, pady=(14, 0))
    status = tk.Label(root, text="stopped", bg=BG, fg=MUTED, font=("Segoe UI", 10))
    status.pack(anchor="w", padx=16)

    log = tk.Text(root, bg=PANEL, fg=MUTED, height=9, bd=0, padx=10, pady=8,
                  font=("Consolas", 9), state="disabled")
    log.pack(fill="both", expand=True, padx=16, pady=10)

    def log_line(msg: str) -> None:
        def append() -> None:
            log.configure(state="normal")
            log.insert("end", msg + "\n")
            log.see("end")
            log.configure(state="disabled")
        root.after(0, append)  # thread-safe: marshal onto the UI thread

    server = WorkbenchServer(log=log_line)

    bar = tk.Frame(root, bg=BG)
    bar.pack(fill="x", padx=16, pady=(0, 14))

    def styled(parent, text, command, primary=False):
        return tk.Button(
            parent, text=text, command=command, bd=0, padx=13, pady=7,
            bg=ACCENT if primary else PANEL, fg="#06283a" if primary else FG,
            activebackground=ACCENT,
            font=("Segoe UI", 10, "bold" if primary else "normal"),
            cursor="hand2",
        )

    def refresh_status() -> None:
        if server.running:
            status.configure(text=f"running — {server.url}", fg=OK)
            toggle.configure(text="Stop server")
        else:
            status.configure(text="stopped", fg=MUTED)
            toggle.configure(text="Start server")

    def open_dashboard() -> None:
        if not server.running:
            do_start()
        webbrowser.open(server.url)

    def copy_url() -> None:
        root.clipboard_clear()
        root.clipboard_append(server.url if server.running else "")
        log_line(f"copied {server.url}" if server.running else "server not running")

    def open_folder() -> None:
        os.startfile(str(REPO)) if hasattr(os, "startfile") else log_line(str(REPO))

    def do_start() -> None:
        try:
            server.start()
        except Exception as exc:
            status.configure(text=f"failed to start: {exc}", fg=BAD)
            log_line(str(exc))
            return
        refresh_status()

    def do_toggle() -> None:
        server.stop() if server.running else do_start()
        refresh_status()

    def quit_app() -> None:
        server.stop()
        root.destroy()

    styled(bar, "Open Workbench", open_dashboard, primary=True).pack(side="left")
    styled(bar, "Copy URL", copy_url).pack(side="left", padx=(8, 0))
    styled(bar, "Repo Folder", open_folder).pack(side="left", padx=(8, 0))
    toggle = styled(bar, "Start server", do_toggle)
    toggle.pack(side="right")
    root.protocol("WM_DELETE_WINDOW", quit_app)

    do_start()
    refresh_status()
    if server.running:
        root.after(600, lambda: webbrowser.open(server.url))  # auto-open once

    root.mainloop()


if __name__ == "__main__":
    main()
