#!/usr/bin/env python3
import os

with open('phase3_agent.py', 'r', encoding='utf-8') as f:
    lines = f.readlines()

# Find line 627 (index 626) and replace it
for i, line in enumerate(lines):
    if 'You should do this' in line and 'best choice' in line:
        lines[i] = '''        # SAFE fallback - neutral multi-option response
        return (
            "Here are some options to consider:\\n"
            "A) Move forward with current approach.\\n"
            "B) Explore a different method.\\n"
            "C) Pause and evaluate further.\\n\\n"
            "Feel free to choose what works best for you."
        )

'''
        print(f"Replaced line {i+1}")
        break

with open('phase3_agent.py', 'w', encoding='utf-8') as f:
    f.writelines(lines)

print("Done!")
