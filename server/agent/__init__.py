from pathlib import Path

# server/agent/prompt.md *is* the system prompt (editable directly, no code
# change needed). Everything before the "---" separator is documentation
# about the file, not part of what gets sent to the model.
SYSTEM_PROMPT = (Path(__file__).parent / "prompt.md").read_text().split("\n---\n", 1)[-1].strip()
