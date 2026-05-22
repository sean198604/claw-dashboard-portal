# Fix emoji font in admin.html too
import re

with open('admin.html', 'r', encoding='utf-8') as f:
    content = f.read()

pattern = r"(font-family: -apple-system, '[^']+', '[^']+', )'Inter', sans-serif;"
replacement = r'\1"Segoe UI Emoji", "Inter", sans-serif;'

new_content = re.sub(pattern, replacement, content)

if new_content != content:
    with open('admin.html', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Fixed admin.html emoji font')
else:
    idx = content.find('font-family')
    if idx >= 0:
        print('admin.html font:', repr(content[idx:idx+120]))
    else:
        print('No font-family in admin.html')
