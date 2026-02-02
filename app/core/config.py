import json
import os
from pydantic import BaseModel
from typing import List, Optional

class VCenterConfig(BaseModel):
    id: str
    name: str
    host: str
    port: int = 443
    verify_ssl: bool = False

class AppSettings(BaseModel):
    title: str = "vCompanion"
    session_timeout: int = 3600
    log_level: str = "INFO"
    refresh_interval_seconds: int = 120

class Config(BaseModel):
    app_settings: AppSettings = AppSettings()
    vcenters: List[VCenterConfig]

def load_config(path: str = None) -> Config:
    """
    Load configuration from config.json.
    If path is not provided, uses config/config.json relative to project root.
    """
    if path is None:
        # Get the directory where this config.py file is located (app/core/)
        current_dir = os.path.dirname(os.path.abspath(__file__))
        # Go up two levels to project root, then into config/
        project_root = os.path.dirname(os.path.dirname(current_dir))
        path = os.path.join(project_root, "config", "config.json")
    
    if not os.path.exists(path):
        # Create default config if not exists
        default_config = {
            "app_settings": {
                "title": "vCompanion",
                "session_timeout": 3600,
                "log_level": "INFO"
            },
            "vcenters": [
                {
                    "id": "example-vc",
                    "name": "Example vCenter",
                    "host": "vcenter.example.com",
                    "port": 443,
                    "verify_ssl": False
                }
            ]
        }
        
        # Ensure directory exists
        os.makedirs(os.path.dirname(path), exist_ok=True)
        
        with open(path, "w") as f:
            json.dump(default_config, f, indent=4)
        
        print(f"\n{'='*60}")
        print(f" NOTICE: Configuration file was missing.")
        print(f" Created default configuration file at:")
        print(f" {path}")
        print(f" Please edit this file with your vCenter details before proceeding.")
        print(f"{'='*60}\n")

    with open(path, "r") as f:
        data = json.load(f)
    
    return Config(**data)

# Singleton instance
settings = load_config()
