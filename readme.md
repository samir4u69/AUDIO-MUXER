Here's a comprehensive prompt for creating your **Audio Muxer Bot** with auto-sync detection and trimming capabilities:

---

## AI Bot Creation Prompt - Audio Muxer Bot

```
I need you to create a detailed AI bot for audio muxing and manipulation in video files with the following specifications:

### 1. BOT OVERVIEW
- **Bot Name:** AudioMuxer Pro Bot
- **Primary Purpose:** Audio muxing, demuxing, syncing, and trimming in video files
- **Target Users:** Video editors, content creators, media professionals
- **Platform:** Web-based with Telegram/Discord integration, also CLI support
- **Core Function:** Process video files to add, remove, sync, and trim audio tracks

### 2. CORE CAPABILITIES

#### A. VIDEO PROCESSING
- **Supported Video Formats:**
  - .mp4, .mkv, .avi, .mov, .wmv, .flv, .webm, .m4v, .mpg, .mpeg, .ts, .m2ts
  - 4K, 1080p, 720p, and lower resolutions
  - H.264, H.265/HEVC, VP9, AV1 codecs
  
- **Video Operations:**
  - Extract audio from video
  - Add new audio track to video
  - Replace existing audio track
  - Add multiple audio tracks (multi-language support)
  - Remove specific audio tracks
  - List all audio tracks in a video file

#### B. AUDIO PROCESSING
- **Supported Audio Formats:**
  - .mp3, .aac, .wav, .flac, .ogg, .opus, .m4a, .ac3, .eac3, .dts, .wma
  - Multiple bitrates (64kbps to 320kbps)
  - Various sample rates (44.1kHz, 48kHz, 96kHz)
  - Mono, Stereo, 5.1, 7.1 surround sound

- **Audio Operations:**
  - Extract audio from video files
  - Convert between audio formats
  - Adjust audio volume/gain
  - Normalize audio levels
  - Change audio codec/bitrate
  - Merge multiple audio files
  - Split audio at specific timestamps

#### C. AUTO-SYNC DETECTION
- **Sync Detection Methods:**
  - Waveform analysis for audio alignment
  - Cross-correlation for detecting audio offset
  - Speech recognition for dialogue matching
  - Audio fingerprinting for track identification
  - Frame-accurate sync detection

- **Sync Operations:**
  - Detect audio delay/advance in milliseconds
  - Auto-correct audio sync issues
  - Align multiple audio tracks
  - Sync external audio with video
  - Handle drift correction for long videos
  - Batch sync multiple files

#### D. TRIMMING & EDITING
- **Trim Operations:**
  - Trim video by time range (start/end)
  - Trim audio by time range
  - Remove silence from audio
  - Cut specific segments
  - Remove unwanted parts (intros, outros, ads)
  - Smart trim based on audio silence detection
  - Trim to match audio/video duration

### 3. USER INTERACTION & BUTTONS

#### MAIN MENU BUTTONS:
```
🎬 VIDEO OPERATIONS
├── 📤 Send Video File
├── 🎵 Extract Audio
├── ➕ Add Audio Track
├── 🔄 Replace Audio
└── 📋 List Audio Tracks

🎵 AUDIO OPERATIONS
├── 📤 Send Audio File
├── 🎚️ Adjust Volume
├── 🔄 Convert Format
└── ✂️ Trim Audio

🔄 SYNC OPERATIONS
├── 🔍 Auto-Detect Sync
├── ⚡ Quick Sync
├── 🎯 Manual Sync
└── 📊 Sync Report

✂️ TRIM OPERATIONS
├── ⏱️ Trim by Time
├── 🔇 Remove Silence
├── 🎯 Smart Trim
└── 📐 Custom Trim

🌍 LANGUAGE & TRACKS
├── ➕ Add Language Track
├── 🏷️ Label Audio Track
├── 📝 Set Default Track
└── 🔀 Reorder Tracks
```

#### INTERACTIVE FLOW:
1. **File Upload:** User sends video/audio file
2. **Bot Analysis:** Automatically detects file properties
3. **Option Display:** Shows relevant processing options
4. **Parameter Input:** User provides specific requirements
5. **Processing:** Bot processes with progress updates
6. **Result:** Returns processed file with preview option

### 4. AUTO-SYNC ALGORITHM SPECIFICATIONS

```python
SYNC_DETECTION_METHODS = {
    "waveform": {
        "description": "Compare audio waveforms for alignment",
        "accuracy": "Millisecond precision",
        "best_for": "Same audio in different qualities"
    },
    "cross_correlation": {
        "description": "Find time offset between signals",
        "accuracy": "Sample-level precision",
        "best_for": "Similar audio tracks"
    },
    "speech_recognition": {
        "description": "Match dialogue to detect sync issues",
        "accuracy": "Word-level precision",
        "best_for": "Dialogue-heavy content"
    },
    "fingerprint": {
        "description": "Identify and match audio segments",
        "accuracy": "Frame-level precision",
        "best_for": "Known audio sources"
    }
}

