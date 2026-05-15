import sys

with open('flight_publisher.py', 'r', encoding='utf-8') as f:
    content = f.read()

new_content = content.replace('→', '->')

with open('flight_publisher.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print("Replacement complete.")
