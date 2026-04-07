from huggingface_hub import HfApi
import os
from dotenv import load_dotenv

load_dotenv()  # Loads HF_TOKEN from .env

api = HfApi()
token = os.getenv("HF_TOKEN")
repo_id = "neel-110/sre-bench-env"

# Sync the entire folder directly to the Space
print(f"Uploading to {repo_id}...")
try:
    api.upload_folder(
        folder_path=".",
        repo_id=repo_id,
        repo_type="space",
        token=token,
        delete_patterns=["*"],  # Sync and delete files not present locally
        ignore_patterns=[
            ".git*",
            "__pycache__",
            ".env",
            "upload_hf.py"
        ],
    )
    print("Upload successful!")
except Exception as e:
    print(f"Upload failed: {e}")
