import configparser
import os
import subprocess
import sys
import tempfile

cfg = configparser.ConfigParser(delimiters=(':',), allow_no_value=True)
cfg.optionxform = str  # preserve case and >= in requirement strings
cfg.read('requirements.ini')

reqs = [key for section in cfg.sections() for key in cfg.options(section)]

with tempfile.NamedTemporaryFile('w', suffix='.txt', delete=False) as f:
    f.write('\n'.join(reqs))
    tmp = f.name

try:
    subprocess.run([sys.executable, '-m', 'pip', 'install', '-r', tmp], check=True)
    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'freeze'],
        capture_output=True, text=True, check=True,
    )
    with open('requirements.txt', 'w') as out:
        out.write(result.stdout)
    print('requirements.txt updated.')
finally:
    os.unlink(tmp)
