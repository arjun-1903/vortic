import os
import json
import sys
from typing import List, Literal, Optional, Tuple
from pydantic import BaseModel, Field, ValidationError
from openai import OpenAI, OpenAIError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Initialize the OpenAI client
client = OpenAI()

class Clip(BaseModel):
    title: str = Field(description="A catchy, viral title for the short.")
    start_time: float = Field(description="The precise start time in seconds.")
    end_time: float = Field(description="The precise end time in seconds.")
    score: int = Field(description="An engagement score from 1 to 100.")
    justification: str = Field(description="A brief sentence on why this clip is engaging.")
    clip_type: Literal["viral", "emotional", "controversial", "informative", "funny"] = Field(description="The category of the clip.")

class ClipResponse(BaseModel):
    clips: List[Clip] = Field(description="Exactly 5 extracted clips.")

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
    """Converts a list of segment dictionaries into a readable string for the LLM."""
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

    # Load the transcript JSON
    try:
        with open(transcript_path, 'r', encoding='utf-8') as f:
            segments = json.load(f)
    except Exception as e:
        print(f"Error reading transcript JSON: {e}")
        return None, None

    # Format transcript for the LLM
    formatted_transcript = format_transcript(segments)
    
    # Construct prompts
    system_prompt = (
        "You are an expert video editor and social media manager.\n"
        "Your task is to analyze the provided transcript and identify exactly 5 of the most engaging, "
        "standalone segments that would make excellent short-form clips.\n\n"
        "Guidelines:\n"
        "- Prefer clips between 15 and 90 seconds.\n"
        "- Prioritize clips that are self-contained, emotionally/comedically/informationally complete, "
        "and understandable without surrounding context.\n"
        "- Always return exactly 5 clips.\n"
        "- Only return clips shorter than 15 seconds if absolutely no better alternatives exist."
    )
    
    print("Sending transcript to GPT-4o-mini for clip selection...")
    
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
        
        # Calculate and print cost
        if response.usage:
            prompt_tokens = response.usage.prompt_tokens
            completion_tokens = response.usage.completion_tokens
            # gpt-4o-mini pricing: $0.15/1M prompt, $0.60/1M completion
            cost = (prompt_tokens / 1_000_000 * 0.15) + (completion_tokens / 1_000_000 * 0.60)
            print(f"\n[Token Usage] Prompt: {prompt_tokens} | Completion: {completion_tokens}")
            print(f"[Estimated Cost] ${cost:.6f}\n")
            
        # Backend Validation Layer
        validated_clips = []
        for clip in parsed_response.clips:
            duration = clip.end_time - clip.start_time
            is_fallback = False
            warning = None
            final_score = clip.score
            
            if duration < 15.0:
                is_fallback = True
                warning = f"Duration {duration:.1f}s is under the 15s threshold."
                final_score = max(0, clip.score - 10) # Lower score slightly for fallbacks
                
            validated_clips.append(
                ProcessedClip(
                    title=clip.title,
                    start_time=clip.start_time,
                    end_time=clip.end_time,
                    score=final_score,
                    justification=clip.justification,
                    clip_type=clip.clip_type,
                    duration=duration,
                    is_fallback=is_fallback,
                    warning=warning
                )
            )
            
        # Save to JSON
        output_path = transcript_path.replace("_transcript.json", "_clips.json")
        # Fallback if the filename doesn't end with _transcript.json
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

    except ValidationError as e:
        print(f"Pydantic Validation Error: The LLM output did not match the expected schema.\n{e}")
    except OpenAIError as e:
        print(f"OpenAI API Error: {e}")
    except Exception as e:
        print(f"Unexpected Error: {e}")
        
    return None, None

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
