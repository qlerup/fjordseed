"""Desktop presentation for the existing Fjord NVEncC worker."""
import json
import os
from pathlib import Path
import queue
import threading
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

BG = '#0b1220'
CARD = '#121e30'
FIELD = '#0d1727'
LINE = '#28394f'
TEXT = '#edf3fb'
MUTED = '#9caec5'
MINT = '#7ce4c4'
BLUE = '#8eb8ff'


def clock(seconds):
    seconds = max(0, int(seconds))
    return f'{seconds//3600}:{seconds//60%60:02}:{seconds%60:02}' if seconds >= 3600 else f'{seconds//60}:{seconds%60:02}'


class ConverterUI(tk.Tk):
    def __init__(self, worker, cancelled, root, config):
        super().__init__()
        self.worker, self.cancelled, self.root_dir, self.config_path = worker, cancelled, root, config
        self.title('Fjord · Konvertering')
        self.geometry('1040x850')
        self.minsize(940, 820)
        self.configure(bg=BG)
        self.events = queue.Queue()
        self.stop = threading.Event()
        self.running = False
        self.gpu_lock = threading.Lock()
        self.output_file = self.logfile = None
        self.started = 0
        self.notifications=None;self.tray=None;self.encoding_notice=False
        try:
            settings = json.loads(config.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            settings = {}
        default = Path.home() / 'Videos' / 'FjordEncode'
        default.mkdir(exist_ok=True)
        self.source = tk.StringVar()
        self.folder = tk.StringVar(value=settings.get('folder', str(default)))
        rate = settings.get('bitrate', 20)
        self.bitrate = tk.StringVar(value=str(rate if rate in (10,15,20,25,30) else 20))
        self.filename = tk.StringVar(value='Ingen film valgt endnu')
        self.status = tk.StringVar(value='Vælg en film, så er du klar.')
        self.percent = tk.StringVar(value='0 %')
        self.speed = tk.StringVar(value='—')
        self.remaining = tk.StringVar(value='—')
        self.elapsed = tk.StringVar(value='0:00')
        self.badge = tk.StringVar(value='●  KLAR')
        self._style()
        self._icon()

        nav=tk.Frame(self,bg=BG)
        nav.pack(fill='x',padx=26,pady=(12,0))
        ttk.Button(nav,text='Lokal konvertering',command=lambda:self.show_tab('local')).pack(side='left')
        ttk.Button(nav,text='FjordSeed-forbindelse',command=lambda:self.show_tab('remote')).pack(side='left',padx=10)
        import windows_startup
        self.startup=tk.BooleanVar(value=windows_startup.enabled(self.root_dir/'fjord_encode.pyw'))
        tk.Checkbutton(nav,text='Start med Windows',variable=self.startup,command=self.toggle_startup,
            bg=BG,fg=MUTED,activebackground=BG,activeforeground=TEXT,selectcolor=FIELD,
            highlightthickness=0,font=('Segoe UI',9)).pack(side='left',padx=8)
        ttk.Button(nav,text='Afslut',command=self.close).pack(side='right')
        ttk.Button(nav,text='Kør i baggrunden',command=self.background).pack(side='right',padx=10)
        outer = tk.Frame(self, bg=BG)
        self.local_frame=outer
        outer.pack(fill='both', expand=True, padx=26, pady=(18,16))
        brand = tk.Frame(outer, bg=BG)
        brand.pack(fill='x')
        logo = tk.Canvas(brand, width=36, height=36, bg=BG, highlightthickness=0)
        logo.pack(side='left', padx=(0,11))
        logo.create_rectangle(1,1,35,35,fill='#173e3b',outline='#2b665c')
        logo.create_text(18,18,text='F',font=('Segoe UI',20,'bold'),fill=MINT)
        self.label(brand, 'FJORD', font=('Segoe UI',12,'bold'), bg=BG).pack(side='left')
        self.label(brand, 'LOKAL KONVERTERING', fg=MUTED, font=('Segoe UI',9), bg=BG).pack(side='left',padx=14)
        self.badge_label = self.label(brand, textvariable=self.badge, fg=MINT, bg='#142d2d', font=('Segoe UI',9,'bold'),padx=13,pady=7)
        self.badge_label.pack(side='right')

        intro = tk.Frame(outer, bg=BG)
        intro.pack(fill='x', pady=(16,18))
        self.label(intro,'Mere film. Mindre plads.',font=('Segoe UI',25,'bold'),bg=BG).pack(anchor='w')
        self.label(intro,'Konvertér på din NVIDIA-GPU med dine faste Fjord-indstillinger.',fg=MUTED,bg=BG,font=('Segoe UI',11)).pack(anchor='w',pady=(6,0))

        main = tk.Frame(outer,bg=BG)
        main.pack(fill='both',expand=True)
        main.columnconfigure(0,weight=1)
        main.columnconfigure(1,weight=0,minsize=290)
        main.rowconfigure(0,weight=1)
        files = self.card(main)
        files.grid(row=0,column=0,sticky='nsew',padx=(0,18))
        files.columnconfigure(0,weight=1)
        self.label(files,'01  /  DIN FILM',fg=MUTED,font=('Segoe UI',9,'bold')).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,14))
        well = tk.Frame(files,bg=FIELD,highlightbackground=LINE,highlightthickness=1,padx=14,pady=12)
        well.grid(row=1,column=0,columnspan=2,sticky='ew')
        well.columnconfigure(1,weight=1)
        film = tk.Canvas(well,width=40,height=43,bg=FIELD,highlightthickness=0)
        film.grid(row=0,column=0,rowspan=2,padx=(0,14))
        film.create_rectangle(4,4,34,38,outline=MINT,width=2)
        film.create_line(11,5,11,37,fill=MINT)
        film.create_line(27,5,27,37,fill=MINT)
        for y in (11,20,29):
            film.create_line(5,y,10,y,fill=MINT)
            film.create_line(28,y,33,y,fill=MINT)
        self.file_label=self.label(well,textvariable=self.filename,font=('Segoe UI',11,'bold'),bg=FIELD,wraplength=270,justify='left')
        self.file_label.grid(row=0,column=1,sticky='w')
        self.drop_hint=self.label(well,'Vælg en video fra din pc eller dit netværk',fg=MUTED,bg=FIELD,font=('Segoe UI',9),wraplength=270)
        self.drop_hint.grid(row=1,column=1,sticky='w',pady=(4,0))
        self.choose_button=ttk.Button(well,text='Vælg film',command=self.choose)
        self.choose_button.grid(row=0,column=2,rowspan=2,padx=(12,0))
        self.source_entry=ttk.Entry(files,textvariable=self.source)
        self.source_entry.grid(row=2,column=0,columnspan=2,sticky='ew',pady=(12,10))
        self.divider(files).grid(row=4,column=0,columnspan=2,sticky='ew',pady=14)
        self.label(files,'GEM DEN NYE FIL I',fg=MUTED,font=('Segoe UI',9,'bold')).grid(row=5,column=0,columnspan=2,sticky='w',pady=(0,10))
        self.folder_entry=ttk.Entry(files,textvariable=self.folder)
        self.folder_entry.grid(row=6,column=0,sticky='ew',padx=(0,10))
        self.folder_button=ttk.Button(files,text='Vælg …',command=self.choose_folder)
        self.folder_button.grid(row=6,column=1)
        self.label(files,'Originalen beholdes. Resultatet får sit eget filnavn.',fg=MUTED,font=('Segoe UI',9),wraplength=470,justify='left').grid(row=7,column=0,columnspan=2,sticky='w',pady=(12,0))

        recipe=self.card(main)
        recipe.grid(row=0,column=1,sticky='nsew')
        self.label(recipe,'02  /  DINE INDSTILLINGER',fg=MUTED,font=('Segoe UI',9,'bold')).pack(anchor='w',pady=(0,14))
        self.label(recipe,'Fjord · GPU',font=('Segoe UI',18,'bold')).pack(anchor='w')
        self.label(recipe,'Samme opsætning som din test',fg=MUTED,font=('Segoe UI',9)).pack(anchor='w',pady=(3,15))
        specs=[('FORMAT','MKV · HEVC'),('BILLEDE','Original opløsning'),('HDR','HDR10 / Dolby Vision 8.1*'),('LYD OG UNDERTEKSTER','Alle spor kopieres')]
        for title,value in specs:
            self.label(recipe,title,fg=MUTED,font=('Segoe UI',8,'bold')).pack(anchor='w',pady=(4,1))
            self.label(recipe,value,font=('Segoe UI',10)).pack(anchor='w')
        self.divider(recipe).pack(fill='x',pady=(12,10))
        rate_row=tk.Frame(recipe,bg=CARD)
        rate_row.pack(fill='x')
        self.label(rate_row,'Video-bitrate',font=('Segoe UI',10)).pack(side='left')
        self.rate_box=ttk.Combobox(rate_row,textvariable=self.bitrate,values=(10,15,20,25,30),state='readonly',width=4)
        self.rate_box.pack(side='left',padx=(10,6))
        self.label(rate_row,'Mbps',fg=MUTED,font=('Segoe UI',9)).pack(side='left')
        info=tk.Label(recipe,text='* Om kvalitet og Dolby Vision',fg=BLUE,bg=CARD,cursor='hand2',font=('Segoe UI',9),anchor='w',takefocus=True)
        info.pack(anchor='w',pady=(14,0))
        info.bind('<Button-1>',lambda e:self.show_info())
        info.bind('<Return>',lambda e:self.show_info())

        progress=self.card(outer,padding=16)
        progress.pack(fill='x',pady=(14,0))
        heading=tk.Frame(progress,bg=CARD)
        heading.pack(fill='x')
        self.status_label=self.label(heading,textvariable=self.status,font=('Segoe UI',11,'bold'),wraplength=790,justify='left')
        self.status_label.pack(side='left',fill='x',expand=True)
        self.label(heading,textvariable=self.percent,fg=MINT,font=('Segoe UI',19,'bold')).pack(side='right',padx=(12,0))
        self.bar=ttk.Progressbar(progress,maximum=100)
        self.bar.pack(fill='x',pady=(10,12))
        stats=tk.Frame(progress,bg=CARD)
        stats.pack(fill='x')
        for i,(title,var) in enumerate((('HASTIGHED',self.speed),('TILBAGE',self.remaining),('TID BRUGT',self.elapsed))):
            col=tk.Frame(stats,bg=CARD)
            col.pack(side='left',fill='x',expand=True)
            self.label(col,title,fg=MUTED,font=('Segoe UI',8,'bold')).pack(anchor='w')
            self.label(col,textvariable=var,font=('Segoe UI',12,'bold')).pack(anchor='w',pady=(4,0))

        actions=tk.Frame(outer,bg=BG)
        actions.pack(fill='x',pady=(14,0))
        self.log_button=ttk.Button(actions,text='Se log',state='disabled',command=lambda:os.startfile(self.logfile))
        self.log_button.pack(side='left')
        self.result_button=ttk.Button(actions,text='Åbn resultat ↗',state='disabled',command=lambda:os.startfile(self.output_file))
        self.result_button.pack(side='left',padx=10)
        self.start_button=ttk.Button(actions,text='Start konvertering  →',style='Primary.TButton',command=self.start)
        self.start_button.pack(side='right')
        self.cancel_button=ttk.Button(actions,text='Stop',style='Stop.TButton',state='disabled',command=self.cancel)
        self.cancel_button.pack(side='right',padx=10)
        self.source.trace_add('write',self.source_changed)
        from remote_panel import RemotePanel
        self.remote_panel=RemotePanel(self)
        self.protocol('WM_DELETE_WINDOW',self.background)
        self.bind('<Control-q>',lambda e:self.close())
        self.after_idle(self.enable_background)
        self.after(150,self.poll)
        self.after(1000,self.timer)
        self.after_idle(self.enable_drop)

    def label(self,parent,text=None,**kw):
        options=dict(bg=CARD,fg=TEXT,font=('Segoe UI',10),bd=0,anchor='w')
        options.update(kw)
        return tk.Label(parent,text=text,**options)

    def show_tab(self,tab):
        self.local_frame.pack_forget();self.remote_panel.frame.pack_forget()
        frame=self.remote_panel.frame if tab=='remote' else self.local_frame
        if tab=='remote':frame.pack(fill='both',expand=True)
        else:frame.pack(fill='both',expand=True,padx=26,pady=(18,16))

    def enable_background(self):
        if os.name!='nt':return
        from windows_background import Notice,Tray
        self.notifications=Notice(self)
        try:self.tray=Tray(self,self.root_dir/'fjord.ico',self.restore,self.close)
        except OSError:self.tray=None

    def toggle_startup(self):
        import windows_startup
        try:windows_startup.configure(self.root_dir/'fjord_encode.pyw',self.startup.get())
        except OSError:
            self.startup.set(not self.startup.get())
            messagebox.showerror('Opstart kunne ikke ændres','Windows kunne ikke gemme opstartsvalget. Prøv igen med din normale Windows-bruger.')

    def background(self):
        if self.tray:self.withdraw()
        else:self.iconify()

    def restore(self):
        self.deiconify();self.lift();self.focus_set()

    def notify_started(self,name):
        if self.notifications:self.notifications.started(name)

    def notify_eta(self,seconds):
        if self.notifications:self.notifications.progress(seconds)

    def card(self,parent,padding=20):
        return tk.Frame(parent,bg=CARD,highlightbackground=LINE,highlightthickness=1,padx=padding,pady=padding)

    def divider(self,parent):
        return tk.Frame(parent,bg=LINE,height=1)

    def _style(self):
        s=ttk.Style(self)
        s.theme_use('clam')
        s.configure('.',font=('Segoe UI',10))
        s.configure('TButton',background='#23364d',foreground=TEXT,borderwidth=0,padding=(14,10),focusthickness=1,focuscolor=BLUE)
        s.map('TButton',background=[('disabled','#172337'),('pressed','#304e69'),('active','#2c4561')],foreground=[('disabled','#63758e')])
        s.configure('Primary.TButton',background=MINT,foreground='#102e2b',font=('Segoe UI',10,'bold'),padding=(22,11))
        s.map('Primary.TButton',background=[('disabled','#263b40'),('pressed','#59c7a7'),('active','#98f3d6')],foreground=[('disabled','#829999')])
        s.configure('Stop.TButton',foreground='#ffb9bf')
        s.configure('TEntry',fieldbackground=FIELD,foreground=TEXT,insertcolor=MINT,bordercolor=LINE,lightcolor=LINE,darkcolor=LINE,padding=10)
        s.map('TEntry',fieldbackground=[('disabled','#142032')],foreground=[('disabled',MUTED)],bordercolor=[('focus',MINT)])
        s.configure('TCombobox',fieldbackground=FIELD,background='#23364d',foreground=TEXT,arrowcolor=MINT,bordercolor=LINE,padding=6)
        s.map('TCombobox',fieldbackground=[('readonly',FIELD),('disabled',CARD)],foreground=[('readonly',TEXT),('disabled',MUTED)],selectbackground=[('readonly',FIELD)],selectforeground=[('readonly',TEXT)])
        self.option_add('*TCombobox*Listbox.background',FIELD)
        self.option_add('*TCombobox*Listbox.foreground',TEXT)
        self.option_add('*TCombobox*Listbox.selectBackground','#284d58')
        self.option_add('*TCombobox*Listbox.selectForeground',TEXT)
        s.configure('Horizontal.TProgressbar',background=MINT,troughcolor='#23354a',bordercolor='#23354a',borderwidth=0,lightcolor=MINT,darkcolor=MINT,thickness=7)

    def _icon(self):
        if (self.root_dir/'fjord.ico').exists():
            self.iconbitmap(default=str(self.root_dir/'fjord.ico'))
        self.app_icon=tk.PhotoImage(width=32,height=32)
        self.app_icon.put('#173e3b',to=(0,0,32,32))
        for rect in ((9,7,13,26),(13,7,25,11),(13,15,22,19)):
            self.app_icon.put(MINT,to=rect)
        self.iconphoto(True,self.app_icon)

    def source_changed(self,*_):
        name=Path(self.source.get().strip().strip('"')).name
        self.filename.set((name[:69]+'…') if len(name)>70 else name or 'Ingen film valgt endnu')
        if not self.running:
            self.status.set('Klar til konvertering.' if name else 'Vælg en film, så er du klar.')
            self.status_label.configure(fg=TEXT)
            self.badge.set('●  KLAR')
            self.bar['value']=0;self.percent.set('0 %')
            self.speed.set('—');self.remaining.set('—');self.elapsed.set('0:00')
            self.result_button['state']='disabled'

    def choose(self):
        name=filedialog.askopenfilename(title='Vælg filmen, du vil konvertere',filetypes=[('Video','*.mkv *.mp4 *.m4v *.mov *.ts *.m2ts *.avi *.webm'),('Alle filer','*.*')])
        if name:self.source.set(name)

    def enable_drop(self):
        if os.name != 'nt':return
        try:
            from windows_drop import FileDrop
            self.file_drop=FileDrop(self,lambda paths:self.events.put(('drop',paths)))
            self.drop_hint.configure(text='Træk en videofil hertil, eller vælg en film')
        except (OSError,ImportError):
            self.status.set('Træk og slip kunne ikke aktiveres. Brug Vælg film.')

    def dropped(self,paths):
        if self.running:
            self.status.set('En konvertering er i gang. Vent eller brug Stop, før du vælger en ny film.')
            return
        allowed={'.mkv','.mp4','.m4v','.mov','.ts','.m2ts','.avi','.webm'}
        if len(paths)!=1 or Path(paths[0]).suffix.lower() not in allowed or not Path(paths[0]).is_file():
            self.status.set('Slip én videofil ad gangen, f.eks. en MKV- eller MP4-fil.')
            self.status_label.configure(fg='#ffb9bf')
            return
        self.source.set(paths[0])

    def choose_folder(self):
        name=filedialog.askdirectory(title='Gem den nye MKV-fil i',initialdir=self.folder.get())
        if name:self.folder.set(name)

    def show_info(self):
        messagebox.showinfo('Dine Fjord-indstillinger','GPU: NVIDIA NVENC · HEVC quality\nOriginal opløsning og billedhastighed bevares.\nLyd, undertekster og kapitler kopieres.\n\nHDR10 bevares, når det findes i originalen. Dolby Vision-profil 7/8.1 konverteres til 8.1; profil 7’s ekstra billedlag følger ikke med. Andre Dolby Vision-profiler afvises.\n\n20 Mbps er videoens gennemsnitlige mål. Lyd lægges oveni. Lavere bitrate kan koste detaljer. Resultatet kontrolleres før det meldes færdigt.')

    def start(self):
        if self.running:return
        source,folder=self.source.get().strip().strip('"'),self.folder.get().strip().strip('"')
        if not Path(source).is_file() or not Path(folder).is_dir():
            self.status.set('Vælg en eksisterende film og en gemmemappe.')
            self.status_label.configure(fg='#ffb9bf')
            self.badge.set('●  VÆLG FILM')
            self.source_entry.focus_set()
            return
        rate=int(self.bitrate.get())
        try:self.config_path.write_text(json.dumps({'folder':folder,'bitrate':rate}),encoding='utf-8')
        except OSError:
            messagebox.showerror('Indstillinger kunne ikke gemmes','Kontrollér skriveadgangen til programmets mappe.')
            return
        if not self.gpu_lock.acquire(blocking=False):
            self.status.set('Pc’en behandler et FjordSeed-job. Se FjordSeed-forbindelse.')
            return
        self.running=True
        self.stop.clear()
        self.started=time.monotonic()
        self.encoding_notice=False
        self.bar['value']=0
        self.percent.set('0 %')
        self.speed.set('—');self.remaining.set('—');self.elapsed.set('0:00')
        self.status_label.configure(fg=TEXT)
        self.badge.set('●  ARBEJDER')
        self.result_button['state']='disabled';self.log_button['state']='disabled'
        self.cancel_button['state']='normal'
        for w in (self.start_button,self.choose_button,self.folder_button,self.source_entry,self.folder_entry,self.rate_box):w['state']='disabled'
        def work():
            try:self.worker(source,folder,rate,lambda k,v:self.events.put((k,v)),self.stop)
            except self.cancelled:self.events.put(('error','Stoppet. En eventuel .partial.mkv er ufærdig.'))
            except Exception as exc:self.events.put(('error',str(exc)))
            finally:
                self.gpu_lock.release()
                self.events.put(('finished',None))
        threading.Thread(target=work,daemon=True).start()

    def cancel(self):
        self.stop.set();self.cancel_button['state']='disabled';self.status.set('Stopper sikkert …')

    def timer(self):
        if self.running:self.elapsed.set(clock(time.monotonic()-self.started))
        self.after(1000,self.timer)

    def poll(self):
        try:
            while True:
                kind,value=self.events.get_nowait()
                if kind=='remote':self.remote_panel.event(*value)
                elif kind=='drop':self.dropped(value)
                elif kind=='status':
                    self.status.set(value)
                    if value.startswith('Konverterer på NVIDIA') and not self.encoding_notice:
                        self.encoding_notice=True
                        self.notify_started(Path(self.source.get()).name)
                elif kind=='log':self.logfile=value;self.log_button['state']='normal'
                elif kind=='progress':
                    pct,fps,remaining=value
                    self.bar['value']=pct;self.percent.set(f'{pct:.0f} %')
                    self.speed.set(f'{fps:.1f} fps');self.remaining.set('≈ '+clock(remaining))
                    self.notify_eta(remaining)
                elif kind=='done':
                    self.output_file,seconds,report=value
                    self.bar['value']=100;self.percent.set('100 %')
                    self.status.set(f'Færdig og kontrolleret · {report["audio_tracks"]} lydspor · {report["subtitle_tracks"]} undertekstspor')
                    self.status_label.configure(fg=MINT)
                    self.remaining.set('Færdig');self.elapsed.set(clock(seconds))
                    self.badge.set('●  FÆRDIG');self.result_button['state']='normal'
                elif kind=='error':
                    self.status.set(value);self.status_label.configure(fg='#ffb9bf')
                    self.badge.set('●  STOPPET' if self.stop.is_set() else '●  KRÆVER HANDLING')
                    self.remaining.set('—')
                elif kind=='finished':
                    self.running=False;self.cancel_button['state']='disabled'
                    for w in (self.start_button,self.choose_button,self.folder_button,self.source_entry,self.folder_entry):w['state']='normal'
                    self.rate_box['state']='readonly'
        except queue.Empty:pass
        self.after(150,self.poll)

    def close(self):
        if self.running:messagebox.showinfo('Konvertering i gang','Brug Stop, og vent på at jobbet afsluttes, før du lukker.')
        elif self.remote_panel.agent and self.remote_panel.agent.busy:
            messagebox.showinfo('FjordSeed-job i gang','Afbryd forbindelsen under FjordSeed, og vent på at jobbet stopper.')
        else:
            if self.remote_panel.agent:self.remote_panel.agent.disconnect()
            self.destroy()
