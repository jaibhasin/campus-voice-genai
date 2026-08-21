import os
import json
import re
from pathlib import Path

# Get the directory where this file is located
module_dir = os.path.dirname(os.path.abspath(__file__))

# ── Load chat prompt ──
prompt_path = os.path.join(module_dir, 'college_assistant.md')
with open(prompt_path, 'r', encoding='utf-8') as f:
    system_prompt = f.read()

# ── Load voice prompt ──
voice_prompt_path = os.path.join(module_dir, 'voice_assistant.md')
with open(voice_prompt_path, 'r', encoding='utf-8') as f:
    voice_system_prompt = f.read()

# Scan for dynamic documents in pageindex_data
data_dir = Path(module_dir).parent.parent / "pageindex_data"
dynamic_docs_list = []
if data_dir.exists():
    for json_file in sorted(data_dir.glob("*.json")):
        name = json_file.stem
        try:
            with open(json_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                meta = data.get("metadata", {})
                desc = meta.get("description", "No description available")
                # Keep it concise
                if len(desc) > 200:
                    desc = desc[:197] + "..."
                dynamic_docs_list.append(f"- **{name}** — {desc}")
        except Exception:
            pass

# Reconstruct DOCUMENTS section in both prompts
if dynamic_docs_list:
    doc_section_content = "\n".join(dynamic_docs_list)
    pattern = r"(## DOCUMENTS\s*\n)([\s\S]*?)(### Document Selection Guide)"
    replacement = rf"\1{doc_section_content}\n\n\3"
    system_prompt = re.sub(pattern, replacement, system_prompt)
    voice_system_prompt = re.sub(pattern, replacement, voice_system_prompt)

college_assistant_system_prompt = system_prompt
voice_assistant_system_prompt = voice_system_prompt