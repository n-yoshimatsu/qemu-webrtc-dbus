# QEMU D-Bus Display 性能問題調査 - フェーズ3

## 概要

日付: 2026-01-20  
調査対象: QEMU D-Bus Display + WebRTC統合における画面転送問題  
前回の結論: gl=onでQEMU側のScanoutDmabuf送信は成功、しかしクライアント側で受信できない

---

## 前回（Phase 2）までの状況

### 確認できた事実

1. ✅ gl=on環境でQEMUは正常にScanoutDmabufを呼び出している
2. ✅ P2P D-Bus接続は確立されている（GetAllメッセージは届く）
3. ❌ ScanoutDmabufメッセージがクライアント側に届かない
4. ❌ QEMUが"The connection is closed"エラーを報告

### QEMUログ（正常に送信）

```
[SCANOUT_TEX] tex_id=559, y_0_top=0, backing=1280x800, region=0,0 1280x800
[SCANOUT_TEX] Using CONFIG_GBM path (DMA-BUF)
[SCANOUT_DMABUF] Entry
[SCANOUT_DMABUF] fd=65
[SCANOUT_DMABUF] Calling ScanoutDmabuf: 1280x800, stride=5120, fourcc=0x34324258
[SCANOUT_DMABUF] ScanoutDmabuf called successfully
qemu-system-x86_64: Failed to call update: The connection is closed
```

---

## Phase 3 調査内容

### 1. クライアント側の実装追加

#### 1.1 ScanoutDmabuf/UpdateDmabufメソッドの実装

**ファイル**: `dbus/listener.py`

```python
def ScanoutDmabuf(self, fd, width, height, stride, fourcc, modifier, y0_top):
    """DMA-BUF共有メモリでの画面更新（OpenGL使用時）"""
    logger.info("🎯 ScanoutDmabuf called!")
    logger.info(f"   fd={fd}, size={width}x{height}, stride={stride}")
    logger.info(f"   fourcc=0x{fourcc:08x}, modifier={modifier}, y0_top={y0_top}")
    
    # DMA-BUFをmmap
    size = stride * height
    self.shared_memory = mmap.mmap(fd, size, mmap.MAP_SHARED, mmap.PROT_READ)
    
    # 初回データ読み込み
    self._update_from_dmabuf(fourcc, y0_top)

def UpdateDmabuf(self, x, y, width, height):
    """DMA-BUFの部分更新通知"""
    if self.shared_memory is not None:
        self._update_from_dmabuf(self.current_fourcc, True)
```

#### 1.2 D-Busインターフェース定義の修正

**ファイル**: `dbus/p2p_glib.py`

**問題**: メソッド名の大文字小文字の不一致
- 誤: `ScanoutDMABUF`, `UpdateDMABUF`
- 正: `ScanoutDmabuf`, `UpdateDmabuf`

```xml
<method name="ScanoutDmabuf">
  <arg type="h" name="fd" direction="in"/>
  <arg type="u" name="width" direction="in"/>
  <arg type="u" name="height" direction="in"/>
  <arg type="u" name="stride" direction="in"/>
  <arg type="u" name="fourcc" direction="in"/>
  <arg type="t" name="modifier" direction="in"/>
  <arg type="b" name="y0_top" direction="in"/>
</method>
```

#### 1.3 メソッドハンドラの実装

**ファイル**: `dbus/p2p_glib.py`

```python
def _handle_method_call(self, connection, sender, object_path, interface_name,
                       method_name, parameters, invocation):
    if method_name == "ScanoutDmabuf":
        logger.info("📥 ScanoutDmabuf METHOD_CALL received!")
        unix_fd_list = invocation.get_message().get_unix_fd_list()
        if unix_fd_list and unix_fd_list.get_length() > 0:
            fd_index = parameters.unpack()[0]
            actual_fd = unix_fd_list.get(fd_index)
            _, width, height, stride, fourcc, modifier, y0_top = parameters.unpack()
            self.listener.ScanoutDmabuf(actual_fd, width, height, stride, fourcc, modifier, y0_top)
            invocation.return_value(None)
```

---

### 2. DELAY_MESSAGE_PROCESSINGの理解

#### 目的
D-Bus接続確立後、明示的に`start_message_processing()`を呼ぶまでメッセージ処理を遅延させる。

