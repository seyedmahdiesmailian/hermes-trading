"""Configuration loader.

Loads configuration from environment variables and .env file.
"""

import os
from pathlib import Path
from typing import Dict, Any


class Config:
    """Configuration manager.
    
    Loads from:
    1. Environment variables
    2. .env file (if exists)
    
    Usage:
        config = Config()
        
        bridge_url = config.get('BRIDGE_URL')
        dry_run = config.get_bool('DRY_RUN', default=True)
    """
    
    def __init__(self, env_file: str | Path | None = None):
        self._config: Dict[str, str] = {}
        
        # Load from .env if provided
        if env_file:
            self._load_env_file(env_file)
        
        # Load from environment (overrides .env)
        self._load_from_env()
    
    def _load_env_file(self, env_file: str | Path):
        """Load from .env file."""
        path = Path(env_file)
        if not path.exists():
            return
        
        with open(path, 'r') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                if '=' in line:
                    key, value = line.split('=', 1)
                    self._config[key.strip()] = value.strip()
    
    def _load_from_env(self):
        """Load from environment variables."""
        # Load Hermes-specific vars
        hermes_vars = [
            'HERMES_DRY_RUN',
            'HERMES_WIN_IP',
            'HERMES_BRIDGE_URL',
            'HERMES_BRIDGE_TOKEN',
            'TELEGRAM_BOT_TOKEN',
            'TELEGRAM_CHAT_ID',
            'TELEGRAM_SIGNAL_GROUP',
            'DATA_DIR'
        ]
        
        for var in hermes_vars:
            value = os.getenv(var)
            if value:
                self._config[var] = value
    
    def get(self, key: str, default: str | None = None) -> str | None:
        """Get config value.
        
        Args:
            key: Config key
            default: Default value
            
        Returns:
            Config value or default
        """
        return self._config.get(key, default)
    
    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get boolean config value.
        
        Args:
            key: Config key
            default: Default value
            
        Returns:
            Boolean value
        """
        value = self.get(key)
        if value is None:
            return default
        
        return value.lower() in ('true', '1', 'yes', 'on')
    
    def get_int(self, key: str, default: int = 0) -> int:
        """Get integer config value.
        
        Args:
            key: Config key
            default: Default value
            
        Returns:
            Integer value
        """
        value = self.get(key)
        if value is None:
            return default
        
        try:
            return int(value)
        except ValueError:
            return default
    
    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get float config value.
        
        Args:
            key: Config key
            default: Default value
            
        Returns:
            Float value
        """
        value = self.get(key)
        if value is None:
            return default
        
        try:
            return float(value)
        except ValueError:
            return default
    
    def require(self, key: str) -> str:
        """Get required config value.
        
        Args:
            key: Config key
            
        Returns:
            Config value
            
        Raises:
            ValueError: If key not found
        """
        value = self.get(key)
        if value is None:
            raise ValueError(f"Required config key not found: {key}")
        return value
    
    def __repr__(self) -> str:
        # Hide sensitive values
        safe_keys = [k for k in self._config.keys() if 'TOKEN' not in k and 'PASS' not in k]
        return f"Config({len(self._config)} keys, showing {len(safe_keys)} non-sensitive)"
