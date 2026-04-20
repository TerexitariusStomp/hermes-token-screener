# Minimal config for token integration
from pathlib import Path
import os

class Settings:
    def __init__(self):
        # Database paths
        self.db_path = Path.home() / '.hermes' / 'data' / 'central_contracts.db'
        self.output_path = Path.home() / '.hermes' / 'data' / 'token_screener' / 'top100.json'
        
        # Enrichment settings
        self.top_n = 100
        self.max_enrich = 150  # Reduced from 500 to fit within 10min timeout
        self.min_channels = 1
        
        # Scoring weights
        self.w_channel = 0.3
        self.w_freshness = 0.2
        self.w_low_fdv = 0.15
        self.w_volume = 0.15
        self.w_txns = 0.1
        self.w_momentum = 0.1
        
        # Thresholds
        self.sell_ratio_threshold = 0.5
        self.stagnant_volume_ratio = 0.1
        self.no_activity_hours = 24
        
        # Rate limiting
        self.rate_limit_delay = 0.5  # seconds between API calls
        
        # API keys (empty = skip)
        self.coingecko_api_key = os.getenv('COINGECKO_API_KEY', '')
        self.etherscan_api_key = os.getenv('ETHERSCAN_API_KEY', '')
        self.defi_api_key = os.getenv('DEFI_API_KEY', '')
        self.rugcheck_api_key = os.getenv('RUGCHECK_API_KEY', '')
        self.gmgn_api_key = os.getenv('GMGN_API_KEY', '')
        self.surf_api_key = os.getenv('SURF_API_KEY', '')
        self.zerion_api_key = os.getenv('ZERION_API_KEY', '')
        self.coinstats_api_key = os.getenv('COINSTATS_API_KEY', '')
        
        # GMGN CLI path
        self.gmgn_cli = Path.home() / '.hermes' / 'scripts' / 'gmgn-cli'
        
        # Session
        self.session_path = Path.home() / '.hermes' / '.telegram_session' / 'hermes_user'
        self.tg_api_id = int(os.getenv('TG_API_ID', '39533004'))
        self.tg_api_hash = os.getenv('TG_API_HASH', '958e52889177eec2fa15e9e4e4c2cc4c')
        self.state_file = Path.home() / '.hermes' / 'data' / 'tg_scraper_state.json'

# Global settings instance
settings = Settings()
