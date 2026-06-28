import os
import sys
import requests
import docker

# 環境変数から設定を取得
API_TOKEN = os.getenv("CF_API_TOKEN")
ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
TUNNEL_ID = os.getenv("CF_TUNNEL_ID")
ACCESS_GROUP_ID = os.getenv("CF_ACCESS_GROUP_ID")  # 既存の使い回したいグループID
DOMAIN = os.getenv("CF_DOMAIN", "clusters-prj.com")

if not all([API_TOKEN, ACCOUNT_ID, TUNNEL_ID, ACCESS_GROUP_ID]):
    print("Error: Missing required environment variables.")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

def get_current_tunnel_config():
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/cfd_tunnel/{TUNNEL_ID}/configurations"
    res = requests.get(url, headers=HEADERS)
    return res.json().get("result", {}).get("config", {}) if res.status_code == 200 else None

def update_tunnel_config(current_config, hostname, dest_url):
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/cfd_tunnel/{TUNNEL_ID}/configurations"
    ingress = current_config.get("ingress", [])
    
    for rule in ingress:
        if rule.get("hostname") == hostname:
            print(f"[{hostname}] Already exists in tunnel config.")
            return True
            
    new_rule = {"hostname": hostname, "service": dest_url}
    if ingress and "service" in ingress[-1] and "hostname" not in ingress[-1]:
        ingress.insert(-1, new_rule)
    else:
        ingress.append(new_rule)
        
    res = requests.put(url, headers=HEADERS, json={"config": {"ingress": ingress}})
    return res.status_code == 200

def create_access_app(hostname, app_name):
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/access/apps"
    payload = {"name": app_name, "domain": hostname, "type": "self_hosted", "session_duration": "24h"}
    res = requests.post(url, headers=HEADERS, json=payload)
    if res.status_code in [200, 201]:
        return res.json().get("result", {}).get("id")
    print(f"Failed to create Access App: {res.text}")
    return None

def create_access_policy(app_id):
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/access/apps/{app_id}/policies"
    # includeに対象のAccess Group IDを指定することで既存のルールを使い回す
    payload = {
        "name": "Inherited Group Policy",
        "decision": "allow",
        "include": [{"group": {"id": ACCESS_GROUP_ID}}]
    }
    res = requests.post(url, headers=HEADERS, json=payload)
    return res.status_code in [200, 201]

def process_container(container):
    labels = container.labels
    if labels.get("cf-tunnel.enable") != "true":
        return

    c_name = container.name
    # ラベルでサブドメインの指定がなければ「コンテナ名-docker」をデフォルトにする
    subdomain = labels.get("cf-tunnel.subdomain", f"{c_name}-docker")
    hostname = f"{subdomain}.{DOMAIN}"
    
    # Cloudflare Tunnel（cloudflared）から見た、このコンテナへの転送先URL
    dest_url = labels.get("cf-tunnel.dest")
    if not dest_url:
        print(f"Error: 'cf-tunnel.dest' label is missing for {c_name}")
        return

    print(f" New container detected: {c_name} -> Target: {hostname} ({dest_url})")

    config = get_current_tunnel_config()
    if not config:
        print("Failed to fetch tunnel configuration.")
        return

    if update_tunnel_config(config, hostname, dest_url):
        app_id = create_access_app(hostname, f"Automated - {c_name}")
        if app_id and create_access_policy(app_id):
            print(f" Successfully protected {hostname} with existing Access Group!")

def main():
    print("Starting Cloudflare Zero Trust Docker Monitor...")
    client = docker.from_env()
    
    # 既存の起動中コンテナもチェック
    for container in client.containers.list():
        process_container(container)

    # コンテナの起動イベントをストリーム監視
    for event in client.events(decode=True, filters={"event": "start", "type": "container"}):
        try:
            # Docker イベントペイロードの構造に合わせてコンテナID取得
            container_id = event.get("Actor", {}).get("ID")
            
            if not container_id:
                print(f"Warning: Event missing container ID: {event}")
                continue
            
            container = client.containers.get(container_id)
            process_container(container)
        except Exception as e:
            print(f"Error processing event: {e}")

if __name__ == "__main__":
    main()
