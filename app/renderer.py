import os
import sys
import subprocess
import json
import re
import imageio_ffmpeg

def format_srt_time(seconds: float) -> str:
    """Converts a float in seconds to strict SRT timestamp format: HH:MM:SS,mmm"""
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    # Handle rounding edge case where millis is 1000
    if millis == 1000:
        millis = 0
        secs += 1
        if secs == 60:
            secs = 0
            minutes += 1
            if minutes == 60:
                minutes = 0
                hours += 1
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"

def generate_srt(segments: list, start_time: float, end_time: float, srt_path: str) -> bool:
    """
    Generates an SRT file for the clip timeframe. 
    Adjusts all timestamps relative to start_time.
    """
    os.makedirs(os.path.dirname(os.path.abspath(srt_path)), exist_ok=True)
    
    srt_content = []
    index = 1
    
    for seg in segments:
        seg_start = seg.get('start', 0.0)
        seg_end = seg.get('end', 0.0)
        text = seg.get('text', '').strip()
        
        # Filter out segments completely outside our clip window
        if seg_end <= start_time or seg_start >= end_time:
            continue
            
        # Clamp timestamps to clip boundaries relative to 0.0s
        adj_start = max(0.0, seg_start - start_time)
        adj_end = min(end_time - start_time, seg_end - start_time)
        
        # Ignore extremely short subtitle glitches
        if adj_end - adj_start < 0.1:
            continue
            
        start_str = format_srt_time(adj_start)
        end_str = format_srt_time(adj_end)
        
        srt_content.append(f"{index}")
        srt_content.append(f"{start_str} --> {end_str}")
        srt_content.append(text)
        srt_content.append("") # Blank line
        index += 1
        
    try:
        with open(srt_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(srt_content))
        return True
    except Exception as e:
        print(f"Error writing SRT file: {e}")
        return False

def render_clip(video_path: str, start_time: float, end_time: float, segments: list, output_path: str) -> bool:
    if not os.path.exists(video_path):
        print(f"Error: Video file not found: {video_path}")
        return False
        
    clip_duration = end_time - start_time
    if clip_duration <= 0:
        print("Error: Invalid clip duration.")
        return False
        
    # Setup directories
    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    os.makedirs("subtitles", exist_ok=True)
    
    # Define relative SRT path
    base_name = os.path.splitext(os.path.basename(output_path))[0]
    srt_path = f"subtitles/{base_name}.srt"
    
    # 1. Generate the subtitle file exactly aligned to 0.0s
    if not generate_srt(segments, start_time, end_time, srt_path):
        print("Error: Failed to generate subtitles.")
        return False
        
    # FFmpeg subtitles filter on Windows is notorious for failing with absolute paths.
    # Using a clean relative path with forward slashes is much safer.
    safe_srt_path = srt_path.replace("\\", "/")
    
    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    
    # 2. Build FFmpeg command (Re-encode + Crop + Burn Subtitles)
    # force_style adds nice yellow subtitles with a strong black outline
    style = "FontSize=24,PrimaryColour=&H00FFFF,OutlineColour=&H000000,BorderStyle=1,Outline=1,Shadow=1,MarginV=20"
    vf_filter = f"crop=ih*9/16:ih,subtitles={safe_srt_path}:force_style='{style}'"
    
    cmd = [
        ffmpeg_exe, "-y",
        "-ss", str(start_time),
        "-i", video_path,
        "-t", str(clip_duration),
        "-vf", vf_filter,
        "-c:v", "libx264",
        "-preset", "fast",
        "-c:a", "aac",
        output_path
    ]
    
    print(f"Rendering clip to {output_path}...")
    
    # 3. Execute FFmpeg
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except subprocess.CalledProcessError as e:
        print(f"FFmpeg failed during render: {e}")
        return False
        
    # 4. Validation Layer
    if os.path.exists(output_path) and os.path.getsize(output_path) > 0:
        print(f"Success: Final rendered video saved to {output_path}")
        return True
    else:
        print("Error: Render completed, but output file is missing or 0 bytes.")
        return False

if __name__ == "__main__":
    # Load test files for manual verification
    video_file = "downloads/TowEXCJ3XUg.mp4"
    clips_json = "transcripts/TowEXCJ3XUg_clips.json"
    transcript_json = "transcripts/TowEXCJ3XUg_transcript.json"
    
    if not all(os.path.exists(f) for f in [video_file, clips_json, transcript_json]):
        print("Test files not found. Ensure downloader, transcriber, and clip_selector have been run.")
        sys.exit(1)
        
    try:
        with open(clips_json, 'r', encoding='utf-8') as f:
            clips = json.load(f)
        with open(transcript_json, 'r', encoding='utf-8') as f:
            transcript_segments = json.load(f)
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
    output_filename = f"clips/rendered_1_{safe_title}.mp4"
    
    print(f"Testing renderer on: '{first_clip['title']}'")
    print(f"Start: {first_clip['start_time']}s | End: {first_clip['end_time']}s")
    
    success = render_clip(
        video_path=video_file,
        start_time=first_clip['start_time'],
        end_time=first_clip['end_time'],
        segments=transcript_segments,
        output_path=output_filename
    )
    
    if success:
        print(f"Test complete. Check {output_filename} to verify sync and cropping.")
    else:
        print("Test failed.")
