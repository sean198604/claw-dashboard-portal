# Fix emoji font in index.html
import re

with open('index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Pattern: font-family with 'Inter', sans-serif (single quotes)
pattern = r"(font-family: -apple-system, '[^']+', '[^']+', )'Inter', sans-serif;"
replacement = r'\1"Segoe UI Emoji", "Inter", sans-serif;'

new_content = re.sub(pattern, replacement, content)

if new_content != content:
    with open('index.html', 'w', encoding='utf-8') as f:
        f.write(new_content)
    print('Fixed: added Segoe UI Emoji to font-family')
else:
    # Try double-quote variant
    pattern2 = r'(font-family: -apple-system, "[^"]+", "[^"]+", )"Inter", sans-serif;'
    new_content2 = re.sub(pattern2, replacement, content)
    if new_content2 != content:
        with open('index.html', 'w', encoding='utf-8') as f:
            f.write(new_content2)
        print('Fixed via double-quote pattern')
    else:
        # Find current font-family
        idx = content.find('font-family')
        if idx >= 0:
            print('Current font-family:', repr(content[idx:idx+120]))
        else:
            print('No font-family found')
