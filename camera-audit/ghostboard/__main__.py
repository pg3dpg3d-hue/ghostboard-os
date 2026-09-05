"""Point d'entrée : `python -m ghostboard` lance la TUI RECON."""
import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main())
