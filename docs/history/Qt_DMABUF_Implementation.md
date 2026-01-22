# Qt-based OpenGL DMA-BUF Implementation Guide

**Date**: 2026-01-22  
**Status**: Implementation Plan Ready  
**Target**: gl=on mode support with PyQt5

---

## Executive Summary

このドキュメントは、QEMUのgl=onモード（OpenGL/DMA-BUF）に対応するため、PyQt5を使用したクライアント実装の方針を詳述します。

### 実装の目的
- DMA-BUFの**タイリングフォーマット**（modifier値）をOpenGLドライバで自動処理
- CPU直接読み取りの失敗（Phase 5で発見）を克服
- GPU加速により、フレーム処理速度を**<5ms/frame**に削減

### 主な変更
1. **dmabuf_gl.py**: PyOpenGL → PyQt5に移行
2. **listener.py**: Qt-based rendererの統合
3. **requirements.txt**: PyQt5追加
4. **サーバー実装**: GLib/Gioベース（変更なし）

---

## アーキテクチャ概要

### 従来の方法（失敗）
```
QEMU (gl=on, DMA-BUF with tiling)
  ↓
P2P D-Bus (fd転送)
  ↓
Python listener (mmap + CPU読み取り)
  ↓ ❌ タイリングフォーマットが正しく解釈されない
RGB変換失敗 → 画面乱れ
```

### Qt-based実装（新規）
```
QEMU (gl=on, DMA-BUF with tiling)
  ↓
P2P D-Bus (fd転送)
  ↓
Python listener (Qt renderer呼び出し)
  ↓
PyQt5 OpenGL Context
  ↓
EGL_EXT_image_dma_buf_import (DMA-BUFをインポート)
  ↓
OpenGL Texture (GPU処理、modifier自動解釈)
  ↓
FBO + glReadPixels (RGB配列)
  ↓ ✅ RGB変換成功
WebRTC配信
```

---

## 技術実装詳細

### 1. PyQt5インストール

#### システムパッケージ経由（推奨、Linux固有）
```bash
sudo apt install -y python3-pyqt5
```

#### 仮想環境内
```bash
python3 -m venv venv
source venv/bin/activate
pip install PyQt5==5.15.11
```

#### requirements.txt
```
PyQt5==5.15.11  # OpenGL + EGL サポート
```

---

### 2. QtDMABUFRenderer クラス（dmabuf_gl.py）

```python
class QtDMABUFRenderer:
    """
    PyQt5ベースのDMA-BUFレンダラー
    
    機能:
    - ヘッドレスOpenGLコンテキスト作成
    - DMA-BUFのEGLImageへの変換
    - OpenGLテクスチャ化
    - FBOレンダリング + glReadPixels
    """
    
    def __init__(self):
        self.app = None              # QCoreApplication
        self.surface = None          # QOffscreenSurface
        self.context = None          # QOpenGLContext
        self.initialized = False
    
    def initialize(self):
        """ヘッドレスOpenGLコンテキスト初期化"""
        # 1. QCoreApplicationをシングルトン作成
        # 2. QOffscreenSurfaceでオフスクリーンサーフェス作成
        # 3. QOpenGLContextで新しいコンテキスト作成
        # 4. context.makeCurrent(surface)でコンテキスト有効化
        
    def render_from_dmabuf(self, dmabuf_fd, width, height, stride, fourcc, modifier):
        """
        DMA-BUF → RGB変換（GPU処理）
        
        手順:
        1. eglCreateImageKHR()でDMA-BUFをEGLImageに変換
           - EGL_LINUX_DMA_BUF_EXT を指定
           - modifier値のサポート確認
        2. glEGLImageTargetTexture2DOES()でテクスチャ作成
        3. FBO作成してテクスチャをアタッチ
        4. glReadPixels()でRGBデータ取得
        5. NumPy配列に変換
        """
        # 実装は dmabuf_gl.py参照
```

### 3. listener.py への統合

