from ai_cad_designer.repair import RepairIssue, run_bounded_repair


def test_bounded_repair_records_and_resolves_allowed_wall_change():
    wall_issue = RepairIssue("wall_too_thin", "wall below nozzle limit", ("wall_mm",))

    result = run_bounded_repair(
        {"wall_mm": 0.4},
        (wall_issue,),
        allowed_ranges={"wall_mm": (0.4, 3.0)},
        suggest=lambda issues, current: {"wall_mm": 0.8},
        evaluate=lambda parameters: () if parameters["wall_mm"] >= 0.8 else (wall_issue,),
    )

    assert result.status == "resolved"
    assert result.stop_reason == "all_constraints_passed"
    assert [item.number for item in result.iterations] == [0, 1]
    assert result.best_parameters == {"wall_mm": 0.8}


def test_bounded_repair_stops_for_hard_issue_without_changes():
    result = run_bounded_repair(
        {"wall_mm": 2.0},
        (RepairIssue("pcb_measurement_unconfirmed", "measure first"),),
        allowed_ranges={"wall_mm": (0.4, 3.0)},
        suggest=lambda issues, current: {"wall_mm": 2.5},
        evaluate=lambda parameters: (),
    )

    assert result.status == "stopped"
    assert result.stop_reason == "manual_measurement_or_hard_constraint"
    assert len(result.iterations) == 1


def test_bounded_repair_does_not_change_parameters_when_a_hard_issue_is_mixed_in():
    result = run_bounded_repair(
        {"wall_mm": 0.4},
        (
            RepairIssue("wall_too_thin", "wall below nozzle limit", ("wall_mm",)),
            RepairIssue("measurement_confirmation_required", "measure first"),
        ),
        allowed_ranges={"wall_mm": (0.4, 3.0)},
        suggest=lambda issues, current: {"wall_mm": 0.8},
        evaluate=lambda parameters: (),
    )

    assert result.stop_reason == "manual_measurement_or_hard_constraint"
    assert result.best_parameters == {"wall_mm": 0.4}


def test_bounded_repair_rejects_repeated_or_unapproved_suggestion():
    issue = RepairIssue("wall_too_thin", "wall below nozzle limit", ("wall_mm",))
    result = run_bounded_repair(
        {"wall_mm": 0.4},
        (issue,),
        allowed_ranges={"wall_mm": (0.4, 3.0)},
        suggest=lambda issues, current: {"wall_mm": 0.4},
        evaluate=lambda parameters: (issue,),
    )

    assert result.stop_reason == "duplicate_suggestion"


def test_bounded_repair_stops_cleanly_when_planner_or_validator_errors():
    issue = RepairIssue("wall_too_thin", "wall below nozzle limit", ("wall_mm",))
    common = {
        "initial_parameters": {"wall_mm": 0.4},
        "initial_issues": (issue,),
        "allowed_ranges": {"wall_mm": (0.4, 3.0)},
    }
    planner_failure = run_bounded_repair(
        **common,
        suggest=lambda issues, current: (_ for _ in ()).throw(TimeoutError()),
        evaluate=lambda parameters: (),
    )
    validation_failure = run_bounded_repair(
        **common,
        suggest=lambda issues, current: {"wall_mm": 0.8},
        evaluate=lambda parameters: (_ for _ in ()).throw(RuntimeError()),
    )

    assert planner_failure.stop_reason == "planner_error"
    assert validation_failure.stop_reason == "validation_error"
