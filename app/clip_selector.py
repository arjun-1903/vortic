import os
import json
import sys
from typing import List, Literal, Optional, Tuple
from pydantic import BaseModel, Field, ValidationError
from openai import OpenAI, OpenAIError
from dotenv import load_dotenv

# load env
load_dotenv()

# init openai
client = OpenAI()

class Clip(BaseModel):
    title: str = Field(description="A catchy, viral title for the short.")
    start_time: float = Field(description="The precise start time in seconds.")
    end_time: float = Field(description="The precise end time in seconds.")
    score: int = Field(description="An engagement score from 1 to 100.")
    justification: str = Field(description="A brief sentence on why this clip is engaging.")
    clip_type: Literal["viral", "emotional", "controversial", "informative", "funny"] = Field(description="The category of the clip.")

class ClipResponse(BaseModel):
    clips: List[Clip] = Field(description="Exactly 10 extracted clips.")

class ProcessedClip(BaseModel):
    title: str
    start_time: float
    end_time: float
    score: int
    justification: str
    clip_type: str
    duration: float
    is_fallback: bool
    warning: Optional[str] = None

def format_transcript(segments: List[dict]) -> str:
    # format text
    formatted = []
    for seg in segments:
        start = seg.get('start', 0.0)
        end = seg.get('end', 0.0)
        text = seg.get('text', '')
        formatted.append(f"[{start:.2f} - {end:.2f}] {text}")
    return "\n".join(formatted)

def select_clips(transcript_path: str) -> Tuple[Optional[List[ProcessedClip]], Optional[str]]:
    if not os.path.exists(transcript_path):
        print(f"Error: File not found at {transcript_path}")
        return None, None

    # load file
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            segments = json.load(f)
    except Exception as e:
        print(f"Error reading transcript JSON: {e}")
        return None, None

    # format
    formatted_transcript = format_transcript(segments)
    
    # setup prompt
    system_prompt = (
        "You are an expert video editor and social media manager.\n"
        "Your task is to analyze the provided transcript and identify 10 of the most engaging, "
        "standalone viral moments that would make excellent short-form clips.\n\n"
        "CRITICAL INSTRUCTIONS:\n"
        "1. DO NOT just pick a single line of text. You MUST group multiple continuous lines together to form a cohesive, flowing narrative.\n"
        "2. A clip MUST be between 30 and 90 seconds long. Calculate the duration using (end_time - start_time).\n"
        "3. The `start_time` should be the start of the first line in your chosen block, and `end_time` should be the end of the last line in your block.\n"
        "4. Prioritize moments that are self-contained, emotionally/comedically/informationally complete, and understandable without surrounding context.\n"
        "5. Always return exactly 10 clips. We will filter them down later."
        "6. Ensure to always check the next segment once you have selected an endtime for your current clip to ensure the clip is complete and flowing naturally. A lot of the times the segments have ended in abrupt pauses and there is usually one or two more words spoken by the speaker that makes the clip complete. Use your judgement to select the best endtime."
    )
    
    print("Analyzing transcript...")
    
    max_retries = 2
    import time
    
    for attempt in range(1, max_retries + 1):
        try:
            response = client.beta.chat.completions.parse(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": f"Here is the transcript:\n\n{formatted_transcript}"}
                ],
                response_format=ClipResponse,
                temperature=0.7
            )
            
            if response.choices[0].message.refusal:
                print(f"Model refused to process the request: {response.choices[0].message.refusal}")
                return None, None
                
            parsed_response = response.choices[0].message.parsed
            
            # cost check
            if response.usage:
                prompt_tokens = response.usage.prompt_tokens
                completion_tokens = response.usage.completion_tokens
                cost = (prompt_tokens / 1_000_000 * 0.15) + (completion_tokens / 1_000_000 * 0.60)
                print(f"\n[Token Usage] Prompt: {prompt_tokens} | Completion: {completion_tokens}")
                print(f"[Estimated Cost] ${cost:.6f}\n")
                
            break # Success, exit retry loop
            
        except ValidationError as e:
            print(f"Attempt {attempt}/{max_retries} - Validation Error: {e}")
            if attempt == max_retries:
                raise Exception(f"Validation failed after {max_retries} attempts.")
            time.sleep(2 ** attempt)
        except OpenAIError as e:
            print(f"Attempt {attempt}/{max_retries} - OpenAI API Error: {e}")
            if attempt == max_retries:
                raise Exception(f"OpenAI API failed after {max_retries} attempts: {e}")
            time.sleep(2 ** attempt)
        except Exception as e:
            print(f"Attempt {attempt}/{max_retries} - Unexpected Error: {e}")
            if attempt == max_retries:
                raise Exception(f"Unexpected error in clip selector: {e}")
            time.sleep(2 ** attempt)
            
    # process clips
    valid_clips = []
    
    for clip in parsed_response.clips:
        # snap timestamps
        closest_start = min(segments, key=lambda seg: abs(seg.get('start', 0.0) - clip.start_time))
        closest_end = min(segments, key=lambda seg: abs(seg.get('end', 0.0) - clip.end_time))
        
        start = closest_start.get('start', 0.0)
        end = closest_end.get('end', 0.0)
        
        if start > end:
            start, end = end, start
            
        duration = end - start
        
        if duration >= 15.0 and duration <= 90.0:
            valid_clips.append(
                ProcessedClip(
                    title=clip.title,
                    start_time=start,
                    end_time=end,
                    score=clip.score,
                    justification=clip.justification,
                    clip_type=clip.clip_type,
                    duration=duration,
                    is_fallback=False,
                    warning=None
                )
            )
            
    # Sort by score descending and take the top 5 valid clips
    valid_clips.sort(key=lambda x: x.score, reverse=True)
    validated_clips = valid_clips[:5]
    
    # check count
    if not validated_clips:
        print("Warning: Failed to generate valid clips.")
        return None, None
        
    # save output
    output_path = transcript_path.replace("_transcript.json", "_clips.json")
    # fallback
    if output_path == transcript_path:
        base, ext = os.path.splitext(transcript_path)
        output_path = f"{base}_clips.json"
        
    try:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump([clip.model_dump() for clip in validated_clips], f, indent=4, ensure_ascii=False)
        print(f"Saved extracted clips to: {output_path}")
    except Exception as e:
        print(f"Error saving clips JSON: {e}")
        
    return validated_clips, output_path

if __name__ == "__main__":
    if len(sys.argv) > 1:
        transcript_file = sys.argv[1]
    else:
        print("Please provide a transcript JSON file path. Example: python app/clip_selector.py transcripts/video_transcript.json")
        sys.exit(1)
        
    print(f"Processing transcript: {transcript_file}")
    
    result, out_path = select_clips(transcript_file)
    if result:
        print(f"Successfully extracted {len(result)} clips:\n")
        for i, clip in enumerate(result, 1):
            print(f"--- Clip {i}: {clip.title} ---")
            print(f"Type: {clip.clip_type.capitalize()}")
            print(f"Time: {clip.start_time:.2f}s - {clip.end_time:.2f}s (Duration: {clip.duration:.2f}s)")
            print(f"Score: {clip.score}/100")
            print(f"Justification: {clip.justification}")
            if clip.is_fallback:
                print(f"[WARNING - Fallback Clip]: {clip.warning}")
            print()
    else:
        print("Failed to extract clips.")
