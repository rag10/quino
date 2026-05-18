from quino import ApplicationService


def test_create_and_delete_parameter_roundtrip():
    svc = ApplicationService()
    svc.new_project("T")
    pid = svc.create_parameter("L", "100 mm", "mm", "")
    assert any(p.id == pid for p in svc.project.parameters)
    svc.delete_parameter(pid)
    assert not any(p.id == pid for p in svc.project.parameters)


def test_update_parameter_definition():
    svc = ApplicationService()
    svc.new_project("T")
    pid = svc.create_parameter("L", "100 mm", "mm", "")
    svc.update_parameter_definition(pid, "L", "200 mm", "mm", "")
    p = next(p for p in svc.project.parameters if p.id == pid)
    assert "200" in p.expression
