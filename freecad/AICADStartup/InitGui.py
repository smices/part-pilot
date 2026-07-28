"""FreeCAD GUI startup configuration for the AI CAD workstation."""

import FreeCADGui as Gui
from PySide import QtCore

try:
    from PySide import QtWidgets
except ImportError:
    from PySide import QtGui as QtWidgets


def configure_ai_cad_gui():
    """Show the Python console and start in the Part workbench."""
    main_window = Gui.getMainWindow()
    for dock in main_window.findChildren(QtWidgets.QDockWidget):
        identity = f"{dock.objectName()} {dock.windowTitle()}".lower()
        if "python" in identity and "console" in identity:
            dock.show()
            dock.raise_()
            break
    try:
        Gui.activateWorkbench("PartWorkbench")
    except Exception as exc:
        print(f"AI CAD startup: Part workbench activation failed: {exc}")


QtCore.QTimer.singleShot(1200, configure_ai_cad_gui)

