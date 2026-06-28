import os
import sys
import requests
import docker

# 環境変数から設定を取得
API_TOKEN = os.getenv("CF_API_TOKEN")
ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
TUNNEL_ID = os.getenv("CF_TUNNEL_ID")
DOMAIN = os.getenv("CF_DOMAIN", "clusters-prj.com")

if not all([API_TOKEN, ACCOUNT_ID, TUNNEL_ID]):
    print("Error: Missing required environment variables.")
    sys.exit(1)

HEADERS = {
    "Authorization": f"Bearer {API_TOKEN}",
    "Content-Type": "application/json"
}

def get_current_tunnel_config():
    print("[DEBUG] Fetching tunnel config...")
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/cfd_tunnel/{TUNNEL_ID}/configurations"
    res = requests.get(url, headers=HEADERS, timeout=10)
    print(f"[DEBUG] Tunnel config response: {res.status_code}")
    return res.json().get("result", {}).get("config", {}) if res.status_code == 200 else None

def get_zone_id():
    """ドメインの Zone ID を取得"""
    print(f"[DEBUG] Fetching Zone ID for {DOMAIN}...")
    url = f"https://api.cloudflare.com/client/v4/zones?name={DOMAIN}"
    res = requests.get(url, headers=HEADERS, timeout=10)
    if res.status_code == 200:
        zones = res.json().get("result", [])
        if zones:
            zone_id = zones[0].get("id")
            print(f"[DEBUG] Zone ID: {zone_id}")
            return zone_id
    print(f"[DEBUG] Failed to fetch Zone ID")
    return None

def get_tunnel_cname():
    """Tunnel の CNAME ターゲットを取得"""
    print(f"[DEBUG] Fetching Tunnel CNAME...")
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/cfd_tunnel/{TUNNEL_ID}"
    res = requests.get(url, headers=HEADERS, timeout=10)
    if res.status_code == 200:
        tunnel = res.json().get("result", {})
        cname = tunnel.get("cname")
        print(f"[DEBUG] Tunnel CNAME: {cname}")
        return cname
    print(f"[DEBUG] Failed to fetch Tunnel CNAME")
    return None

def create_dns_record(zone_id, subdomain, cname_target):
    """DNS CNAME レコードを作成"""
    print(f"[DEBUG] Creating DNS record for {subdomain}.{DOMAIN} -> {cname_target}...")
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    payload = {
        "type": "CNAME",
        "name": subdomain,
        "content": cname_target,
        "ttl": 1,  # Auto
        "proxied": True
    }
    res = requests.post(url, headers=HEADERS, json=payload, timeout=10)
    
    if res.status_code in [200, 201]:
        print(f"[DEBUG] DNS record created successfully")
        return True
    elif res.status_code == 400:
        # レコードが既に存在する場合
        if "already_exists" in res.text or "duplicate" in res.text.lower():
            print(f"[DEBUG] DNS record already exists")
            return True
        print(f"[DEBUG] DNS record creation failed: {res.text}")
        return False
    else:
        print(f"[DEBUG] DNS record creation failed ({res.status_code}): {res.text}")
        return False

def update_tunnel_config(current_config, hostname, dest_url):
    print(f"[DEBUG] Updating tunnel config for {hostname}...")
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
        
    res = requests.put(url, headers=HEADERS, json={"config": {"ingress": ingress}}, timeout=10)
    print(f"[DEBUG] PUT response: {res.status_code}")
    
    if res.status_code == 200:
        # Tunnel 設定成功後、DNS レコードも自動作成
        zone_id = get_zone_id()
        if zone_id:
            cname_target = get_tunnel_cname()
            if cname_target:
                subdomain = hostname.replace(f".{DOMAIN}", "")
                create_dns_record(zone_id, subdomain, cname_target)
    
    return res.status_code == 200

def create_access_app(hostname, app_name):
    """
    Access App を作成（ポリシーは手動で設定）
    """
    print(f"[DEBUG] Creating Access App for {hostname}...")
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/access/apps"
    payload = {"name": app_name, "domain": hostname, "type": "self_hosted", "session_duration": "24h"}
    res = requests.post(url, headers=HEADERS, json=payload, timeout=10)
    if res.status_code in [200, 201]:
        app_id = res.json().get("result", {}).get("id")
        print(f"[DEBUG] Access App created: {app_id}")
        return app_id
    
    # 既に存在する場合はスキップ
    if res.status_code == 400 and "application_already_exists" in res.text:
        print(f"[DEBUG] Access App already exists for {hostname}")
        return None
    
    print(f"Failed to create Access App: {res.text}")
    return None

