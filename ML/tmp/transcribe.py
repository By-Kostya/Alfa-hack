import json
from pathlib import Path

import mlx_whisper

AUDIO = "/Users/nixbi/Documents/Alfa-хакатон/tmp/alfa-hack.wav"
OUT_JSON = Path("/Users/nixbi/Documents/Alfa-хакатон/transcript.json")
OUT_TXT = Path("/Users/nixbi/Documents/Alfa-хакатон/transcript.txt")

result = mlx_whisper.transcribe(
    AUDIO,
    path_or_hf_repo="/Users/nixbi/Documents/Alfa-хакатон/tmp/whisper-large-v3-turbo",
    language="ru",
    verbose=True,
)

segments = []
for s in result["segments"]:
    text = (s.get("text") or "").strip()
    if not text:
        continue
    segments.append(
        {
            "start": round(float(s["start"]), 2),
            "end": round(float(s["end"]), 2),
            "text": text,
        }
    )

payload = {
    "language": result.get("language"),
    "text": result.get("text", ""),
    "segments": segments,
}
OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def fmt(t: float) -> str:
    total = int(t)
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


lines = [f"[{fmt(s['start'])} – {fmt(s['end'])}] {s['text']}" for s in segments]
OUT_TXT.write_text("\n".join(lines) + "\n", encoding="utf-8")
print(f"DONE segments={len(segments)}", flush=True)
