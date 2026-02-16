# TURN (coturn) Setup on AWS for This Project

このドキュメントは、本プロジェクト (`qemu-webrtc-dbus`) をオンプレミスPCから安定して視聴するために、
AWS 上で TURN サーバー (coturn) を構築する手順です。

## 1. 目的

- `8081/tcp` のシグナリングだけでは届かない WebRTC メディアを中継する
- NAT / FW 制約が強いネットワークでも接続を成立させる

## 2. 事前準備

- TURN 用のグローバル到達可能ホスト (EC2推奨)
- DNS名 (例: `turn.example.com`) を利用する場合は A レコードを設定

## 3. coturn インストール

```bash
sudo apt update
sudo apt install -y coturn
```

## 4. coturn 設定

`/etc/turnserver.conf` を以下ベースで設定します。

```conf
listening-port=3478
tls-listening-port=5349

fingerprint
lt-cred-mech
realm=turn.example.com
user=webrtc:strongpassword

# TURNサーバー自身のPublic IP
external-ip=YOUR_PUBLIC_IP

# 中継ポート範囲（運用しやすいよう固定）
min-port=49160
max-port=49200

no-multicast-peers
```

TLS も使う場合は証明書を追加:

```conf
cert=/etc/letsencrypt/live/turn.example.com/fullchain.pem
pkey=/etc/letsencrypt/live/turn.example.com/privkey.pem
```

## 5. サービス有効化

```bash
sudo systemctl enable coturn
sudo systemctl restart coturn
sudo systemctl status coturn --no-pager
```

## 6. AWS Security Group

TURN サーバー側で以下を許可してください。

- `3478/tcp`
- `3478/udp`
- `5349/tcp` (TLS利用時)
- `49160-49200/udp`

必要に応じて送信元をオンプレミスのグローバルIPに制限してください。

## 7. 本プロジェクト側設定

WebRTC サーバー起動前に環境変数を設定します。

```bash
export QEMU_WEBRTC_TURN_HOST=turn.example.com
export QEMU_WEBRTC_TURN_USERNAME=webrtc
export QEMU_WEBRTC_TURN_CREDENTIAL='strongpassword'
export QEMU_WEBRTC_TURN_TRANSPORTS=udp,tcp
export QEMU_WEBRTC_STUN_URL='stun:stun.l.google.com:19302'
export QEMU_WEBRTC_ICE_TRANSPORT_POLICY=all
```

疎通確認時は TURN 強制:

```bash
export QEMU_WEBRTC_ICE_TRANSPORT_POLICY=relay
```

`/webrtc-config` に `YOUR_TURN_HOST` や `<...>` が残っている場合は設定エラーとして扱われ、
ブラウザ側で接続を開始しません。

## 8. 動作確認ポイント

1. ブラウザ開発者ツールで `ICE connection state` が `connected/completed` になる
2. `relay` candidate が選択される
3. 映像が黒画面から更新される

## 9. トラブルシュート

- 接続はするが黒画面:
  - `QEMU_WEBRTC_ICE_TRANSPORT_POLICY=relay` で改善するか確認
  - coturn と SG の中継ポート範囲 (`49160-49200/udp`) を確認
- TURN 認証失敗:
  - `user=` のユーザー名/パスワードと `QEMU_WEBRTC_ICE_SERVERS` の一致を確認
- 名前解決問題:
  - 一時的に `turn:PUBLIC_IP:3478?...` を使って切り分け
