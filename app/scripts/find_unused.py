
from pathlib import Path
import sys

def read_text_with_fallback(path: Path):
    data = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return data.decode(enc), enc, False
        except UnicodeDecodeError:
            continue
    # final safe fallback (won't raise, but may replace invalid bytes)
    return data.decode("utf-8", errors="replace"), "utf-8 (replace)", True

# --- inside main() replace the failing read with:
text, used_enc, replaced = read_text_with_fallback(REQ_FILE)
if replaced:
    print(f"Warning: `requirements.txt` decoded with replacements (invalid bytes). Detected encoding: {used_enc}", file=sys.stderr)
else:
    print(f"Note: `requirements.txt` decoded as {used_enc}", file=sys.stderr)

lines = text.splitlines()