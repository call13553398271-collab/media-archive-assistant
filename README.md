# 素材归档助手 / Media Archive Assistant

Windows 离线视频素材归档工具。拖入视频或文件夹，用本机 Qwen3-VL 4B 生成画面内容名称，预览确认后批量改名或复制导出。

## 功能

- 文件及文件夹拖拽导入、递归扫描和去重。
- 本机自动启动 Ollama，抽取视频15%、50%、85%三帧，生成中文候选名；可手动修改。
- 可编辑命名模板，默认 `{project}_{content}_{device}_{seq:03d}_{date}__{original}`。
- 原文件夹改名，保存对照及SHA-256并支持撤销；或复制到指定文件夹，保留源文件。
- 圆角桌面界面、亮色／暗色／跟随系统、菜单与键盘操作。

## 下载完整离线环境

在 Releases 下载 `media-archive-assistant-v2.0.0-win64.zip`、全部 `qwen3-vl-4b-models.zip.00*` 分卷，以及 `SHA256SUMS.txt`。

1. 解压软件ZIP，保留全部目录结构。
2. 把模型分卷放到同一文件夹，按名称顺序二进制合并成 `qwen3-vl-4b-models.zip`。软件ZIP中的 `恢复模型.ps1` 可以自动合并、校验和解压。
3. 在软件目录运行 `启动软件.cmd`。它会把模型路径设置为本机的绝对路径，再打开EXE。也可以在软件设置页手动选择模型目录。

模型压缩包内为 `models/blobs` 和 `models/manifests`。完整附件包括EXE、Ollama运行环境、FFmpeg/FFprobe、4B量化模型及许可文本。无需Python或API Key；恢复完成后可断网使用。

## 配置与数据

公开包不包含任何用户视频、预览画面、日志、归档记录或用户设置。示例项目、设备和日期为空；首次使用时填写。`设置.json`、`运行数据`、模型和二进制均不纳入Git历史。

模型仅看预览图片，不接收原文件名或视频音频；不转写口播。三帧摘要可能遗漏长视频内容，也可能误认店名或食品，执行前请复核。

## 从源码构建

Windows x64，Python3.12。运行 `build_windows.ps1`，生成 `dist/素材归档助手.exe`。将公开软件包中的runtime、tools保留在EXE旁。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements-build.txt
.\.venv\Scripts\python.exe -m unittest discover -s . -p 'test_*.py' -v
.\.venv\Scripts\python.exe -m PyInstaller --noconfirm --onefile --windowed --collect-all tkinterdnd2 --name 素材归档助手 app.py
```

本机验证：12项文件及界面逻辑测试通过，打包EXE的原生拖拽库、主题切换、复制导出和4B识别自检通过。截图工具不可用时没有宣称完成视觉像素校验。

## 组件

Python3.12 / Pillow13.0.0 / TkinterDnD2 0.7.0 / PyInstaller6.22.3；Ollama0.40.15；Qwen3-VL4B Instruct Q4_K_M（Apache2.0）；FFmpeg8.1 Gyan essentials构建（GPLv3）。具体上游来源和许可见 THIRD_PARTY_NOTICES.md 及软件包中的licenses目录。
