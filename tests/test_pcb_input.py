import pytest

from ai_cad_designer.agents.joint_agent import JointAgent
from ai_cad_designer.pcb_input import PCBMechanicalInput
from ai_cad_designer.validation import validate_printability


def measure(value, confirmed=True, source="user_measurement"):
    return {"value": value, "unit": "mm", "source": source, "confirmed": confirmed}


def payload():
    return {"length": measure(60), "width": measure(40), "thickness": measure(1.6), "max_component_height": measure(12, False), "mounting_holes": [{"x": measure(5), "y": measure(5), "diameter": measure(3)}, {"x": measure(55), "y": measure(35), "diameter": measure(3)}], "interfaces": [{"name": "USB-C", "face": "rear", "x": measure(50), "y": measure(40), "width": measure(8), "height": measure(4)}], "keepouts": [{"x": measure(20), "y": measure(10), "width": measure(10), "height": measure(10)}]}


def test_pcb_input_keeps_sources_confirmation_and_coordinate_system():
    pcb = PCBMechanicalInput.from_payload(payload())
    assert pcb.length.value == 60
    assert pcb.pending_confirmation() == ["max_component_height"]


@pytest.mark.parametrize("mutate", [lambda p: p["length"].update(unit="inch"), lambda p: p["mounting_holes"][0]["x"].update(value=-1), lambda p: p["interfaces"][0]["width"].update(value=25)])
def test_pcb_input_rejects_bad_units_or_outside_features(mutate):
    data = payload(); mutate(data)
    with pytest.raises(ValueError):
        PCBMechanicalInput.from_payload(data)


def test_pcb_input_rejects_overlapping_holes():
    data = payload(); data["mounting_holes"][1]["x"] = measure(6); data["mounting_holes"][1]["y"] = measure(5)
    with pytest.raises(ValueError, match="overlap"):
        PCBMechanicalInput.from_payload(data)


def test_pcb_dimensions_holes_and_ports_change_generated_enclosure():
    first = PCBMechanicalInput.from_payload(payload())
    changed = payload(); changed["mounting_holes"][0]["x"] = measure(12); changed["interfaces"][0]["x"] = measure(42)
    second = PCBMechanicalInput.from_payload(changed)
    first_base, first_lid = JointAgent().pcb_two_piece_enclosure(first)
    second_base, _ = JointAgent().pcb_two_piece_enclosure(second)
    assert validate_printability(first_base)["printable"]
    assert validate_printability(first_lid)["printable"]
    assert first_base.solid().Volume() != second_base.solid().Volume()
