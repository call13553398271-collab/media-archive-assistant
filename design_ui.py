"""Desktop presentation layer. File operations and model calls stay in app/core."""
import json, os, pathlib, queue, re, sys, threading, tkinter as tk
from tkinter import ttk, messagebox, filedialog, font as tkfont
from PIL import Image, ImageTk, ImageDraw
from app import App, APPDIR
from core import DEFAULTS,import_paths,export_batch,render

PALETTES={
    'light':dict(canvas='#f5f6f8',surface='#ffffff',text='#20252b',muted='#5d6672',accent='#24634f',divider='#d4d9df',selection='#e6f0eb',sidebar='#eef1f4',onaccent='#ffffff'),
    'dark':dict(canvas='#181b20',surface='#22262d',text='#f2f4f7',muted='#b0bac7',accent='#86c8ac',divider='#46515e',selection='#2f483e',sidebar='#1e2228',onaccent='#18251f')}

def system_appearance():
    try:
        import winreg,ctypes
        class HC(ctypes.Structure):_fields_=[('size',ctypes.c_uint),('flags',ctypes.c_uint),('scheme',ctypes.c_wchar_p)]
        hc=HC();hc.size=ctypes.sizeof(HC)
        ctypes.windll.user32.SystemParametersInfoW(0x42,hc.size,ctypes.byref(hc),0)
        if hc.flags&1:return 'contrast'
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,r'Software\Microsoft\Windows\CurrentVersion\Themes\Personalize') as key:
            return 'light' if winreg.QueryValueEx(key,'AppsUseLightTheme')[0] else 'dark'
    except Exception:return 'light'

