import base64, datetime as dt, hashlib, json, os, pathlib, re, shutil, socket, string, subprocess, time, uuid, urllib.request

DEFAULT_TEMPLATE = '{project}_{content}_{device}_{seq:03d}_{date}__{original}'
DEFAULTS = dict(template=DEFAULT_TEMPLATE, project='', device='', date='', start=1, keep_seq=True, model='qwen3-vl:4b-instruct', models_dir='G:/AI模型/Ollama', port=11435, appearance='system', output_mode='original', output_dir='')
EXTENSIONS = {'.mp4','.mov','.mkv','.avi','.m4v','.mts','.m2ts','.webm','.wmv'}
FIELDS = {'project','content','device','seq','date','original','stem','ext'}
HIDDEN = subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
PROMPT = ('为这三张同一视频的预览帧生成一个4到12字的简体中文归档名称。只描述看得见的主体、动作或场景。'
          '不要推断具体禽类、菜名、食品口味、人物身份、活动名称或拍摄用途。食材无法确定时用食材、糕点、烧腊等通用名称。'
          '只有文字清楚可读时才使用品牌名。人物拿麦讲话可以称人物口播。普通城市夜景不要称灯光秀，商场巡拍不要称探店。'
          '不要使用忙碌、好看、场景等空泛词。只输出名称，不要解释、编号、引号、标点或文件扩展名。')

def clean(value):
    return re.sub(r'[<>:"/\\|?*\x00-\x1f_]', '-', str(value)).strip(' .-')

def inspect_name(path):
    p=pathlib.Path(path)
    original=p.name.split('__',1)[-1]
    result=dict(project='',content='',device='',date='',original=original)
    m=re.fullmatch(r'(.+?)_(.+?)_([^_]+)_(\d+)_(\d{8})__(.+)',p.name)
    if m: result.update(project=m[1],content=m[2],device=m[3],seq=int(m[4]),date=m[5],original=m[6])
    else:
        match=re.search(r'(20\d{6})\d{6}',p.name)
        if match:
            try: dt.datetime.strptime(match[1],'%Y%m%d'); result['date']=match[1]
            except ValueError: pass
    return result

def validate_template(template):
    if not template.strip(): raise ValueError('命名模板不能为空。')
    for literal,field,spec,conversion in string.Formatter().parse(template):
        if re.search(r'[<>:"/\\|?*\x00-\x1f]',literal): raise ValueError('模板包含 Windows 禁用字符。')
        if field is not None:
            if field not in FIELDS or conversion: raise ValueError('模板含未知字段或转换语法：'+str(field))
            if field=='seq':
                if spec and not re.fullmatch(r'0?[1-8]?d',spec): raise ValueError('序号格式请使用 {seq}、{seq:03d} 或 {seq:04d}。')
            elif spec: raise ValueError('只有序号字段可以指定格式。')

def render(row,settings,seq):
    validate_template(settings['template'])
    data=row['info'].copy()
    for key in ('project','device','date'):
        if settings.get(key,'').strip(): data[key]=settings[key].strip()
    data['content']=row['content'].strip()
    if not data['content']: raise ValueError('尚未填写画面内容')
    template=settings['template']
    for key in ('project','device'):
        if '{'+key+'}' in template and not data[key]: raise ValueError('请填写'+{'project':'地点或项目','device':'设备'}[key])
    data['date']=data['date'] or '00000000'
    if data['date']!='00000000':
        try: dt.datetime.strptime(data['date'],'%Y%m%d')
        except ValueError: raise ValueError('拍摄日期须为有效的 YYYYMMDD')
    original=data['original']
    data.update(seq=int(data.get('seq',seq)) if settings.get('keep_seq',True) else int(seq),stem=pathlib.Path(original).stem,ext=pathlib.Path(original).suffix)
    for key in ('project','device','content'): data[key]=clean(data[key])
    if not data['content']: raise ValueError('画面内容不能只包含禁用字符')
    name=template.format(**data)
    if not name.lower().endswith(pathlib.Path(row['path']).suffix.lower()): name+=pathlib.Path(row['path']).suffix
    if len(name)>240 or not name.strip(' .'): raise ValueError('文件名过长或无效')
    if re.search(r'[<>:"/\\|?*\x00-\x1f]',name) or name.endswith((' ','.')): raise ValueError('生成的文件名含禁用字符或结尾空格/句点')
    if re.match(r'^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)',name,re.I): raise ValueError('文件名为 Windows 保留名称')
    return name

