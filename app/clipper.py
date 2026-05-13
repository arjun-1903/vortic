import os
import subprocess
import re
import json
import imageio_ffmpeg

def get_video_duration(video_path: str) -> float:
    """Uses FFmpeg to parse the total duration of the video."""
    if not os.path.exists(video_path):
        return 0.0
        
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    # Run ffprobe equivalent via ffmpeg by analyzing the file
    cmd = [ffmpeg_exe, "-i", video_path]
    result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    
    # FFmpeg logs input info to stderr
    # Look for Duration: 00:04:05.15
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.\d+)", result.stderr)
    if match:
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        
    # Fallback pattern without decimal seconds
    match = re.search(r"Duration:\s*(\d+):(\d+):(\d+)", result.stderr)
    if match:
        hours, minutes, seconds = match.groups()
        return int(hours) * 3600 + int(minutes) * 60 + float(seconds)
        
    return 0.0

def extract_clip(video_path: str, start_time: float, end_time: float, output_path: str) -> bool:
    """
    Extracts a clip from the video using FFmpeg stream copy.
    Returns True if successful and output exists, False otherwise.
    """
    if not os.path.exists(video_path):
        print(f"Error: Video file not found: {video_path}")
        return False
        
    # 1. Clamp end_time to video duration
    duration = get_video_duration(video_path)
    if duration > 0 and end_time > duration:
        print(f"Warning: end_time {end_time:.2f}s exceeds video duration {duration:.2f}s. Clamping.")
        end_time = duration
        
    if start_time >= end_time:
        print(f"Error: start_time {start_time:.2f} must be less than end_time {end_time:.2f}")
        return False
        
    clip_duration = end_time - start_time
    
    # Ensure output directory exists
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    
    # 2. Build FFmpeg command (stream copy)
    # Placing -ss before -i ensures highly optimized fast-seeking
    cmd = [
        ffmpeg_exe, "-y",
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(clip_duration),
        "-c", "copy",
        output_path
    ]
    
    print(f"Extracting clip to {output_path}...")
    
    # 3. Execute FFmpeg
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg failed during extraction: {e}")
        return False
        
    # 4. Validation Layer
    if os.path.exists(output_path):
        file_size = os.path.getsize(output_path)
        if file_size > 0:
            return True
        else:
            print("Error: Extraction completed, but output file is 0 bytes.")
            return False
    else:
        print("Error: Output file was not created.")
        return False

if __name__ == "__main__":
    import sys
    
    # Load test files for manual verification
    video_file = "downloads/TowEXCJ3XUg.mp4"
    clips_json = "transcripts/TowEXCJ3XUg_clips.json"
    
    if not os.path.exists(video_file) or not os.path.exists(clips_json):
        print("Test files not found. Ensure downloader.py and clip_selector.py have been run.")
        sys.exit(1)
        
    try:
        with open(clips_json, 'r', encoding='utf-8') as f:
            clips = json.load(f)
    except Exception as e:
        print(f"Failed to load JSON: {e}")
        sys.exit(1)
        
    if not clips:
        print("No clips found in JSON.")
        sys.exit(1)
        
    # Process the first clip
    first_clip = clips[0]
    
    # Clean up title for a safe filename
    safe_title = re.sub(r'[\\/*?:"<>|]', "", first_clip["title"]).replace(" ", "_")
    output_filename = f"clips/clip_1_{safe_title}.mp4"
    
    print(f"Testing clipper on: '{first_clip['title']}'")
    print(f"Start: {first_clip['start_time']}s | End: {first_clip['end_time']}s")
    
    success = extract_clip(
        video_path=video_file,
        start_time=first_clip['start_time'],
        end_time=first_clip['end_time'],
        output_path=output_filename
    )
    
    if success:
        print(f"Test complete. Output file is valid: {output_filename}")
        print(f"Size: {os.path.getsize(output_filename) / (1024*1024):.2f} MB")
    else:
        print("Test failed.")