def create_access_policy(app_id):
    print(f"[DEBUG] Policy management is manual. Configure in Cloudflare dashboard.")
    return True

def get_port_forward_url(container):
    """
    コンテナのポート公開情報から、転送先URLを生成
    Docker ホストマシンの IP + ホストポートを使用
    
    複数ポート公開時は、443系（HTTPS）を優先、次に8000系、その他の順
    """
    ports = container.ports
    
    if not ports:
        print(f"[{container.name}] No exposed ports found")
        return None
    
    # Docker ホストマシンの IP を取得（環境変数で指定可能）
    docker_host_ip = os.getenv("DOCKER_HOST_IP", "localhost")
    
    # ポート優先度リスト（443系 > 8000系 > その他）
    priority_ports = []
    other_ports = []
    
    for container_port, bindings in ports.items():
        if bindings:
            binding = bindings[0]
            host_port = binding.get("HostPort")
            
            if not host_port:
                continue
            
            port_num = int(host_port)
            
            # 443系ポート（9443, 8443, 443など）を優先
            if port_num in [443, 8443, 9443]:
                priority_ports.append((port_num, host_port))
            # 8000系ポートを次優先
            elif 8000 <= port_num < 9000:
                priority_ports.append((port_num, host_port))
            else:
                other_ports.append((port_num, host_port))
    
    # ソート：443系を優先（降順で9443, 8443, 443）
    priority_ports.sort(reverse=True)
    selected_port = priority_ports[0][1] if priority_ports else (other_ports[0][1] if other_ports else None)
    
    if not selected_port:
        print(f"[{container.name}] No suitable port found")
        return None
    
    url = f"http://{docker_host_ip}:{selected_port}"
    print(f"[{container.name}] Using host binding: {url}")
    return url

def process_container(container):
    """
    コンテナをチェックして、ポート公開があれば自動でTunnel設定
    """
    # ポート情報がなければスキップ
    if not container.ports:
        return
    
    c_name = container.name
    
    # ラベルで明示的に無効化されてたらスキップ
    if container.labels and container.labels.get("cf-tunnel.enable") == "false":
        print(f"[{c_name}] Explicitly disabled via label")
        return
    
    # サブドメイン決定（ラベル優先、なければ「コンテナ名-docker」）
    subdomain = container.labels.get("cf-tunnel.subdomain") if container.labels else None
    if not subdomain:
        subdomain = f"{c_name}-docker"
    
    hostname = f"{subdomain}.{DOMAIN}"
    
    # 転送先URL決定（ラベル優先、なければ自動検出）
    dest_url = container.labels.get("cf-tunnel.dest") if container.labels else None
    if not dest_url:
        dest_url = get_port_forward_url(container)
    
    if not dest_url:
        print(f"[{c_name}] No destination URL available")
        return

    print(f"[*] Processing container: {c_name} -> {hostname} ({dest_url})")

    config = get_current_tunnel_config()
    if not config:
        print("Failed to fetch tunnel configuration.")
        return

    if update_tunnel_config(config, hostname, dest_url):
        create_access_app(hostname, f"Automated - {c_name}")
        print(f"[✓] Successfully added {hostname} to Tunnel!")

def main():
    print("Starting Cloudflare Zero Trust Docker Monitor...")
    
    print("[DEBUG] Connecting to Docker daemon...")
    try:
        client = docker.from_env()
        print("[DEBUG] Docker connection successful!")
    except Exception as e:
        print(f"[ERROR] Failed to connect to Docker: {e}")
        sys.exit(1)
    
    print("[DEBUG] Listing existing containers...")
    try:
        containers = client.containers.list()
        print(f"[DEBUG] Found {len(containers)} containers")
        for container in containers:
            print(f"[DEBUG]   - {container.name}")
            try:
                process_container(container)
            except Exception as e:
                print(f"[ERROR] Failed to process {container.name}: {e}")
    except Exception as e:
        print(f"[ERROR] Failed to list containers: {e}")
        sys.exit(1)

    print("[DEBUG] Starting event listener...")
    try:
        for event in client.events(decode=True, filters={"event": "start", "type": "container"}):
            try:
                container_id = event.get("Actor", {}).get("ID")
                container_name = event.get("Actor", {}).get("Attributes", {}).get("name")
                
                if not container_id:
                    print(f"Warning: Event missing container ID")
                    continue
                
                print(f"[DEBUG] Container started: {container_name}")
                container = client.containers.get(container_id)
                process_container(container)
            except Exception as e:
                print(f"Error processing event: {e}")
    except Exception as e:
        print(f"[ERROR] Event listener failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()