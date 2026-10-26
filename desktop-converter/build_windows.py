"""Build a native, un-packaged Windows executable with the Fjord PE icon."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile


def build(install_dir):
    if os.name!='nt':raise RuntimeError('Windows executable builds require Windows.')
    source=Path(__file__).resolve().parent
    install_dir=Path(install_dir).resolve();install_dir.mkdir(parents=True,exist_ok=True)
    work=Path(tempfile.mkdtemp(prefix='fjord-encode-build-')).resolve()
    try:
        packages=work/'packages'
        subprocess.run([sys.executable,'-m','pip','install','--only-binary=:all:','--target',str(packages),'pyinstaller==6.22.3'],check=True)
        env={**os.environ,'PYTHONPATH':str(packages)+os.pathsep+os.environ.get('PYTHONPATH','')}
        subprocess.run([sys.executable,'-m','PyInstaller','--onefile','--noconsole',
            '--name','Fjord-konvertering','--icon',str(source/'fjord.ico'),
            '--distpath',str(work/'dist'),'--workpath',str(work/'work'),'--specpath',str(work),
            '--paths',str(source),str(source/'fjord_encode.pyw')],env=env,cwd=source,check=True)
        target=install_dir/'Fjord-konvertering.exe'
        shutil.copy2(work/'dist'/'Fjord-konvertering.exe',target)
        print('Built '+str(target))
        return target
    finally:
        # Delete only this freshly created build directory inside Windows TEMP.
        if work.parent==Path(tempfile.gettempdir()).resolve() and work.name.startswith('fjord-encode-build-'):
            shutil.rmtree(work)


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--install-dir',default=str(Path(os.environ['LOCALAPPDATA'])/'FjordEncode'))
    args=parser.parse_args()
    build(args.install_dir)
