# QEMU D-Bus Display 性能問題調査 - フェーズ2

## 概要

日付: 2026-01-20  
調査対象: QEMU D-Bus Display + WebRTC統合における画面転送問題

## 背景

### 前回までの状況
- WebRTC接続は成功
- P2P D-Bus接続も確立
- SetUIInfo呼び出し成功
- しかし画面が真っ黒（フレームが届かない）

### 今回の調査目標
QEMUがScanout/Updateコールバックをクライアントに送信しているか確認する

---

## 調査フェーズ1: デバッグログ追加

### 追加したログポイント

#### 1. dbus_gfx_update() (ui/dbus-listener.c:739)
```c
fprintf(stderr, "[UPD] Calling dbus_scanout_map()...\n");
fprintf(stderr, "[UPD] dbus_scanout_map() returned: %s\n", ...);
```

#### 2. dbus_scanout_map() (ui/dbus-listener.c:447)
```c
fprintf(stderr, "[SCANOUT_MAP] Entry: ds_share=%d, can_share_map=%d, share_handle=%d\n", ...);
fprintf(stderr, "[SCANOUT_MAP] Calling ScanoutMap D-Bus method...\n");
```

#### 3. dbus_scanout_texture() (ui/dbus-listener.c:505)
```c
fprintf(stderr, "[SCANOUT_TEX] tex_id=%u, y_0_top=%d, backing=%ux%u, region=%u,%u %ux%u\n", ...);
fprintf(stderr, "[SCANOUT_TEX] Using CONFIG_GBM path (DMA-BUF)\n");
```

#### 4. dbus_scanout_dmabuf() (ui/dbus-listener.c:291)
```c
fprintf(stderr, "[SCANOUT_DMABUF] Entry\n");
fprintf(stderr, "[SCANOUT_DMABUF] fd=%d\n", fd);
fprintf(stderr, "[SCANOUT_DMABUF] Calling ScanoutDmabuf: %ux%u, stride=%u, fourcc=0x%x\n", ...);
fprintf(stderr, "[SCANOUT_DMABUF] ScanoutDmabuf called successfully\n");
```

---

## 調査フェーズ2: QEMU起動問題の解決

### 問題
SSH経由でQEMUを起動してログを取得できなかった

### 根本原因
```bash
-serial mon:stdio  # 標準入出力を使用
```
この設定により、SSH経由でバックグラウンド実行（`&`）すると標準入出力が閉じられてQEMUが起動失敗

### 解決方法
```bash
-serial file:/tmp/qemu_serial.log  # ファイルにリダイレクト
nohup ... > /tmp/qemu_stdout.log 2> /tmp/qemu_stderr.log &
```

---

## 調査フェーズ3: gl=off vs gl=on の比較

### gl=off の結果

#### ログ出力
```
[SCANOUT_MAP] Entry: ds_share=0, can_share_map=1, share_handle=29
[SCANOUT_MAP] Setting up fdlist...
[SCANOUT_MAP] Calling ScanoutMap D-Bus method...
[SCANOUT_MAP] ScanoutMap call failed: The connection is closed - returning false
[SCANOUT] ddl_scanout called
```

#### 問題点
1. **ScanoutMapが失敗**: "The connection is closed" エラー
2. **フォールバック**: 古いScanout/Updateメソッドに切り替わる
3. **can_share_mapがfalseに**: 以降の更新でScanoutMapを使用しない
4. **パフォーマンス**: データをD-Bus経由でコピー（低速）

#### 推測される原因
- `gl=off`では共有メモリ（memory-backend-memfd）を作成するが、OpenGLコンテキストがないため`share_handle`が正しく初期化されない
- P2P D-Bus接続が確立されているが、共有メモリのファイルディスクリプタの受け渡しに失敗

---

### gl=on の結果

#### ログ出力
```
[REGISTER_LISTENER] Called by sender=:1.1, console=0x5b42c9222080 (index=0)
[SWITCH] dbus_gl_gfx_switch
[SCANOUT_TEX] tex_id=376, y_0_top=0, backing=1280x800, region=0,0 1280x800
[SCANOUT_TEX] Using CONFIG_GBM path (DMA-BUF)
[SCANOUT_DMABUF] Entry
[SCANOUT_DMABUF] fd=47
[SCANOUT_DMABUF] Calling ScanoutDmabuf: 1280x800, stride=5120, fourcc=0x34324258
[SCANOUT_DMABUF] ScanoutDmabuf called successfully
[SET_UI_INFO] Called! width=1280, height=800
[SCANOUT_TEX] tex_id=552, y_0_top=0, backing=1280x800, region=0,0 1280x800
[SCANOUT_TEX] Using CONFIG_GBM path (DMA-BUF)
[SCANOUT_DMABUF] Entry
[SCANOUT_DMABUF] fd=43
[SCANOUT_DMABUF] Calling ScanoutDmabuf: 1280x800, stride=5120, fourcc=0x34324241
[SCANOUT_DMABUF] ScanoutDmabuf called successfully
```

