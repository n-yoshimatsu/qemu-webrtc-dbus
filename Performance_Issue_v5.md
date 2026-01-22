# QEMU D-Bus Display → WebRTC統合 - DMA-BUF Tiling Format Issue

**Date**: 2026-01-22  
**Status**: gl=off動作確認完了、gl=on OpenGL実装準備中  
**Project**: `/nfs_root/projects2/claude/webrtc_dbus/`

## エグゼクティブサマリー

QEMU D-Bus Display経由でのWebRTC画面配信において、`gl=on`（OpenGL有効）時に画面が乱れる問題を調査。根本原因は**DMA-BUF modifier値が示すタイリングフォーマット**をCPUで直接読み取れないこと。`gl=off`モードでは正常動作を確認。次ステップとしてOpenGLを使用したDMA-BUF処理を実装する。

---

## 問題の症状

### 現象
- **gl=on**: ブラウザで画面が横方向にずれたように乱れる
- **gl=off**: 正常に表示される（起動に約2分）

### 画面の乱れ方
- 横一列にテキストやUIが断片的に表示
- 典型的なタイリングメモリレイアウトの誤解釈パターン

---

## 調査の経過

### Phase 1-4（過去セッション）
- ✅ P2P D-Bus接続確立
- ✅ UnixFD転送サポート（メッセージフィルター内で処理）
- ✅ ScanoutDMABUF/UpdateDMABUF受信確認
- ✅ WebRTC接続確立（ICE completed）
- ✅ RGB変換高速化（500ms → 10ms）
- ✅ Y軸反転処理（y0_top=False対応）

### Phase 5（今回セッション）- 根本原因の特定

#### 試行1: NumPy reshape + stride処理
```python
rows = data_array[:height * stride].reshape(height, stride)
valid_pixels = rows[:, :width * 4]
pixels = valid_pixels.reshape(height, width, 4)
```
**結果**: ❌ 乱れたまま

#### 試行2: NumPy as_strided（Rustリファレンス実装）
```python
pixels = np.lib.stride_tricks.as_strided(
    data_array,
    shape=(height, width, 4),
    strides=(stride, 4, 1)  # (height_stride, width_stride, channel_stride)
)
```
**結果**: ❌ 乱れたまま

#### 試行3: Pythonループ（最確実）
```python
for y in range(height):
    row_offset = y * stride
    for x in range(width):
        pixel_offset = row_offset + x * 4
        rgb[y, x, 0] = data_array[pixel_offset + 2]  # R
        rgb[y, x, 1] = data_array[pixel_offset + 1]  # G
        rgb[y, x, 2] = data_array[pixel_offset + 0]  # B
```
**結果**: ❌ 乱れたまま（処理時間：709ms/frame）

#### 決定的な発見：gl=off での動作確認

QEMU起動コマンドを `gl=off` に変更：
```bash
# gl=on → gl=off に変更
-display dbus,p2p=no,gl=off,addr=unix:path=/tmp/qemu_gl_on_debug.sock
-device virtio-vga,hostmem=4G  # virtio-vga-gl → virtio-vga
```

**結果**: ✅ **画面が正常に表示された！**

---

## 根本原因の特定

### DMA-BUF Modifier値の分析

**gl=on時のパラメータ**:
```
fd=15, width=1280, height=800, stride=5120
fourcc=0x34324258 (XB24/BGRX) or 0x34324241 (AB24/BGRA)
modifier=72057594037927938 (0x0100000000000002)  ← 重要！
y0_top=False
```

**modifier値の意味**:
- `0x0100000000000002` = DRM_FORMAT_MOD_*定数
- IntelのGPUタイリングフォーマット（Y-tiled、X-tiled、またはCCS圧縮）を示す
- メモリレイアウトが**linear（連続）ではなく、タイル単位**で配置

### Linear vs Tiled Memory Layout

**Linear (gl=off, Scanout)**:
```
[行0_ピクセル0][行0_ピクセル1]...[行0_ピクセル1279]
[行1_ピクセル0][行1_ピクセル1]...[行1_ピクセル1279]
...
```
→ `row_offset + x * 4` で正しくアクセス可能

**Tiled (gl=on, DMA-BUF)**:
```
[タイル0_4x4][タイル1_4x4][タイル2_4x4]...
```
→ タイルごとの特殊なアドレス計算が必要  
→ CPUから直接読み取るには、modifier値に応じたデコードロジックが必要

### なぜリファレンス実装（qemu-rdw）は動作するのか

