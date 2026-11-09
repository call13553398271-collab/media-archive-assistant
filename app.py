import datetime as dt, json, os, pathlib, queue, sys, threading, time, uuid
import tkinter as tk
from tkinter import ttk,filedialog,messagebox
from PIL import Image,ImageTk
from core import DEFAULTS,DEFAULT_TEMPLATE,EXTENSIONS,LocalModel,inspect_name,render,rename_batch,undo_batch,atomic_json,validate_template,digest

APPDIR=pathlib.Path(sys.executable).parent if getattr(sys,'frozen',False) else pathlib.Path(__file__).resolve().parent

class App:
    def __init__(self,root):
        self.root=root; self.rows=[]; self.events=queue.Queue(); self.busy=False; self.cancel=threading.Event(); self.model=None; self.photos=[]; self.preview_key=None
        self.settings=DEFAULTS.copy()
        try: self.settings.update(json.loads((APPDIR/'设置.json').read_text(encoding='utf-8')))
        except (OSError,ValueError): pass
        root.title('素材归档助手 · 本地 AI'); root.geometry('1280x850'); root.minsize(1050,720); root.configure(bg='#f3f5f7')
        style=ttk.Style(); style.theme_use('clam'); style.configure('.',font=('Microsoft YaHei UI',10),background='#f3f5f7'); style.configure('Treeview',rowheight=33,background='white',fieldbackground='white'); style.configure('Treeview.Heading',font=('Microsoft YaHei UI',10,'bold'),padding=8); style.configure('TButton',padding=(12,7)); style.configure('Accent.TButton',background='#175c50',foreground='white'); style.map('Accent.TButton',background=[('active','#217968')]); style.configure('TNotebook.Tab',padding=(20,9))
        header=ttk.Frame(root,padding=(22,16)); header.pack(fill='x'); ttk.Label(header,text='素材归档助手',font=('Microsoft YaHei UI',21,'bold')).pack(side='left'); ttk.Label(header,text='本地识别 · 预览确认 · 保留原始文件名',foreground='#58666e').pack(side='left',padx=24)
        self.tabs=ttk.Notebook(root); self.tabs.pack(fill='both',expand=True,padx=18,pady=(0,10))
        self.main=ttk.Frame(self.tabs,padding=12); self.rules=ttk.Frame(self.tabs,padding=22); self.models=ttk.Frame(self.tabs,padding=22)
        for frame,label in [(self.main,'素材与预览'),(self.rules,'命名规则'),(self.models,'本地模型')]: self.tabs.add(frame,text=label)
        self.make_main(); self.make_rules(); self.make_models()
        self.status=tk.StringVar(value='导入素材后，填写地点与设备；识别只生成候选名，点击“执行改名”后才修改文件。')
        ttk.Label(root,textvariable=self.status,padding=(22,10),foreground='#344951',wraplength=1200).pack(fill='x')
        self.progress=ttk.Progressbar(root,mode='indeterminate'); self.progress.pack(fill='x',padx=20,pady=(0,10))
        self.root.protocol('WM_DELETE_WINDOW',self.close); self.root.after(100,self.poll); self.refresh()

    def make_main(self):
        bar=ttk.Frame(self.main); bar.pack(fill='x',pady=(0,12))
        self.controls=[]
        for label,command in [('导入文件',self.add_files),('导入文件夹',self.add_folder),('移除选中',self.remove),('清空列表',self.clear),('修改内容',self.edit),('撤销改名',self.undo)]:
            b=ttk.Button(bar,text=label,command=command); b.pack(side='left',padx=(0,6)); self.controls.append(b)
        self.count=tk.StringVar(value='0 条素材'); ttk.Label(bar,textvariable=self.count).pack(side='right')
        options=ttk.Frame(self.main); options.pack(fill='x',pady=(0,10))
        self.force=tk.BooleanVar(value=False); ttk.Checkbutton(options,text='重新识别已有画面名称',variable=self.force).pack(side='left')
        ttk.Label(options,text='默认保留已归档的内容名；按住 Ctrl / Shift 可多选。',foreground='#67747b').pack(side='left',padx=20)
        pane=ttk.Panedwindow(self.main,orient='vertical'); pane.pack(fill='both',expand=True)
        table=ttk.Frame(pane); pane.add(table,weight=3)
        self.tree=ttk.Treeview(table,columns=('content','date','name','new','status'),show='headings',selectmode='extended')
        for key,label,width in [('content','画面内容（双击修改）',195),('date','拍摄日期',95),('name','当前文件名',240),('new','新文件名预览',370),('status','状态',115)]: self.tree.heading(key,text=label); self.tree.column(key,width=width,minwidth=65)
        scroll=ttk.Scrollbar(table,orient='vertical',command=self.tree.yview); horizontal=ttk.Scrollbar(table,orient='horizontal',command=self.tree.xview); self.tree.configure(yscrollcommand=scroll.set,xscrollcommand=horizontal.set)
        self.tree.grid(row=0,column=0,sticky='nsew'); scroll.grid(row=0,column=1,sticky='ns'); horizontal.grid(row=1,column=0,sticky='ew'); table.rowconfigure(0,weight=1); table.columnconfigure(0,weight=1)
        self.tree.bind('<Double-1>',lambda event:self.edit()); self.tree.bind('<<TreeviewSelect>>',lambda event:self.show_preview())
        self.preview=ttk.Frame(pane,padding=(0,10)); pane.add(self.preview,weight=1)
        self.preview_title=ttk.Label(self.preview,text='选择一条素材，点击“查看画面”生成三帧预览。'); self.preview_title.pack(anchor='w')
        self.pictures=ttk.Frame(self.preview); self.pictures.pack(fill='both',expand=True)
        bottom=ttk.Frame(self.main); bottom.pack(fill='x',pady=(12,0))
        for label,command in [('查看画面',self.load_preview),('打开所在文件夹',self.open_folder)]:
            b=ttk.Button(bottom,text=label,command=command); b.pack(side='left',padx=(0,8)); self.controls.append(b)
        self.stop=ttk.Button(bottom,text='停止识别',command=self.cancel.set,state='disabled'); self.stop.pack(side='left')
        self.rename=ttk.Button(bottom,text='执行改名',command=self.rename_files,style='Accent.TButton'); self.rename.pack(side='right',padx=(8,0)); self.controls.append(self.rename)
        self.recognize=ttk.Button(bottom,text='AI 识别候选名',command=self.recognize_files,style='Accent.TButton'); self.recognize.pack(side='right'); self.controls.append(self.recognize)

    def make_rules(self):
        self.vars={}
        ttk.Label(self.rules,text='默认沿用目前规则，可随时修改',font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w',pady=(0,14))
        ttk.Label(self.rules,text='地点或项目、设备留空时沿用文件已有字段；新素材需自行填写。日期留空时优先使用原文件名日期，其次读取视频拍摄元数据。',wraplength=1050).pack(anchor='w',pady=(0,16))
        grid=ttk.Frame(self.rules); grid.pack(fill='x')
        fields=[('project','地点或项目','例如：示例项目'),('device','设备代号','例如：P3 / A7M4'),('date','拍摄日期','留空自动判断；手动输入 YYYYMMDD'),('start','起始序号','按列表导入顺序编号；可使用001、0001等格式'),('template','命名模板','使用下方字段组合；扩展名缺失时自动补上')]
        for i,(key,label,hint) in enumerate(fields):
            ttk.Label(grid,text=label).grid(row=i,column=0,sticky='w',pady=9)
            self.vars[key]=tk.StringVar(value=str(self.settings[key])); ttk.Entry(grid,textvariable=self.vars[key],width=75 if key=='template' else 40).grid(row=i,column=1,sticky='ew',padx=16,pady=9)
            ttk.Label(grid,text=hint,foreground='#67747b').grid(row=i,column=2,sticky='w',pady=9)
            self.vars[key].trace_add('write',lambda *args:self.refresh())
        grid.columnconfigure(1,weight=1)
        self.keep_seq=tk.BooleanVar(value=self.settings['keep_seq']); ttk.Checkbutton(self.rules,text='已归档素材保留原序号（新素材仍从起始序号编号）',variable=self.keep_seq,command=self.refresh).pack(anchor='w',pady=14)
        ttk.Label(self.rules,text='可用字段',font=('Microsoft YaHei UI',12,'bold')).pack(anchor='w',pady=(14,8))
        ttk.Label(self.rules,text='{project} 地点或项目    {content} 画面内容    {device} 设备    {date} 拍摄日期\n{seq:03d} 三位序号    {seq:04d} 四位序号    {original} 完整原始文件名\n{stem} 原始文件名（不含扩展名）    {ext} 扩展名（含小数点）',justify='left').pack(anchor='w')
        self.rule_example=tk.StringVar(); ttk.Label(self.rules,textvariable=self.rule_example,foreground='#175c50',wraplength=1050).pack(anchor='w',pady=20)
        bar=ttk.Frame(self.rules); bar.pack(anchor='w')
        for label,cmd in [('保存规则',self.save_settings),('恢复默认模板',self.restore_template),('导出规则说明',self.export_rules)]: ttk.Button(bar,text=label,command=cmd).pack(side='left',padx=(0,10))
        ttk.Label(self.rules,text='建议让 {original} 留在末尾。若删除该字段，对照记录仍会保存改名前后的名称。\n日期无法核实时使用 00000000，并在列表中提示核实。规则修改会立即更新列表预览。',foreground='#67747b',wraplength=1050).pack(anchor='w',pady=20)

    def make_models(self):
        ttk.Label(self.models,text='自动调用本机 Qwen3-VL 4B',font=('Microsoft YaHei UI',16,'bold')).pack(anchor='w',pady=(0,16))
        ttk.Label(self.models,text='点击识别时会自动启动便携模型服务。素材只通过本机回环地址发送给模型，不上传到云端。',wraplength=1000).pack(anchor='w',pady=(0,18))
        for key,label in [('models_dir','模型存储目录'),('model','模型名称'),('port','本机服务端口')]:
            row=ttk.Frame(self.models); row.pack(fill='x',pady=9); ttk.Label(row,text=label,width=16).pack(side='left'); self.vars[key]=tk.StringVar(value=str(self.settings[key])); ttk.Entry(row,textvariable=self.vars[key],width=65).pack(side='left',padx=10)
            if key=='models_dir': ttk.Button(row,text='选择目录',command=self.choose_models).pack(side='left')
        bar=ttk.Frame(self.models); bar.pack(anchor='w',pady=20)
        ttk.Button(bar,text='检测并自动启动模型',command=self.check_model).pack(side='left',padx=(0,10)); ttk.Button(bar,text='保存设置',command=self.save_settings).pack(side='left')
        ttk.Label(self.models,text='首次模型加载可能需要约一分钟；后续视频通常更快。\n默认每条抽取15%、50%、85%三个位置，用于生成画面检索摘要。\n这不等于逐帧分析，也不识别口播的具体话题。食品细分、店名和小字仍建议复核。\n关闭本软件时，会停止由本软件启动的模型服务；已有外部服务不会被关闭。',foreground='#67747b',wraplength=1050).pack(anchor='w',pady=15)

    def current_settings(self):
        s=self.settings.copy()
        for key,var in self.vars.items(): s[key]=var.get().strip()
        try: s['start']=int(s['start']); s['port']=int(s['port'])
        except ValueError: raise ValueError('起始序号和端口必须是整数')
        if s['start']<1: raise ValueError('起始序号至少为1')
        s['keep_seq']=self.keep_seq.get(); validate_template(s['template']); return s

    def save_settings(self,quiet=False):
        try: self.settings=self.current_settings(); atomic_json(APPDIR/'设置.json',self.settings)
        except Exception as e: messagebox.showerror('设置未保存',str(e)); return False
        if not quiet: self.status.set('设置已保存，下次启动会自动载入。')
        return True

    def restore_template(self): self.vars['template'].set(DEFAULT_TEMPLATE); self.keep_seq.set(True); self.refresh()
    def choose_models(self):
        path=filedialog.askdirectory(title='选择含 blobs 和 manifests 的模型目录')
        if path: self.vars['models_dir'].set(path)
    def export_rules(self):
        try: s=self.current_settings()
        except Exception as e: messagebox.showerror('规则有误',str(e)); return
        path=filedialog.asksaveasfilename(title='保存命名规则',initialfile='00_素材命名规则.txt',defaultextension='.txt',filetypes=[('文本文件','*.txt')])
        if path:
            pathlib.Path(path).write_text('素材归档命名规则\n\n模板：'+s['template']+'\n\n{project}地点或项目；{content}画面内容；{device}设备；{seq:03d}三位序号；{date}拍摄日期；{original}完整原始文件名；{stem}原始文件名不含扩展名；{ext}扩展名。\n\n设置：\n'+json.dumps(s,ensure_ascii=False,indent=2)+'\n\n识别只生成候选名，预览确认后才改名。默认保留原始文件名，日期无法核实时为00000000。改名记录包含SHA-256，支持撤销。\n',encoding='utf-8-sig'); self.status.set('命名规则已导出：'+path)

    def add_files(self):
        paths=filedialog.askopenfilenames(title='选择视频素材',filetypes=[('视频文件','*.mp4 *.MP4 *.mov *.MOV *.mkv *.avi *.m4v *.mts *.m2ts *.webm *.wmv'),('所有文件','*.*')]); self.add(paths)
    def add_folder(self):
        path=filedialog.askdirectory(title='选择素材文件夹（含子文件夹）')
        if not path: return
        paths=[]
        for directory,dirs,files in os.walk(path,followlinks=False):
            dirs[:]=[d for d in dirs if d not in {'归档记录','运行数据','runtime','tools'} and not pathlib.Path(directory,d).is_symlink()]
            paths.extend(str(pathlib.Path(directory,name)) for name in sorted(files) if pathlib.Path(name).suffix.lower() in EXTENSIONS)
        self.add(sorted(paths))
    def add(self,paths):
        if self.busy: return
        known={str(pathlib.Path(r['path']).absolute()).casefold() for r in self.rows}
        for p in paths:
            p=str(pathlib.Path(p).absolute())
            if pathlib.Path(p).suffix.lower() not in EXTENSIONS or p.casefold() in known: continue
            info=inspect_name(p); content=info['content'] if info['content'] not in {'空镜','素材','视频'} else ''; self.rows.append(dict(id=uuid.uuid4().hex,path=p,info=info,content=content,status='沿用已有内容名' if content else '待识别',frames=[])); known.add(p.casefold())
        self.refresh()
    def remove(self):
        if self.busy:return
        selected=set(self.tree.selection()); self.rows=[r for r in self.rows if r['id'] not in selected]; self.refresh()
    def clear(self):
        if not self.busy: self.rows=[]; self.refresh(); self.show_preview()
    def selected(self):
        ids=set(self.tree.selection()); return [r for r in self.rows if r['id'] in ids]
    def edit(self):
        selected=self.selected()
        if self.busy or not selected:return
        win=tk.Toplevel(self.root); win.title('修改画面内容'); win.transient(self.root); win.grab_set(); win.geometry('650x175'); ttk.Label(win,text=f'为选中的 {len(selected)} 条素材设置画面内容',padding=14).pack(anchor='w'); var=tk.StringVar(value=selected[0]['content']); entry=ttk.Entry(win,textvariable=var,width=65); entry.pack(padx=15,fill='x'); entry.focus_set(); entry.select_range(0,'end')
        def done():
            if not var.get().strip():return
            for r in selected:r.update(content=var.get().strip(),status='已手动修改')
            win.destroy(); self.refresh()
        ttk.Button(win,text='保存修改',command=done).pack(pady=12); entry.bind('<Return>',lambda event:done())

    def refresh(self):
        if not hasattr(self,'rule_example') or not hasattr(self,'keep_seq'):return
        try: s=self.current_settings(); error=None
        except Exception as e:s=None; error=str(e)
        example=dict(path='示例.MP4',content='商场中庭人物口播',info=dict(project='示例项目',device='P3',date='20260929',original='DJI_20260929180136_0438_D.MP4'))
        try:self.rule_example.set('示例：'+render(example,s or DEFAULTS,1) if not error else '模板提示：'+error)
        except Exception as e:self.rule_example.set('模板提示：'+str(e))
        selection=self.tree.selection(); existing=set(self.tree.get_children()); current={r['id'] for r in self.rows}
        for removed in existing-current:self.tree.delete(removed)
        targets={}
        for i,r in enumerate(self.rows):
            try:
                if error:raise ValueError(error)
                r['new']=render(r,s,s['start']+i); r['error']=''
                target=str(pathlib.Path(r['path']).with_name(r['new'])).casefold(); targets.setdefault(target,[]).append(r)
                if pathlib.Path(r['path']).with_name(r['new']).exists() and str(pathlib.Path(r['path'])).casefold()!=target:r['error']='目标名称已存在'
            except Exception as e:r['new']=''; r['error']=str(e)
        for group in targets.values():
            if len(group)>1:
                for r in group:r['error']='预览名称重复，请调整序号或模板'
        for r in self.rows:
            date=(s or {}).get('date') or r['info']['date'] or '00000000'
            status=r['error'] or ('日期待核实' if date=='00000000' else r['status'])
            values=(r['content'],date,pathlib.Path(r['path']).name,r['new'],status)
            if r['id'] in existing:self.tree.item(r['id'],values=values)
            else:self.tree.insert('', 'end',iid=r['id'],values=values)
        if selection:self.tree.selection_set([x for x in selection if x in current])
        self.count.set(f'{len(self.rows)} 条素材')

    def show_preview(self):
        selected=self.selected(); r=selected[0] if selected else None
        key=(r['id'],tuple(r['frames'])) if r else None
        if key==self.preview_key:return
        self.preview_key=key
        for widget in self.pictures.winfo_children():widget.destroy()
        self.photos=[]
        self.preview_title.configure(text=(pathlib.Path(r['path']).name if r else '选择一条素材查看画面'))
        if not r:return
        if not r['frames']:ttk.Label(self.pictures,text='点击“查看画面”或进行 AI 识别后，这里显示15%、50%、85%三个位置的预览。',foreground='#67747b').pack(anchor='w',pady=12);return
        for path in r['frames']:
            try:
                with Image.open(path) as im:im.thumbnail((310,175)); photo=ImageTk.PhotoImage(im.copy())
                self.photos.append(photo); ttk.Label(self.pictures,image=photo).pack(side='left',padx=8,pady=5)
            except OSError:pass
    def open_folder(self):
        selected=self.selected()
        if selected:os.startfile(str(pathlib.Path(selected[0]['path']).parent))

    def get_model(self,s):
        if self.model and self.model.settings!=s:self.model.close(); self.model=None
        if not self.model:self.model=LocalModel(APPDIR,s)
        return self.model
    def start(self,work,kind):
        if self.busy:return
        self.busy=True; self.cancel.clear()
        for b in self.controls:b.configure(state='disabled')
        for tab in (1,2):self.tabs.tab(tab,state='disabled')
        self.stop.configure(state='normal' if kind=='recognize' else 'disabled'); self.progress.start(12)
        def run():
            try:result=work(); self.events.put(('done',kind,result))
            except Exception as e:self.events.put(('error',str(e)))
        threading.Thread(target=run,daemon=True).start()
    def notify(self,text):self.events.put(('status',text))
    def check_model(self):
        if self.busy or not self.save_settings(quiet=True):return
        s=self.current_settings(); self.start(lambda:self.get_model(s).ensure(self.notify),'check')
    def load_preview(self):
        selected=self.selected()
        if not selected or self.busy:return
        r=selected[0]; s=self.current_settings()
        def work():
            model=self.get_model(s); paths,duration,created=model.frames(r['path'],APPDIR/'运行数据'/'预览'/r['id']); self.events.put(('row',r['id'],dict(frames=[str(p) for p in paths]))); return '预览已生成'
        self.start(work,'preview')
    def recognize_files(self):
        if self.busy or not self.rows:return
        if not self.save_settings(quiet=True):return
        s=self.current_settings(); selected=self.selected(); candidates=selected or self.rows
        jobs=[r.copy() for r in candidates if self.force.get() or not r['content']]
        if not jobs:messagebox.showinfo('无需重复识别','所选素材已有内容名称。勾选“重新识别已有画面名称”可重新生成。');return
        def work():
            model=self.get_model(s); model.ensure(self.notify); successes=0; failures=0; total=time.perf_counter()
            for i,r in enumerate(jobs,1):
                if self.cancel.is_set():break
                self.notify(f'正在识别 {i}/{len(jobs)} · '+pathlib.Path(r['path']).name)
                try:
                    start=time.perf_counter(); paths,duration,created=model.frames(r['path'],APPDIR/'运行数据'/'预览'/r['id']); content=model.recognize(paths); updates=dict(content=content,frames=[str(p) for p in paths],status=f'AI候选 · {time.perf_counter()-start:.1f}秒')
                    if not r['info']['date'] and created:
                        try:
                            date=dt.datetime.fromisoformat(created.replace('Z','+00:00')).astimezone(dt.timezone(dt.timedelta(hours=8))).strftime('%Y%m%d'); info=r['info'].copy(); info['date']=date; updates['info']=info
                        except ValueError:pass
                    self.events.put(('row',r['id'],updates)); successes+=1
                except Exception as e:failures+=1; self.events.put(('row',r['id'],dict(status='识别失败：'+str(e)[:100])))
            return f'识别结束：成功{successes}条，失败{failures}条，共{time.perf_counter()-total:.1f}秒。请复核候选名称后执行改名。'
        self.start(work,'recognize')
    def rename_files(self):
        if self.busy or not self.rows:return
        self.refresh(); errors=[r for r in self.rows if r['error']]
        if errors:messagebox.showerror('暂不能改名',f'有{len(errors)}条素材需要处理：\n'+errors[0]['error']);return
        if not self.save_settings(quiet=True):return
        changes=[r for r in self.rows if pathlib.Path(r['path']).name.casefold()!=r['new'].casefold()]
        if not changes:messagebox.showinfo('无需改名','当前名称与预览一致。');return
        warning='\n有日期未核实，将使用00000000。' if any(not (self.settings['date'] or r['info']['date']) for r in changes) else ''
        if not messagebox.askokcancel('确认执行预览中的改名',f'将按预览修改 {len(changes)} 个文件名。\n请确认已复核画面内容。会保存对照记录并校验文件内容。'+warning):return
        pairs=[(r['path'],r['new']) for r in changes]
        def work():journal,count=rename_batch(pairs,self.settings,self.notify);return dict(journal=str(journal),count=count,pairs=pairs)
        self.start(work,'rename')
    def undo(self):
        if self.busy:return
        path=filedialog.askopenfilename(title='选择本软件生成的 rename_*.json 改名记录',filetypes=[('改名记录','rename_*.json')])
        if not path:return
        try:
            record=json.loads(pathlib.Path(path).read_text(encoding='utf-8')); entries=record.get('entries',[])
            detail='\n'.join(pathlib.Path(e['target']).name+' → '+pathlib.Path(e['source']).name for e in entries[:3])
            if not messagebox.askokcancel('确认撤销',f'将恢复记录中的 {len(entries)} 个原名称：\n\n'+detail):return
        except Exception as e:messagebox.showerror('记录无效',str(e));return
        self.start(lambda:(undo_batch(path,self.notify),path),'undo')
    def poll(self):
        try:
            while True:
                event=self.events.get_nowait()
                if event[0]=='status':self.status.set(event[1])
                elif event[0]=='row':
                    for r in self.rows:
                        if r['id']==event[1]:r.update(event[2]);break
                    self.refresh(); self.show_preview()
                elif event[0] in ('done','error'):
                    self.busy=False; self.progress.stop(); self.stop.configure(state='disabled')
                    for b in self.controls:b.configure(state='normal')
                    for tab in (1,2):self.tabs.tab(tab,state='normal')
                    if event[0]=='error':self.status.set('操作未完成：'+event[1]); messagebox.showerror('操作未完成',event[1])
                    else:
                        kind,result=event[1:]
                        if kind=='rename':
                            paths={str(pathlib.Path(src)):str(pathlib.Path(src).with_name(name)) for src,name in result['pairs']}
                            for r in self.rows:
                                if r['path'] in paths:r['path']=paths[r['path']];r['info']=inspect_name(r['path']);r['status']='已改名并校验'
                            self.status.set(f'完成 {result["count"]} 条改名。撤销记录：{result["journal"]}')
                        elif kind=='undo':self.rows=[];self.status.set(f'已撤销{result[0]}条改名，请重新导入素材。')
                        else:self.status.set(str(result))
                    self.refresh();self.show_preview()
        except queue.Empty:pass
        self.root.after(100,self.poll)
    def close(self):
        if self.busy:messagebox.showinfo('仍在处理','请先停止识别并等待当前文件完成，或等待改名/撤销结束后退出。');return
        self.save_settings(quiet=True)
        if self.model:self.model.close()
        self.root.destroy()

def main():
    if '--ui-self-test' in sys.argv:
        import tempfile,types
        from tkinterdnd2 import TkinterDnD
        from design_ui import DesignedApp
        from core import export_batch
        report=pathlib.Path(sys.argv[sys.argv.index('--ui-self-test')+1]);root=None
        try:
            root=TkinterDnD.Tk();root.withdraw();ui=DesignedApp(root);ui.save_settings=lambda *args,**kwargs:True
            with tempfile.TemporaryDirectory(prefix='archive-ui-test-') as temp:
                folder=pathlib.Path(temp);source=folder/'素材 folder';source.mkdir();video=source/'项目_空镜_P3_042_20260929__camera.MP4';video.write_bytes(b'package-check-original')
                event=types.SimpleNamespace(data=root.tk.call('list',str(source),str(video)))
                ui.on_drop(event);assert len(ui.rows)==1 and not ui.rows[0]['content'];row=ui.rows[0];row['content']='商场入口'
                for key in ('project','device','date'):ui.vars[key].set('')
                ui.refresh();assert '_042_' in row['new']
                for choice in ('dark','light','system'):ui.theme_mode.set(choice);ui.theme_changed();root.update_idletasks()
                out=folder/'export';out.mkdir();ui.output_mode.set('export');ui.output_dir.set(str(out));ui.output_changed();assert not row['error']
                journal,count=export_batch([(video,row['new'])],out,ui.current_settings());assert count==1 and video.read_bytes()==b'package-check-original'
                atomic_json(report,dict(ok=True,native_dnd_loaded=True,folder_drop_and_dedup=True,rounded_buttons=True,three_appearances=True,export_verified=True,original_retained=True,sequence_preserved=True))
        except Exception as e:atomic_json(report,dict(ok=False,error=str(e)))
        finally:
            if root:
                for callback in root.tk.call('after','info'):root.after_cancel(callback)
                root.destroy()
        return
    if '--self-test' in sys.argv:
        # Noninteractive diagnostic for the exact packaged runtime, never renames input.
        index=sys.argv.index('--self-test'); source=pathlib.Path(sys.argv[index+1]); report=pathlib.Path(sys.argv[index+2]); model=LocalModel(APPDIR,DEFAULTS)
        try:
            before=digest(source); started=time.perf_counter(); ready=model.ensure(lambda text:None)
            frames,duration,created=model.frames(source,APPDIR/'运行数据'/'自检预览')
            content=model.recognize(frames)
            assert digest(source)==before,'Input content changed during test'
            atomic_json(report,dict(ok=True,model=DEFAULTS['model'],content=content,duration=duration,seconds=round(time.perf_counter()-started,3),input=str(source),input_unchanged=True))
        except Exception as e:atomic_json(report,dict(ok=False,error=str(e)))
        finally:model.close()
        return
    try:
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:pass
    mutex=None
    try:
        import ctypes
        mutex=ctypes.windll.kernel32.CreateMutexW(None,False,'Local\\CodexMediaArchiveHelperV1')
        if ctypes.windll.kernel32.GetLastError()==183:
            ctypes.windll.user32.MessageBoxW(None,'素材归档助手已经运行，请切换到已打开的窗口。','素材归档助手',0);return
    except Exception:pass
    from design_ui import DesignedApp
    from tkinterdnd2 import TkinterDnD
    root=TkinterDnD.Tk();DesignedApp(root);root.mainloop()

if __name__=='__main__':main()
