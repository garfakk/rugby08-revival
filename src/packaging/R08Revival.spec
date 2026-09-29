# PyInstaller spec for the Rugby 08 Revival frontend (Windows, onedir).
# Build:  pyinstaller --noconfirm R08Revival.spec     (see build_wine.sh / build_windows.bat)
import os

ROOT = os.path.abspath(os.path.join(SPECPATH, ".."))
FRONTEND = os.path.join(ROOT, "frontend")


def modules_in(base, package):
    """All module names of a source package, e.g. ui.theme, app.roster_import.reader.
    The frontend imports its packages as top-level (ui, app, screens) via sys.path
    tricks and some imports are lazy, so list everything explicitly."""
    out = []
    pkg_dir = os.path.join(base, package)
    for dirpath, _dirs, files in os.walk(pkg_dir):
        if "__pycache__" in dirpath:
            continue
        rel = os.path.relpath(dirpath, base).replace(os.sep, ".")
        for f in files:
            if f.endswith(".py"):
                name = f[:-3]
                out.append(rel if name == "__init__" else f"{rel}.{name}")
    return out


hidden = []
for pkg in ("ui", "app", "screens"):
    hidden += modules_in(FRONTEND, pkg)
for pkg in ("backend", "shared"):
    hidden += modules_in(ROOT, pkg)
hidden += ["tkinter", "tkinter.filedialog", "tkinter.messagebox", "winreg",
           "win32api", "win32con", "win32gui", "win32process", "pywintypes",
           "PyQt5.sip", "PyQt5.QtMultimedia", "PyQt5.QtOpenGL"]
# PyOpenGL picks its platform/array backends by name at runtime; PyInstaller's own
# collection can't import OpenGL on a build host without GL (e.g. wine), so list them.
hidden += ["OpenGL.platform.win32", "OpenGL.GL", "OpenGL.GLU",
           "OpenGL.arrays.numpymodule", "OpenGL.arrays.ctypesarrays",
           "OpenGL.arrays.ctypesparameters", "OpenGL.arrays.ctypespointers",
           "OpenGL.arrays.lists", "OpenGL.arrays.nones", "OpenGL.arrays.numbers",
           "OpenGL.arrays.strings", "OpenGL.arrays.buffers", "OpenGL.arrays.vbo",
           "OpenGL.arrays.formathandler", "OpenGL.raw.GL.VERSION.GL_1_1",
           "OpenGL.raw.GL._types", "OpenGL_accelerate"]

a = Analysis(
    [os.path.join(FRONTEND, "main.py")],
    pathex=[ROOT, FRONTEND],
    binaries=[],
    datas=[(os.path.join(FRONTEND, "ui", "fonts"), os.path.join("ui", "fonts"))],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=[],
    excludes=["matplotlib", "scipy", "pandas", "IPython", "pytest", "PyQt5.QtWebEngine",
              "PyQt5.QtWebEngineWidgets", "PyQt5.QtWebKit", "PyQt5.QtQml", "PyQt5.QtQuick",
              "PyQt5.QtDesigner", "PyQt5.QtSql", "PyQt5.QtTest", "PyQt5.QtBluetooth",
              "PyQt5.QtNfc", "PyQt5.QtSensors", "PyQt5.QtSerialPort", "PyQt5.QtLocation"],
    noarchive=False,
)
# Data nobody uses: Tcl's timezone database (~600 tiny files, slow to install; Tk is only
# used for message/file boxes), Tcl/Tk locale message catalogs and Qt's translations.
_STRIP = ("_tcl_data/tzdata/", "_tcl_data/msgs/", "_tk_data/msgs/", "PyQt5/Qt5/translations/")
a.datas = [d for d in a.datas if not d[0].replace("\\", "/").startswith(_STRIP)]
pyz = PYZ(a.pure)

# Version resource of the exe: packaging/version_info.txt with the numbers taken from
# APP_VERSION in shared/version.py (the single source of truth, see release.sh).
def _version_file():
    ns = {}
    with open(os.path.join(ROOT, "shared", "version.py"), encoding="utf-8") as f:
        exec(f.read(), ns)
    version = ns["APP_VERSION"]
    nums = ([int(p) for p in version.split(".") if p.isdigit()] + [0, 0, 0, 0])[:4]
    with open(os.path.join(SPECPATH, "version_info.txt"), encoding="utf-8") as f:
        text = f.read()
    text = text.replace("@FILEVERS@", ", ".join(map(str, nums))).replace("@VERSION@", version)
    out = os.path.join(SPECPATH, "build", "version_info.rendered.txt")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write(text)
    return out


exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="R08Revival",
    console=os.environ.get("R08_CONSOLE") == "1",   # release: windowed, stdout/stderr go to R08Revival.log (see frontend/main.py)
    icon=os.path.join(SPECPATH, "icon", "app_icon.ico"),
    version=_version_file(),
    upx=False,              # UPX triggers antivirus false positives
)
coll = COLLECT(exe, a.binaries, a.datas, upx=False, name="R08Revival")
