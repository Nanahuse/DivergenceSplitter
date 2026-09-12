"""Small native Windows entry point for the AutoSplit converter."""

from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

from autosplit_converter import analyze, convert


def main() -> int:
    root = tk.Tk()
    root.title("AutoSplit → DivergenceSplitter")
    root.geometry("720x300")
    settings = tk.StringVar()
    output = tk.StringVar()
    report = tk.StringVar(value="Select settings.toml to analyze the profile.")

    def choose_settings() -> None:
        value = filedialog.askopenfilename(
            title="AutoSplit settings.toml",
            filetypes=(("TOML files", "*.toml"), ("All files", "*.*")),
        )
        if not value:
            return
        settings.set(value)
        try:
            analysis = analyze(value)
            report.set(
                f"Start: {analysis.start.source_path.name if analysis.start else 'none'}\n"
                f"Reset: {analysis.reset.source_path.name if analysis.reset else 'none'}\n"
                f"Split files: {len(analysis.images)}"
            )
        except ValueError as error:
            report.set(f"Analysis failed: {error}")

    def choose_output() -> None:
        value = filedialog.asksaveasfilename(
            title="Save Scenario YAML",
            defaultextension=".yaml",
            filetypes=(("YAML files", "*.yaml"),),
        )
        if value:
            output.set(value)

    def run_convert() -> None:
        if not settings.get() or not output.get():
            messagebox.showwarning(
                "Converter", "Choose settings.toml and an output YAML."
            )
            return
        try:
            result = convert(analyze(settings.get()), Path(output.get()))
            report.set(f"Result: {result.status}\nOutput: {result.output_path}")
        except (OSError, ValueError) as error:
            messagebox.showerror("Conversion failed", str(error))

    for row, (label, variable, command) in enumerate(
        (
            ("AutoSplit settings.toml", settings, choose_settings),
            ("Output scenario", output, choose_output),
        )
    ):
        tk.Label(root, text=label, anchor="w").grid(
            row=row, column=0, sticky="ew", padx=12, pady=12
        )
        tk.Entry(root, textvariable=variable).grid(
            row=row, column=1, sticky="ew", padx=4, pady=12
        )
        tk.Button(root, text="Browse...", command=command).grid(
            row=row, column=2, padx=12, pady=12
        )
    tk.Label(root, textvariable=report, justify="left", anchor="nw").grid(
        row=2, column=0, columnspan=3, sticky="nsew", padx=12, pady=12
    )
    tk.Button(root, text="Convert", command=run_convert).grid(row=3, column=1, pady=8)
    root.columnconfigure(1, weight=1)
    root.rowconfigure(2, weight=1)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