**qemu-rdwの実装** (`qemu-rdw/src/display.rs`):
```rust
// DMA-BUFをCPUで読まず、OpenGLで直接レンダリング
gl::TexImage2D(...);  // EGLImageからテクスチャ作成
// OpenGLドライバがmodifier値を自動的に処理
```

**qemu-vncの実装** (`qemu-vnc/src/main.rs`):
```rust
// 非DMA-BUFモード（Scanout）を使用
// linear memoryなので、strideだけで正しく読める
```

---

## 2つのモードの比較

| 項目 | gl=off (Scanout) | gl=on (DMA-BUF) |
|------|------------------|-----------------|
| QEMUメソッド | `Scanout` | `ScanoutDMABUF` |
| メモリ形式 | Linear | Tiled (modifier指定) |
| ストライド処理 | シンプル | タイル単位デコード必要 |
| CPU読み取り | ✅ 可能 | ❌ 不可（modifier未対応） |
| OpenGL処理 | 不要 | 必要 |
| RGB変換速度 | 8.6ms | N/A（未成功） |
| 表示結果 | ✅ 正常 | ❌ 乱れる |

---

## gl=off モードのパフォーマンス

### 起動シーケンス
```
09:09:18.072 - RegisterListener開始
09:09:18.090 - Scanout受信
09:09:33.820 - Scanout処理完了（約15秒後）
09:09:33.829 - RGB変換完了（8.6ms）
09:09:34.902 - WebRTCサーバー起動
```

**起動時間**: 約16秒（Scanout待ち15秒 + RGB変換0.01秒）

### リアルタイムパフォーマンス
- RGB変換: 8.6ms/frame（NumPy最適化版）
- Update処理: <1ms
- フレームレート: 10fps（設定値）

---

## リファレンス実装の調査結果

### qemu-displayパッケージ
**場所**: `/nfs_root/projects2/claude/qemu-display`

**qemu-rdw** (`qemu-rdw/src/display.rs`):
- DMA-BUFをEGLImageとしてインポート
- OpenGLテクスチャに変換
- GPUで直接レンダリング（CPUコピー不要）

**qemu-vnc** (`qemu-vnc/src/main.rs`):
- 非DMA-BUFモード使用
- `image::flat::SampleLayout`でstrideのみ処理

---

## 次のステップ: OpenGL実装

### 実装方針

**アーキテクチャ**:
```
DMA-BUF (GPU memory, tiled format)
  ↓
EGL_EXT_image_dma_buf_import
  ↓
EGLImage
  ↓
OpenGL Texture (GPU処理)
  ↓
FBO (FrameBuffer Object)
  ↓
glReadPixels → RGB配列 (CPU memory)
  ↓
WebRTC配信
```

### 必要な技術要素

1. **EGL初期化** (ヘッドレスコンテキスト)
   - `eglGetDisplay(EGL_DEFAULT_DISPLAY)`
   - `eglCreateContext()` with EGL_OPENGL_API
   - PBufferサーフェス作成（オフスクリーンレンダリング）

2. **DMA-BUFインポート**
   - `EGL_EXT_image_dma_buf_import`拡張
   - `eglCreateImageKHR()` with DMA-BUF attributes
   - modifier値のサポート確認

3. **OpenGLテクスチャ化**
   - `glGenTextures()`
   - `glBindTexture(GL_TEXTURE_2D, texture)`
   - `glEGLImageTargetTexture2DOES()`

4. **FBOレンダリング**
   - `glGenFramebuffers()`
   - `glFramebufferTexture2D()`
   - 必要に応じてY軸反転処理

5. **RGB読み取り**
   - `glReadPixels(0, 0, width, height, GL_RGB, GL_UNSIGNED_BYTE, buffer)`
   - NumPy配列に変換

### 実装の利点

✅ **タイリングフォーマット自動処理**: OpenGLドライバがmodifier値を解釈  
✅ **GPUアクセラレーション**: CPU負荷削減  
✅ **高速化**: DMA-BUF → RGB変換が10ms未満  
✅ **スケーラビリティ**: 解像度増加に対応  

### 実装の課題

⚠️ **複雑性**: EGL拡張関数の取得とエラー処理  
⚠️ **環境依存**: OpenGL/EGLドライバの互換性  
⚠️ **デバッグ難度**: GPUメモリの可視化が困難  

---

## 技術的な学び

### DMA-BUFとタイリングフォーマット

1. **DMA-BUFは共有メモリのハンドル**
   - GPU/CPUで共有可能なメモリ領域
   - ゼロコピーでデータ転送可能

2. **Modifier値の重要性**
   - メモリレイアウトの形式を指定
   - 0x0 = LINEAR（通常の連続メモリ）
   - その他 = GPU固有のタイリングフォーマット

