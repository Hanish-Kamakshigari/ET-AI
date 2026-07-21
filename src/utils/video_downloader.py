import os
import requests
from typing import Optional

import streamlit as st

VIDEO_URLS = {
    "Battery_4.mp4": "https://huggingface.co/datasets/ActKamen/surakshaai-footage/resolve/main/Battery_4.mp4",
    "Battery_5.mp4": "https://huggingface.co/datasets/ActKamen/surakshaai-footage/resolve/main/Battery_5.mp4",
    "Battery_6.mp4": "https://huggingface.co/datasets/ActKamen/surakshaai-footage/resolve/main/Battery_6.mp4",
    "Reactor_Block.mp4": "https://huggingface.co/datasets/ActKamen/surakshaai-footage/resolve/main/Reactor_Block.mp4",
    "Storage_Block.mp4": "https://huggingface.co/datasets/ActKamen/surakshaai-footage/resolve/main/Storage_Block.mp4",
}

CACHE_DIR = "footage"

os.makedirs(CACHE_DIR, exist_ok=True)


@st.cache_resource
def get_video(filename: str) -> Optional[str]:
    local_path = os.path.join(CACHE_DIR, filename)

    print(f"Looking for: {local_path}")

    if os.path.exists(local_path):
        print(f"Found cached video: {local_path}")
        return local_path

    print(f"Downloading {filename}...")
    url = VIDEO_URLS.get(filename)
    if url is None:
        return None

    try:
        r = requests.get(url, stream=True)

        print(f"Status: {r.status_code}")
        r.raise_for_status()

        with open(local_path, "wb") as f:
            for chunk in r.iter_content(8192):
                if chunk:
                    f.write(chunk)

        print(f"Saved to {local_path}")
        return local_path

    except Exception as e:
        print(f"Failed to download {filename}: {e}")
        return None