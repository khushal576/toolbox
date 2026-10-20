"""Install CTAN fontawesome / fontawesome5 zips into TEXMFLOCAL (TDS layout).

Run at image build time (see Dockerfile). Gives LaTeX \\usepackage{fontawesome} and
\\usepackage{fontawesome5} without the ~1.7 GB texlive-fonts-extra package (these two zips are
~2 MB). The caller then runs mktexlsr and `updmap-sys --enable Map=<name>.map`.
Usage: python install_fontawesome.py <texmf-root> <zip> [<zip> ...]
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(sys.argv[1])
KIND = {  # folder inside the CTAN zip -> TDS folder (the package name is appended)
    "tex": "tex/latex",
    "enc": "fonts/enc/dvips",
    "map": "fonts/map/dvips",
    "tfm": "fonts/tfm/public",
    "type1": "fonts/type1/public",
    "opentype": "fonts/opentype/public",
}
for zip_path in sys.argv[2:]:
    with zipfile.ZipFile(zip_path) as z:
        for info in z.infolist():
            parts = info.filename.split("/")      # <package>/<kind>/<file>
            if info.is_dir() or len(parts) != 3 or parts[1] not in KIND:
                continue                            # skips README and doc/
            target = ROOT / KIND[parts[1]] / parts[0] / parts[2]
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(z.read(info))
