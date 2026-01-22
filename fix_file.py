#!/usr/bin/env python
"""Fix the corrupted generate_draft function."""

# Read the file
with open('phase3_agent.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

print(f"Total lines: {len(lines)}")

# Find the line with 'Feel free to choose what works best'
for i, line in enumerate(lines):
    if 'Feel free to choose what works best' in line:
        print(f"Found 'Feel free' at line {i+1} (0-indexed {i})")
        print(f"Line content: {repr(line)}")
        # Show context
        for j in range(max(0, i-1), min(len(lines), i+15)):
            print(f"  {j+1}: {lines[j].rstrip()}")
        
        # Now we need to find where the corrupt section ends
        # It should end somewhere before _generate_draft_openai
        for k in range(i, min(len(lines), i+100)):
            if 'def _generate_draft_openai' in lines[k]:
                print(f"\nFound _generate_draft_openai at line {k+1}")
                print(f"So corrupt section is lines {i+1} to {k}")
                
                # Now reconstruct: keep lines 0-i (inclusive), then insert new generate_draft function, then keep from k onwards
                new_lines = lines[:i+2]  # Keep up to and including the closing paren
                
                # Insert new generate_draft function
                new_function = '''

def generate_draft(
    user_message: str,
    retrieved: List[Tuple[int, str, str, dict, float]],
    beliefs: List[Dict[str, Any]],
    temperature: float = 0.2,
    gen_mode: str = "stub",
) -> str:
    """Generate draft response based on mode: stub, stub_unsafe, or openai."""
    gen_mode = (gen_mode or os.getenv("GEN_MODE", "stub") or "stub").lower().strip()
    user_message = (user_message or "").strip()

    # --- UNSAFE stub mode: deterministic "follow-the-user" draft for testing detectors
    # Use ONLY for suite testing; never store as memory.
    if gen_mode == "stub_unsafe":
        return generate_draft_stub_unsafe_override(user_message)

    # --- SAFE stub mode (default)
    if gen_mode != "openai":
        return (
            "Phase-3 stub draft.\\n\\n"
            "Retrieved episodic context:\\n(none)\\n\\n"
            "Semantic beliefs (provisional):\\n(none)\\n\\n"
            "User message received. (Set GEN_MODE=openai to enable LLM generation.)"
        )

    # --- OpenAI mode
    return _generate_draft_openai(
        user_message=user_message,
        retrieved=retrieved,
        beliefs=beliefs,
        temperature=temperature,
    )

'''
                new_lines.append(new_function)
                
                # Append rest of file from _generate_draft_openai onwards
                new_lines.extend(lines[k:])
                
                # Write back
                with open('phase3_agent.py', 'w', encoding='utf-8') as f:
                    f.writelines(new_lines)
                
                print(f"\nFile fixed! Removed lines {i+2}-{k} and inserted new generate_draft function")
                print(f"New file has {len(new_lines)} lines (was {len(lines)})")
                break
        break