```python
# インポート追加
from .dmabuf_gl import get_renderer

class DisplayListener:
    def _update_from_dmabuf(self, fourcc, y0_top):
        """
        手順:
        1. get_renderer()でグローバルレンダラー取得
        2. renderer.initialize()で初期化（未初期化の場合）
        3. renderer.render_from_dmabuf()でGPU処理
        4. 失敗時はCPUフォールバック（従来の_convert_fourcc_to_rgb）
        5. y0_top処理とWebRTC配信
        """
```

---

## DMA-BUFパラメータ詳細

### modifier値の例
- **0x0**: LINEAR（linear memory）- gl=off時
- **0x0100000000000002**: Intel Y-tiled（gl=on時のよくある値）
- **0x0300000000000002**: Intel CCS（Color Compression Surface）

### Fourccコード
- **0x34324258** = "XB24" = XRGB8888（alpha無視）
- **0x34324241** = "AB24" = ARGB8888（alpha有効）

### EGL_EXT_image_dma_buf_import 拡張

```c
// PyQt5内部で自動的に以下が処理される
EGLImage eglCreateImageKHR(
    EGL_DISPLAY,
    EGL_NO_CONTEXT,
    EGL_LINUX_DMA_BUF_EXT,
    NULL,
    {
        EGL_WIDTH, width,
        EGL_HEIGHT, height,
        EGL_LINUX_DRM_FOURCC_EXT, fourcc,
        EGL_DMA_BUF_PLANE0_FD_EXT, fd,
        EGL_DMA_BUF_PLANE0_PITCH_EXT, stride,
        EGL_DMA_BUF_PLANE0_MODIFIER_LO_EXT, modifier & 0xFFFFFFFF,
        EGL_DMA_BUF_PLANE0_MODIFIER_HI_EXT, (modifier >> 32) & 0xFFFFFFFF,
        EGL_NONE
    }
);
```

---

## 実装フロー

### Phase 1: セットアップ
```
1. requirements.txt に PyQt5==5.15.11 を追加
2. pip install -r requirements.txt
3. sys.exit()回避のため QCoreApplication.instance() チェック
```

### Phase 2: Renderer初期化
```
listener.ScanoutDMABUF() 呼び出し時
  ↓
get_renderer().initialize()
  ↓
QOffscreenSurface + QOpenGLContext 作成
  ↓
renderer.initialized = True
```

### Phase 3: フレーム処理
```
UpdateDMABUF() または ScanoutDMABUF() 呼び出し時
  ↓
renderer.render_from_dmabuf(fd, width, height, stride, fourcc, modifier)
  ↓
EGLImage作成 → OpenGLテクスチャ → FBO → glReadPixels
  ↓
NumPy配列(height, width, 3) 返却
  ↓
WebRTC配信
```

### Phase 4: フォールバック
```
Qt rendering 失敗時
  ↓
従来の CPU処理（_convert_fourcc_to_rgb）を実行
  ↓
警告ログ出力
```

---

## パフォーマンス予測

### gl=off (従来, CPU処理)
- RGB変換: 8.6ms/frame
- フレームレート: 10fps

### gl=on (Qt-based, GPU処理)
- DMA-BUF → EGLImage: <0.5ms
- glReadPixels: <3ms
- **合計: <5ms/frame** （目標達成予定）
- フレームレート: 20fps以上

### スピードアップ係数
約**1.7倍** の高速化を期待

---

## 環境要件

### システム
- Linux (Ubuntu 24.04推奨)
- OpenGL 3.3+ 対応GPU
- EGL + DMA-BUF サポート (Mesa 20.0+)
- X11/Wayland (不要 - ヘッドレス動作)

### Python環境
- Python 3.12+
- PyQt5 5.15.10+
- PyOpenGL 3.1.10+
- NumPy 2.4+

### QEMU設定
```bash
qemu-system-x86_64 \
    -display dbus,p2p=no,gl=on \
    -device virtio-vga-gl,hostmem=4G,blob=true \
    ...
```

