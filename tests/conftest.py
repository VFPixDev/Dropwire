import os

# Test suite imports modules that load src.config at import time.
# Ensure required env var is always present in CI during collection.
os.environ.setdefault("BOT_TOKEN", "test-bot-token")
