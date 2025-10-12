# version.py
"""
Version and environment info for s3smart utility.
"""

import platform
import boto3

__version__ = "1.0.0"

def get_version_info() -> str:
    """Return formatted version string."""
    python_version = platform.python_version()
    boto3_version = boto3.__version__
    return f"s3smart {__version__}  |  Python {python_version}  |  boto3 {boto3_version}"

def get_detailed_info() -> dict:
    """Return version info as a dictionary (for logs or APIs)."""
    return {
        "tool": "s3smart",
        "version": __version__,
        "python": platform.python_version(),
        "boto3": boto3.__version__,
        "platform": platform.system(),
        "platform_release": platform.release()
    }
