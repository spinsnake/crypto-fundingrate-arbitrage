import re

def map_k_symbol(symbol: str) -> str:
    k_tokens = {"BONK", "PEPE", "SHIB", "FLOKI", "LUNC"}  # เพิ่มเหรียญได้ที่นี่

    match = re.match(r"([A-Z]+)(/USDC:USDC)", symbol, re.IGNORECASE)
    if match and match.group(1).upper() in k_tokens:
        return f'k{match.group(1).upper()}{match.group(2)}'
    return symbol

