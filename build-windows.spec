# build-windows.spec
# Run on a Windows machine with:
#   pip install pyinstaller requests
#   pyinstaller build-windows.spec

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=['.'],
    binaries=[],
    datas=[
        ('syndicate_client.py', '.'),
        ('bulk_editor.py', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='Syndicate Bulk Updater',
    debug=False,
    strip=False,
    upx=True,
    console=False,       # no terminal window
    onefile=True,        # single .exe
)
