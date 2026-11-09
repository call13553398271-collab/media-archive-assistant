import copy,json,pathlib,tempfile,unittest
from unittest.mock import patch
from core import DEFAULTS,DEFAULT_TEMPLATE,inspect_name,render,rename_batch,undo_batch,export_batch,import_paths

class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=pathlib.Path(__file__).parent)
        self.root=pathlib.Path(self.temp.name);self.settings=DEFAULTS.copy()
    def tearDown(self):self.temp.cleanup()
    def make(self,name,data=b'untouched original bytes'):
        p=self.root/name;p.write_bytes(data);return p
    def test_archived_name_keeps_original_and_sequence(self):
        p=self.make('地点_空镜_P3_042_20260929__DJI_20260929180136_0438_D.MP4')
        row=dict(path=str(p),info=inspect_name(p),content='顾客乘坐扶梯')
        name=render(row,self.settings,1)
        self.assertEqual(name,'地点_顾客乘坐扶梯_P3_042_20260929__DJI_20260929180136_0438_D.MP4')
    def test_custom_template_and_dates(self):
        p=self.make('DJI_20260929180136_0438_D.MP4')
        row=dict(path=str(p),info=inspect_name(p),content='商场入口')
        s=dict(self.settings,project='测试',device='P3',template='{date}_{project}_{seq:04d}_{content}__{original}')
        self.assertEqual(render(row,s,7),'20260929_测试_0007_商场入口__DJI_20260929180136_0438_D.MP4')
        for t in ('../{original}','{original.__class__}','{seq:999999d}'):
            with self.assertRaises(ValueError):render(row,dict(s,template=t),1)
    def test_rename_undo_preserves_bytes_and_collision_blocks_all(self):
        a=self.make('a.mp4',b'a');b=self.make('b.mp4',b'b');self.make('occupied.mp4')
        with self.assertRaises(ValueError):rename_batch([(a,'renamed_a.mp4'),(b,'occupied.mp4')],self.settings)
        self.assertTrue(a.exists());self.assertFalse((self.root/'renamed_a.mp4').exists())
        log,n=rename_batch([(a,'renamed_a.mp4'),(b,'renamed_b.mp4')],self.settings)
        self.assertEqual(n,2);self.assertEqual((self.root/'renamed_a.mp4').read_bytes(),b'a')
        self.assertEqual(undo_batch(log),2);self.assertEqual(a.read_bytes(),b'a');self.assertEqual(b.read_bytes(),b'b')
    def test_modified_content_blocks_entire_undo(self):
        a=self.make('a.mp4',b'a');b=self.make('b.mp4',b'b')
        log,_=rename_batch([(a,'new_a.mp4'),(b,'new_b.mp4')],self.settings)
        (self.root/'new_b.mp4').write_bytes(b'changed')
        with self.assertRaises(ValueError):undo_batch(log)
        self.assertTrue((self.root/'new_a.mp4').exists());self.assertFalse(a.exists())
    def test_failed_second_rename_rolls_back_first(self):
        import os
        a=self.make('a.mp4');b=self.make('b.mp4');original=os.rename
        def fail(src,dst):
            if pathlib.Path(src)==b:raise OSError('simulated second-file failure')
            return original(src,dst)
        with patch('core.os.rename',side_effect=fail):
            with self.assertRaises(ValueError):rename_batch([(a,'new_a.mp4'),(b,'new_b.mp4')],self.settings)
        self.assertTrue(a.exists());self.assertTrue(b.exists());self.assertFalse((self.root/'new_a.mp4').exists())
        log=next((self.root/'归档记录').glob('*.json'));self.assertEqual(json.loads(log.read_text(encoding='utf-8'))['status'],'rolled_back')

    def test_export_keeps_sources_and_checks_copy(self):
        a=self.make('source one.mp4',b'camera original');out=self.root/'export';out.mkdir()
        log,n=export_batch([(a,'项目_画面.mp4')],out,self.settings)
        self.assertEqual(n,1);self.assertEqual(a.read_bytes(),b'camera original')
        self.assertEqual((out/'项目_画面.mp4').read_bytes(),a.read_bytes())
        self.assertEqual(json.loads(log.read_text(encoding='utf-8'))['operation'],'copy_export')
        with self.assertRaises(ValueError):undo_batch(log)

    def test_export_collision_blocks_all(self):
        a=self.make('source.mp4');out=self.root/'export';out.mkdir();existing=out/'existing.mp4';existing.write_bytes(b'other content')
        with self.assertRaises(ValueError):export_batch([(a,'first.mp4'),(a,'existing.mp4')],out,self.settings)
        self.assertFalse((out/'first.mp4').exists());self.assertEqual(existing.read_bytes(),b'other content')

    def test_export_copy_failure_cleans_only_created_copies(self):
        a=self.make('a.mp4',b'a');b=self.make('b.mp4',b'b');out=self.root/'export';out.mkdir()
        import shutil
        real=shutil.copyfileobj;calls=[]
        def fail(src,dst,*args):
            calls.append(1)
            if len(calls)==2:raise OSError('simulated copy failure')
            return real(src,dst,*args)
        with patch('core.shutil.copyfileobj',side_effect=fail):
            with self.assertRaises(ValueError):export_batch([(a,'new_a.mp4'),(b,'new_b.mp4')],out,self.settings)
        self.assertEqual(a.read_bytes(),b'a');self.assertEqual(b.read_bytes(),b'b');self.assertFalse(list(out.glob('*.mp4')))

    def test_drag_folder_scan_deduplicates_and_handles_spaces(self):
        p=self.make('中文 video.mp4');nested=self.root/'folder with space';nested.mkdir();q=nested/'clip.MOV';q.write_bytes(b'video');(nested/'notes.txt').write_text('ignore')
        found=import_paths([self.root,p,nested])
        self.assertEqual(set(found),{str(p),str(q)});self.assertEqual(len(found),2)

if __name__=='__main__':unittest.main(verbosity=2)
