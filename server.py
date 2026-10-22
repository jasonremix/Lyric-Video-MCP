from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("lyric-video-mcp")

SUPPORTED_AUDIO = {".mp3", ".wav", ".m4a", ".flac", ".aac", ".ogg", ".opus"}
ASPECTS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}


def main() -> None:
    mcp.run(transport="stdio")


def _require_binary(name: str) -> str:
    path = shutil.which(name)
    if not path:
        raise RuntimeError(f"{name} wurde nicht gefunden. Bitte FFmpeg installieren.")
    return path


def _audio_path(path: str) -> Path:
    p = Path(path).expanduser().resolve()
    if not p.exists() or not p.is_file():
        raise FileNotFoundError(f"Audiodatei nicht gefunden: {p}")
    if p.suffix.lower() not in SUPPORTED_AUDIO:
        raise ValueError(f"Nicht unterstütztes Audioformat: {p.suffix}")
    return p


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, text=True, capture_output=True)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()[-4000:]
        raise RuntimeError(f"Befehl fehlgeschlagen: {' '.join(args[:3])} …\n{detail}")
    return result


def _probe(audio: Path) -> dict[str, Any]:
    ffprobe = _require_binary("ffprobe")
    result = _run([
        ffprobe, "-v", "error", "-show_format", "-show_streams",
        "-of", "json", str(audio),
    ])
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), {})
    fmt = data.get("format", {})
    duration = float(fmt.get("duration") or audio_stream.get("duration") or 0)
    tags = {str(k).lower(): v for k, v in (fmt.get("tags") or {}).items()}
    return {
        "path": str(audio),
        "format": fmt.get("format_name"),
        "duration_seconds": round(duration, 3),
        "duration_formatted": _timestamp(duration),
        "sample_rate": int(audio_stream.get("sample_rate") or 0),
        "channels": audio_stream.get("channels"),
        "codec": audio_stream.get("codec_name"),
        "title": tags.get("title"),
        "artist": tags.get("artist") or tags.get("album_artist"),
        "album": tags.get("album"),
    }


def _timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:05.2f}"


