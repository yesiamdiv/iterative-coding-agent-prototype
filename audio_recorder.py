
import sounddevice as sd
import numpy as np
from faster_whisper import WhisperModel
import google.generativeai as genai
from typing import Optional, Dict, Any, List, Union
from config import Config

# ============================================================================
# Audio & Speech Recognition
# ============================================================================

class AudioRecorder:
    """Handles audio recording and transcription with multiple STT providers"""
    
    def __init__(self, config: Config):
        self.config = config
        self.sample_rate = config.get("audio_sample_rate", 16000)
        self.channels = config.get("audio_channels", 1)
        self.recording = []
        self.is_recording = False
        self.stt_provider = config.get("stt_provider", "whisper").lower()
        
        # Initialize STT provider
        if self.stt_provider == "whisper":
            self._init_whisper()
        elif self.stt_provider == "gemini":
            self._init_gemini_stt()
        else:
            raise ValueError(f"Unknown STT provider: {self.stt_provider}")
    
    def _init_whisper(self):
        """Initialize Whisper model (local or custom)"""
        custom_model = self.config.get("whisper_custom_model")
        
        if custom_model:
            # Use custom HuggingFace model
            model_name = custom_model
            print(f"Loading custom Whisper model: {model_name}...")
        else:
            # Use standard Whisper model
            model_name = self.config.get("whisper_model_size", "base")
            print(f"Loading Whisper model: {model_name}...")
        
        device = self.config.get("whisper_device", "cpu")
        compute_type = self.config.get("whisper_compute_type", "int8")
        
        try:
            self.whisper_model = WhisperModel(
                model_name, 
                device=device, 
                compute_type=compute_type
            )
            print(f"✓ Whisper model loaded successfully on {device}!")
        except Exception as e:
            print(f"✗ Error loading Whisper model: {e}")
            print("Tip: For custom models, ensure they're compatible with faster-whisper")
            raise
    
    def _init_gemini_stt(self):
        """Initialize Gemini STT"""
        api_key = self.config.get("gemini_api_key")
        if not api_key or api_key == "YOUR_GEMINI_API_KEY_HERE":
            raise ValueError("Please set your Gemini API key in config.json")
        
        genai.configure(api_key=api_key)
        model_name = self.config.get("gemini_stt_model", "gemini-1.5-flash")
        self.gemini_stt_model = genai.GenerativeModel(model_name)
        print(f"✓ Gemini STT initialized with {model_name}!")
    
    def start_recording(self):
        """Start recording audio"""
        self.recording = []
        self.is_recording = True
        
        def audio_callback(indata, frames, time_info, status):
            if status:
                print(f"Audio status: {status}")
            if self.is_recording:
                self.recording.append(indata.copy())
        
        self.stream = sd.InputStream(
            callback=audio_callback,
            channels=self.channels,
            samplerate=self.sample_rate,
            dtype=np.float32
        )
        self.stream.start()
    
    def stop_recording(self) -> Optional[str]:
        """Stop recording and transcribe"""
        self.is_recording = False
        self.stream.stop()
        self.stream.close()
        
        if not self.recording:
            return None
        
        # Concatenate audio chunks
        audio_data = np.concatenate(self.recording, axis=0)
        audio_data = audio_data.flatten()
        
        # Transcribe based on provider
        if self.stt_provider == "whisper":
            return self._transcribe_whisper(audio_data)
        elif self.stt_provider == "gemini":
            return self._transcribe_gemini(audio_data)
    
    def _transcribe_whisper(self, audio_data: np.ndarray) -> str:
        """Transcribe using Whisper"""
        try:
            segments, info = self.whisper_model.transcribe(
                audio_data,
                language="en",
                beam_size=5
            )
            
            text = " ".join([segment.text for segment in segments])
            return text.strip()
        except Exception as e:
            print(f"Whisper transcription error: {e}")
            return None
    
    def _transcribe_gemini(self, audio_data: np.ndarray) -> str:
        """Transcribe using Gemini API"""
        try:
            import wave
            import tempfile
            
            # Convert float32 audio to int16 WAV format
            audio_int16 = (audio_data * 32767).astype(np.int16)
            
            # Create temporary WAV file
            with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as temp_wav:
                with wave.open(temp_wav.name, 'wb') as wav_file:
                    wav_file.setnchannels(self.channels)
                    wav_file.setsampwidth(2)  # 16-bit
                    wav_file.setframerate(self.sample_rate)
                    wav_file.writeframes(audio_int16.tobytes())
                
                temp_path = temp_wav.name
            
            # Upload audio to Gemini
            audio_file = genai.upload_file(path=temp_path)
            
            # Get transcription
            language = self.config.get("gemini_stt_language", "en")
            prompt = f"Transcribe this audio to text. Language: {language}. Return only the transcribed text, nothing else."
            
            response = self.gemini_stt_model.generate_content([prompt, audio_file])
            
            # Clean up
            import os
            os.unlink(temp_path)
            genai.delete_file(audio_file.name)
            
            return response.text.strip()
            
        except Exception as e:
            print(f"Gemini STT error: {e}")
            return None

