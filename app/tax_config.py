"""Tax Configuration Module for EquityPulse Capital Gains Calculation.

Default Indian Equity Capital Gains Tax Rates (as per Budget 2024 update):
- STCG (Short-Term Capital Gains, held < 365 days): 20% (0.20)
- LTCG (Long-Term Capital Gains, held >= 365 days): 12% (0.12)
- Threshold Days: 365

These values can be configured via:
1. Environment variables (STCG_TAX_RATE, LTCG_TAX_RATE, CAPITAL_GAINS_THRESHOLD_DAYS)
2. Direct edits in this configuration module
3. Runtime API endpoints (/api/tax-config)
"""

import os
from typing import Dict, Any
from dotenv import load_dotenv

load_dotenv()

# Read default configurations with fallbacks
_DEFAULT_STCG_RATE = float(os.getenv("STCG_TAX_RATE", "0.20"))
_DEFAULT_LTCG_RATE = float(os.getenv("LTCG_TAX_RATE", "0.12"))
_DEFAULT_THRESHOLD_DAYS = int(os.getenv("CAPITAL_GAINS_THRESHOLD_DAYS", "365"))

# Active configuration dictionary
_tax_settings: Dict[str, Any] = {
    "stcg_rate": _DEFAULT_STCG_RATE,
    "ltcg_rate": _DEFAULT_LTCG_RATE,
    "threshold_days": _DEFAULT_THRESHOLD_DAYS,
}

def get_tax_config() -> Dict[str, Any]:
    """Retrieve the active tax configuration."""
    return dict(_tax_settings)

def update_tax_config(stcg_rate: float, ltcg_rate: float, threshold_days: int = 365) -> Dict[str, Any]:
    """Update the active tax configuration."""
    if stcg_rate < 0 or stcg_rate > 1:
        raise ValueError("STCG rate must be between 0.0 (0%) and 1.0 (100%).")
    if ltcg_rate < 0 or ltcg_rate > 1:
        raise ValueError("LTCG rate must be between 0.0 (0%) and 1.0 (100%).")
    if threshold_days < 1:
        raise ValueError("Threshold days must be at least 1 day.")
        
    _tax_settings["stcg_rate"] = round(float(stcg_rate), 4)
    _tax_settings["ltcg_rate"] = round(float(ltcg_rate), 4)
    _tax_settings["threshold_days"] = int(threshold_days)
    return dict(_tax_settings)
