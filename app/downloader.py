import os
from typing import Tuple, Optional
import yt_dlp
import imageio_ffmpeg

def download_video(url: str) -> Optional[Tuple[str, int]]:
    # dl video
    download_dir = "downloads"
    os.makedirs(download_dir, exist_ok=True)
    
    # opts
    ydl_opts = {
        'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
        'outtmpl': os.path.join(download_dir, '%(id)s.%(ext)s'),
        'merge_output_format': 'mp4',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'ffmpeg_location': imageio_ffmpeg.get_ffmpeg_exe(),
    }

    max_retries = 3
    import time
    
    for attempt in range(1, max_retries + 1):
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                
                if not info:
                    return None
                
                video_id = info.get('id', 'unknown')
                duration = info.get('duration', 0)
                
                expected_path = os.path.abspath(os.path.join(download_dir, f"{video_id}.mp4"))
                
                if not os.path.exists(expected_path):
                    prepared = ydl.prepare_filename(info)
                    base, _ = os.path.splitext(prepared)
                    if os.path.exists(base + ".mp4"):
                        expected_path = os.path.abspath(base + ".mp4")
                    else:
                        expected_path = os.path.abspath(prepared)

                # check size
                if os.path.exists(expected_path) and os.path.getsize(expected_path) > 1024:
                    return expected_path, duration
                else:
                    raise Exception(f"Output file {expected_path} is missing or corrupted.")
                
        except yt_dlp.utils.DownloadError as e:
            print(f"Attempt {attempt}/{max_retries} - Download Error: {e}")
            if attempt == max_retries:
                return None
            time.sleep(2 ** attempt)
        except Exception as e:
            print(f"Attempt {attempt}/{max_retries} - Unexpected error: {e}")
            if attempt == max_retries:
                return None
            time.sleep(2 ** attempt)
            
    return None

if __name__ == "__main__":
    # test
    test_url = "https://www.youtube.com/watch?v=TowEXCJ3XUg" 
    print(f"Starting download for {test_url}...")
    
    result = download_video(test_url)
    
    if result:
        file_path, duration = result
        print(f"Success! Video saved to: {file_path}")
        print(f"Duration: {duration} seconds")
    else:
        print("Download failed.")
