import os
import json
import re
from fastapi import FastAPI, BackgroundTasks, HTTPException
from pydantic import BaseModel
from celery import Celery
from typing import List, Optional

# Import pipeline components
from app import downloader, transcriber, clip_selector, renderer

app = FastAPI(title="Video Shorts Automation API")

# Initialize Celery
# Assumes Redis is running locally on default port 6379
celery_app = Celery(
    "video_pipeline",
    broker="redis://localhost:6379/0",
    backend="redis://localhost:6379/0"
)

# Configuration
os.makedirs("transcripts", exist_ok=True)
os.makedirs("clips", exist_ok=True)

class ProcessRequest(BaseModel):
    url: str

class ProcessResponse(BaseModel):
    job_id: str

@celery_app.task(bind=True, autoretry_for=(Exception,), max_retries=2)
def process_video_task(self, url: str):
    """
    Master Celery task that runs the entire pipeline synchronously.
    Updates states in Redis so the frontend can track progress.
    """
    try:
        # ---------------------------------------------------------
        # STAGE 1: DOWNLOAD
        # ---------------------------------------------------------
        self.update_state(state='PROCESSING', meta={'stage': 'Downloading video...'})
        download_result = downloader.download_video(url)
        
        if not download_result:
            raise Exception("Failed to download video. It might be unavailable or restricted.")
            
        video_path, duration = download_result
        video_basename = os.path.splitext(os.path.basename(video_path))[0]
        
        # ---------------------------------------------------------
        # STAGE 2: TRANSCRIBE
        # ---------------------------------------------------------
        transcript_path = f"transcripts/{video_basename}_transcript.json"
        
        if os.path.exists(transcript_path):
            self.update_state(state='PROCESSING', meta={'stage': 'Found existing transcript, skipping Whisper API...'})
            with open(transcript_path, 'r', encoding='utf-8') as f:
                segments = json.load(f)
        else:
            self.update_state(state='PROCESSING', meta={'stage': 'Transcribing audio via Whisper...'})
            segments = transcriber.transcribe_video(video_path)
            
            if not segments:
                raise Exception("Transcription failed or returned no segments.")
                
            # Save transcript to disk for clip_selector to use
            with open(transcript_path, 'w', encoding='utf-8') as f:
                json.dump(segments, f, indent=4, ensure_ascii=False)
            
        # ---------------------------------------------------------
        # STAGE 3: SELECT CLIPS
        # ---------------------------------------------------------
        self.update_state(state='PROCESSING', meta={'stage': 'Selecting clips via GPT-4o-mini...'})
        # select_clips returns (list of ProcessedClip objects, output_clips_path)
        clips, clips_json_path = clip_selector.select_clips(transcript_path)
        
        if not clips:
            raise Exception("Clip selection failed. LLM might have refused or returned invalid schema.")
            
        # ---------------------------------------------------------
        # STAGE 4: RENDER CLIPS
        # ---------------------------------------------------------
        final_video_paths = []
        total_clips = len(clips)
        
        for i, clip in enumerate(clips, 1):
            self.update_state(state='PROCESSING', meta={
                'stage': f'Rendering clip {i}/{total_clips}: {clip.title}'
            })
            
            # Clean up title for a safe filename
            safe_title = re.sub(r"[\\/*?:\"<>|!'`]", "", clip.title).replace(" ", "_")
            output_filename = f"clips/rendered_{video_basename}_{i}_{safe_title}.mp4"
            
            success = renderer.render_clip(
                video_path=video_path,
                start_time=clip.start_time,
                end_time=clip.end_time,
                segments=segments,
                output_path=output_filename
            )
            
            if success:
                final_video_paths.append(output_filename)
            else:
                # We log the failure but continue rendering the rest
                print(f"Warning: Failed to render clip {i}")
                
        if not final_video_paths:
            raise Exception("All rendering attempts failed.")
            
        # Return success payload to Redis
        return {
            "status": "Complete",
            "video_id": video_basename,
            "clips_generated": len(final_video_paths),
            "paths": final_video_paths
        }
        
    except Exception as e:
        # Pass the exact failure reason to Redis so the user knows what broke
        self.update_state(state='FAILURE', meta={'exc_message': str(e)})
        raise e

@app.post("/process", response_model=ProcessResponse)
def start_processing(req: ProcessRequest):
    """
    Accepts a YouTube URL, triggers the Celery pipeline, and returns immediately.
    """
    task = process_video_task.delay(req.url)
    return ProcessResponse(job_id=task.id)

@app.get("/status/{job_id}")
def get_status(job_id: str):
    """
    Queries Celery/Redis for the current status of the job.
    """
    task = process_video_task.AsyncResult(job_id)
    
    if task.state == 'PENDING':
        return {"job_id": job_id, "status": "Pending", "stage": "Waiting in queue..."}
        
    elif task.state == 'PROCESSING':
        # The meta dictionary is updated by our task manually
        meta = task.info or {}
        return {
            "job_id": job_id,
            "status": "Processing",
            "stage": meta.get("stage", "Working...")
        }
        
    elif task.state == 'SUCCESS':
        return {
            "job_id": job_id,
            "status": "Complete",
            "result": task.result
        }
        
    elif task.state == 'FAILURE':
        # Safely extract the exception message
        meta = task.info or {}
        exc_message = meta.get("exc_message", str(task.result))
        return {
            "job_id": job_id,
            "status": "Failed",
            "error": exc_message
        }
        
    return {"job_id": job_id, "status": task.state}

if __name__ == "__main__":
    import uvicorn
    # Make sure to run this via standard uvicorn for production
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
