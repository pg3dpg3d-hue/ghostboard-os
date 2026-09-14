#!/usr/bin/env python3
"""Centre de contrôle natif, redimensionnable, utilisable au clavier."""
import concurrent.futures
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import tomllib
import ghostboard as gb


class Center(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title('GHOSTBOARD · Control Center')
        self.geometry('760x430')
        self.minsize(560, 330)
        self.pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.style = ttk.Style(self)
        self.style.theme_use('clam')
        palette = Path('/usr/share/ghostboard/palette.toml')
        if not palette.exists():
            palette = Path(__file__).resolve().parents[1] / 'brand/palette.toml'
        if palette.exists():
            p = tomllib.loads(palette.read_text())
            c = p['color']
            self.configure(bg=c['bg'])
            self.style.configure('.', background=c['bg'], foreground=c['text'], font=(p['font']['ui'], 11))
            self.style.configure('TButton', background=c['panel'], padding=8)
            self.style.map('TButton', background=[('active', c['accent'])])
            self.style.configure('TNotebook.Tab', padding=(10, 6))
        bar = ttk.Frame(self, padding=10)
        bar.pack(fill='x')
        ttk.Label(bar, text='GHOSTBOARD', font=('sans-serif', 16, 'bold')).pack(side='left')
        ttk.Button(bar, text='STOP AGENT', command=self.stop).pack(side='right')
        ttk.Button(bar, text='Lock', command=lambda: self.run_command(['ghost-system', 'lock'])).pack(side='right', padx=5)
        book = ttk.Notebook(self)
        book.pack(fill='both', expand=True, padx=10)
        self.overview = ttk.Frame(book, padding=12)
        book.add(self.overview, text='System')
        self.health = tk.StringVar(value='Reading system status…')
        ttk.Label(self.overview, textvariable=self.health, justify='left').pack(anchor='w')
        actions = ttk.Frame(self.overview)
        actions.pack(fill='x', pady=12)
        for text, action in [('Diagnostics', lambda: self.open('diagnostics')), ('Updates', lambda: self.open('updates')), ('Backup', self.backup), ('Restore', self.restore), ('Resume agent', self.resume)]:
            ttk.Button(actions, text=text, command=action).pack(side='left', padx=3)
        self.add_grid(book, 'Applications', ['browser', 'files', 'terminal', 'editor', 'office', 'media', 'spatial', 'calculator', 'passwords', 'screenshots', 'processes', 'serial'])
        self.add_grid(book, 'Settings', ['wifi', 'bluetooth', 'audio', 'display', 'power', 'settings', 'hardware', 'remote'])
        self.add_grid(book, 'Assistant', ['assistant', 'local-ai', 'local-vision', 'codex', 'claude', 'ai-setup', 'voice', 'agent-browser', 'agent-assistant'])
        self.note = tk.StringVar(value='Ctrl+Alt+Escape stops computer use · No cloud connection until you start an assistant.')
        ttk.Label(self, textvariable=self.note, wraplength=720, padding=10).pack(fill='x')
        self.bind('<Escape>', lambda _: self.stop())
        self.protocol('WM_DELETE_WINDOW', self.close)
        self.after(50, self.refresh)

    def add_grid(self, book, label, apps):
        frame = ttk.Frame(book, padding=12)
        book.add(frame, text=label)
        for col in range(3):
            frame.columnconfigure(col, weight=1)
        for i, name in enumerate(apps):
            ttk.Button(frame, text=gb.APPS[name][0], command=lambda n=name: self.open(n)).grid(row=i//3, column=i%3, sticky='ew', padx=4, pady=5)

    def open(self, name):
        try:
            gb.launch(name)
        except Exception as exc:
            messagebox.showerror('Cannot open application', str(exc))

    def run_command(self, args):
        import subprocess
        subprocess.Popen(args)

    def stop(self):
        gb.set_stopped(True)
        self.note.set('Computer use stopped. Use Resume agent to enable it again.')

    def resume(self):
        gb.set_stopped(False)
        self.note.set('Computer use enabled. Start a new task in the Assistant tab.')

    def backup(self):
        name = filedialog.asksaveasfilename(defaultextension='.tar.gz', initialfile='ghostboard-settings.tar.gz')
        if name:
            try:
                self.note.set('Saved: ' + gb.backup(name))
            except Exception as exc:
                messagebox.showerror('Backup failed', str(exc))

    def restore(self):
        name = filedialog.askopenfilename(filetypes=[('Configuration backup', '*.tar.gz')])
        if name and messagebox.askyesno('Restore', 'Restore saved settings? Your current settings will be backed up first.'):
            try:
                self.note.set('Restored. Previous settings: ' + gb.restore(name) + ' · Log out to apply.')
            except Exception as exc:
                messagebox.showerror('Restore failed', str(exc))

    def refresh(self):
        if self.future is None:
            self.future = self.pool.submit(gb.status)
        if self.future.done():
            try:
                s = self.future.result()
                ram = f"{s['memory_available']/1024**3:.1f} / {s['memory_total']/1024**3:.1f} GiB available" if s['memory_total'] else 'unavailable'
                temp = ', '.join(f"{t['celsius']:.1f} °C" for t in s['temperatures']) or 'unavailable'
                battery = ', '.join(f"{b['percent']}% ({b['state']})" for b in s['batteries']) or 'No battery telemetry exposed by the hardware'
                self.health.set(f"{s['board']} · {s['architecture']}\nMemory: {ram}    Disk free: {s['disk_free']/1024**3:.1f} GiB\nTemperature: {temp}\nBattery: {battery}\nSession: {s['session']}    Agent: {'STOPPED' if s['agent_stopped'] else 'ready'}\nNetwork: {', '.join(s['network']) or 'unavailable'}")
            except Exception as exc:
                self.note.set(str(exc))
            self.future = None
            self.after(5000, self.refresh)
        else:
            self.after(150, self.refresh)

    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.destroy()


if __name__ == '__main__':
    Center().mainloop()
