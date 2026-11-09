import json,pathlib,sys,tempfile,types,unittest
from unittest.mock import patch
from tkinterdnd2 import TkinterDnD
import app,design_ui
from core import DEFAULTS

class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=pathlib.Path(__file__).parent);self.folder=pathlib.Path(self.temp.name).absolute()
        self.a=patch.object(app,'APPDIR',self.folder);self.b=patch.object(design_ui,'APPDIR',self.folder);self.a.start();self.b.start()
        self.root=TkinterDnD.Tk();self.root.withdraw();self.ui=design_ui.DesignedApp(self.root);self.root.update()
    def tearDown(self):
        for callback in self.root.tk.call('after','info'):self.root.after_cancel(callback)
        self.root.destroy();self.a.stop();self.b.stop();self.temp.cleanup()
    def test_native_drop_with_braced_paths(self):
        directory=self.folder/'素材 folder';directory.mkdir();video=directory/'中文 素材.MP4';video.write_bytes(b'fake video')
        event=types.SimpleNamespace(data=self.root.tk.call('list',str(directory),str(video)))
        self.assertEqual(self.ui.on_drop(event),'copy');self.assertEqual(len(self.ui.rows),1)
        self.assertEqual(self.ui.on_drop(event),'copy');self.assertEqual(len(self.ui.rows),1)
        self.assertEqual(len(self.ui.drop_targets),5)
    def test_theme_rounding_and_saved_preference(self):
        for value in ('dark','light','system'):
            self.ui.theme_mode.set(value);self.ui.theme_changed();self.root.update()
            self.assertEqual(self.ui.current_settings()['appearance'],value)
        self.assertIn('Round',str(design_ui.ttk.Style().layout('TButton')))
        saved=json.loads((self.folder/'设置.json').read_text(encoding='utf-8'));self.assertEqual(saved['appearance'],'system')
    def test_export_preview_and_switch_back(self):
        p=self.folder/'项目_画面_P3_042_20260929__camera.MP4';p.write_bytes(b'video');self.ui.add([p]);row=self.ui.rows[0]
        self.assertFalse(row['error']);self.assertIn('_042_',row['new'])
        self.ui.output_mode.set('export');self.ui.output_changed();self.assertEqual(row['error'],'请选择导出位置')
        out=self.folder/'out';out.mkdir();self.ui.output_dir.set(str(out));self.ui.output_changed();self.assertFalse(row['error']);self.assertEqual(self.ui.rename.cget('text'),'复制并导出')
        (out/row['new']).write_bytes(b'other');self.ui.refresh();self.assertEqual(row['error'],'导出名称已存在')
        self.ui.output_mode.set('original');self.ui.output_changed();self.assertFalse(row['error']);self.assertEqual(self.ui.rename.cget('text'),'执行改名')

if __name__=='__main__':unittest.main(verbosity=2)
