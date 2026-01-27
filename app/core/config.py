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

class Config(BaseModel):
    app_settings: AppSettings
    vcenters: List[VCenterConfig]

def load_config(path: str = "config/config.json") -> Config:
    if not os.path.exists(path):
        raise FileNotFoundError(f"Configuration file not found at {path}")
    
    with open(path, "r") as f:
        data = json.load(f)
    
    return Config(**data)

# Singleton instance
settings = load_config()
