from __future__ import annotations


def pick_pdf_file() -> str | None:
    try:
        import tkinter as tk
        from tkinter import filedialog

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        path = filedialog.askopenfilename(
            title="Select a PDF",
            filetypes=[("PDF files", "*.pdf")],
        )
        root.destroy()
        return path if path else None
    except Exception:
        return None
