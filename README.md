# Flaredock
Flaredock は、Dockerコンテナの起動をリアルタイムに監視し、Cloudflare Tunnel（Argo Tunnel）のルーティング設定と、Cloudflare Zero Trust（Access）による認証保護を完全自動化する軽量デーモンコンテナです。
# Flaredock 🚀

Dockerコンテナの起動を検知し、Cloudflare Tunnelの設定とZero Trust認証の適用を完全自動化するデーモンツール。

コンテナに特定のラベルを貼って起動するだけで、世界中どこからでも安全にアクセスできる「認証付きサブドメイン」が即座に生えてきます。

## 🌟 特徴
- **完全自動のインバウンドルーティング**: `docker run` や `docker compose up` を検知して自動でTunnelのIngressルールを更新。
- **Zero Trustによる即時保護**: 新規サブドメインに対して、既存のCloudflare Access Group（認証ポリシー）を自動で適用。
- **コンテナ単体で動作**: ホストの `/var/run/docker.sock` を読み込むだけで動く軽量設計。

---

## 🛠️ 事前準備
1. **Cloudflare API トークン**
   - 以下の権限を持ったトークンを生成してください。
     - `Account.Cloudflare Tunnel (Edit)`
     - `Account.Access (Edit)`
2. **Cloudflare 既存の Access Group**
   - 使い回したい既存の閲覧許可ルール（Access Group）の **Group ID (UUID)** をダッシュボードから控えておいてください。

---

## 🚀 使い方

### 1. Flaredock の起動

まずは、Dockerホスト側で `Flaredock` 自体を常駐させます。

#### `docker-compose.yml` (Flaredock用)
```yaml
version: '3.8'

services:
  flaredock:
    image: your-registry/flaredock:latest  # またはビルド指定
    container_name: flaredock
    restart: always
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    environment:
      - CF_API_TOKEN=your_cloudflare_api_token
      - CF_ACCOUNT_ID=your_cloudflare_account_id
      - CF_TUNNEL_ID=your_cloudflare_tunnel_id
      - CF_ACCESS_GROUP_ID=your_existing_access_group_id
      - CF_DOMAIN=clusters-prj.com
