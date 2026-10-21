# -*- mode: python ; coding: utf-8 -*-
# HikeReel v2.0 打包設定：主程式 HikeReel.exe + _internal 套件資料夾（onedir）
# 用法：pyinstaller --noconfirm HikeReel.spec   → 輸出在 dist\HikeReel\
from PyInstaller.utils.hooks import collect_all, collect_submodules, copy_metadata

datas = []
binaries = []
hiddenimports = [
    'gpx_to_video', 'terrain3d', 'landmark_photos',
    'pyproj.datadir', 'certifi', 'truststore', 'gpxpy', 'gpxpy.gpx', 'openpyxl',
    'PIL', 'PIL.Image', 'PIL.ImageDraw', 'PIL.ImageFont', 'PIL.ImageOps', 'PIL.ImageTk',
    'matplotlib', 'matplotlib.pyplot', 'matplotlib.font_manager', 'matplotlib.collections', 'numpy',
    'pyvista', 'vtkmodules.util.numpy_support',
]
for pkg in ('contextily', 'pyproj', 'rasterio', 'pyvista'):
    datas += copy_metadata(pkg)
for pkg in ('cv2', 'contextily', 'pyproj', 'rasterio', 'mercantile', 'xyzservices', 'certifi'):
    d, b, h = collect_all(pkg)
    datas += d; binaries += b; hiddenimports += h
# PyVista：收所有子模組，但略過網頁/筆記本/範例下載這些 HikeReel 用不到的部分
hiddenimports += [m for m in collect_submodules('pyvista')
                  if not any(x in m for x in ('trame', 'jupyter', 'examples', 'ext.downloads'))]
# VTK 是 3D 繪圖引擎，完整版有數百個模組（醫學影像、體積渲染加速、網頁伺服器…）。
# 只收 HikeReel 3D 渲染實際載入的模組（實測清單），其餘不打包，_internal 可小一半以上。
VTK_USED = ['vtkmodules.numpy_interface', 'vtkmodules.numpy_interface._vtk_array_mixin', 'vtkmodules.numpy_interface.array_overrides', 'vtkmodules.numpy_interface.dataset_adapter', 'vtkmodules.numpy_interface.vtk_affine_array', 'vtkmodules.numpy_interface.vtk_aos_array', 'vtkmodules.numpy_interface.vtk_composite_array', 'vtkmodules.numpy_interface.vtk_constant_array', 'vtkmodules.numpy_interface.vtk_implicit_array', 'vtkmodules.numpy_interface.vtk_indexed_array', 'vtkmodules.numpy_interface.vtk_soa_array', 'vtkmodules.numpy_interface.vtk_strided_array', 'vtkmodules.numpy_interface.vtk_structured_point_array', 'vtkmodules.util', 'vtkmodules.util.data_array_selection', 'vtkmodules.util.data_model', 'vtkmodules.util.execution_model', 'vtkmodules.util.numpy_support', 'vtkmodules.util.pickle_support', 'vtkmodules.util.vtkAlgorithm', 'vtkmodules.vtkChartsCore', 'vtkmodules.vtkCommonColor', 'vtkmodules.vtkCommonCore', 'vtkmodules.vtkCommonDataModel', 'vtkmodules.vtkCommonExecutionModel', 'vtkmodules.vtkCommonMath', 'vtkmodules.vtkCommonMisc', 'vtkmodules.vtkCommonSystem', 'vtkmodules.vtkCommonTransforms', 'vtkmodules.vtkFiltersCore', 'vtkmodules.vtkFiltersGeneral', 'vtkmodules.vtkFiltersGeometry', 'vtkmodules.vtkFiltersPython', 'vtkmodules.vtkFiltersSources', 'vtkmodules.vtkIOCore', 'vtkmodules.vtkIOImage', 'vtkmodules.vtkImagingCore', 'vtkmodules.vtkImagingMath', 'vtkmodules.vtkImagingSources', 'vtkmodules.vtkInteractionStyle', 'vtkmodules.vtkInteractionWidgets', 'vtkmodules.vtkParallelCore', 'vtkmodules.vtkPythonContext2D', 'vtkmodules.vtkRenderingAnnotation', 'vtkmodules.vtkRenderingContext2D', 'vtkmodules.vtkRenderingContextOpenGL2', 'vtkmodules.vtkRenderingCore', 'vtkmodules.vtkRenderingFreeType', 'vtkmodules.vtkRenderingHyperTreeGrid', 'vtkmodules.vtkRenderingLabel', 'vtkmodules.vtkRenderingMatplotlib', 'vtkmodules.vtkRenderingOpenGL2', 'vtkmodules.vtkRenderingUI', 'vtkmodules.vtkRenderingVolume', 'vtkmodules.vtkRenderingVolumeOpenGL2', 'vtkmodules.vtkViewsContext2D', 'vtkmodules.vtkViewsCore']
hiddenimports += VTK_USED

a = Analysis(
    ['gpx_video_app.py'],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['PyQt5', 'PyQt6', 'PySide2', 'PySide6', 'IPython', 'jupyter', 'notebook', 'trame', 'pytest',
              'imageio_ffmpeg',            # ffmpeg 由使用者自行安裝，不隨附
              'vtkmodules.web', 'vtkmodules.test'],
    noarchive=False,
    optimize=0,
)
# ── 精簡 VTK：只保留實際用到的 VTK 模組，以及它們（遞迴）相依的 DLL ──
import os, pefile


def _imports(path):
    try:
        pe = pefile.PE(path, fast_load=True)
        pe.parse_data_directories(directories=[pefile.DIRECTORY_ENTRY['IMAGE_DIRECTORY_ENTRY_IMPORT']])
        return [e.dll.decode().lower() for e in getattr(pe, 'DIRECTORY_ENTRY_IMPORT', [])]
    except Exception:
        return []


_used = {m.split('.')[-1] for m in VTK_USED if m.startswith('vtkmodules.vtk')}
_vtk_pyd, _vtk_dll, _other = [], {}, []
for entry in a.binaries:
    dest = entry[0].replace('\\', '/')
    low = dest.lower()
    if low.startswith('vtkmodules/vtk') and low.endswith('.pyd'):
        _vtk_pyd.append(entry)
    elif low.startswith('vtk.libs/'):
        _vtk_dll[os.path.basename(low)] = entry
    else:
        _other.append(entry)
_keep_pyd = [e for e in _vtk_pyd if os.path.basename(e[0]).split('.')[0] in _used]
_need, _todo = set(), [e[1] for e in _keep_pyd]
while _todo:
    for d in _imports(_todo.pop()):
        if d in _vtk_dll and d not in _need:
            _need.add(d)
            _todo.append(_vtk_dll[d][1])
a.binaries = _other + _keep_pyd + [_vtk_dll[d] for d in sorted(_need)]
print(f"VTK 精簡：模組 {len(_vtk_pyd)} → {len(_keep_pyd)}，DLL {len(_vtk_dll)} → {len(_need)}")

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,          # onedir：套件放在 _internal，主程式只有幾 MB
    name='HikeReel',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name='HikeReel',
)
