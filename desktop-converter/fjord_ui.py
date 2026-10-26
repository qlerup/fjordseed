"""One FjordSeed workspace; the replacement conversion flow is added separately."""
import json
import os
import queue
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox, filedialog

BG = '#0b1220'
CARD = '#121e30'
FIELD = '#0d1727'
LINE = '#28394f'
TEXT = '#edf3fb'
MUTED = '#9caec5'
MINT = '#7ce4c4'
BLUE = '#8eb8ff'
QUALITY_CHOICES = {20: '20 Mbps – spar plads', 30: '30 Mbps – balance (anbefalet)', 40: '40 Mbps – høj kvalitet'}


def clock(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds//3600}:{seconds//60%60:02}:{seconds%60:02}' if seconds >= 3600 else f'{seconds//60}:{seconds%60:02}'


def read_settings(path):
    try:
        data = Path(path).read_text(encoding='utf-8')
        result = json.loads(data)
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


def save_media_folder(path, folder):
    selected = Path(folder)
    if not selected.is_absolute() or not selected.is_dir():
        raise ValueError('Vælg en eksisterende mappe.')
    from remote_agent import atomic
    data = read_settings(path)
    data['media_folder'] = str(selected)
    atomic(Path(path), data)
    return data['media_folder']


class ConverterUI(tk.Tk):
    def __init__(self, worker, cancelled, root, config):
        super().__init__()
        self.root_dir, self.config_path = Path(root), Path(config)
        self.connection_path = self.root_dir / 'worker-settings.json'
        self.tray = None
        self.settings_window = None
        self.title('FjordSeed · Konvertering')
        self.geometry('900x800')
        self.minsize(780, 780)
        self.configure(bg=BG)
        self._style()
        if (self.root_dir / 'fjord.ico').exists():
            self.iconbitmap(default=str(self.root_dir / 'fjord.ico'))
        settings = read_settings(self.config_path)
        self.media_folder = tk.StringVar(value=settings.get('media_folder', settings.get('drive', '')))
        self.status = tk.StringVar(value='Ingen konvertering i gang.')
        self.selected_path = tk.StringVar()
        self.percent = tk.StringVar(value='0 %')
        self.job_detail = tk.StringVar()
        self.folder_status = tk.StringVar(value='Vælg mappen til dine FjordSeed-filer.')
        self.connection_status = tk.StringVar()
        import windows_startup
        self.startup = tk.BooleanVar(value=windows_startup.enabled(self.root_dir / 'fjord_encode.pyw'))

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill='both', expand=True, padx=30, pady=22)
        header = tk.Frame(outer, bg=BG)
        header.pack(fill='x')
        self.label(header, 'FJORD', bg=BG, fg=MINT, font=('Segoe UI', 11, 'bold')).pack(side='left')
        ttk.Button(header, text='Indstillinger', command=self.open_settings).pack(side='right')
        self.label(outer, 'FjordSeed-konvertering', bg=BG, font=('Segoe UI', 26, 'bold')).pack(anchor='w', pady=(20, 6))
        self.label(outer, 'Vælg den mappe, hvor dine FjordSeed-filer ligger.', bg=BG, fg=MUTED).pack(anchor='w')
        self.label(outer, textvariable=self.connection_status, bg=BG, fg=MINT, font=('Segoe UI', 9)).pack(anchor='w', pady=(10, 18))

        drive_card = self.card(outer)
        drive_card.pack(fill='x')
        self.label(drive_card, 'MAPPE TIL FJORDSEED', fg=MUTED, font=('Segoe UI', 9, 'bold')).pack(anchor='w', pady=(0, 10))
        row = tk.Frame(drive_card, bg=CARD)
        row.pack(fill='x')
        self.folder_entry = ttk.Entry(row, textvariable=self.media_folder, state='readonly', font=('Segoe UI', 12))
        self.folder_entry.pack(side='left', fill='x', expand=True)
        ttk.Button(row, text='Vælg mappe…', command=self.choose_folder).pack(side='right', padx=(12, 0))
        self.label(drive_card, textvariable=self.folder_status, fg=MUTED, font=('Segoe UI', 10)).pack(anchor='w', pady=(12, 0))

        progress = self.card(outer)
        progress.pack(fill='both', expand=True, pady=(18, 0))
        self.label(progress, 'STATUS', fg=MUTED, font=('Segoe UI', 9, 'bold')).pack(anchor='w')
        self.label(progress, textvariable=self.status, font=('Segoe UI', 13, 'bold')).pack(anchor='w', pady=(16, 16))
        self.label(progress, textvariable=self.selected_path, fg=MUTED, font=('Segoe UI', 10),
                   wraplength=700, justify='left').pack(anchor='w', pady=(0, 16))
        self.bar = ttk.Progressbar(progress, maximum=100)
        self.bar.pack(fill='x')
        self.label(progress, textvariable=self.percent, fg=MINT, font=('Segoe UI', 20, 'bold')).pack(anchor='e', pady=(8, 0))
        self.label(progress, textvariable=self.job_detail, fg=MUTED, font=('Segoe UI',10)).pack(anchor='w')
        actions = tk.Frame(outer, bg=BG)
        actions.pack(fill='x', pady=(18, 0))
        ttk.Button(actions, text='Kør i baggrunden', command=self.background).pack(side='left')
        ttk.Button(actions, text='Afslut', command=self.close).pack(side='left', padx=10)
        self.cancel_button=ttk.Button(actions,text='Afbryd konvertering',command=self.cancel_conversion,state='disabled')
        self.cancel_button.pack(side='left')
        self.label(actions,'Startes fra FjordSeed',bg=BG,fg=MUTED,font=('Segoe UI',10)).pack(side='right')
        self.refresh_connection()
        from workspace_sync import WorkspaceSync
        self.workspace_sync = WorkspaceSync(self.connection_path, self.config_path,worker,cancelled)
        self.after(300, self.poll_workspace)
        self.protocol('WM_DELETE_WINDOW', self.background)
        self.bind('<Control-q>', lambda event: self.close())
        self.after_idle(self.enable_background)

    def label(self, parent, text=None, **kwargs):
        return tk.Label(parent, text=text, bg=kwargs.pop('bg', CARD), fg=kwargs.pop('fg', TEXT),
                        font=kwargs.pop('font', ('Segoe UI', 11)), **kwargs)

    def card(self, parent):
        return tk.Frame(parent, bg=CARD, highlightbackground=LINE, highlightthickness=1, padx=22, pady=20)

    def refresh_connection(self):
        saved = read_settings(self.connection_path)
        self.connection_status.set('FjordSeed-forbindelse gemt' if saved.get('server') and saved.get('token_dpapi')
                                   else 'Tilføj din FjordSeed-forbindelse under Indstillinger')

    def choose_folder(self):
        if self.workspace_sync.runner and self.workspace_sync.runner.busy:
            self.folder_status.set('Afvent eller afbryd konverteringen før mappen ændres.')
            return
        folder = filedialog.askdirectory(parent=self, title='Vælg mappe til FjordSeed',
                                         initialdir=self.media_folder.get() or str(Path.home()), mustexist=True)
        if not folder:
            return
        try:
            selected = save_media_folder(self.config_path, folder)
            self.media_folder.set(selected)
            self.folder_status.set('Mappe valgt.')
            self.selected_path.set('')
            self.status.set('Ingen fil valgt fra FjordSeed.')
            self.workspace_sync.selection_id=None
            self.workspace_sync.changed.set()
        except (OSError, ValueError) as exc:
            self.folder_status.set(str(exc))

    def poll_workspace(self):
        try:
            while True:
                state, value = self.workspace_sync.messages.get_nowait()
                if state == 'ok':
                    if value != self.media_folder.get():
                        continue  # A previous request completed after a new selection.
                    self.folder_status.set('Mappe delt med FjordSeed.' if value else 'Vælg mappen til dine FjordSeed-filer.')
                elif state == 'selected':
                    if value['folder'] != self.media_folder.get():continue
                    self.selected_path.set(value['path'])
                    self.status.set('Klar · tryk Send til pc i FjordSeed for at starte.')
                elif state == 'selection_cleared':
                    self.selected_path.set('')
                    self.status.set(value or 'Ingen fil valgt fra FjordSeed.')
                elif state == 'job_start':
                    self.selected_path.set(value['path'])
                    self.job_detail.set(str(value['bitrate'])+' Mbps · direkte fra netværksmappen')
                    self.status.set('Starter konvertering på NVIDIA-GPU …')
                    self.bar['value']=0;self.percent.set('0 %')
                elif state == 'job_status':self.status.set(value)
                elif state == 'job_progress':
                    percent,fps,remaining=value
                    self.bar['value']=percent;self.percent.set(f'{percent:.0f} %')
                    self.job_detail.set(f'{fps:.1f} billeder/s · cirka {clock(remaining)} tilbage')
                elif state == 'job_done':
                    self.bar['value']=100;self.percent.set('100 %')
                    self.status.set('Færdig · filmen er i Bibliotek, og originaltorrenten er i Seeder.')
                    self.job_detail.set('Alle originalfiler og torrentens mappestruktur er bevaret.')
                elif state == 'job_error':self.status.set(value)
                else:
                    self.folder_status.set(value)
        except queue.Empty:
            pass
        runner=self.workspace_sync.runner
        stoppable=runner and ((runner.busy and runner.can_cancel) or (not runner.busy and runner.receipt and runner.receipt.get('state')=='error' and runner.command))
        self.cancel_button['state']='normal' if stoppable else 'disabled'
        self.after(300, self.poll_workspace)

    def cancel_conversion(self):
        if self.workspace_sync.runner:self.workspace_sync.runner.cancel()

    def open_settings(self):
        if self.settings_window and self.settings_window.winfo_exists():
            self.settings_window.lift()
            return
        win = tk.Toplevel(self)
        self.settings_window = win
        win.title('FjordSeed · Indstillinger')
        win.configure(bg=BG)
        win.geometry('650x330')
        win.minsize(580, 320)
        win.transient(self)
        body = tk.Frame(win, bg=BG, padx=24, pady=22)
        body.pack(fill='both', expand=True)
        self.label(body, 'Forbindelse til FjordSeed', bg=BG, font=('Segoe UI', 16, 'bold')).pack(anchor='w')
        self.label(body, 'Indsæt en ny forbindelseskode, hvis forbindelsen skal ændres.', bg=BG, fg=MUTED, font=('Segoe UI', 10)).pack(anchor='w', pady=(8, 12))
        code = tk.StringVar()
        ttk.Entry(body, textvariable=code, show='•').pack(fill='x')
        feedback = tk.StringVar(value=self.connection_status.get())
        self.label(body, textvariable=feedback, bg=BG, fg=MUTED, font=('Segoe UI', 10)).pack(anchor='w', pady=(8, 12))
        tk.Checkbutton(body, text='Start med Windows', variable=self.startup, command=self.toggle_startup,
                       bg=BG, fg=TEXT, activebackground=BG, activeforeground=TEXT, selectcolor=FIELD,
                       highlightthickness=0, font=('Segoe UI', 10)).pack(anchor='w')
        def save():
            try:
                self.save_connection(code.get())
                self.refresh_connection()
                self.workspace_sync.changed.set()
                win.destroy()
            except (OSError, ValueError) as exc:
                feedback.set(str(exc))
        ttk.Button(body, text='Gem indstillinger', style='Primary.TButton', command=save).pack(anchor='e', pady=(18, 0))

    def save_connection(self, code):
        if not code.strip():
            return
        if getattr(self,'workspace_sync',None) and self.workspace_sync.runner and self.workspace_sync.runner.busy:
            raise ValueError('Afvent eller afbryd konverteringen før forbindelsen ændres.')
        from remote_agent import atomic, connection_details
        from windows_secret import protect
        saved = read_settings(self.connection_path)
        server, token = connection_details(saved.get('server', ''), code)
        if not server or not token.startswith('fsw_'):
            raise ValueError('Indsæt forbindelseskoden fra FjordSeed.')
        atomic(self.connection_path, {**saved, 'server': server, 'token_dpapi': protect(token)})

    def toggle_startup(self):
        import windows_startup
        try:
            windows_startup.configure(self.root_dir / 'fjord_encode.pyw', self.startup.get())
        except OSError:
            self.startup.set(not self.startup.get())
            messagebox.showerror('Opstart kunne ikke ændres', 'Windows kunne ikke gemme opstartsvalget.')

    def enable_background(self):
        if os.name == 'nt':
            from windows_background import Tray
            try:
                self.tray = Tray(self, self.root_dir / 'fjord.ico', self.restore, self.close)
            except OSError:
                self.tray = None

    def background(self):
        self.withdraw() if self.tray else self.iconify()

    def restore(self):
        self.deiconify()
        self.lift()
        self.focus_set()

    def close(self):
        self.workspace_sync.close()
        def finish():
            if self.workspace_sync.runner and self.workspace_sync.runner.busy and self.workspace_sync.runner.can_cancel:self.after(100,finish)
            else:self.destroy()
        finish()

    def _style(self):
        style = ttk.Style(self)
        style.theme_use('clam')
        style.configure('.', font=('Segoe UI', 10))
        style.configure('TButton', background='#23364d', foreground=TEXT, borderwidth=0, padding=(15, 10))
        style.map('TButton', background=[('active', '#2c4561')], foreground=[('disabled', '#8394a8')])
        style.configure('Primary.TButton', background=MINT, foreground='#102e2b', font=('Segoe UI', 11, 'bold'), padding=(25, 12))
        style.map('Primary.TButton', background=[('disabled', '#263b40'), ('active', '#98f3d6')], foreground=[('disabled', '#829999')])
        style.configure('TEntry', fieldbackground=FIELD, foreground=TEXT, insertcolor=MINT, bordercolor=LINE, padding=10)
        style.configure('TCombobox', fieldbackground=FIELD, background='#23364d', foreground=TEXT, arrowcolor=MINT, padding=12)
        style.map('TCombobox', fieldbackground=[('readonly', FIELD)], foreground=[('readonly', TEXT)], selectbackground=[('readonly', FIELD)], selectforeground=[('readonly', TEXT)])
        self.option_add('*TCombobox*Listbox.background', FIELD)
        self.option_add('*TCombobox*Listbox.foreground', TEXT)
        self.option_add('*TCombobox*Listbox.selectBackground', '#284d58')
        style.configure('Horizontal.TProgressbar', background=MINT, troughcolor='#23354a', borderwidth=0, thickness=9)
