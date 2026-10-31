"""Build the downloadable extension deterministically from reviewed source files."""
from pathlib import Path
from zipfile import ZipFile, ZipInfo, ZIP_DEFLATED

root = Path(__file__).resolve().parents[1]
files = ['manifest.json', 'background.js', 'common.mjs', 'package.mjs', 'popup.html', 'popup.js', 'popup.css', 'icon.png', 'README.md']
target = root/'static'/'fjordseed-chrome.zip'
with ZipFile(target, 'w', compression=ZIP_DEFLATED) as archive:
    for name in files:
        info = ZipInfo('fjordseed-chrome/' + name, date_time=(2026, 10, 12, 0, 0, 0))
        info.compress_type = ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, (root/'chrome-extension'/name).read_bytes())
print(target)