#### 使用理由
1. **セットアップの完了を保証**
   - インターフェース登録
   - メッセージハンドラの登録
   - メッセージフィルタの登録

2. **メッセージ到着タイミング制御**
   ```
   接続確立
     ↓
   [メッセージが到着] ← ここでメッセージが来る可能性
     ↓
   インターフェース登録中... ← まだ準備中
     ↓
   start_message_processing() ← ここまで待機
   ```

#### 実装
```python
self.connection = Gio.DBusConnection.new_sync(
    io_stream,
    None,
    Gio.DBusConnectionFlags.AUTHENTICATION_CLIENT | Gio.DBusConnectionFlags.DELAY_MESSAGE_PROCESSING,
    None,
    None
)
# インターフェース登録
# ...
self.connection.start_message_processing()
```

---

### 3. 公式プロトコルの発見

#### ファイル
`/nfs_root/projects2/virtio/qemu/qemu-v9.2.0/ui/dbus-display1.xml`

QEMUのD-Bus Display APIの**公式な定義**が存在します。

#### RegisterListenerプロトコル

```xml
<!--
    RegisterListener:
    @listener: a Unix socket FD, for peer-to-peer D-Bus communication.

    Register a console listener, which will receive display updates, until
    it is disconnected.

    Multiple listeners may be registered simultaneously.

    The listener is expected to implement the
    :dbus:iface:`org.qemu.Display1.Listener` interface.
-->
<method name="RegisterListener">
  <arg type="h" name="listener" direction="in"/>
</method>
```

#### ScanoutDMABUFプロトコル

```xml
<!--
    ScanoutDMABUF:
    @dmabuf: the DMABUF file descriptor.
    @width: display width, in pixels.
    @height: display height, in pixels.
    @stride: stride, in bytes.
    @fourcc: DMABUF fourcc.
    @modifier: DMABUF modifier.
    @y0_top: whether Y position 0 is the top or not.

    Resize and update the display content with a DMABUF.
-->
<method name="ScanoutDMABUF">
  <arg type="h" name="dmabuf" direction="in"/>
  <arg type="u" name="width" direction="in"/>
  <arg type="u" name="height" direction="in"/>
  <arg type="u" name="stride" direction="in"/>
  <arg type="u" name="fourcc" direction="in"/>
  <arg type="t" name="modifier" direction="in"/>
  <arg type="b" name="y0_top" direction="in"/>
</method>
```

---

### 4. QEMUの実装調査

#### RegisterListenerの処理順序

**ファイル**: `ui/dbus-console.c:256`

```c
// 1. RegisterListenerの戻り値を返す
qemu_dbus_display1_console_complete_register_listener(
    ddc->iface, invocation, NULL);

// 2. P2P接続確立（SERVER側として）
listener_conn = g_dbus_connection_new_sync(
    G_IO_STREAM(socket_conn),
    guid,
    G_DBUS_CONNECTION_FLAGS_AUTHENTICATION_SERVER,  // サーバー側
    NULL, NULL, &err);

// 3. Listenerオブジェクト作成（ここでScanoutDmabuf送信）
listener = dbus_display_listener_new(sender, listener_conn, ddc);
```

#### ScanoutDmabuf送信タイミング

**ファイル**: `ui/dbus-listener.c:1200`

```c
// register_displaychangelistener()内で即座に送信
register_displaychangelistener(&ddl->dcl);
  ↓
dbus_gl_gfx_switch()
  ↓
dbus_scanout_texture()
  ↓
dbus_scanout_dmabuf()  // ← ここでScanoutDmabuf送信
```

**重要**: QEMUは`RegisterListener`メソッドが戻った**後**に`ScanoutDmabuf`を送信する。

---

## 現在の問題

### 症状

```
[QEMU側]
[SCANOUT_DMABUF] ScanoutDmabuf called successfully
qemu-system-x86_64: Failed to call update: The connection is closed

[クライアント側]
[FILTER] Incoming METHOD_CALL
[FILTER]   Member: GetAll  ← これしか届いていない
```

### 確認できていること

1. ✅ P2P D-Bus接続は確立されている（`GetAll`は受信できる）
2. ✅ QEMUは`ScanoutDmabuf`を送信している（ログ確認）
3. ❌ クライアント側のメッセージフィルタに`ScanoutDmabuf`が届かない
4. ❌ QEMUが"The connection is closed"エラーを報告