SYNC_DETECTION_FEATURES = [
    "Detect audio delay in milliseconds",
    "Detect audio advance in milliseconds",
    "Handle gradual drift in long videos",
    "Sync external audio with video",
    "Align multiple audio tracks",
    "Fix A/V sync for dubbed content",
    "Auto-correct sync issues",
    "Generate sync report with timestamps"
]

TRIMMING_ALGORITHMS = {
    "silence_detection": {
        "threshold_db": -40,
        "min_silence_duration": 0.5,
        "padding": 0.1,
        "description": "Remove silence below threshold"
    },
    "smart_trim": {
        "scene_detection": True,
        "audio_cues": True,
        "keep_context": 2.0,
        "description": "Intelligent content-aware trimming"
    },
    "custom_trim": {
        "user_defined": True,
        "frame_accurate": True,
        "description": "Manual trim with timestamps"
    }
}
```

### 5. FILE HANDLING & PROCESSING

#### INPUT VALIDATION:
```python
VALIDATION_CHECKS = {
    "file_size": "Up to 2GB per file",
    "duration": "Up to 4 hours",
    "corruption_check": "Verify file integrity",
    "codec_support": "Check codec compatibility",
    "metadata_extraction": "Get file information"
}

FILE_INFORMATION_DISPLAY = {
    "video_info": ["Resolution", "Frame rate", "Codec", "Duration", "Bitrate"],
    "audio_info": ["Codec", "Sample rate", "Channels", "Bitrate", "Language"],
    "container_info": ["Format", "File size", "Chapters", "Subtitles"],
    "track_info": ["Track ID", "Type", "Language", "Default flag"]
}
```

### 6. MULTI-LANGUAGE AUDIO TRACK SUPPORT

#### LANGUAGE FEATURES:
```python
LANGUAGE_SUPPORT = {
    "add_language": {
        "method": "User sends audio file",
        "trigger": "Button: ➕ Add Language Track",
        "process": [
            "1. Bot asks for video file",
            "2. Bot asks for audio file",
            "3. Bot asks for language (auto-detect or manual)",
            "4. Bot asks for track label",
            "5. Bot muxes audio into video",
            "6. Bot returns processed video"
        ]
    },
    "language_detection": {
        "auto_detect": True,
        "manual_override": True,
        "supported_languages": ["English", "Spanish", "French", "German", "Chinese", "Japanese", "Korean", "Hindi", "Arabic", "Portuguese", "Russian", "Italian", "Dutch", "Polish", "Turkish", "Vietnamese", "Thai", "Indonesian"]
    },
    "track_management": {
        "set_default": True,
        "reorder_tracks": True,
        "remove_tracks": True,
        "rename_tracks": True,
        "duplicate_tracks": True
    }
}
```

### 7. PROCESSING PIPELINE

```python
PROCESSING_STEPS = {
    "1_file_validation": {
        "check_format": True,
        "check_integrity": True,
        "extract_metadata": True,
        "generate_preview": True
    },
    "2_audio_analysis": {
        "waveform_generation": True,
        "sync_detection": True,
        "silence_detection": True,
        "loudness_analysis": True
    },
    "3_processing": {
        "ffmpeg_operations": True,
        "progress_tracking": True,
        "error_handling": True,
        "parallel_processing": True
    },
    "4_quality_check": {
        "output_validation": True,
        "sync_verification": True,
        "quality_metrics": True
    },
    "5_delivery": {
        "file_return": True,
        "download_link": True,
        "processing_report": True
    }
}
```

### 8. TECHNICAL REQUIREMENTS

```python
TECHNICAL_SPECS = {
    "ffmpeg": {
        "version": "4.4+",
        "codecs": ["libx264", "libx265", "libvpx", "libopus", "aac", "ac3", "eac3"],
        "filters": ["aresample", "volume", "loudnorm", "silenceremove", "adelay", "atrim"]
    },
    "python_libraries": {
        "moviepy": "For video editing",
        "pydub": "For audio manipulation",
        "librosa": "For audio analysis",
        "numpy": "For signal processing",
        "scipy": "For cross-correlation"
    },
    "performance": {
        "max_file_size": "2GB",
        "processing_time": "Real-time to 2x speed",
        "parallel_jobs": "2-4 concurrent",
        "temp_storage": "Auto-cleanup after 24 hours"
    }
}
```

### 9. ERROR HANDLING

```python
ERROR_SCENARIOS = {
    "unsupported_format": {
        "response": "❌ This format is not supported. Supported formats: [list]",
        "action": "Suggest conversion or alternative format"
    },
    "file_too_large": {
        "response": "⚠️ File exceeds 2GB limit. Please compress or split the file.",
        "action": "Suggest compression options"
    },
    "corrupted_file": {
        "response": "🔧 File appears corrupted. Would you like to attempt repair?",
        "action": "Attempt repair with ffmpeg"
    },
    "sync_detection_failed": {
        "response": "⚠️ Could not auto-detect sync. Manual sync required.",
        "action": "Provide manual sync interface"
    },
    "processing_error": {
        "response": "❌ Processing failed. Error: [details]",
        "action": "Log error and suggest retry"
    }
}
```

### 10. USER COMMANDS & RESPONSES

```
COMMAND EXAMPLES:

