from huggingface_hub import HfApi
import os

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
        delete_patterns=["*"],  # Ensures clean sync of the restored root structures
        ignore_patterns=[".git*", "hf_error*", "uv_error*", "hf_push_error*", "hf_upload_error*", "upload_hf.py"],
    )
    print("Upload successful!")
except Exception as e:
    print(f"Upload failed: {e}")
