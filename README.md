# QEMU WebRTC D-Bus Display

QEMU の D-Bus Display 出力を WebRTC でブラウザに配信するツールです。  
gl=on（DMA-BUF + OpenGL）と gl=off（Scanout）に対応しています。

## 目的

- QEMU ゲスト画面をブラウザで表示・操作する
- D-Bus Display を利用して低レイテンシな画面取得と入力転送を行う

## ツール構成

```
QEMU VM
  ↓ D-Bus Display (RegisterListener + P2P D-Bus)
Python Backend (DisplayCapture / Listener / DMA-BUF renderer)
  ↓ aiortc
WebRTC
  ↓
Browser (client/index.html)
```

## セットアップ

```bash
python3 -m venv venv
./venv/bin/python -m pip install --upgrade pip
./venv/bin/python -m pip install -r requirements.txt
```

## 利用手順

### 1. QEMU を起動

推奨: `start_qemu_gl_on.sh` を使う（D-Bus デーモン起動込み）。

```bash
./start_qemu_gl_on.sh
```

手動起動する場合の例（gl=on）:

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

### 2. WebRTC サーバーを起動

```bash
export DBUS_SESSION_BUS_ADDRESS=unix:path=/tmp/qemu_dbus.sock
./venv/bin/python server/main.py
```

### 3. ブラウザでアクセス

`http://localhost:8081`

## 環境変数

- `DBUS_SESSION_BUS_ADDRESS`  
  QEMU の D-Bus ソケットに接続するためのアドレス
- `QEMU_WEBRTC_DOWNSAMPLE`  
  `1` で 1/2 ダウンサンプル（既定は `0` でフル解像度）

## プロジェクト構成

```
qemu-webrtc-dbus/
├── client/
│   └── index.html             # ブラウザ UI
├── dbus/
│   ├── display_capture.py      # D-Bus接続・入力送信
│   ├── listener.py             # D-Bus Listener
│   ├── p2p_glib.py             # P2P D-Bus接続
│   └── dmabuf_gl.py            # EGL + OpenGL DMA-BUFレンダラ
├── server/
│   ├── main.py                 # WebRTCサーバー
│   ├── video_track.py          # VideoStreamTrack
│   ├── signaling.py            # SDP/ICE
│   └── input_handler.py        # 入力処理
├── docs/
│   └── QEMU_DBus_Display.md     # D-Bus出力の詳細
└── README.md
```

## 既知の課題

- 解像度変更時は再接続が必要な場合あり
- マルチディスプレイ未対応
- 音声未対応

## 詳細ドキュメント

- D-Bus 出力の詳細: `docs/QEMU_DBus_Display.md`
- 調査ログ: `Performance_Issue_v5.md`

