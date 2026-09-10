import json
import zipfile

from ai_cad_designer.delivery import build_delivery_bundle


def test_delivery_bundle_contains_only_current_run_hashed_artifacts(tmp_path):
    model = tmp_path / "part.stl"
    model.write_text("mesh", encoding="utf-8")
    outside = tmp_path.parent / "outside.txt"
    outside.write_text("not packaged", encoding="utf-8")

    delivery = build_delivery_bundle(tmp_path, [str(model), str(outside)])

    with zipfile.ZipFile(delivery["archive"]) as bundle:
        assert set(bundle.namelist()) == {"part.stl", "delivery_manifest.json"}
        manifest = json.loads(bundle.read("delivery_manifest.json"))
    assert manifest["artifact_count"] == 1
    assert manifest["artifacts"][0]["path"] == "part.stl"
