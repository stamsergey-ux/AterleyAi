import os
from openai import OpenAI

client = OpenAI(api_key=os.environ.get("OPENAI_API_KEY"))

audio_dir = "/Users/sergej/Desktop/AI startup/Ai психолог"
files = sorted([f for f in os.listdir(audio_dir) if f.endswith(".m4a")])

for f in files:
    path = os.path.join(audio_dir, f)
    print(f"\n{'='*60}")
    print(f"Файл: {f}")
    print(f"{'='*60}\n")

    with open(path, "rb") as audio_file:
        transcript = client.audio.transcriptions.create(
            model="whisper-1",
            file=audio_file,
            language="ru",
            response_format="text"
        )

    print(transcript)

    # Save transcript
    txt_path = path.rsplit(".", 1)[0] + ".txt"
    with open(txt_path, "w") as out:
        out.write(transcript)

    print(f"\nСохранено: {txt_path}")
