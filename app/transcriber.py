import os
import subprocess
import tempfile
import glob
from typing import List, Dict, Optional
from dotenv import load_dotenv
import imageio_ffmpeg
from openai import OpenAI, OpenAIError

# Load environment variables from .env file
load_dotenv()

# Initialize the OpenAI client.
client = OpenAI()

def transcribe_audio_file(file_path: str, offset: float = 0.0) -> List[Dict]:
    # transcribe single
    segments = []
    max_retries = 3
    import time
    
    for attempt in range(1, max_retries + 1):
        try:
            with open(file_path, "rb") as audio_file:
                response = client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    response_format="verbose_json"
                )
                
                if hasattr(response, 'segments') and response.segments:
                    for segment in response.segments:
                        if isinstance(segment, dict):
                            start = segment.get('start', 0.0)
                            end = segment.get('end', 0.0)
                            text = segment.get('text', '')
                        else:
                            start = getattr(segment, 'start', 0.0)
                            end = getattr(segment, 'end', 0.0)
                            text = getattr(segment, 'text', '')
                            
                        segments.append({
                            "start": start + offset,
                            "end": end + offset,
                            "text": text.strip()
                        })
                return segments # Success, break out of loop
        except OpenAIError as e:
            print(f"Attempt {attempt}/{max_retries} - OpenAI API Error for {file_path}: {e}")
            if attempt == max_retries:
                raise Exception(f"OpenAI transcription failed after {max_retries} attempts: {e}")
            time.sleep(2 ** attempt)
        except Exception as e:
            print(f"Attempt {attempt}/{max_retries} - Unexpected error for {file_path}: {e}")
            if attempt == max_retries:
                raise Exception(f"Unexpected transcription error after {max_retries} attempts: {e}")
            time.sleep(2 ** attempt)
            
    return segments

def transcribe_video(file_path: str) -> Optional[List[Dict]]:
    # transcribe video
    if not os.path.exists(file_path):
        print(f"Error: File not found at {file_path}")
        return None

    ffmpeg_exe = imageio_ffmpeg.get_ffmpeg_exe()
    all_segments = []

    with tempfile.TemporaryDirectory() as temp_dir:
        print(f"Created temporary directory at {temp_dir}")
        mp3_path = os.path.join(temp_dir, "audio.mp3")
        
        # extract
        print("Extracting compressed audio...")
        extract_cmd = [
            ffmpeg_exe, "-y", "-i", file_path,
            "-vn", "-c:a", "libmp3lame", "-b:a", "64k",
            mp3_path
        ]
        
        try:
            subprocess.run(extract_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except subprocess.CalledProcessError as e:
            print(f"FFmpeg audio extraction failed: {e}")
            return None

        # size check
        file_size = os.path.getsize(mp3_path)
        print(f"Extracted audio size: {file_size / (1024 * 1024):.2f} MB")
        
        MAX_SIZE = 24 * 1024 * 1024 # 24 MB
        SEGMENT_TIME = 1800 # 30 minutes in seconds

        if file_size <= MAX_SIZE:
            print("Audio is under 24MB. Transcribing directly...")
            all_segments.extend(transcribe_audio_file(mp3_path, offset=0.0))
        else:
            print("Audio exceeds 24MB. Chunking into 30-minute segments...")
            chunk_pattern = os.path.join(temp_dir, "chunk_%03d.mp3")
            chunk_cmd = [
                ffmpeg_exe, "-y", "-i", mp3_path,
                "-f", "segment", "-segment_time", str(SEGMENT_TIME),
                "-c", "copy", chunk_pattern
            ]
            
            try:
                subprocess.run(chunk_cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except subprocess.CalledProcessError as e:
                print(f"FFmpeg chunking failed: {e}")
                return None
                
            # get chunks
            search_pattern = os.path.join(temp_dir, "chunk_*.mp3")
            chunks = sorted(glob.glob(search_pattern))
            print(f"Split into {len(chunks)} chunks. Transcribing...")
            
            for index, chunk_file in enumerate(chunks):
                print(f"Processing chunk {index + 1}/{len(chunks)}...")
                offset = index * SEGMENT_TIME
                chunk_segments = transcribe_audio_file(chunk_file, offset=offset)
                all_segments.extend(chunk_segments)

    # cleanup
    print("Cleanup complete.")
    
    if not all_segments:
        return None
        
    return all_segments

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        test_file = sys.argv[1]
    else:
        print("Please provide a file path to test. Example: python app/transcriber.py downloads/video.mp4")
        sys.exit(1)
        
    print(f"Starting pipeline for {test_file}...")
    result_segments = transcribe_video(test_file)
    
    if result_segments:
        print(f"Transcription successful! Found {len(result_segments)} segments.")
        
        import json
        
        # Ensure transcripts directory exists
        os.makedirs("transcripts", exist_ok=True)
        
        # Extract just the filename without extension or directory
        base_name = os.path.splitext(os.path.basename(test_file))[0]
        json_path = os.path.join("transcripts", f"{base_name}_transcript.json")
        
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(result_segments, f, indent=4, ensure_ascii=False)
        print(f"Saved full transcription to: {json_path}")
        
        print("-" * 40)
        # Print the first 5 segments as a sample
        for i, seg in enumerate(result_segments[:5]):
            print(f"[{seg['start']:.2f} - {seg['end']:.2f}] {seg['text']}")
        if len(result_segments) > 5:
            print("...")
            for i, seg in enumerate(result_segments[-3:]):
                print(f"[{seg['start']:.2f} - {seg['end']:.2f}] {seg['text']}")
    else:
        print("Transcription failed or returned no segments.")
