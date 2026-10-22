# Lyric-Video-MCP

Lokaler Python-stdio-MCP-Server für vollständige Lyric-Music-Videos. Er analysiert Audio mit `ffprobe`, transkribiert Gesang mit `faster-whisper`, schreibt zeitcodierte JSON-/SRT-Lyrics und rendert ein vollständiges MP4 mit FFmpeg und ASS-Textanimation.

## Voraussetzungen

- Python 3.10 oder neuer
- FFmpeg inklusive `ffprobe` im `PATH`
- ausreichend Speicher für das gewählte Whisper-Modell

## Installation

```bash
./install.sh
```

Oder manuell:

```bash
python3 -m venv .venv
. .venv/bin/activate
pip install -e .
```

Für CPU-Systeme:

```bash
export WHISPER_DEVICE=cpu
export WHISPER_COMPUTE_TYPE=int8
```

## MCP-Konfiguration

```json
{
  "mcpServers": {
    "lyric-video": {
      "command": "/absoluter/pfad/zu/lyric-video-mcp/.venv/bin/python",
      "args": ["/absoluter/pfad/zu/lyric-video-mcp/server.py"],
      "env": {
        "WHISPER_DEVICE": "cpu",
        "WHISPER_COMPUTE_TYPE": "int8"
      }
    }
  }
}
```

## Tools

- `analyze_audio(audio_path)`: Dauer, Tags, Codec, Samplingrate und Kanäle.
- `transcribe_audio(audio_path, model="small", language=null, output_dir=null)`: Gesangstranskription mit Zeitstempeln; erzeugt `.lyrics.json` und `.lyrics.srt`.
- `render_lyric_video(audio_path, lyrics, output_path, title="", aspect_ratio="16:9", background_color="101828", fps=30)`: Rendert ein MP4 mit Originalton, Hintergrund und ASS-Lyrics.
- `create_lyric_video(...)`: End-to-end-Pipeline für Transkription, SRT und MP4.

`lyrics` kann als zeitcodierte Segmentliste übergeben werden:

```json
[
  {"start": 0.0, "end": 3.2, "text": "Erste Zeile"},
  {"start": 3.2, "end": 6.8, "text": "Zweite Zeile"}
]
```

Unterstützte Videoformate sind `16:9`, `9:16` und `1:1`. Die Ausgabe verwendet H.264, AAC, 48 kHz und `yuv420p`.

## Hinweis

Die erste Version erzeugt eine hochwertige Motion-Lyric-Grundfassung mit einheitlichem FFmpeg-Hintergrund. Generative Filmszenen und externe Videomodelle können später als zusätzliche Provider ergänzt werden. Für urheberrechtlich geschützte Songs müssen die erforderlichen Nutzungsrechte vorliegen.
