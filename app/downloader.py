import os
from typing import Tuple, Optional
import yt_dlp
import imageio_ffmpeg

def download_video(url: str) -> Optional[Tuple[str, int]]:
    """
    Downloads a video from the given URL using yt-dlp.
    Saves the file as an MP4 in the 'downloads' folder.
    
    Args:
        url: The YouTube (or other platform) video URL.
        
    Returns:
        A tuple containing (file_path: str, duration_in_seconds: int),
        or None if the download fails due to invalid URL or unavailability.
    """
    download_dir = "downloads"
    os.makedirs(download_dir, exist_ok=True)
    
    # yt-dlp options to prioritize mp4 and merge audio/video if necessary
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': os.path.join(download_dir, '%(id)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe(),
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # extract_info downloads the video when download=True
            info = ydl.extract_info(url, download=True)
            
            if not info:
                return None
            
            video_id = info.get('id', 'unknown')
            duration = info.get('duration', 0)
            
            # The exact filepath might vary if merging happened, 
            # but prepare_filename usually gives the base structure.
            # Using our outtmpl, the final file should be an mp4.
            expected_path = os.path.abspath(os.path.join(download_dir, f"{video_id}.mp4"))
            
            # Fallback check if for some reason it wasn't named exactly as expected
            if not os.path.exists(expected_path):
                prepared = ydl.prepare_filename(info)
                # If merged into mp4, the extension of prepared might be wrong, so we check
                base, _ = os.path.splitext(prepared)
                if os.path.exists(base + ".mp4"):
                    expected_path = os.path.abspath(base + ".mp4")
                else:
                    expected_path = os.path.abspath(prepared)

            return expected_path, duration
            
    except yt_dlp.utils.DownloadError as e:
        print(f"Download Error: The video is unavailable or the URL is invalid. Details: {e}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred during download: {e}")
        return None

if __name__ == "__main__":
    # A short, public YouTube video for testing
    test_url = "https://www.youtube.com/watch?v=TowEXCJ3XUg" 
    print(f"Starting download for {test_url}...")
    
    result = download_video(test_url)
    
    if result:
        file_path, duration = result
        print(f"Success! Video saved to: {file_path}")
        print(f"Duration: {duration} seconds")
    else:
        print("Download failed.")
