"""
MiniGrok Swarm — Entry point.

Tiered parallel Grok agents with PC automation tools.
"""
import sys
import os

# Ensure project root is on the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from gui.app import SwarmApp


def main():
    app = SwarmApp()
    app.mainloop()


if __name__ == "__main__":
    main()
