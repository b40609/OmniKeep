import sys
from pathlib import Path

# Ensure Hub directory is in sys.path
BASE_DIR = Path(__file__).resolve().parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from app.mcp_server import main

if __name__ == "__main__":
    main()
