"""Make the source package importable from the project's virtual environment."""

import sysconfig
from pathlib import Path


source_dir = Path(__file__).resolve().parent
site_packages = Path(sysconfig.get_path('purelib'))
site_packages.joinpath('scalp_lab_source.pth').write_text(str(source_dir) + '\n', encoding='utf-8')
print(f'Registered source package: {source_dir}')
