"""Persist FreeCAD preferences when executed by FreeCADCmd."""

import FreeCAD as App


general = App.ParamGet("User parameter:BaseApp/Preferences/General")
general.SetString("AutoloadModule", "PartWorkbench")
general.SetString("LastModule", "PartWorkbench")
general.SetBool("ShowPythonConsole", True)
general.SetString("AICADConfiguration", "enabled")

print(f"FreeCAD {'.'.join(App.Version()[:3])}")
print(f"User data: {App.getUserAppDataDir()}")
print("Default workbench: PartWorkbench")
print("Python console startup extension: expected in Mod/AICADStartup")
