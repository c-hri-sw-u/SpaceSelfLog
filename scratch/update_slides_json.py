import json
import re

path = 'visualization/slides_data.json'
with open(path, 'r') as f:
    data = json.load(f)

new_slides = []
insertion_index = 112 # Index of 19_system_pipeline.html in the original list? No, I need to find it by value.

# Find the insertion point: where src starts with /slides/slide-files/19_
# Note: In the file, "src": "/slides/slide-files/19_system_pipeline.html" is at index 113? No, the line numbers in view_file were different.
# Let's iterate and find.

for i, slide in enumerate(data['slides']):
    src = slide.get('src', '')
    match = re.search(r'/slides/slide-files/(\d+)_', src)
    if match:
        num = int(match.group(1))
        if num >= 19:
            # Update the src to reflect the renamed file
            new_num = num + 1
            slide['src'] = src.replace(f'/slides/slide-files/{num}_', f'/slides/slide-files/{new_num}_')
    
    # We want to insert the new slide BEFORE the one that was 19 (now 20)
    if match and int(match.group(1)) == 19 and not any(s.get('src') == '/slides/slide-files/19_abstract_pipeline.html' for s in new_slides):
        new_slides.append({
            "section": "System Design",
            "subtitle": "Abstract Pipeline",
            "src": "/slides/slide-files/19_abstract_pipeline.html",
            "script": "Before we look at the specific technical layers, let's look at the abstract logic of the pipeline: Information Collection, Information Filtering, Information Implantation, and Feedback."
        })
    
    new_slides.append(slide)

data['slides'] = new_slides

with open(path, 'w') as f:
    json.dump(data, f, indent=2, ensure_ascii=False)