class DesignedApp(App):
    def __init__(self,root):
        self.root=root;self.rows=[];self.events=queue.Queue();self.busy=False;self.cancel=threading.Event();self.model=None;self.photos=[];self.preview_key=None
        self.settings=DEFAULTS.copy()
        try:self.settings.update(json.loads((APPDIR/'设置.json').read_text(encoding='utf-8')))
        except (OSError,ValueError):pass
        self.theme_mode=tk.StringVar(value=self.settings.get('appearance','system'));self.output_mode=tk.StringVar(value=self.settings.get('output_mode','original'));self.output_dir=tk.StringVar(value=self.settings.get('output_dir',''));self.canvases=[];self.button_images=[]
        self.appearance=self.selected_appearance();self.zoom=1.;self.fonts={};self.pages=[];self.nav=[];self.form_controls=[];self.controls=[];self.page_index=0
        self.p=PALETTES['dark' if self.appearance=='dark' else 'light'].copy()
        if self.appearance=='contrast':self.p.update(canvas='SystemWindow',surface='SystemWindow',text='SystemWindowText',muted='SystemWindowText',accent='SystemHighlight',selection='SystemHighlight',onaccent='SystemHighlightText',divider='SystemWindowText',sidebar='SystemWindow')
        root.title('素材归档助手');root.geometry('1320x900');root.minsize(1000,800)
        for name,size,weight in [('body',11,'normal'),('small',10,'normal'),('title',22,'bold'),('section',13,'bold'),('strong',11,'bold'),('code',11,'normal')]:
            self.fonts[name]=tkfont.Font(root,family='Consolas' if name=='code' else 'Microsoft YaHei UI',size=size,weight=weight)
        self.apply_theme()
        self.shell=ttk.Frame(root);self.shell.pack(fill='both',expand=True)
        self.sidebar=ttk.Frame(self.shell,style='Side.TFrame',width=174,padding=(16,25,16,18));self.sidebar.pack(side='left',fill='y');self.sidebar.pack_propagate(False)
        ttk.Label(self.sidebar,text='素材归档',font=self.fonts['section'],style='Side.TLabel').pack(anchor='w',padx=8)
        ttk.Frame(self.sidebar,style='Side.TFrame',height=24).pack()
        for index,label in enumerate(('素材工作台','命名规则','软件设置')):
            button=ttk.Button(self.sidebar,text=label,style='Nav.TButton',command=lambda i=index:self.navigate(i),takefocus=True);button.pack(fill='x',pady=4);self.nav.append(button)
        ttk.Label(self.sidebar,text='仅在本机处理\n保留原始素材',style='SideMuted.TLabel',justify='left').pack(side='bottom',anchor='w',padx=8,pady=6)
        ttk.Separator(self.shell,orient='vertical').pack(side='left',fill='y')
        self.workspace=ttk.Frame(self.shell,padding=(25,20,25,14));self.workspace.pack(side='left',fill='both',expand=True)
        head=ttk.Frame(self.workspace);head.pack(fill='x',pady=(0,18))
        self.page_title=tk.StringVar(value='素材工作台');ttk.Label(head,textvariable=self.page_title,font=self.fonts['title']).pack(side='left')
        ttk.Label(head,text='离线 AI  ·  4B',style='Badge.TLabel',padding=(12,6)).pack(side='right',pady=5)
        self.tabs=ttk.Notebook(self.workspace,style='Pages.TNotebook');self.tabs.pack(fill='both',expand=True)
        self.main=ttk.Frame(self.tabs);self.rules=ttk.Frame(self.tabs);self.models=ttk.Frame(self.tabs)
        for page in (self.main,self.rules,self.models):self.tabs.add(page,text='');self.pages.append(page)
        self.make_main();self.make_rules();self.make_models();self.make_menu()
        self.status=tk.StringVar(value='导入素材后生成候选名称，复核后再改名。')
        footer=ttk.Frame(self.workspace,padding=(0,12,0,0));footer.pack(side='bottom',fill='x',before=self.tabs)
        self.status_label=ttk.Label(footer,textvariable=self.status,style='Muted.TLabel',wraplength=950);self.status_label.pack(fill='x')
        self.progress=ttk.Progressbar(footer,mode='determinate',maximum=100,value=0);self.progress.pack(fill='x',pady=(8,0));self.progress.pack_forget()
        self.status.trace_add('write',self.status_changed)
        self.root.protocol('WM_DELETE_WINDOW',self.close);self.root.bind('<Configure>',self.on_resize,add='+')
        self.root.after(100,self.poll);self.root.after(1500,self.appearance_tick);self.refresh();self.navigate(0);self.enable_drop();self.output_dir.trace_add('write',lambda *args:self.refresh())

    def apply_theme(self):
        p=self.p;self.root.configure(bg=p['canvas']);s=ttk.Style();s.theme_use('clam')
        s.configure('.',font=self.fonts['body'],background=p['canvas'],foreground=p['text'])
        for name,color in [('TFrame',p['canvas']),('Surface.TFrame',p['surface']),('Side.TFrame',p['sidebar'])]:s.configure(name,background=color)
        s.configure('TLabel',background=p['canvas'],foreground=p['text']);s.configure('Muted.TLabel',foreground=p['muted']);s.configure('Surface.TLabel',background=p['surface']);s.configure('SurfaceMuted.TLabel',background=p['surface'],foreground=p['muted']);s.configure('Side.TLabel',background=p['sidebar']);s.configure('SideMuted.TLabel',background=p['sidebar'],foreground=p['muted']);s.configure('Badge.TLabel',background=p['selection'],foreground=p['text'],font=self.fonts['small'])
        s.configure('TButton',background=p['surface'],foreground=p['text'],padding=(9,3),width=0,borderwidth=1,relief='flat',focuscolor=p['accent'],focusthickness=2)
        s.map('TButton',background=[('disabled',p['canvas']),('pressed',p['selection']),('active',p['selection'])],foreground=[('disabled',p['muted'])],bordercolor=[('focus',p['accent']),('!focus',p['divider'])])
        s.configure('Primary.TButton',background=p['accent'],foreground=p['onaccent'],font=self.fonts['strong']);s.map('Primary.TButton',background=[('disabled',p['divider']),('active',p['accent']),('pressed',p['accent'])],foreground=[('disabled',p['muted']),('!disabled',p['onaccent'])])
        s.configure('Nav.TButton',anchor='w',padding=(13,12),background=p['sidebar'],borderwidth=0);s.map('Nav.TButton',background=[('selected',p['selection']),('active',p['selection'])],foreground=[('selected',p['text'])])
        s.configure('TEntry',fieldbackground=p['surface'],foreground=p['text'],padding=(10,8),borderwidth=1,insertcolor=p['text']);s.map('TEntry',bordercolor=[('focus',p['accent']),('!focus',p['divider'])])
        s.configure('Name.TEntry',padding=(5,2))
        s.map('TEntry',fieldbackground=[('readonly',p['surface']),('disabled',p['canvas']),('!disabled',p['surface'])],foreground=[('disabled',p['muted']),('!disabled',p['text'])])
        s.configure('TMenubutton',background=p['surface'],foreground=p['text'],padding=(12,8));s.map('TMenubutton',background=[('active',p['selection']),('!active',p['surface'])])
        s.configure('TCheckbutton',padding=(0,7));s.map('TCheckbutton',background=[('active',p['canvas'])])
        s.configure('Treeview',font=self.fonts['body'],rowheight=43,background=p['surface'],fieldbackground=p['surface'],foreground=p['text'],borderwidth=0)
        s.map('Treeview',background=[('selected',p['selection'])],foreground=[('selected',p['text'])]);s.configure('Treeview.Heading',font=self.fonts['strong'],padding=(10,10),background=p['canvas'],foreground=p['muted'],borderwidth=0);s.map('Treeview.Heading',background=[('active',p['selection'])])
        s.layout('Pages.TNotebook.Tab',[]);s.configure('Pages.TNotebook',background=p['canvas'],borderwidth=0,tabmargins=0)
        s.configure('Horizontal.TProgressbar',troughcolor=p['divider'],background=p['accent'],borderwidth=0,thickness=4)
        s.configure('TSeparator',background=p['divider']);s.configure('Sash',sashthickness=8,gripcount=0,background=p['canvas'])
        s.configure('TRadiobutton',background=p['canvas'],foreground=p['text'],padding=(5,7));s.map('TRadiobutton',background=[('active',p['canvas'])])
        self.rounded_styles(s)
        for canvas in getattr(self,'canvases',[]):canvas.configure(bg=p['canvas'])

    def rounded_styles(self,style):
        generation=getattr(self,'theme_generation',0)+1;self.theme_generation=generation
        def picture(fill,border):
            def rgb(color):return tuple(v//256 for v in self.root.winfo_rgb(color))
            im=Image.new('RGBA',(256,176),(0,0,0,0));draw=ImageDraw.Draw(im);draw.rounded_rectangle((2,2,253,173),radius=36,fill=rgb(fill),outline=rgb(border),width=4)
            photo=ImageTk.PhotoImage(im.resize((64,44),Image.Resampling.LANCZOS));self.button_images.append(photo);return photo
        p=self.p
        for name,normal,active,border in [('TButton',p['surface'],p['selection'],p['divider']),('Primary.TButton',p['accent'],p['accent'],p['accent']),('Nav.TButton',p['sidebar'],p['selection'],p['sidebar'])]:
            default=picture(normal,border);hover=picture(active,p['accent']);pressed=picture(active,p['accent']);disabled=picture(p['canvas'],p['divider']);focus=picture(normal,p['accent']);selected=picture(p['selection'],p['selection'])
            element=f'Round{generation}{name.replace(".","")}.border'
            style.element_create(element,'image',default,('disabled',disabled),('pressed',pressed),('focus',focus),('selected',selected),('active',hover),border=9,sticky='nsew')
            style.layout(name,[(element,{'sticky':'nsew','children':[('Button.padding',{'sticky':'nsew','children':[('Button.label',{'sticky':'nsew'})]})]})])

    def button(self,parent,text,command,primary=False,track=True):
        b=ttk.Button(parent,text=text,command=command,style='Primary.TButton' if primary else 'TButton',takefocus=True)
        if track:self.controls.append(b)
        return b

    def make_main(self):
        toolbar=ttk.Frame(self.main);toolbar.pack(fill='x',pady=(0,12))
        self.button(toolbar,'导入文件',self.add_files).pack(side='left',padx=(0,8));self.button(toolbar,'导入文件夹',self.add_folder).pack(side='left',padx=(0,8))
        more=ttk.Menubutton(toolbar,text='列表操作 ▾',padding=(12,8));more.pack(side='left');menu=tk.Menu(more,tearoff=False);menu.add_command(label='移除选中',command=self.remove);menu.add_command(label='清空列表',command=self.clear);menu.add_separator();menu.add_command(label='撤销改名…',command=self.undo);more.configure(menu=menu);self.controls.append(more)
        self.count=tk.StringVar(value='0 条素材');ttk.Label(toolbar,textvariable=self.count,style='Muted.TLabel').pack(side='right')
        self.batch_strip=ttk.Frame(self.main,style='Surface.TFrame',padding=(14,10));self.batch_strip.pack(fill='x',pady=(0,12))
        ttk.Label(self.batch_strip,text='本批信息',style='Surface.TLabel',font=self.fonts['strong']).grid(row=0,column=0,padx=(0,14),sticky='w')
        self.batch_fields=ttk.Frame(self.batch_strip,style='Surface.TFrame');self.batch_fields.grid(row=0,column=1,sticky='ew');self.batch_strip.columnconfigure(1,weight=1)
        self.batch_entries={}
        for index,(key,label,width) in enumerate([('project','地点或项目',22),('device','设备',9)]):
            ttk.Label(self.batch_fields,text=label,style='SurfaceMuted.TLabel',font=self.fonts['small']).pack(side='left',padx=(10 if index else 0,7));var=tk.StringVar(value=str(self.settings[key]));entry=ttk.Entry(self.batch_fields,textvariable=var,width=width);entry.pack(side='left');self.batch_entries[key]=(var,entry);self.form_controls.append(entry)
        self.button(self.batch_strip,'调整规则',lambda:self.navigate(1),track=False).grid(row=0,column=2,padx=(14,0))
        self.force=tk.BooleanVar(value=False)
        opts=ttk.Frame(self.main);opts.pack(fill='x',pady=(0,9))
        self.force_control=ttk.Checkbutton(opts,text='重新识别已有名称',variable=self.force);self.force_control.pack(side='left');self.form_controls.append(self.force_control)
        self.queue_summary=tk.StringVar(value='等待导入素材');ttk.Label(opts,textvariable=self.queue_summary,style='Muted.TLabel',font=self.fonts['small']).pack(side='right')
        output=ttk.Frame(self.main);output.pack(fill='x',pady=(0,10))
        ttk.Label(output,text='输出位置',font=self.fonts['small'],style='Muted.TLabel').pack(side='left',padx=(0,9))
        for text,value in [('原文件夹','original'),('指定文件夹','export')]:
            b=ttk.Radiobutton(output,text=text,value=value,variable=self.output_mode,command=self.output_changed);b.pack(side='left',padx=(0,8));self.form_controls.append(b)
        self.output_path=ttk.Entry(output,textvariable=self.output_dir,width=20);self.output_path.pack(side='left',fill='x',expand=True,padx=(0,7));self.form_controls.append(self.output_path)
        self.output_choose=self.button(output,'选择位置',self.choose_output,track=False);self.output_choose.pack(side='left');self.form_controls.append(self.output_choose)
        pane=ttk.Panedwindow(self.main,orient='horizontal');self.pane=pane;pane.pack(fill='both',expand=True)
        table=ttk.Frame(pane,style='Surface.TFrame');pane.add(table,weight=3)
        self.tree=ttk.Treeview(table,columns=('content','date','name','new','status'),show='headings',selectmode='extended',height=6)
        # Full paths are in the inspector; the table keeps the classification easy to scan.
        for key,label,width in [('content','画面内容',195),('date','拍摄日期',100),('name','来源文件',240),('new','改名预览',300),('status','状态',130)]:self.tree.heading(key,text=label);self.tree.column(key,width=width,minwidth=80,stretch=key in ('content','name','new'))
        self.tree.configure(displaycolumns=('content','date','name','status'))
        v=ttk.Scrollbar(table,orient='vertical',command=self.tree.yview);h=ttk.Scrollbar(table,orient='horizontal',command=self.tree.xview);self.tree.configure(yscrollcommand=v.set,xscrollcommand=h.set)
        self.tree.grid(row=0,column=0,sticky='nsew');v.grid(row=0,column=1,sticky='ns');h.grid(row=1,column=0,sticky='ew');table.rowconfigure(0,weight=1);table.columnconfigure(0,weight=1)
        self.tree.bind('<Double-1>',lambda event:self.edit());self.tree.bind('<<TreeviewSelect>>',lambda event:self.show_preview())
        self.empty=ttk.Frame(table,style='Surface.TFrame',padding=20)
        ttk.Label(self.empty,text='把拍摄素材整理成看得懂的名字',font=self.fonts['section'],style='Surface.TLabel').pack(pady=(0,8))
        ttk.Label(self.empty,text='将视频或文件夹拖到这里，或点击下方按钮导入。',style='SurfaceMuted.TLabel').pack(pady=(0,15))
        self.button(self.empty,'选择素材文件夹',self.add_folder).pack()
        self.preview=ttk.Frame(pane,style='Surface.TFrame',padding=(16,13));pane.add(self.preview,weight=2)
        detailhead=ttk.Frame(self.preview,style='Surface.TFrame');detailhead.pack(fill='x')
        ttk.Label(detailhead,text='画面核对',font=self.fonts['section'],style='Surface.TLabel').pack(side='left')
        self.button(detailhead,'查看三帧',self.load_preview).pack(side='right');self.button(detailhead,'修改内容',self.edit).pack(side='right',padx=7)
        self.preview_title=ttk.Label(self.preview,text='选择一条素材，查看画面与完整文件名。',style='SurfaceMuted.TLabel',font=self.fonts['small'],wraplength=900);self.preview_title.pack(fill='x',pady=(8,8))
        self.pictures=ttk.Frame(self.preview,style='Surface.TFrame');self.pictures.pack(fill='both',expand=True)
        self.detail_names=ttk.Frame(self.preview,style='Surface.TFrame');self.detail_names.pack(side='bottom',fill='x',pady=(7,0),before=self.pictures);self.detail_names.columnconfigure(1,weight=1)
        self.before_var=tk.StringVar(value='—');self.after_var=tk.StringVar(value='—')
        for i,(label,var) in enumerate([('当前',self.before_var),('预览',self.after_var)]):
            ttk.Label(self.detail_names,text=label,style='SurfaceMuted.TLabel',font=self.fonts['small']).grid(row=i,column=0,sticky='nw',padx=(0,10),pady=3)
            entry=ttk.Entry(self.detail_names,textvariable=var,state='readonly',font=self.fonts['small'],style='Name.TEntry');entry.grid(row=i,column=1,sticky='ew',pady=3)
        action=ttk.Frame(self.main,padding=(0,10,0,0));action.pack(side='bottom',fill='x',before=pane)
        self.action_hint=tk.StringVar(value='AI 只生成建议，文件在确认后才会改名。');ttk.Label(action,textvariable=self.action_hint,style='Muted.TLabel',font=self.fonts['small']).pack(side='left')
        self.rename=self.button(action,'执行改名',self.rename_files);self.rename.pack(side='right',padx=(8,0))
        self.recognize=self.button(action,'AI 识别候选名',self.recognize_files,primary=True);self.recognize.pack(side='right')
        self.stop=ttk.Button(action,text='停止识别',command=self.cancel.set,state='disabled');self.stop.pack(side='right',padx=(8,8))

    def scroller(self,parent):
        container=ttk.Frame(parent);container.pack(fill='both',expand=True)
        canvas=tk.Canvas(container,highlightthickness=0,bg=self.p['canvas']);self.canvases.append(canvas);bar=ttk.Scrollbar(container,orient='vertical',command=canvas.yview);canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side='left',fill='both',expand=True);bar.pack(side='right',fill='y')
        inner=ttk.Frame(canvas,padding=(0,0,18,10));win=canvas.create_window(0,0,anchor='nw',window=inner)
        inner.bind('<Configure>',lambda e:canvas.configure(scrollregion=canvas.bbox('all')))
        canvas.bind('<Configure>',lambda e:canvas.itemconfigure(win,width=e.width))
        def wheel(event):
            if canvas.winfo_exists() and self.page_index==self.pages.index(parent):canvas.yview_scroll(int(-event.delta/120),'units')
        self.root.bind('<MouseWheel>',wheel,add='+');return inner

    def section(self,parent,title,description=''):
        box=ttk.Frame(parent,style='Surface.TFrame',padding=19);box.pack(fill='x',pady=(0,16))
        ttk.Label(box,text=title,font=self.fonts['section'],style='Surface.TLabel').pack(anchor='w')
        if description:ttk.Label(box,text=description,style='SurfaceMuted.TLabel',wraplength=780).pack(anchor='w',pady=(8,12))
        return box

    def field(self,parent,key,label,hint='',wide=False):
        row=ttk.Frame(parent,style='Surface.TFrame');row.pack(fill='x',pady=(10,4))
        ttk.Label(row,text=label,style='Surface.TLabel',font=self.fonts['strong']).pack(anchor='w',pady=(0,7))
        self.vars.setdefault(key,tk.StringVar(value=str(self.settings[key])))
        entry=ttk.Entry(row,textvariable=self.vars[key],font=self.fonts['code'] if key=='template' else self.fonts['body']);entry.pack(fill='x');self.form_controls.append(entry)
        if hint:ttk.Label(row,text=hint,style='SurfaceMuted.TLabel',font=self.fonts['small'],wraplength=780).pack(anchor='w',pady=(6,0))
        return entry

    def make_rules(self):
        self.vars={};inner=self.scroller(self.rules)
        ttk.Label(inner,text='规则可调整，原始文件名默认保留在末尾。',style='Muted.TLabel').pack(anchor='w',pady=(0,18))
        batch=self.section(inner,'本批素材','地点、设备留空时沿用已有归档名。日期留空时按原名或视频元数据判断。')
        for key,label,hint in [('project','地点或项目','同一拍摄项目使用固定名称。'),('device','设备代号','例如 P3、A7M4、IP。'),('date','拍摄日期','YYYYMMDD，例如20261109；不确定时保留空白。'),('start','起始序号','新素材按列表顺序编号；追加归档时填写后续起始号。')]:self.field(batch,key,label,hint)
        self.keep_seq=tk.BooleanVar(value=self.settings['keep_seq']);control=ttk.Checkbutton(batch,text='已归档素材保留原序号',variable=self.keep_seq,command=self.refresh);control.pack(anchor='w',pady=(12,0));self.form_controls.append(control)
        template=self.section(inner,'命名模板','调整字段和顺序，下方示例与素材预览会同步更新。')
        self.field(template,'template','文件名结构','{seq:03d} 为三位序号，{seq:04d} 为四位序号。')
        self.rule_example=tk.StringVar();ttk.Label(template,textvariable=self.rule_example,style='Surface.TLabel',wraplength=780,padding=(0,14,0,8)).pack(fill='x')
        ttk.Label(template,text='字段参考\n{project} 地点或项目   {content} 画面内容   {device} 设备\n{seq:03d} 序号   {date} 日期   {original} 原始文件名\n{stem} 原名不含扩展名   {ext} 扩展名',justify='left',style='SurfaceMuted.TLabel',font=self.fonts['small'],wraplength=780).pack(anchor='w',pady=10)
        for key in ('project','device','date','start','template'):self.vars[key].trace_add('write',lambda *args:self.refresh())
        # Shared variables keep task-specific options in the workspace, not hidden in settings.
        for key,(_,entry) in self.batch_entries.items():entry.configure(textvariable=self.vars[key])
        bar=ttk.Frame(self.rules,padding=(0,14,0,0));bar.pack(side='bottom',fill='x',before=self.rules.winfo_children()[0])
        for label,cmd,primary in [('保存规则',self.save_settings,True),('恢复默认模板',self.restore_template,False),('导出规则说明',self.export_rules,False)]:
            button=self.button(bar,label,cmd,primary,track=False);button.pack(side='left',padx=(0,8));self.form_controls.append(button)

    def make_models(self):
        inner=self.scroller(self.models)
        ttk.Label(inner,text='识别时自动启动，素材只在本机处理。',style='Muted.TLabel').pack(anchor='w',pady=(0,18))
        appearance=self.section(inner,'外观','选择亮色、暗色，或随Windows系统切换。')
        row=ttk.Frame(appearance);row.pack(fill='x',pady=8)
        for text,value in [('亮色','light'),('暗色','dark'),('跟随系统','system')]:
            button=ttk.Radiobutton(row,text=text,value=value,variable=self.theme_mode,command=self.theme_changed);button.pack(side='left',padx=(0,24));self.form_controls.append(button)
        summary=self.section(inner,'本地视觉模型','Qwen3-VL 4B · 根据三帧画面生成中文候选名')
        ttk.Label(summary,text='第一次加载可能较慢；后续素材可连续识别。\n生成的名称可以修改，确认后才会执行改名。',style='Surface.TLabel',wraplength=780).pack(anchor='w',pady=6)
        modelbox=self.section(inner,'运行设置','模型已经下载，无需重复下载。')
        self.field(modelbox,'models_dir','模型存储目录','目录中应包含 blobs 和 manifests。')
        choose=self.button(modelbox,'选择模型目录',self.choose_models,track=False);choose.pack(anchor='w',pady=(7,10));self.form_controls.append(choose)
        self.field(modelbox,'model','模型名称');self.field(modelbox,'port','本机服务端口')
        note=self.section(inner,'识别范围')
        ttk.Label(note,text='每条视频取15%、50%、85%三个位置。适合概括画面，不转写口播内容。\n店名、食品细分和多场景长视频，请结合预览画面复核。\n退出软件会关闭由本软件启动的服务；已有外部服务不受影响。',style='SurfaceMuted.TLabel',wraplength=780,justify='left').pack(anchor='w',pady=(12,0))
        bar=ttk.Frame(self.models,padding=(0,14,0,0));bar.pack(side='bottom',fill='x',before=self.models.winfo_children()[0])
        for text,cmd,primary in [('检测并启动模型',self.check_model,True),('保存设置',self.save_settings,False)]:
            button=self.button(bar,text,cmd,primary,track=False);button.pack(side='left',padx=(0,9));self.form_controls.append(button)

    def navigate(self,index):
        self.tabs.select(index);self.page_index=index;self.page_title.set(('素材工作台','命名规则','软件设置')[index])
        for i,button in enumerate(self.nav):button.state(['selected' if i==index else '!selected'])
    def make_menu(self):
        bar=tk.Menu(self.root);file=tk.Menu(bar,tearoff=False);edit=tk.Menu(bar,tearoff=False);view=tk.Menu(bar,tearoff=False);help_menu=tk.Menu(bar,tearoff=False)
        for text,cmd,key in [('导入文件…',self.add_files,'Ctrl+O'),('导入文件夹…',self.add_folder,'Ctrl+Shift+O'),('打开所在文件夹',self.open_folder,'')]:file.add_command(label=text,command=cmd,accelerator=key)
        file.add_separator();file.add_command(label='退出',command=self.close)
        for text,cmd,key in [('修改画面内容',self.edit,'F2'),('移除选中',self.remove,'Delete'),('清空列表',self.clear,''),('查看三帧',self.load_preview,''),('AI 识别候选名',self.recognize_files,''),('执行改名',self.rename_files,''),('撤销改名…',self.undo,'Ctrl+Z')]:edit.add_command(label=text,command=cmd,accelerator=key)
        for index,text in enumerate(('素材工作台','命名规则','软件设置')):view.add_command(label=text,command=lambda i=index:self.navigate(i),accelerator=f'Alt+{index+1}')
        view.add_separator();view.add_command(label='放大界面文字',command=lambda:self.change_zoom(.1),accelerator='Ctrl++');view.add_command(label='缩小界面文字',command=lambda:self.change_zoom(-.1),accelerator='Ctrl+-');view.add_command(label='恢复文字大小',command=lambda:self.change_zoom(0),accelerator='Ctrl+0')
        help_menu.add_command(label='使用说明',command=self.open_help)
        for title,menu in [('文件',file),('编辑',edit),('视图',view),('帮助',help_menu)]:bar.add_cascade(label=title,menu=menu)
        self.root.configure(menu=bar)
        for key,cmd in [('<Control-o>',self.add_files),('<Control-Shift-O>',self.add_folder),('<Control-s>',self.save_settings),('<Control-z>',self.undo),('<F2>',self.edit),('<Control-plus>',lambda:self.change_zoom(.1)),('<Control-equal>',lambda:self.change_zoom(.1)),('<Control-minus>',lambda:self.change_zoom(-.1)),('<Control-0>',lambda:self.change_zoom(0))]:self.root.bind(key,lambda e,c=cmd:c())
        for i in range(3):self.root.bind(f'<Alt-Key-{i+1}>',lambda e,index=i:self.navigate(index))
        self.tree.bind('<Delete>',lambda e:self.remove())
    def open_help(self):
        path=APPDIR/'使用说明.txt'
        if path.exists():os.startfile(path)
    def change_zoom(self,delta):
        self.zoom=1 if not delta else max(1,min(2,self.zoom+delta))
        for name,size in [('body',11),('small',10),('title',22),('section',13),('strong',11),('code',11)]:self.fonts[name].configure(size=round(size*self.zoom))
        ttk.Style().configure('Treeview',rowheight=round(43*self.zoom));self.preview_key=None;self.show_preview()

    def show_preview(self):
        selected=self.selected();row=selected[0] if selected else None
        self.before_var.set(pathlib.Path(row['path']).name if row else '—');self.after_var.set(row.get('new','') if row else '—')
        self.preview_title.configure(text=(row['content'] or '尚未生成画面名称') if row else '选择一条素材，查看画面与完整文件名。')
        key=(row['id'],tuple(row['frames'])) if row else None
        if key==self.preview_key:return
        self.preview_key=key;self.photos=[]
        for widget in self.pictures.winfo_children():widget.destroy()
        for column,label in enumerate(('15% · 片段前段','50% · 片段中段','85% · 片段后段')):
            frame=ttk.Frame(self.pictures,style='Surface.TFrame');frame.grid(row=0,column=column,sticky='nsew',padx=(0,12 if column<2 else 0));self.pictures.columnconfigure(column,weight=1,uniform='frames')
            if row and row['frames']:
                try:
                    with Image.open(row['frames'][column]) as im:im.thumbnail((max(70,(self.pictures.winfo_width()-30)//3),max(55,min(190,self.pictures.winfo_height()-32))));photo=ImageTk.PhotoImage(im.copy())
                    self.photos.append(photo);ttk.Label(frame,image=photo,style='Surface.TLabel',anchor='center').pack(fill='both',expand=True)
                except (OSError,IndexError):ttk.Label(frame,text='预览暂不可用',style='SurfaceMuted.TLabel',anchor='center').pack(fill='both',expand=True)
            else:
                placeholder=ttk.Frame(frame,style='TFrame',height=58);placeholder.pack(fill='both',expand=True);placeholder.pack_propagate(False)
                ttk.Label(placeholder,text='等待抽帧' if row else '三帧画面预览',style='Muted.TLabel',anchor='center').pack(expand=True)
            ttk.Label(frame,text=label,style='SurfaceMuted.TLabel',font=self.fonts['small'],anchor='center').pack(fill='x',pady=(6,0))

    def refresh(self):
        if not hasattr(self,'rule_example') or not hasattr(self,'keep_seq'):return
        super().refresh()
        if not hasattr(self,'queue_summary'):return
        if self.output_mode.get()=='export':
            targets={}
            try:s=self.current_settings()
            except Exception:s=None
            for i,r in enumerate(self.rows):
                try:
                    if s is None:raise ValueError('请检查命名规则')
                    r['new']=render(r,s,s['start']+i);r['error']=''
                    if not self.output_dir.get().strip():raise ValueError('请选择导出位置')
                    dest=pathlib.Path(self.output_dir.get())/r['new'];key=str(dest.absolute()).casefold()
                    if dest.exists():raise ValueError('导出名称已存在')
                    if key in targets:r['error']='导出名称重复';targets[key]['error']='导出名称重复'
                    targets[key]=r
                except Exception as e:r['error']=str(e)
        missing=sum(not r['content'] for r in self.rows);issues=sum(bool(r.get('error')) and bool(r['content']) for r in self.rows)
        self.queue_summary.set(f'{missing} 条待识别  ·  {issues} 条需处理' if self.rows else '等待导入素材')
        if self.rows:self.empty.place_forget()
        else:self.empty.place(relx=.5,rely=.45,anchor='center')
        for i,r in enumerate(self.rows):
            source=r['info']['original'];tag='even' if i%2==0 else 'odd'
            date=self.tree.set(r['id'],'date');state=r.get('error') or ('日期待核实' if date=='00000000' else r['status'])
            self.tree.item(r['id'],values=(r['content'] or '待识别',date,source,r.get('new',''),state),tags=(tag,))
        self.tree.tag_configure('even',background=self.p['surface']);self.tree.tag_configure('odd',background=self.p['canvas'])
        if not self.busy:
            ready=bool(self.rows) and all(r['content'] and not r.get('error') for r in self.rows)
            self.rename.configure(style='Primary.TButton' if ready else 'TButton');self.recognize.configure(style='TButton' if ready else 'Primary.TButton')
            for widget in self.form_controls:
                try:widget.state(['!disabled'])
                except tk.TclError:pass
        self.show_preview()
        self.sync_output_controls()

    def current_settings(self):
        s=super().current_settings();s.update(appearance=self.theme_mode.get(),output_mode=self.output_mode.get(),output_dir=self.output_dir.get().strip());return s

    def selected_appearance(self):
        system=system_appearance()
        if system=='contrast':return system
        selected=self.theme_mode.get()
        return selected if selected in ('light','dark') else system

    def theme_changed(self):
        appearance=self.selected_appearance();self.appearance=appearance
        self.p=PALETTES['dark' if appearance=='dark' else 'light'].copy()
        if appearance=='contrast':self.p.update(canvas='SystemWindow',surface='SystemWindow',text='SystemWindowText',muted='SystemWindowText',accent='SystemHighlight',selection='SystemHighlight',onaccent='SystemHighlightText',divider='SystemWindowText',sidebar='SystemWindow')
        self.apply_theme();self.preview_key=None;self.refresh();self.navigate(self.page_index)
        if hasattr(self,'status'):self.save_settings(quiet=True)

    def sync_output_controls(self):
        if not hasattr(self,'rename'):return
        exporting=self.output_mode.get()=='export'
        self.rename.configure(text='复制并导出' if exporting else '执行改名')
        for widget in (self.output_path,self.output_choose):widget.state(['disabled' if self.busy or not exporting else '!disabled'])
        self.action_hint.set('导出副本，原素材保留不变' if exporting else ('复核后再改名' if self.root.winfo_width()<1160 else 'AI 只生成建议，文件在确认后才会改名。'))

    def output_changed(self):
        if self.busy:return
        self.refresh()
        if hasattr(self,'status'):self.status.set('导出会复制素材并使用新名称，原文件保留。' if self.output_mode.get()=='export' else '将在原文件夹重命名，完成后可以撤销。')

    def choose_output(self):
        path=filedialog.askdirectory(title='选择重命名副本的导出位置')
        if path:self.output_dir.set(path);self.output_mode.set('export');self.output_changed()

    def enable_drop(self):
        from tkinterdnd2 import DND_FILES
        self.drop_targets=[]
        for widget in (self.root,self.main,self.tree,self.empty,self.pictures):
            widget.drop_target_register(DND_FILES);widget.dnd_bind('<<Drop>>',self.on_drop);self.drop_targets.append(widget)

    def on_drop(self,event):
        if self.busy:self.status.set('请等待当前操作完成后再导入。');return 'refuse_drop'
        try:
            paths=self.root.tk.splitlist(event.data);before=len(self.rows);self.add(import_paths(paths));self.navigate(0)
            self.status.set(f'拖拽导入 {len(self.rows)-before} 条视频，已跳过重复和不支持的文件。')
        except Exception as e:self.status.set('导入未完成：'+str(e))
        return 'copy'

    def rename_files(self):
        if self.output_mode.get()!='export':return super().rename_files()
        if self.busy or not self.rows:return
        self.refresh();errors=[r for r in self.rows if r.get('error')]
        if errors:messagebox.showerror('暂不能导出',f'{len(errors)}条素材需处理：\n'+errors[0]['error']);return
        if not self.save_settings(quiet=True):return
        if not messagebox.askokcancel('确认复制并导出',f'将复制 {len(self.rows)} 条视频到：\n{self.output_dir.get()}\n\n使用预览中的名称，原素材保留不变。'):return
        pairs=[(r['path'],r['new']) for r in self.rows];settings=self.settings.copy();directory=self.output_dir.get()
        def work():
            journal,count=export_batch(pairs,directory,settings,self.notify)
            return f'已复制并导出 {count} 条素材，原文件保留。记录：{journal}'
        self.start(work,'export')

    def status_changed(self,*args):
        if not self.busy:return
        text=self.status.get();match=re.search(r'(\d+)/(\d+)',text)
        if match:
            a,b=map(int,match.groups());self.progress.stop();self.progress.configure(mode='determinate',maximum=max(b,1),value=max(0,a-1) if text.startswith('正在识别') else a)
        else:self.progress.stop();self.progress.configure(mode='determinate',maximum=1,value=0)
    def start(self,work,kind):
        if self.busy:return
        super().start(work,kind)
        self.progress.stop();self.progress.configure(mode='determinate',maximum=1,value=0);self.progress.pack(fill='x',pady=(8,0))
        for tab in (1,2):self.tabs.tab(tab,state='normal')
        for widget in self.form_controls:
            try:widget.state(['disabled'])
            except tk.TclError:pass
        self.recognize.configure(text='识别中…' if kind=='recognize' else 'AI 识别候选名')
    def poll(self):
        was_busy=self.busy;super().poll()
        if was_busy and not self.busy:
            self.progress.pack_forget();self.recognize.configure(text='AI 识别候选名')
            for widget in self.form_controls:
                try:widget.state(['!disabled'])
                except tk.TclError:pass
    def on_resize(self,event):
        if event.widget!=self.root or not hasattr(self,'status_label'):return
        width=max(550,event.width-250);self.status_label.configure(wraplength=width);self.preview_title.configure(wraplength=width-40)
        compact=event.width<1160
        self.action_hint.set('复核后再改名' if compact else 'AI 只生成建议，文件在确认后才会改名。')
        self.tree.configure(displaycolumns=('content','date','status') if compact else ('content','date','name','status'))
        self.sync_output_controls()
        if hasattr(self,'pane'):
            if getattr(self,'layout_job',None):
                try:self.root.after_cancel(self.layout_job)
                except tk.TclError:pass
            self.layout_job=self.root.after(60,self.balance_panes)

    def balance_panes(self):
        self.layout_job=None
        if self.pane.winfo_exists() and self.pane.winfo_width()>1:
            width=self.pane.winfo_width();self.pane.sashpos(0,max(320,width-(420 if width>950 else 355)))
            self.root.update_idletasks();self.preview_title.configure(wraplength=max(200,self.preview.winfo_width()-34));self.preview_key=None;self.show_preview()
    def appearance_tick(self):
        appearance=self.selected_appearance()
        if appearance!=self.appearance:
            self.theme_changed()
        self.root.after(1500,self.appearance_tick)
