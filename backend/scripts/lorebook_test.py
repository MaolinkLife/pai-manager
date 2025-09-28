import json
import os
import sys

sys.path.append(os.path.dirname(__file__) + '/..')

from services import lorebook_service

entries = lorebook_service.search_lore_entries('как меня зовут', top_k=5, min_similarity=0.6, use_keyword_fallback=True)
print(json.dumps(entries, ensure_ascii=False, indent=2))
