from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from script_making.desktop import main

if __name__ == "__main__":
    raise SystemExit(main())
