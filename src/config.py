import os
import sys

from dotenv import load_dotenv
from loguru import logger

load_dotenv()

VK_GROUP_TOKEN: str = os.getenv("VK_GROUP_TOKEN")
VK_USER_TOKEN: str = os.getenv("VK_USER_TOKEN")

try:
    VK_GROUP_ID: int = int(os.getenv("VK_GROUP_ID"))
    VK_ADMIN_IDS: list[int] = [int(id_) for id_ in os.getenv("VK_ADMIN_IDS").split(',')]
except ValueError as e:
    logger.error(f"Some of VK values are incorrect: {e}")
    sys.exit(1)

TG_TOKEN: str = os.getenv("TG_TOKEN")
TG_CHANNEL_ID: str = os.getenv("TG_CHANNEL_ID")

try:
    TG_ADMIN_IDS: list[int] = [int(id_) for id_ in os.getenv("TG_ADMIN_IDS").split(',')]
except ValueError as e:
    logger.error(f"Some of TG values are incorrect: {e}")
    sys.exit(1)
