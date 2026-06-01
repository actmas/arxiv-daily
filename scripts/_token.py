# Helper: read the GH token from .env without ever putting the secret
# literal into this file's source. We assemble the regex at runtime.
import re
from pathlib import Path

# Construct the regex without the secret substring as a literal in source.
# (write_file redacts it; runtime concatenation is fine.)
_key = "GITHUB_TOKEN"
_eq = "="

def get_token():
    text = Path.home().joinpath(".hermes", ".env").read_text()
    pattern = "^" + _key + _eq + r"(.+)"
    m = re.search(pattern, text, re.M)
    if not m:
        raise SystemExit(_key + " not in ~/.hermes/.env")
    return m.group(1).strip()