3. **タイリングフォーマットの目的**
   - メモリアクセスの局所性向上
   - GPUキャッシュ効率化
   - テクスチャ圧縮（CCS: Color Compression Surface）

### なぜCPU読み取りが失敗したか

1. **メモリレイアウトの違い**
   ```
   Linear:  [0][1][2][3][4][5][6][7]...
   Tiled:   [0][4][1][5][2][6][3][7]...  (簡略化した例)
   ```

2. **Stride値だけでは不十分**
   - Strideは行間のオフセット
   - タイル内部の配置は別ロジック

3. **Modifier固有のデコード必要**
   - Intel、AMD、NVIDIAで異なる
   - ドライバー内部の知識が必要

---

## プロジェクト構成

```
/nfs_root/projects2/claude/webrtc_dbus/
├── dbus/
│   ├── listener.py              # DisplayListener（Scanout/ScanoutDMABUF処理）
│   ├── p2p_glib.py              # P2P D-Bus接続（GLib実装）
│   ├── display_capture.py       # メインキャプチャクラス
│   └── dmabuf_gl.py             # OpenGL DMA-BUFレンダラー（作成中）
├── server/
│   ├── main.py                  # WebRTCサーバーメイン
│   ├── video_track.py           # ビデオトラック
│   └── signaling.py             # シグナリングサーバー
└── Performance_Issue_v5.md      # このドキュメント
```

---

## 環境情報

**実行環境**: tsubame (192.168.10.101)  
**QEMU**: v9.2.0 (`/nfs_root/projects2/virtio/qemu/qemu-v9.2.0/build/`)  
**VM Image**: `/nfs_root/projects2/virtio/demo/ubuntu-24-04.qcow2`  
**Python**: 3.12  
**主要ライブラリ**:
- aiortc: WebRTC実装
- dasbus: D-Bus Python実装
- PyGObject: GLib/GIO/GDBus Python binding
- numpy: 高速配列処理
- PyOpenGL: OpenGL Python binding（インストール済み）

**QEMUコマンド（gl=off）**:
```bash
/nfs_root/projects2/virtio/qemu/qemu-v9.2.0/build/qemu-system-x86_64 \
  -enable-kvm -M q35 -smp 4 -m 4G -cpu host \
  -display dbus,p2p=no,gl=off,addr=unix:path=/tmp/qemu_gl_on_debug.sock \
  -device virtio-vga,hostmem=4G \
  -device virtio-tablet-pci -device virtio-keyboard-pci \
  -serial file:/tmp/qemu_gl_on_serial.log \
  -netdev user,id=net0,hostfwd=tcp::10022-:22 \
  -device e1000,netdev=net0 \
  -object memory-backend-memfd,id=mem1,size=4G \
  -machine memory-backend=mem1 \
  -drive file=/nfs_root/projects2/virtio/demo/ubuntu-24-04.qcow2
```

---

## 関連ファイル

**デバッグ画像**: `/tmp/dmabuf_debug.png` (gl=on時に保存された乱れた画像)  
**QEMUログ**: `/tmp/qemu_gl_off.log`  
**トランスクリプト**: `/mnt/transcripts/2026-01-22-00-17-19-webrtc-dmabuf-stride-debugging.txt`

---

## まとめ

### 確認された事実

1. ✅ **gl=off (Scanout)**: Linear memoryで正常動作（8.6ms/frame）
2. ❌ **gl=on (DMA-BUF)**: Tiled memoryでCPU読み取り不可
3. ✅ **根本原因特定**: Modifier値が示すタイリングフォーマット
4. ✅ **解決策明確**: OpenGLでDMA-BUF処理

### 次のアクション

**優先度: 最高**
1. OpenGL DMA-BUFレンダラー実装
   - EGL初期化（ヘッドレスコンテキスト）
   - `EGL_EXT_image_dma_buf_import`拡張使用
   - FBOレンダリング + glReadPixels

2. `listener.py`のScanoutDMABUF統合
   - OpenGLレンダラー呼び出し
   - フォールバック処理（OpenGL失敗時）

3. パフォーマンス測定
   - DMA-BUF → RGB変換時間
   - gl=on vs gl=off比較

**優先度: 中**
4. エラーハンドリング
   - OpenGL拡張サポート確認
   - ドライバー互換性チェック

5. ドキュメント更新
   - OpenGL実装の詳細
   - ベンチマーク結果

---

**Document Version**: 5.0  
**Last Updated**: 2026-01-22 09:15 JST  
**Status**: Ready for Step 2 - OpenGL Implementation
