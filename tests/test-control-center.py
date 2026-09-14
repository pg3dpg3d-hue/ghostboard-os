#!/usr/bin/env python3
"""Construire les vrais widgets et contrôler leur disposition sans lancer d'app."""
from pathlib import Path
import sys
import tkinter as tk
from tkinter import ttk

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'runtime'))
from control_center import Center

app = Center()
try:
    app.update()
    tabs = next(w for w in app.winfo_children() if isinstance(w, ttk.Notebook))
    assert len(tabs.tabs()) == 4
    for size in ('760x430', '800x480'):
        app.geometry(size)
        app.update()
        for tab in tabs.tabs():
            tabs.select(tab)
            app.update()
            for frame in app.winfo_children():
                assert frame.winfo_x() + frame.winfo_width() <= app.winfo_width() + 1
    print('PASS: native control center, four tabs, 760x430 and 800x480 layouts.')
finally:
    app.close()