---

## トラブルシューティング

### 問題1: "QXcbConnection: Could not connect to display"
**原因**: Qt が X11を探そうとしている  
**解決**:
```python
# dmabuf_gl.py で環境変数を設定
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
```

### 問題2: "EGL_EXT_image_dma_buf_import not supported"
**原因**: ドライバがDMA-BUF拡張をサポートしていない  
**確認**:
```bash
glxinfo | grep "EGL_EXT_image_dma_buf_import"
```
**解決**: Mesa ドライバのアップデート

### 問題3: "glEGLImageTargetTexture2DOES not found"
**原因**: OpenGL拡張関数が不足している  
**解決**: PyOpenGL + PyQt5の再インストール
```bash
pip install --upgrade PyOpenGL PyQt5
```

### 問題4: メモリリーク
**原因**: EGLImage や OpenGL resources の未解放  
**解決**: cleanup() メソッドの確実な呼び出し
```python
# サーバー終了時
renderer.cleanup()
```

---

## テスト方法

### ユニットテスト
```bash
# dmabuf_gl.py のみテスト
python3 -c "
from dbus.dmabuf_gl import QtDMABUFRenderer
r = QtDMABUFRenderer()
assert r.initialize(), 'Renderer init failed'
print('✓ Renderer initialized')
"
```

### 統合テスト
```bash
# QEMUで gl=on, listener.py で ScanoutDMABUF 処理
python3 server/main.py --debug
# ブラウザで http://localhost:8081 を確認
```

### パフォーマンステスト
```python
# timing measurements in listener.py
import time
t_start = time.time()
rgb = renderer.render_from_dmabuf(...)
t_render = time.time() - t_start
logger.info(f"DMA-BUF render time: {t_render*1000:.2f}ms")
```

---

## 今後の拡張

### Phase 6 (将来)
- [ ] マルチプレーン DMA-BUF サポート
- [ ] YUV フォーマット対応 (YUYV, NV12等)
- [ ] 色空間変換 (BT.709等)
- [ ] HDR対応
- [ ] Vulkan への移行検討

---

## 参考実装

### qemu-display (Rust)
- 場所: `/nfs_root/projects2/claude/qemu-display/`
- 参考: `qemu-rdw/src/display.rs` (EGL + DMA-BUF)

### 公式ドキュメント
- [QEMU D-Bus Display](https://www.qemu.org/docs/master/interop/dbus-display.html)
- [EGL_EXT_image_dma_buf_import](https://www.khronos.org/registry/EGL/extensions/EXT/EGL_EXT_image_dma_buf_import.txt)
- [PyQt5 Documentation](https://www.riverbankcomputing.com/static/Docs/PyQt5/)

---

## チェックリスト

実装時の確認項目:

- [ ] requirements.txt に PyQt5 追加
- [ ] `sudo apt install -y python3-pyqt5` でシステム PyQt5 インストール
- [ ] dmabuf_gl.py で QtDMABUFRenderer 実装
- [ ] listener.py で get_renderer() 統合
- [ ] QT_QPA_PLATFORM=offscreen 環境変数確認
- [ ] QEMU で gl=on, virtio-vga-gl で起動
- [ ] ブラウザで画面表示確認
- [ ] フレームレート測定（目標: 20fps+）
- [ ] cpu fallback 動作確認

---

## 関連ファイル

**実装ファイル**:
- `dbus/dmabuf_gl.py` (リライト完了)
- `dbus/listener.py` (統合完了)
- `requirements.txt` (更新完了)

**テストスクリプト**:
- `test_qt_renderer.py` (新規作成予定)

**ドキュメント**:
- `docs/Qt_DMABUF_Implementation.md` (本ドキュメント)
- `Performance_Issue_v5.md` (背景)

---

**Implementation Status**: Ready to Test  
**Last Updated**: 2026-01-22 09:30 JST  
**Next Step**: QEMU with gl=on でテスト実行
