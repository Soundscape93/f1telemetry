"""PyInstaller entry point for f1telemetry package. Kept trivial, real logic lives in the package."""
from f1telemetry.src.ui.app import main


if __name__ == "__main__":
    main()
    