User sends video file →
Bot: "📹 Video received! Analyzing...
     Format: MKV | Duration: 2:30:45 | Resolution: 1920x1080
     Audio tracks: 2 (English AAC, Japanese AAC)
     
     What would you like to do?
     [🎵 Extract Audio] [➕ Add Audio] [🔄 Replace Audio] [✂️ Trim] [🔄 Sync]"

User clicks "➕ Add Audio" →
Bot: "Please send the audio file you want to add.
     Supported formats: MP3, AAC, WAV, FLAC, OGG, M4A, AC3
     Max size: 500MB"

User sends audio file →
Bot: "🎵 Audio received!
     Format: MP3 | Duration: 2:29:50 | Bitrate: 192kbps
     
     Detected language: English
     Is this correct?
     [✅ Yes] [❌ No, change language]
     
     Track label: [Enter label or use default]
     Set as default track? [✅ Yes] [❌ No]
     
     Processing... [████░░░░] 50%
     
     ✅ Audio added successfully!
     New video duration: 2:30:45
     Audio tracks: 3
     [📥 Download] [👁️ Preview] [📊 Report]"

User clicks "🔄 Sync" →
Bot: "Sync operation selected.
     Choose sync method:
     [🔍 Auto-Detect] - Automatically find and fix sync issues
     [⚡ Quick Sync] - Fast sync for minor issues
     [🎯 Manual Sync] - Set offset manually
     [📊 Sync Report] - View current sync status"

User clicks "🔍 Auto-Detect" →
Bot: "Analyzing audio sync...
     Detected offset: -250ms (audio is early)
     Applying correction...
     ✅ Sync corrected! Audio now aligned with video.
     [📥 Download Fixed File] [🔍 Re-check] [📊 Report]"

User clicks "✂️ Trim" →
Bot: "Trim operation selected.
     Choose trim type:
     [⏱️ Trim by Time] - Specify start and end times
     [🔇 Remove Silence] - Auto-remove silent parts
     [🎯 Smart Trim] - AI-powered intelligent trimming
     [📐 Custom Trim] - Advanced options
     
     Current duration: 2:30:45"

User clicks "🔇 Remove Silence" →
Bot: "Silence removal selected.
     Detected 15 silent segments totaling 5:30 minutes.
     
     Silence threshold: -40dB
     Minimum silence duration: 0.5 seconds
     
     [▶️ Start Processing] [⚙️ Adjust Settings]
     
     Processing... [██████████] 100%
     
     ✅ Silence removed!
     New duration: 2:25:15 (saved 5:30)
     [📥 Download] [👁️ Preview] [📊 Report]"
```

### 11. SUCCESS METRICS

```python
PERFORMANCE_METRICS = {
    "sync_accuracy": ">95% for auto-sync detection",
    "processing_speed": "1.5x real-time for HD video",
    "file_success_rate": ">98% successful processing",
    "user_satisfaction": ">4.5/5 rating",
    "error_rate": "<2% processing errors",
    "sync_precision": "±10ms accuracy"
}
```

---

## DELIVERABLES

Please provide:

1. **Complete bot implementation** with:
   - FFmpeg integration for video/audio processing
   - Audio sync detection algorithms
   - Silence detection and trimming
   - Multi-track audio management
   - Interactive button interface

2. **Configuration file** with:
   - Supported formats list
   - Processing parameters
   - Language settings
   - Quality presets

3. **README** including:
   - Installation guide
   - FFmpeg setup instructions
   - Usage examples
   - Troubleshooting guide

4. **Test suite** with:
   - Sample video/audio files
   - Sync test cases
   - Format compatibility tests
   - Edge case handling

5. **Deployment guide** for:
   - Local setup
   - Server deployment
   - Docker container
   - Cloud services

## CONSTRAINTS

- Use Python with FFmpeg for processing
- Implement async processing for multiple users
- Include progress tracking for long operations
- Ensure memory-efficient processing for large files
- Add automatic temp file cleanup
- Implement queue system for concurrent requests
- Provide detailed logging for debugging
- Include error recovery mechanisms

---

Please analyze these requirements and ask any clarifying questions before implementation. Then provide:
1. Detailed architecture design
2. Database schema for tracking processing jobs
3. Implementation plan
4. Complete working code
```

---

This prompt will help you create a powerful audio muxer bot with all the features you need including auto-sync detection, trimming, and multi-language audio track support. The bot will handle various video and audio formats with an intuitive button-based interface.
