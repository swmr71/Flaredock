import os
import sys
import requests
import docker

# 環境変数から設定を取得
API_TOKEN = os.getenv("CF_API_TOKEN")
ACCOUNT_ID = os.getenv("CF_ACCOUNT_ID")
TUNNEL_ID = os.getenv("CF_TUNNEL_ID")
ACCESS_GROUP_ID = os.getenv("CF_ACCESS_GROUP_ID")
DOMAIN = os.getenv("CF_DOMAIN", "clusters-prj.com")

if not all([API_TOKEN, ACCOUNT_ID, TUNNEL_ID, ACCESS_GROUP_ID]):
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
    return res.status_code == 200

def create_access_app(hostname, app_name):
    print(f"[DEBUG] Creating Access App for {hostname}...")
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/access/apps"
    payload = {"name": app_name, "domain": hostname, "type": "self_hosted", "session_duration": "24h"}
    res = requests.post(url, headers=HEADERS, json=payload, timeout=10)
    if res.status_code in [200, 201]:
        app_id = res.json().get("result", {}).get("id")
        print(f"[DEBUG] Access App created: {app_id}")
        return app_id
    print(f"Failed to create Access App: {res.text}")
    return None

def create_access_policy(app_id):
    print(f"[DEBUG] Creating policy for app {app_id}...")
    url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/access/apps/{app_id}/policies"
    payload = {
        "name": "Inherited Group Policy",
        "decision": "allow",
        "include": [{"group": {"id": ACCESS_GROUP_ID}}]
    }
    res = requests.post(url, headers=HEADERS, json=payload, timeout=10)
    print(f"[DEBUG] Policy creation response: {res.status_code}")
    return res.status_code in [200, 201]

def process_container(container):
    labels = container.labels
    if labels.get("cf-tunnel.enable") != "true":
        return

    c_name = container.name
    subdomain = labels.get("cf-tunnel.subdomain", f"{c_name}-docker")
    hostname = f"{subdomain}.{DOMAIN}"
    
    dest_url = labels.get("cf-tunnel.dest")
    if not dest_url:
        print(f"Error: 'cf-tunnel.dest' label is missing for {c_name}")
        return

    print(f"[*] New container detected: {c_name} -> Target: {hostname} ({dest_url})")

    config = get_current_tunnel_config()
    if not config:
        print("Failed to fetch tunnel configuration.")
        return

    if update_tunnel_config(config, hostname, dest_url):
        app_id = create_access_app(hostname, f"Automated - {c_name}")
        if app_id and create_access_policy(app_id):
            print(f"[✓] Successfully protected {hostname} with existing Access Group!")

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
            process_container(container)
    except Exception as e:
        print(f"[ERROR] Failed to list containers: {e}")
        sys.exit(1)

    print("[DEBUG] Starting event listener...")
    try:
        for event in client.events(decode=True, filters={"event": "start", "type": "container"}):
            print(f"[DEBUG] Event received: {event.get('Actor', {}).get('Attributes', {}).get('name')}")
            try:
                container_id = event.get("Actor", {}).get("ID")
                
                if not container_id:
                    print(f"Warning: Event missing container ID")
                    continue
                
                container = client.containers.get(container_id)
                process_container(container)
            except Exception as e:
                print(f"Error processing event: {e}")
    except Exception as e:
        print(f"[ERROR] Event listener failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()