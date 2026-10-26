"""Pairing and remote-job view, sharing the desktop GPU lock."""
import json
from pathlib import Path
import threading
import tkinter as tk
from tkinter import ttk, filedialog
from remote_agent import Agent, atomic, connection_details
from windows_secret import protect, unprotect


class RemotePanel:
    def __init__(self,app):
        self.app=app;self.agent=None;self.connected=False
        self.path=app.root_dir/'worker-settings.json'
        try:settings=json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError,ValueError):settings={}
        token=''
        if settings.get('token_dpapi'):
            try:token=unprotect(settings['token_dpapi'])
            except (OSError,ValueError):pass
        self.url=tk.StringVar(value=settings.get('server',''))
        self.token=tk.StringVar(value=token)
        self.cache=tk.StringVar(value=settings.get('cache',str(Path.home()/'Videos'/'FjordEncode'/'worker-cache')))
        self.auto=tk.BooleanVar(value=bool(settings.get('auto',False)))
        self.status=tk.StringVar(value='Forbind pc’en med adressen og pc-tokenet fra FjordSeed.')
        self.percent=tk.StringVar(value='0 %')
        self.quality=tk.StringVar(value='Afventer et job fra FjordSeed')
        self.metrics=tk.StringVar(value='Pc’en henter selv jobs · ingen indgående port er nødvendig')
        bg='#0b1220';muted='#9caec5'
        self.frame=tk.Frame(app,bg=bg,padx=26,pady=20)
        app.label(self.frame,'Konvertér for FjordSeed',bg=bg,font=('Segoe UI',25,'bold')).pack(anchor='w',pady=(6,7))
        app.label(self.frame,'Brug pc’ens GPU, og send den færdige film tilbage til biblioteket. Kvaliteten vælges i FjordSeed.',bg=bg,fg=muted,font=('Segoe UI',11)).pack(anchor='w',pady=(0,20))
        card=app.card(self.frame);card.pack(fill='x');card.columnconfigure(0,weight=1)
        app.label(card,'01  /  FORBIND PC OG SERVER',fg=muted,font=('Segoe UI',9,'bold')).grid(row=0,column=0,columnspan=2,sticky='w',pady=(0,14))
        app.label(card,'FjordSeed-adresse (udfyldes fra forbindelseskoden)').grid(row=1,column=0,columnspan=2,sticky='w')
        self.url_entry=ttk.Entry(card,textvariable=self.url);self.url_entry.grid(row=2,column=0,columnspan=2,sticky='ew',pady=(6,12))
        app.label(card,'Forbindelseskode eller pc-token').grid(row=3,column=0,columnspan=2,sticky='w')
        self.token.trace_add('write',self.pairing_changed)
        self.token_entry=ttk.Entry(card,textvariable=self.token,show='•');self.token_entry.grid(row=4,column=0,columnspan=2,sticky='ew',pady=(6,8))
        app.label(card,'Kopiér forbindelseskoden fra FjordSeed → Indstillinger → Konvertering.\nAdressen udfyldes automatisk. Adgangen gemmes krypteret til denne Windows-bruger.',fg=muted,font=('Segoe UI',9),justify='left').grid(row=5,column=0,columnspan=2,sticky='w',pady=(0,14))
        app.label(card,'Midlertidig plads på pc’en').grid(row=6,column=0,columnspan=2,sticky='w')
        self.cache_entry=ttk.Entry(card,textvariable=self.cache);self.cache_entry.grid(row=7,column=0,sticky='ew',padx=(0,10),pady=(6,10))
        self.cache_button=ttk.Button(card,text='Vælg …',command=self.choose_cache);self.cache_button.grid(row=7,column=1,pady=(6,10))
        self.auto_button=tk.Checkbutton(card,text='Forbind automatisk, når programmet åbnes',variable=self.auto,bg='#121e30',fg='#edf3fb',activebackground='#121e30',activeforeground='#edf3fb',selectcolor=bg,highlightthickness=0,font=('Segoe UI',10))
        self.auto_button.grid(row=8,column=0,columnspan=2,sticky='w')
        app.label(card,'Brug HTTPS over internettet. HTTP kan bruges på dit betroede lokalnet.',fg=muted,font=('Segoe UI',9)).grid(row=9,column=0,columnspan=2,sticky='w',pady=(8,0))
        progress=app.card(self.frame);progress.pack(fill='x',pady=(16,0))
        app.label(progress,'02  /  JOB FRA FJORDSEED',fg=muted,font=('Segoe UI',9,'bold')).pack(anchor='w',pady=(0,10))
        app.label(progress,'Kvalitet fra FjordSeed',fg=muted,font=('Segoe UI',9)).pack(anchor='w')
        ttk.Entry(progress,textvariable=self.quality,state='readonly').pack(fill='x',pady=(6,10))
        app.label(progress,textvariable=self.status,wraplength=870,justify='left',font=('Segoe UI',11,'bold')).pack(anchor='w')
        app.label(progress,textvariable=self.percent,fg='#7ce4c4',font=('Segoe UI',20,'bold')).pack(anchor='w',pady=(10,8))
        self.bar=ttk.Progressbar(progress,maximum=100);self.bar.pack(fill='x')
        app.label(progress,textvariable=self.metrics,fg=muted,font=('Segoe UI',9)).pack(anchor='w',pady=(10,0))
        controls=tk.Frame(self.frame,bg=bg);controls.pack(fill='x',pady=(16,0))
        self.connect_button=ttk.Button(controls,text='Forbind og hent jobs →',style='Primary.TButton',command=self.connect);self.connect_button.pack(side='right')
        self.stop_button=ttk.Button(controls,text='Afbryd forbindelse',state='disabled',command=self.disconnect);self.stop_button.pack(side='right',padx=10)
        app.label(self.frame,'Originalerne bliver på serveren til seeding. Pc-bufferen ryddes efter serverens kvittering.',bg=bg,fg=muted,font=('Segoe UI',9),wraplength=900,justify='left').pack(anchor='w',pady=(14,0))
        if self.auto.get() and token and self.url.get():app.after(1000,self.connect)

    def pairing_changed(self,*_):
        if not self.token.get().strip().startswith('fsp1_'):return
        try:
            server,token=connection_details('',self.token.get())
            self.url.set(server)
            self.status.set('Adressen er hentet fra koden. Tryk Forbind og hent jobs.')
        except ValueError as exc:self.status.set(str(exc))

    def choose_cache(self):
        folder=filedialog.askdirectory(title='Midlertidig plads til FjordSeed-jobs')
        if folder:self.cache.set(folder)

    def connect(self):
        if self.connected:return
        app=self.app
        try:
            server,token=connection_details(self.url.get(),self.token.get())
            agent=Agent(server,token,self.cache.get(),app.gpu_lock,app.worker,app.cancelled,lambda k,v:app.events.put(('remote',(k,v))))
            atomic(self.path,{'server':agent.server,'token_dpapi':protect(agent.token),'cache':str(agent.cache),'auto':self.auto.get()})
        except (ValueError,OSError) as exc:self.status.set(str(exc));return
        self.agent=agent;self.connected=True
        for w in (self.connect_button,self.url_entry,self.token_entry,self.cache_entry,self.cache_button,self.auto_button):w['state']='disabled'
        self.stop_button['state']='normal'
        threading.Thread(target=agent.run,daemon=True).start()

    def disconnect(self):
        if self.agent:self.agent.disconnect()
        self.status.set('Afbryder forbindelsen …');self.stop_button['state']='disabled'

    def event(self,kind,value):
        if kind=='settings':
            from fjord_ui import QUALITY_CHOICES
            rate=value['bitrate']
            self.quality.set(QUALITY_CHOICES.get(rate,f'{rate} Mbps – tidligere valg'))
        elif kind in ('status','error'):self.status.set(value)
        elif kind=='started':self.app.notify_started(value)
        elif kind=='progress':self.bar['value']=value;self.percent.set(f'{value:.0f} %')
        elif kind=='metrics':
            self.metrics.set(f'{value[1]:.1f} fps · GPU-konvertering')
            self.app.notify_eta(value[2])
        elif kind=='finished':
            self.connected=False
            for w in (self.connect_button,self.url_entry,self.token_entry,self.cache_entry,self.cache_button,self.auto_button):w['state']='normal'
            self.stop_button['state']='disabled'
