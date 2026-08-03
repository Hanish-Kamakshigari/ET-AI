import os
import logging
import requests
from typing import Optional

import streamlit as st

logger = logging.getLogger(__name__)

VIDEO_URLS = {
    "Battery_4.mp4": "https://huggingface.co/datasets/ActKamen/surakshaai-footage/resolve/main/Battery_4.mp4",
    "Battery_5.mp4": "https://huggingface.co/datasets/ActKamen/surakshaai-footage/resolve/main/Battery_5.mp4",
    "Battery_6.mp4": "https://huggingface.co/datasets/ActKamen/surakshaai-footage/resolve/main/Battery_6.mp4",
    "Reactor_Block.mp4": "https://huggingface.co/datasets/ActKamen/surakshaai-footage/resolve/main/Reactor_Block.mp4",
    "Storage_Block.mp4": "https://huggingface.co/datasets/ActKamen/surakshaai-footage/resolve/main/Storage_Block.mp4",
}

CACHE_DIR = "footage"

os.makedirs(CACHE_DIR, exist_ok=True)

# Track in-progress downloads so we only attempt each file once per session.
_DOWNLOAD_ATTEMPTED: set[str] = set()


def get_video(filename: str) -> Optional[str]:
    """Return local path to the video file, downloading from HuggingFace if needed.

    Unlike the previous @st.cache_resource version, failed downloads are NOT
    cached — the function will retry on each rerun until the file is available.
    Successful downloads are stored on disk and reused across reruns.
    """
    local_path = os.path.join(CACHE_DIR, filename)

    # Already on disk — serve immediately.
    if os.path.exists(local_path) and os.path.getsize(local_path) > 0:
        return local_path

    # Only attempt each download once per Streamlit session to avoid hammering HF.
    if filename in _DOWNLOAD_ATTEMPTED:
        return None
    _DOWNLOAD_ATTEMPTED.add(filename)

    url = VIDEO_URLS.get(filename)
    if url is None:
        return None

    logger.info("Downloading %s from HuggingFace...", filename)
    try:
        # follow_redirects=True + stream avoids loading the whole file in memory.
        with requests.get(url, stream=True, timeout=60, allow_redirects=True) as r:
            content_type = r.headers.get("content-type", "")
            if r.status_code != 200:
                logger.warning("HTTP %s for %s", r.status_code, filename)
                return None
            # HuggingFace may return an HTML error page — reject it.
            if "text/html" in content_type:
                logger.warning("Got HTML instead of video for %s (dataset may be private or the file name is wrong)", filename)
                return None

            tmp_path = local_path + ".part"
            with open(tmp_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=65536):
                    if chunk:
                        f.write(chunk)

            os.replace(tmp_path, local_path)
            logger.info("Saved %s → %s", filename, local_path)
            return local_path

    except Exception as e:
        logger.error("Failed to download %s: %s", filename, e)
        # Remove partial file if it exists.
        for p in (local_path + ".part", local_path):
            try:
                if os.path.exists(p):
                    os.remove(p)
            except OSError:
                pass
        return None