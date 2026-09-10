from threading import Event

from ai_cad_designer.jobs import LocalJobManager


def test_jobs_deduplicate_active_payload_and_capture_result():
    manager = LocalJobManager()
    gate = Event()
    first = manager.submit({"request": "pcb"}, lambda: (gate.wait(), {"ok": True})[1])
    same = manager.submit({"request": "pcb"}, lambda: {"wrong": True})
    assert first.job_id == same.job_id
    gate.set()
    assert first.future.result(timeout=2) is None
    assert manager.get(first.job_id).to_dict()["result"] == {"ok": True}


def test_jobs_cancel_queued_work_without_claiming_it_completed():
    manager = LocalJobManager()
    gate = Event()
    running = manager.submit({"request": "running"}, lambda: gate.wait())
    queued = manager.submit({"request": "queued"}, lambda: {"ok": True})
    assert manager.cancel(queued.job_id).status == "cancelled"
    gate.set()
    running.future.result(timeout=2)
    assert manager.get(queued.job_id).status == "cancelled"


def test_running_job_honors_cancel_request_after_current_step():
    manager = LocalJobManager()
    started = Event()
    gate = Event()
    job = manager.submit(
        {"request": "running"},
        lambda: (started.set(), gate.wait(), {"partial": True})[2],
    )
    assert started.wait(timeout=2)
    assert manager.cancel(job.job_id).status == "cancel_requested"
    gate.set()
    job.future.result(timeout=2)
    assert manager.get(job.job_id).to_dict()["status"] == "cancelled"
    assert manager.get(job.job_id).result is None
