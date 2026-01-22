#!/usr/bin/env python3
import re

with open('phase3_agent.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find and remove the broken lines from line 603 onwards until we find _generate_draft_openai
start_idx = None
end_idx = None

for i, line in enumerate(lines):
    if 'def generate_draft_stub_unsafe_override' in line:
        start_idx = i
    if start_idx is not None and 'def _generate_draft_openai' in line:
        end_idx = i
        break

if start_idx is not None and end_idx is not None:
    # Keep only the helper function and the cleanly defined generate_draft
    new_lines = lines[:start_idx]
    
    # Add the helper function
    new_lines.extend(lines[start_idx:start_idx+19])  # Lines up to and including the return statement of helper
    
    # Add clean generate_draft function
    new_lines.extend([
        '\n',
        'def generate_draft(\n',
        '    user_message: str,\n',
        '    retrieved: List[Tuple[int, str, str, dict, float]],\n',
        '    beliefs: List[Dict[str, Any]],\n',
        '    temperature: float = 0.2,\n',
        '    gen_mode: str | None = None,\n',
        ') -> str:\n',
        '    gen_mode = (gen_mode or os.getenv("GEN_MODE", "stub") or "stub").lower().strip()\n',
        '    user_message = (user_message or "").strip()\n',
        '\n',
        '    # --- UNSAFE stub mode\n',
        '    if gen_mode == "stub_unsafe":\n',
        '        return generate_draft_stub_unsafe_override(user_message)\n',
        '\n',
        '    # --- SAFE stub mode (default)\n',
        '    if gen_mode != "openai":\n',
        '        return (\n',
        '            "Phase-3 stub draft.\\n\\n"\n',
        '            "Retrieved episodic context:\\n(none)\\n\\n"\n',
        '            "Semantic beliefs (provisional):\\n(none)\\n\\n"\n',
        '            "User message received. (Set GEN_MODE=openai to enable LLM generation.)"\n',
        '        )\n',
        '\n',
        '    # --- OpenAI mode\n',
        '    return _generate_draft_openai(\n',
        '        user_message=user_message,\n',
        '        retrieved=retrieved,\n',
        '        beliefs=beliefs,\n',
        '        temperature=temperature,\n',
        '    )\n',
        '\n',
    ])
    
    # Add everything from _generate_draft_openai onwards
    new_lines.extend(lines[end_idx:])
    
    with open('phase3_agent.py', 'w', encoding='utf-8') as f:
        f.writelines(new_lines)
    
    print(f"Fixed! Removed lines {start_idx+20} to {end_idx-1}")
else:
    print(f"Could not find boundaries: start={start_idx}, end={end_idx}")