def _srt_timestamp(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    whole = int(seconds % 60)
    millis = int(round((seconds - int(seconds)) * 1000))
    if millis == 1000:
        whole += 1
        millis = 0
    return f"{hours:02d}:{minutes:02d}:{whole:02d},{millis:03d}"


def _parse_lyrics(lyrics: Any) -> list[dict[str, Any]]:
    if isinstance(lyrics, str):
        text = lyrics.strip()
        if not text:
            return []
        try:
            lyrics = json.loads(text)
        except json.JSONDecodeError:
            return [{"start": 0.0, "end": 0.0, "text": line.strip()} for line in text.splitlines() if line.strip()]
    if not isinstance(lyrics, list):
        raise ValueError("lyrics muss eine Liste von Segmenten oder ein Text sein.")
    out = []
    for item in lyrics:
        if not isinstance(item, dict) or "text" not in item:
            continue
        out.append({
            "start": float(item.get("start", 0)),
            "end": float(item.get("end", 0)),
            "text": str(item["text"]).strip(),
        })
    return [x for x in out if x["text"]]


def _ensure_timings(segments: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    if not segments or duration <= 0:
        return segments
    if all(float(s.get("start", 0)) == 0 and float(s.get("end", 0)) == 0 for s in segments):
        step = duration / len(segments)
        return [{**s, "start": round(i * step, 3), "end": round((i + 1) * step, 3)} for i, s in enumerate(segments)]
    return segments


def _write_srt(segments: list[dict[str, Any]], path: Path, duration: float = 0) -> None:
    normalized = []
    for i, seg in enumerate(segments):
        start = max(0.0, float(seg.get("start", 0)))
        fallback_end = float(segments[i + 1].get("start", 0)) if i + 1 < len(segments) else duration
        end = float(seg.get("end", 0)) or fallback_end or (start + 3)
        if end <= start:
            end = start + 2.5
        normalized.append((start, end, str(seg.get("text", "")).strip()))
    with path.open("w", encoding="utf-8") as f:
        for i, (start, end, text) in enumerate(normalized, 1):
            f.write(f"{i}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{text}\n\n")


def _ass_escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("{", r"\{").replace("}", r"\}").replace("\n", r"\N")


def _ass_time(seconds: float) -> str:
    seconds = max(0.0, float(seconds))
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = seconds % 60
    return f"{h}:{m:02d}:{s:05.2f}"


def _write_ass(segments: list[dict[str, Any]], path: Path, width: int, height: int, duration: float, title: str = "") -> None:
    margin = max(60, int(min(width, height) * 0.07))
    font_size = max(34, int(min(width, height) * 0.055))
    title_size = max(22, int(font_size * 0.45))
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 2", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]", "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        f"Style: Lyrics,DejaVu Sans,{font_size},&H00FFFFFF,&H00FFFFFF,&H99000000,&H66000000,1,0,0,0,100,100,0,0,1,3,1,2,{margin},{margin},{margin},1",
        f"Style: Title,DejaVu Sans,{title_size},&H00B8C7FF,&H00B8C7FF,&H99000000,&H66000000,0,0,0,0,100,100,0,0,1,2,1,8,{margin},{margin},{margin},1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    if title:
        lines.append(f"Dialogue: 0,0:00:00.00,{_ass_time(duration)},Title,,0,0,0,,{_ass_escape(title)}")
    for i, seg in enumerate(segments):
        start = float(seg.get("start", 0))
        end = float(seg.get("end", 0)) or (float(segments[i + 1].get("start", 0)) if i + 1 < len(segments) else duration) or start + 2.5
        if end <= start:
            end = start + 2.5
        lines.append(f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Lyrics,,0,0,0,,{_ass_escape(str(seg.get('text', '')))}")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _parse_whisper_cpp_time(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value) / (1000 if float(value) > 1000 else 1)
    text = str(value).replace(",", ".")
    parts = text.split(":")
    if len(parts) == 3:
        return float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
    return float(text)


def _transcribe_whisper_cpp(audio: Path, model_path: str, output_dir: Path) -> tuple[list[dict[str, Any]], str | None]:
    binary = os.getenv("WHISPER_CPP_BIN", "whisper-cli")
    binary_path = shutil.which(binary) or (binary if Path(binary).exists() else None)
    if not binary_path:
        raise RuntimeError("whisper.cpp wurde nicht gefunden. Setze WHISPER_CPP_BIN oder installiere whisper-cli.")
    model = Path(model_path).expanduser().resolve()
    if not model.exists():
        raise FileNotFoundError(f"Whisper.cpp-Modell nicht gefunden: {model}")
    ffmpeg = _require_binary("ffmpeg")
    with tempfile.TemporaryDirectory(prefix="whisper-cpp-") as tmp:
        wav = Path(tmp) / "audio.wav"
        _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(audio), "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(wav)])
        prefix = Path(tmp) / "transcript"
        extra = shlex.split(os.getenv("WHISPER_CPP_ARGS", ""))
        _run([binary_path, "-m", str(model), "-f", str(wav), "-oj", "-of", str(prefix), *extra])
        json_path = prefix.with_suffix(".json")
        if not json_path.exists():
            candidates = list(Path(tmp).glob("*.json"))
            if candidates:
                json_path = candidates[0]
        if not json_path.exists():
            raise RuntimeError("whisper.cpp lief, erzeugte aber keine JSON-Transkription.")
        data = json.loads(json_path.read_text(encoding="utf-8"))
    raw_segments = data.get("transcription", data.get("segments", []))
    segments: list[dict[str, Any]] = []
    for item in raw_segments:
        timestamps = item.get("timestamps", {})
        offsets = item.get("offsets", {})
        start_raw = timestamps.get("from", offsets.get("from", 0))
        end_raw = timestamps.get("to", offsets.get("to", 0))
        segments.append({
            "start": round(_parse_whisper_cpp_time(start_raw), 3),
            "end": round(_parse_whisper_cpp_time(end_raw), 3),
            "text": str(item.get("text", "")).strip(),
        })
    return [s for s in segments if s["text"]], None


@mcp.tool()
def analyze_audio(audio_path: str) -> dict[str, Any]:
    """Liest Dauer, Format, Audio-Codec, Tags, Samplingrate und Kanäle einer Audiodatei aus."""
    return _probe(_audio_path(audio_path))


@mcp.tool()
def transcribe_audio(audio_path: str, model: str = "small", language: str | None = None, output_dir: str | None = None) -> dict[str, Any]:
    """Transkribiert Gesang mit faster-whisper oder whisper.cpp und speichert JSON-/SRT-Lyrics."""
    audio = _audio_path(audio_path)
    out_dir = Path(output_dir or audio.parent / "lyric-video-output").expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    backend = os.getenv("WHISPER_BACKEND", "auto").lower()
    result_segments: list[dict[str, Any]] = []
    detected_language = language
    if backend in {"auto", "faster-whisper", "faster_whisper"}:
        try:
            from faster_whisper import WhisperModel
            device = os.getenv("WHISPER_DEVICE", "cpu")
            compute_type = os.getenv("WHISPER_COMPUTE_TYPE", "int8")
            whisper = WhisperModel(model, device=device, compute_type=compute_type)
            segments, info = whisper.transcribe(str(audio), language=language, vad_filter=True, word_timestamps=True)
            detected_language = getattr(info, "language", language)
            for seg in segments:
                result_segments.append({
                    "start": round(float(seg.start), 3),
                    "end": round(float(seg.end), 3),
                    "text": seg.text.strip(),
                    "words": [
                        {"start": round(float(w.start), 3), "end": round(float(w.end), 3), "word": w.word}
                        for w in (seg.words or []) if w.start is not None and w.end is not None
                    ],
                })
        except ImportError:
            if backend != "auto":
                raise RuntimeError("faster-whisper fehlt. Für iSH nutze WHISPER_BACKEND=whisper.cpp.")
    if not result_segments and backend in {"auto", "whisper.cpp", "whisper_cpp"}:
        model_path = os.getenv("WHISPER_CPP_MODEL", model)
        result_segments, detected_language = _transcribe_whisper_cpp(audio, model_path, out_dir)
    metadata = _probe(audio)
    payload = {"audio": metadata, "language": detected_language, "language_probability": None, "segments": result_segments}
    json_path = out_dir / f"{audio.stem}.lyrics.json"
    srt_path = out_dir / f"{audio.stem}.lyrics.srt"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_srt(result_segments, srt_path, metadata["duration_seconds"])
    return {"json_path": str(json_path), "srt_path": str(srt_path), "language": payload["language"], "segment_count": len(result_segments), "duration_seconds": metadata["duration_seconds"]}


@mcp.tool()
def render_lyric_video(audio_path: str, lyrics: str | list[dict[str, Any]], output_path: str, title: str = "", aspect_ratio: str = "16:9", background_color: str = "101828", fps: int = 30) -> dict[str, Any]:
    """Rendert ein vollständiges MP4 mit Originalton, animierten Lyrics und einer FFmpeg-Hintergrundfläche."""
    audio = _audio_path(audio_path)
    if aspect_ratio not in ASPECTS:
        raise ValueError(f"aspect_ratio muss eines von {list(ASPECTS)} sein.")
    if not 1 <= int(fps) <= 120:
        raise ValueError("fps muss zwischen 1 und 120 liegen.")
    width, height = ASPECTS[aspect_ratio]
    meta = _probe(audio)
    segments = _ensure_timings(_parse_lyrics(lyrics), meta["duration_seconds"])
    out = Path(output_path).expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="lyric-video-") as tmp:
        ass = Path(tmp) / "lyrics.ass"
        _write_ass(segments, ass, width, height, meta["duration_seconds"], title)
        ffmpeg = _require_binary("ffmpeg")
        vf = f"subtitles={ass.as_posix()}"
        command = [
            ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "lavfi", "-i", f"color=c=0x{background_color}:s={width}x{height}:r={int(fps)}:d={meta['duration_seconds']}",
            "-i", str(audio), "-map", "0:v:0", "-map", "1:a:0", "-vf", vf,
            "-t", str(meta["duration_seconds"]), "-r", str(int(fps)), "-c:v", "libx264", "-preset", "medium", "-crf", "18",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-movflags", "+faststart", str(out),
        ]
        _run(command)
    return {"video_path": str(out), "srt_path": None, "duration_seconds": meta["duration_seconds"], "resolution": f"{width}x{height}", "fps": int(fps), "segment_count": len(segments)}


@mcp.tool()
def create_lyric_video(audio_path: str, output_dir: str | None = None, lyrics_json_path: str | None = None, lyrics_text: str | None = None, title: str = "", aspect_ratio: str = "16:9", whisper_model: str = "small", language: str | None = None, background_color: str = "101828", fps: int = 30) -> dict[str, Any]:
    """End-to-end: analysiert Audio, transkribiert bei Bedarf, erstellt SRT und rendert das vollständige Lyric-Music-Video."""
    audio = _audio_path(audio_path)
    out_dir = Path(output_dir or audio.parent / "lyric-video-output").expanduser().resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if lyrics_json_path:
        data = json.loads(Path(lyrics_json_path).expanduser().read_text(encoding="utf-8"))
        lyrics = data.get("segments", data) if isinstance(data, dict) else data
        transcript = {"source": "lyrics_json_path", "json_path": str(Path(lyrics_json_path).expanduser().resolve())}
    elif lyrics_text:
        lyrics = lyrics_text
        transcript = {"source": "lyrics_text"}
    else:
        transcript = transcribe_audio(str(audio), model=whisper_model, language=language, output_dir=str(out_dir))
        lyrics = json.loads(Path(transcript["json_path"]).read_text(encoding="utf-8"))["segments"]
    video = render_lyric_video(str(audio), lyrics, str(out_dir / f"{audio.stem}.lyric-video.mp4"), title=title, aspect_ratio=aspect_ratio, background_color=background_color, fps=fps)
    srt_path = out_dir / f"{audio.stem}.lyrics.srt"
    if not srt_path.exists():
        _write_srt(_parse_lyrics(lyrics), srt_path, _probe(audio)["duration_seconds"])
    return {"status": "completed", "audio": _probe(audio), "transcript": transcript, "video": video, "srt_path": str(srt_path)}


if __name__ == "__main__":
    main()