def digest(path):
    with open(path,'rb') as f: return hashlib.file_digest(f,'sha256').hexdigest()

def atomic_json(path,data):
    path=pathlib.Path(path); temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    os.replace(temp,path)

def import_paths(paths):
    result=[];seen=set()
    for value in paths:
        path=pathlib.Path(value).absolute()
        if path.is_dir():
            found=[]
            for directory,dirs,files in os.walk(path,followlinks=False):
                dirs[:]=[d for d in dirs if d not in {'归档记录','运行数据','runtime','tools'} and not pathlib.Path(directory,d).is_symlink() and not pathlib.Path(directory,d).is_junction()]
                found.extend(pathlib.Path(directory,f) for f in sorted(files))
        else:found=[path]
        for p in found:
            key=str(p).casefold()
            if p.is_file() and p.suffix.lower() in EXTENSIONS and key not in seen:seen.add(key);result.append(str(p))
    return result

def export_batch(pairs,directory,settings,progress=lambda text:None):
    folder=pathlib.Path(directory).absolute()
    if not str(directory).strip() or not folder.is_dir():raise ValueError('请先选择已存在的导出文件夹。')
    entries=[];targets=set()
    for source,name in pairs:
        src=pathlib.Path(source).absolute();dst=folder/name
        if pathlib.Path(name).name!=name or re.search(r'[<>:"/\\|?*\x00-\x1f]',name):raise ValueError('非法导出名称')
        if dst.exists() or str(dst).casefold() in targets:raise ValueError('导出名称已存在或重复：'+name)
        targets.add(str(dst).casefold());st=src.stat()
        entries.append(dict(source=str(src),target=str(dst),size=st.st_size,mtime_ns=st.st_mtime_ns,sha256=digest(src)))
        progress(f'导出前校验 {len(entries)}/{len(pairs)}')
    if not entries:raise ValueError('没有需要导出的素材。')
    logs=folder/'归档记录';logs.mkdir(exist_ok=True)
    journal=logs/('export_'+dt.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.json')
    record=dict(version=1,operation='copy_export',status='prepared',settings=settings,entries=entries,applied=[])
    atomic_json(journal,record);created=[]
    try:
        for i,e in enumerate(entries,1):
            src=pathlib.Path(e['source']);dst=pathlib.Path(e['target']);st=src.stat()
            if (st.st_size,st.st_mtime_ns)!=(e['size'],e['mtime_ns']):raise ValueError('源文件在校验后发生变化：'+src.name)
            # Exclusive create prevents replacing an unrelated file, including races.
            with dst.open('xb') as target:
                created.append(dst)
                with src.open('rb') as source:shutil.copyfileobj(source,target,8*1024*1024)
            shutil.copystat(src,dst)
            if digest(dst)!=e['sha256']:raise ValueError('导出校验失败：'+dst.name)
            record['applied'].append(str(dst));atomic_json(journal,record);progress(f'复制并校验 {i}/{len(entries)}')
        record['status']='complete';atomic_json(journal,record)
    except BaseException as exc:
        failures=[]
        for path in reversed(created):
            try:path.unlink()
            except OSError as err:failures.append(str(err))
        record.update(status='rollback_failed' if failures else 'rolled_back',error=str(exc),rollback_errors=failures);atomic_json(journal,record)
        raise ValueError(str(exc)+'\n记录：'+str(journal)) from exc
    return journal,len(entries)

def rename_batch(pairs,settings,progress=lambda text:None):
    entries=[]; targets=set()
    for source,name in pairs:
        src=pathlib.Path(source).absolute()
        if pathlib.Path(name).name!=name or re.search(r'[<>:"/\\|?*\x00-\x1f]',name): raise ValueError('非法目标文件名')
        dst=src.with_name(name)
        if str(src).casefold()==str(dst).casefold(): continue
        key=str(dst).casefold()
        if key in targets or dst.exists(): raise ValueError('目标名称已存在或重复：'+name)
        targets.add(key)
        st=src.stat()
        entries.append(dict(source=str(src),target=str(dst),size=st.st_size,mtime_ns=st.st_mtime_ns,sha256=digest(src)))
        progress(f'改名前校验 {len(entries)}/{len(pairs)}')
    if not entries: raise ValueError('没有需要改名的文件。')
    folder=pathlib.Path(entries[0]['source']).parent/'归档记录'
    folder.mkdir(exist_ok=True)
    journal=folder/('rename_'+dt.datetime.now().strftime('%Y%m%d_%H%M%S')+'_'+uuid.uuid4().hex[:8]+'.json')
    record=dict(version=1,status='prepared',settings=settings,entries=entries,applied=[])
    atomic_json(journal,record)
    try:
        for e in entries:
            src,dst=pathlib.Path(e['source']),pathlib.Path(e['target'])
            st=src.stat()
            if (st.st_size,st.st_mtime_ns)!=(e['size'],e['mtime_ns']): raise ValueError('文件在校验后发生变化：'+src.name)
            os.rename(src,dst)
            record['applied'].append(e['target']); atomic_json(journal,record)
        for n,e in enumerate(entries,1):
            if digest(e['target'])!=e['sha256']: raise ValueError('改名后内容校验失败：'+e['target'])
            progress(f'改名后校验 {n}/{len(entries)}')
        record['status']='complete'; atomic_json(journal,record)
    except BaseException as exc:
        failures=[]
        for e in reversed(entries):
            if e['target'] in record['applied']:
                try:
                    if pathlib.Path(e['source']).exists(): raise ValueError('原名称被占用')
                    os.rename(e['target'],e['source'])
                except Exception as err: failures.append(str(err))
        record.update(status='rollback_failed' if failures else 'rolled_back',error=str(exc),rollback_errors=failures)
        atomic_json(journal,record)
        raise ValueError(str(exc)+'\n记录：'+str(journal)) from exc
    return journal,len(entries)

def undo_batch(journal,progress=lambda text:None):
    path=pathlib.Path(journal); record=json.loads(path.read_text(encoding='utf-8'))
    if record.get('version')!=1 or record.get('status')!='complete': raise ValueError('只能撤销本软件生成且已完成的改名记录。')
    entries=record['entries']
    # Validate the entire undo operation before changing anything.
    for n,e in enumerate(entries,1):
        src,dst=pathlib.Path(e['source']),pathlib.Path(e['target'])
        if src.parent!=dst.parent or src.exists() or not dst.is_file(): raise ValueError('原名称已占用或文件已移动：'+str(src))
        if dst.stat().st_size!=e['size'] or digest(dst)!=e['sha256']: raise ValueError('文件内容已变化，停止撤销：'+dst.name)
        progress(f'撤销前校验 {n}/{len(entries)}')
    done=[]
    try:
        for e in reversed(entries): os.rename(e['target'],e['source']); done.append(e)
    except BaseException:
        for e in reversed(done):
            if not pathlib.Path(e['target']).exists(): os.rename(e['source'],e['target'])
        raise
    record['status']='undone'; atomic_json(path,record)
    return len(entries)

class LocalModel:
    def __init__(self,appdir,settings):
        self.appdir=pathlib.Path(appdir); self.settings=settings.copy(); self.process=None
        self.url=f'http://127.0.0.1:{int(settings["port"])}'
        self.opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def api(self,route,payload=None,timeout=10):
        req=urllib.request.Request(self.url+route,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json'})
        with self.opener.open(req,timeout=timeout) as response: return json.load(response)

    def ensure(self,progress):
        try: models=self.api('/api/tags')['models']
        except Exception:
            port=int(self.settings['port'])
            if not 1024<=port<=65535: raise ValueError('本地端口必须在1024—65535之间')
            with socket.socket() as sock:
                try: sock.bind(('127.0.0.1',port))
                except OSError: raise ValueError(f'端口{port}被其他程序占用，请在模型设置中更换端口。')
            executable=self.appdir/'runtime'/'ollama.exe'
            if not executable.exists(): raise ValueError('缺少便携运行环境 runtime/ollama.exe，请完整解压软件包。')
            modeldir=pathlib.Path(self.settings['models_dir'])
            if not modeldir.is_dir(): raise ValueError('模型目录不存在，请在本地模型设置中选择已下载的模型目录。')
            env=os.environ.copy(); env.update(OLLAMA_HOST=f'127.0.0.1:{port}',OLLAMA_MODELS=str(modeldir),OLLAMA_NO_CLOUD='1',OLLAMA_CONTEXT_LENGTH='8192')
            logs=self.appdir/'运行数据'; logs.mkdir(exist_ok=True)
            with (logs/'模型运行.log').open('a',encoding='utf-8') as log:
                self.process=subprocess.Popen([str(executable),'serve'],env=env,stdout=log,stderr=log,creationflags=HIDDEN)
            progress('正在自动启动本地模型服务…')
            for _ in range(60):
                if self.process.poll() is not None: raise ValueError('模型服务启动失败，请查看运行数据/模型运行.log。')
                try: models=self.api('/api/tags')['models']; break
                except Exception: time.sleep(.5)
            else: raise ValueError('模型服务启动超时')
        if self.settings['model'] not in [m['name'] for m in models]: raise ValueError('当前目录没有模型 '+self.settings['model']+'，请选择 G:/AI模型/Ollama。')
        return '本地模型服务已就绪：'+self.settings['model']

    def tools(self,name):
        path=self.appdir/'tools'/(name+'.exe')
        found=str(path) if path.exists() else shutil.which(name)
        if not found: raise ValueError('缺少 '+name+'，请完整解压软件包。')
        return found

    def frames(self,path,cache):
        cache=pathlib.Path(cache); cache.mkdir(parents=True,exist_ok=True)
        result=subprocess.run([self.tools('ffprobe'),'-v','error','-show_entries','format=duration:format_tags=creation_time','-of','json',str(path)],capture_output=True,creationflags=HIDDEN,timeout=60)
        if result.returncode: raise ValueError('无法读取视频：'+result.stderr.decode('utf-8',errors='replace')[-500:])
        metadata=json.loads(result.stdout); duration=float(metadata['format']['duration'])
        paths=[]
        for n,fraction in enumerate((.15,.5,.85)):
            dest=cache/f'{n}.jpg'
            result=subprocess.run([self.tools('ffmpeg'),'-v','error','-threads','1','-ss',str(duration*fraction),'-i',str(path),'-frames:v','1','-vf','scale=512:912:force_original_aspect_ratio=decrease','-q:v','3','-y',str(dest)],capture_output=True,creationflags=HIDDEN,timeout=90)
            if result.returncode or not dest.exists(): raise ValueError('视频抽帧失败：'+result.stderr.decode('utf-8',errors='replace')[-500:])
            paths.append(dest)
        return paths,duration,metadata['format'].get('tags',{}).get('creation_time')

    def recognize(self,paths):
        data=self.api('/api/chat',dict(model=self.settings['model'],stream=False,keep_alive='10m',messages=[dict(role='user',content=PROMPT,images=[base64.b64encode(p.read_bytes()).decode() for p in paths])],options=dict(temperature=0,num_predict=80,num_ctx=8192)),timeout=600)
        content=data['message']['content'].strip().strip('"“”\'`')
        content=re.sub(r'^(名称|画面内容|文件名)[：:]\s*','',content)
        if '\n' in content or len(content)>40 or not clean(content): raise ValueError('模型输出格式不符合短名称要求，请手动填写：'+content[:120])
        return content

    def close(self):
        if self.process and self.process.poll() is None:
            try:self.api('/api/generate',dict(model=self.settings['model'],keep_alive=0),timeout=15)
            except Exception:pass
            if os.name=='nt':
                subprocess.run(['taskkill.exe','/PID',str(self.process.pid),'/T','/F'],capture_output=True,creationflags=HIDDEN,timeout=15)
            else:self.process.terminate()
            try: self.process.wait(timeout=10)
            except subprocess.TimeoutExpired: self.process.kill()
