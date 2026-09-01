#!/usr/bin/env python3
"""Reset the IDOR lab database."""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from seed import seed

if __name__ == "__main__":
    seed()
    print("Lab reset complete.")
