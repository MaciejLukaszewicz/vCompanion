import json
import os
import webbrowser
import time
import socket

def wait_for_port(port, timeout=30):
    """Wait until the port is open on localhost."""
    start_time = time.time()
    while time.time() - start_time < timeout:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(1)
            result = sock.connect_ex(('127.0.0.1', port))
            if result == 0:
                return True
        time.sleep(0.5)
    return False

def open_browser():
    try:
        # Resolve config path
        base_path = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(base_path, "config", "config.json")
        
        if not os.path.exists(config_path):
            return

        with open(config_path, "r") as f:
            config = json.load(f)
            
        app_settings = config.get("app_settings", {})
        should_open = app_settings.get("open_browser_on_start", True)
        port = app_settings.get("port", 8000)
        
        if should_open:
            print(f"Waiting for server on port {port}...")
            if wait_for_port(port):
                # Extra delay to ensure app is fully initialized (lifespan tasks etc)
                time.sleep(2)
                url = f"http://localhost:{port}"
                print(f"Server is up! Opening {url}...")
                webbrowser.open(url)
            else:
                print(f"Timeout waiting for server on port {port}.")
            
    except Exception as e:
        print(f"Error launching browser: {e}")

if __name__ == "__main__":
    # Give the server a moment to at least start spawning
    time.sleep(1)
    open_browser()
