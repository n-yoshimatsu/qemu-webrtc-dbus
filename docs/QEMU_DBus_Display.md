# QEMU D-Bus Display 出力の利用方法

このドキュメントは、QEMU の D-Bus Display 出力を WebRTC 配信に利用するための構成・プロトコル・描画方法をまとめたものです。

## 1. QEMU の起動オプション

### gl=on（DMA-BUF）

```bash
qemu-system-x86_64 \
  -enable-kvm -M q35 -smp 4 -m 4G \
  -display dbus,p2p=no,gl=on,addr=unix:path=/tmp/qemu_dbus.sock \
  -device virtio-vga-gl,hostmem=4G,blob=true,venus=true \
  -device virtio-tablet-pci \
  -device virtio-keyboard-pci \
  -object memory-backend-memfd,id=mem1,size=4G \
  -machine memory-backend=mem1 \
  -drive file=vm.qcow2
```

### gl=off（Scanout）

```bash
qemu-system-x86_64 \
  -enable-kvm -M q35 -smp 4 -m 4G \
  -display dbus,p2p=no,gl=off,addr=unix:path=/tmp/qemu_dbus.sock \
  -device virtio-vga,hostmem=4G \
  -device virtio-tablet-pci \
  -device virtio-keyboard-pci \
  -drive file=vm.qcow2
```

### D-Bus デーモン

QEMU が接続する session bus を明示的に起動します。

```bash
dbus-daemon --session --fork \
  --print-address=1 --print-pid=1 \
  --address=unix:path=/tmp/qemu_dbus.sock

export DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/qemu_dbus.sock
```

`start_qemu_gl_on.sh` はこの起動を含みます。

## 2. 配信ソフトウェア構成

```
QEMU D-Bus Display
  ↓ RegisterListener (Unix FD 送付)
P2P D-Bus (GLib/Gio)
  ↓ Listener callbacks
DMA-BUF/EGL/OpenGL → RGB
  ↓ aiortc
WebRTC → Browser
```

主要コンポーネント:

- `dbus/display_capture.py`  
  セッションバス接続、Console/Mouse/Keyboard プロキシ作成
- `dbus/listener.py`  
  Listener 受信（Scanout/ScanoutDMABUF/UpdateDMABUF）
- `dbus/p2p_glib.py`  
  RegisterListener 後の P2P D-Bus 接続
- `dbus/dmabuf_gl.py`  
  DMA-BUF を EGLImage に変換して OpenGL で読み出し
- `server/*`  
  WebRTC サーバーと入力送信

## 3. D-Bus デーモン間のプロトコル概要

1. **Session Bus 接続**
   - `org.qemu.Display1.VM` を取得
   - `ConsoleIDs` から対象 Console を決定

2. **RegisterListener**
   - `socketpair()` で FD を生成
   - `RegisterListener(fd)` を呼び出し、QEMU に FD を渡す

3. **P2P D-Bus 接続**
   - 受け取った FD で P2P D-Bus を確立
   - QEMU → Listener コールバック受信

主なメソッド:

- `Scanout` / `Update`  
  gl=off のピクセルデータ（linear）
- `ScanoutDMABUF` / `UpdateDMABUF`  
  gl=on の DMA-BUF（tiled + modifier）
- `MouseSet` / `CursorDefine`  
  QEMU → クライアント通知（カーソル情報）

入力送信:

- `org.qemu.Display1.Mouse.SetAbsPosition(x, y)`
- `org.qemu.Display1.Mouse.Press(button)`
- `org.qemu.Display1.Mouse.Release(button)`
- `org.qemu.Display1.Keyboard.Press(keycode)`
- `org.qemu.Display1.Keyboard.Release(keycode)`

## 4. 画面表示方法

### gl=off（Scanout）

- `Scanout` / `Update` で取得した linear なピクセルを CPU で RGB 変換
- `pixman_format` を BGRX/BGRA として処理

### gl=on（DMA-BUF）

DMA-BUF は modifier によりタイル形式を持つため、CPU 直接読み取りでは破綻します。  
本実装は EGL + OpenGL で DMA-BUF を処理します。

処理フロー:

```
DMA-BUF (fd, fourcc, modifier)
  ↓ eglCreateImageKHR (EGL_LINUX_DMA_BUF_EXT)
EGLImage
  ↓ glEGLImageTargetTexture2DOES
OpenGL Texture
  ↓ FBO → glReadPixels
RGB array
```

補足:

- `modifier` が 0 でない場合は `EGL_EXT_image_dma_buf_import_modifiers` が必要
- `y0_top=False` の場合は上下反転が必要

