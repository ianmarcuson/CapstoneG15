import re

with open("generador_dashboard.py", "r", encoding="utf-8") as f:
    code = f.read()

# Replace f""" with """
code = code.replace('html_content = f"""<!DOCTYPE html>', 'html_content = """<!DOCTYPE html>')
# Replace placeholder
code = code.replace('{json_data}', 'JSON_DATA_PLACEHOLDER')
# Fix double curly braces
code = code.replace('{{', '{').replace('}}', '}')
# Inject the replace statement before saving
code = code.replace('"""\n    \n    with open(output_path', '"""\n    html_content = html_content.replace("JSON_DATA_PLACEHOLDER", json_data)\n    \n    with open(output_path')

with open("generador_dashboard.py", "w", encoding="utf-8") as f:
    f.write(code)