---

## 仮説

### 仮説1: 接続の不一致
QEMUが送信している接続と、クライアントが受信している接続が異なる。

**根拠:**
- `GetAll`は受信できているが`ScanoutDmabuf`は届かない
- 異なるD-Bus接続が混在している可能性

### 仮説2: タイミング問題
クライアントの受信準備が完了する前にメッセージが送信され、失われている。

**根拠:**
- `DELAY_MESSAGE_PROCESSING`の使い方
- `start_message_processing()`のタイミング
- QEMUがRegisterListenerの処理中に送信

### 仮説3: インターフェース/メソッド名の不一致
D-Busインターフェース定義に見落としがある。

**根拠:**
- 過去に大文字小文字問題があった（現在は修正済み）
- 他に見落としがある可能性

### 仮説4: ファイルディスクリプタ転送の失敗
`ScanoutDmabuf`はファイルディスクリプタを含むため、特別な処理が必要。

**根拠:**
- `GetAll`（FDなし）は届くが、`ScanoutDmabuf`（FDあり）は届かない
- FD転送の失敗で接続が閉じられている可能性

---

## 検証計画

### Phase 1: 接続の同一性を確認（優先度：高）

**目的:** QEMUとクライアントが同じ接続を使っているか確認

**手順:**
1. QEMUのログに、どのfd/接続に送信しているか記録
2. クライアントのログに、どのfdで受信しているか記録
3. 両者が一致しているか確認

**実装:**
```c
// QEMU側
fprintf(stderr, "[SCANOUT_DMABUF] Sending to connection=%p, proxy=%p\n", 
        (void*)listener_conn, (void*)ddl->proxy);
```

```python
# クライアント側
logger.info(f"[FILTER] Connection object: {connection}")
logger.info(f"[FILTER] Connection unique name: {connection.get_unique_name()}")
```

### Phase 2: メッセージ送信タイミングの可視化

**目的:** メッセージがいつ送信され、クライアントがいつ受信可能になるか確認

**確認項目:**
- RegisterListenerの戻り値送信タイミング
- P2P接続確立タイミング
- start_message_processing()タイミング
- ScanoutDmabuf送信タイミング

### Phase 3: 最小テストケースの作成

**目的:** 問題を切り分けるため、最小構成でテスト

**手順:**
1. QEMUの公式サンプルまたはテストコードを確認
2. 既存の動作する実装（qemu-display等）を参照
3. 最小限のコードで再現

### Phase 4: D-Busモニタリング

**目的:** D-Bus通信を外部からモニタリング

**手順:**
1. `dbus-monitor`や`busctl monitor`でP2P接続を監視
2. D-Busメッセージのダンプを取得
3. 実際に何が送信されているか確認

---

## 次のアクション

### 推奨: Phase 1（接続の同一性確認）

最も可能性が高い問題。接続オブジェクトの同一性を確認する必要がある。

### 代替案: 既存実装の参照

- qemu-display (Rust実装)
- GTK VNC Viewer
- その他のQEMU D-Bus Display クライアント

これらの実装を参照し、何が違うのかを確認する。

---

## 参考情報

### 関連ファイル

**QEMU側:**
- `/nfs_root/projects2/virtio/qemu/qemu-v9.2.0/ui/dbus-display1.xml` - プロトコル定義
- `/nfs_root/projects2/virtio/qemu/qemu-v9.2.0/ui/dbus-console.c` - RegisterListener実装
- `/nfs_root/projects2/virtio/qemu/qemu-v9.2.0/ui/dbus-listener.c` - ScanoutDmabuf実装

**クライアント側:**
- `/nfs_root/projects2/claude/webrtc_dbus/dbus/listener.py` - DisplayListener実装
- `/nfs_root/projects2/claude/webrtc_dbus/dbus/p2p_glib.py` - P2P D-Bus実装
- `/nfs_root/projects2/claude/webrtc_dbus/dbus/display_capture.py` - メイン制御

### ログファイル

**QEMU:** `/tmp/qemu_stdout_glon.log` (tsubameサーバー)  
**クライアント:** `/tmp/client_final.log` (tsubameサーバー)

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

### Fourcc フォーマット

- `0x34324258` = "XB24" = XRGB8888（32bit、alpha無視）
- `0x34324241` = "AB24" = ARGB8888（32bit、alpha有効）
