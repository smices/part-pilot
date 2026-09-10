import hashlib
import json
import stat
import sys
from pathlib import Path

from ai_cad_designer.blender_preview import (
    PREVIEW_DIRECTORY,
    SCRIPT_NAME,
    build_blender_command,
    render_isometric_preview,
)


def _stl(directory: Path) -> Path:
    path = directory / "part.stl"
    path.write_text("solid part\nendsolid part\n", encoding="ascii")
    return path


def _fake_blender(path: Path, body: str) -> Path:
    path.write_text(f"#!{sys.executable}\n{body}", encoding="utf-8")
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


def test_background_command_and_success_manifest(tmp_path: Path) -> None:
    source = _stl(tmp_path)
    fake_blender = _fake_blender(
        tmp_path / "fake-blender",
        """import sys
from pathlib import Path
output = Path(sys.argv[sys.argv.index('--') + 1])
(output / 'isometric.png').write_bytes(b'png')
print('Blender 9.9 Test')
""",
    )

    command = build_blender_command(
        fake_blender,
        tmp_path / PREVIEW_DIRECTORY,
        [source],
    )
    assert command[1:5] == [
        "--background",
        "--factory-startup",
        "--python",
        str(tmp_path / PREVIEW_DIRECTORY / SCRIPT_NAME),
    ]
    assert command[5] == "--"

    result = render_isometric_preview([source], tmp_path, blender_binary=fake_blender)
    manifest_path = tmp_path / PREVIEW_DIRECTORY / "visual_preview.json"

    assert result["status"] == "passed"
    assert manifest_path.is_file()
    assert (
        tmp_path / PREVIEW_DIRECTORY / "isometric.png"
    ).read_bytes() == b"png"
    assert result["units"] == "millimeters"
    assert result["sources"] == [
        {
            "file_name": "part.stl",
            "sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        }
    ]
    assert result["blender"] == {
        "version": "Blender 9.9 Test",
        "command": [
            str(fake_blender),
            "--background",
            "--factory-startup",
            "--python",
            str(tmp_path / PREVIEW_DIRECTORY / SCRIPT_NAME),
            "--",
            str(tmp_path / PREVIEW_DIRECTORY),
            str(source),
        ],
        "returncode": 0,
    }
    assert "item.name = (" in (
        tmp_path / PREVIEW_DIRECTORY / SCRIPT_NAME
    ).read_text(encoding="utf-8")
    assert json.loads(manifest_path.read_text(encoding="utf-8"))["status"] == "passed"


def test_preview_manifest_keeps_exploded_render_when_blender_produces_one(tmp_path: Path) -> None:
    first = _stl(tmp_path)
    second = tmp_path / "lid.stl"
    second.write_text("solid lid\nendsolid lid\n", encoding="ascii")
    fake_blender = _fake_blender(
        tmp_path / "fake-exploded-blender",
        """import sys
from pathlib import Path
output = Path(sys.argv[sys.argv.index('--') + 1])
(output / 'isometric.png').write_bytes(b'iso')
(output / 'exploded.png').write_bytes(b'exploded')
print('Blender 9.9 Test')
""",
    )

    result = render_isometric_preview([first, second], tmp_path, blender_binary=fake_blender)

    assert result["exploded_render"]["exists"] is True
    assert "blender_preview/exploded.png" in result["artifacts"]


def test_failed_blender_keeps_local_diagnostic(tmp_path: Path) -> None:
    source = _stl(tmp_path)
    fake_blender = _fake_blender(
        tmp_path / "failing-blender",
        """import sys
print('render failed', file=sys.stderr)
raise SystemExit(7)
""",
    )

    result = render_isometric_preview([source], tmp_path, blender_binary=fake_blender)
    diagnostic = tmp_path / result["diagnostic"]

    assert result["status"] == "failed"
    assert result["blender"]["returncode"] == 7
    assert diagnostic.is_file()
    assert (
        json.loads(diagnostic.read_text(encoding="utf-8"))["stderr"]
        == "render failed\n"
    )
    assert not (tmp_path / PREVIEW_DIRECTORY / "isometric.png").exists()


def test_disabled_preview_is_not_run(tmp_path: Path) -> None:
    assert render_isometric_preview([], tmp_path, enabled=False)["status"] == "not_run"