#### 成功点
1. ✅ **OpenGLテクスチャ**: tex_id（376, 536, 552）が生成されている
2. ✅ **DMA-BUF**: ファイルディスクリプタ（fd=47, 43）が正常に渡されている
3. ✅ **ScanoutDmabuf成功**: エラーなしで完了
4. ✅ **fourcc**: 0x34324258 (XB24), 0x34324241 (AB24) - 適切なピクセルフォーマット
5. ✅ **stride**: 5120 = 1280 * 4 (RGBA32)

#### 使用されているコードパス
```
dbus_gl_gfx_switch()
  ↓
dbus_scanout_texture()  // OpenGLテクスチャを受け取る
  ↓
egl_get_fd_for_texture()  // テクスチャからDMA-BUFファイルディスクリプタを取得
  ↓
dbus_scanout_dmabuf()  // D-Bus経由でfdをクライアントに送信
```

---

## 比較表

| 項目 | gl=off | gl=on |
|------|--------|-------|
| 画面転送方式 | Scanout/Update (コピー) | DMA-BUF (ゼロコピー) |
| 共有メモリ | 初期化失敗 | 正常動作 |
| D-Bus接続 | 閉じられている | 正常 |
| パフォーマンス | 低速 | 高速 |
| エラー | "The connection is closed" | なし |
| QEMU設定 | `-device virtio-vga` | `-device virtio-vga-gl` |
| 推奨度 | ❌ 非推奨 | ✅ 推奨 |

---

## 結論

### 推奨設定

```bash
${QEMU_DIR}/qemu-system-x86_64 \
    -enable-kvm -M q35 -smp 4 -m 4G -cpu host \
    -display dbus,p2p=no,gl=on,addr=unix:path=${SOCKET_PATH} \
    -device virtio-vga-gl \
    -device virtio-tablet-pci \
    -device virtio-keyboard-pci \
    -serial file:/tmp/qemu_serial.log \
    -netdev user,id=net0,hostfwd=tcp::10022-:22 \
    -device e1000,netdev=net0 \
    -object memory-backend-memfd,id=mem1,size=4G \
    -machine memory-backend=mem1 \
    -drive file=${IMG}
```

### 重要なパラメータ
1. **`gl=on`**: OpenGL有効化（必須）
2. **`virtio-vga-gl`**: OpenGL対応VGAデバイス（必須）
3. **`memory-backend-memfd`**: 共有メモリバックエンド（推奨）
4. **`-serial file:`**: SSH経由実行時の標準入出力問題を回避

---

## 次のステップ

### 現在の状況
- ✅ QEMU側: ScanoutDmabufが正常に呼ばれている
- ✅ クライアント側: P2P D-Bus接続が確立されている
- ❓ クライアント側: ScanoutDmabufコールバックが呼ばれているか？

### 必要な調査
1. **クライアント側のコールバック確認**
   - `on_scanout_dmabuf()`が呼ばれているか
   - ファイルディスクリプタ（fd）が正しく受信されているか
   - DMA-BUFのmmapが成功しているか

2. **WebRTCへのフレーム送信確認**
   - VideoTrackがフレームを受け取っているか
   - ブラウザ側でビデオストリームが検出されているか

3. **エラーログ確認**
   - クライアント側でエラーが発生していないか
   - GLibメインループが正常に動作しているか

---

## 参考情報

### QEMU D-Bus Display API
- Scanout/Update: 古い方式、データをコピー
- ScanoutDmabuf/UpdateDmabuf: 推奨方式、DMA-BUF共有メモリ
- ScanoutMap/UpdateMap: Windows用、共有メモリマップ

### DMA-BUF
- Linux kernelの共有メモリ機構
- ゼロコピーでGPUメモリを共有
- ファイルディスクリプタ経由で受け渡し
- mmap()でユーザー空間からアクセス

### Fourcc コード
- 0x34324258 = "XB24" = XRGB8888（32bit、alpha無視）
- 0x34324241 = "AB24" = ARGB8888（32bit、alpha有効）
