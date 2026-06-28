# Flaredock
Dockerコンテナの起動をリアルタイムに監視し、Cloudflare Tunnel（Argo Tunnel）のルーティング設定と、Cloudflare Zero Trust（Access）による認証保護を完全自動化する軽量デーモンコンテナです。

## 🌟 特徴
- **自動ポート検出**: コンテナがポート公開してたら自動で Tunnel に登録
- **ラベルによる上書き**: `cf-tunnel.subdomain` や `cf-tunnel.dest` で詳細制御が可能
- **Zero Trust自動適用**: 既存の Access Group を自動で新規サブドメインに適用
- **コンテナ単体で動作**: ホストの `/var/run/docker.sock` を読み込むだけで動く軽量設計

---

## 🛠️ セットアップ

### 1. 環境変数の設定

`.env.example` から `.env` を作成して、Cloudflare API 情報を入力：

```bash
cp .env.example .env
# .env を編集して以下を入力：
# - CF_API_TOKEN: Cloudflare API トークン
# - CF_ACCOUNT_ID: アカウントID
# - CF_TUNNEL_ID: Tunnel ID
# - CF_ACCESS_GROUP_ID: 既存の Access Group ID
# - CF_DOMAIN: ベースドメイン（例: clusters-prj.com）
```

### 2. 起動

```bash
docker-compose up -d
```

Flaredock が Docker イベントをリッスンし、**ポート公開されたコンテナを自動でスキャン** します。

---

## 🚀 動作原理

### 自動検出モード（デフォルト）
コンテナがポート公開してると、以下の自動設定が走ります：

1. **サブドメイン**: `{コンテナ名}-docker.{DOMAIN}` （例: `nginx-docker.clusters-prj.com`）
2. **転送先**: ホストの IP とポート、またはコンテナ内部通信アドレス
3. **認証**: 既存の Access Group のポリシーを自動適用

### ラベルでのカスタマイズ

```yaml
services:
  my-app:
    image: nginx:latest
    ports:
      - "8080:80"
    labels:
      # サブドメインをカスタマイズ
      - "cf-tunnel.subdomain=custom-dashboard"
      
      # 転送先URLを明示的に指定
      - "cf-tunnel.dest=http://192.168.1.100:8080"
      
      # 明示的に無効化（cf-tunnel.enable=false を指定したら Flaredock は無視）
      # - "cf-tunnel.enable=false"
```

---

## 📋 環境変数リスト

| 環境変数 | 必須 | 説明 |
|---|---|---|
| `CF_API_TOKEN` | ✅ | Cloudflare API トークン（Account.Cloudflare Tunnel (Edit) と Account.Access (Edit) 権限必須） |
| `CF_ACCOUNT_ID` | ✅ | Cloudflare アカウントID |
| `CF_TUNNEL_ID` | ✅ | 使用する Cloudflare Tunnel の ID |
| `CF_ACCESS_GROUP_ID` | ✅ | 既存の Access Group ID（ポリシーの適用先） |
| `CF_DOMAIN` | ⭕ | ベースドメイン（デフォルト: `clusters-prj.com`） |
| `DOCKER_HOST_IP` | ⭕ | Docker ホストマシンの IP アドレス（例: `10.2.0.1`）。Tunnel からコンテナへのアクセス時に使用 |

---

## ⚠️ 注意事項

- **Tunnel 設定の上書き**: Cloudflare の仕様上、Tunnel Ingress は「現在の設定を取得 → ルール追加 → 丸ごと上書き」で更新します。手動での設定変更直後にコンテナ再起動すると競合の可能性があります。
- **DNS 自動同期**: Tunnel 設定更新時に対応する CNAME レコードが Cloudflare 側で自動生成されます。
- **Access Group の事前作成**: Access Group ID は事前にダッシュボードで作成・確認が必要です。

---

## 🔧 トラブルシューティング

### ログを確認

```bash
docker logs -f flaredock
```

### API トークンのテスト

```bash
curl -X GET "https://api.cloudflare.com/client/v4/user" \
  -H "Authorization: Bearer {YOUR_API_TOKEN}"
```

### docker.sock のパーミッション確認

```bash
ls -la /var/run/docker.sock
```

Flaredock コンテナが読み取り可能な状態である必要があります。

---

## 📝 ライセンス

MIT