from quino.application.service import ApplicationService


def test_add_block_creates_block_in_diagram():
    app = ApplicationService()
    app.new_workspace("test")
    app.add_block(block_type="Constant", name="Source", position=(0.0, 0.0))
    model = app.project.model
    assert model.control_graph is not None
    assert any(b.block_type == "Constant" for b in model.control_graph.instances.values())


def test_delete_block_removes_from_diagram():
    app = ApplicationService()
    app.new_workspace("test")
    app.add_block(block_type="Constant", name="Source", position=(0.0, 0.0))
    model = app.project.model
    block_id = next(iter(model.control_graph.instances))
    app.remove_block(block_id)
    assert block_id not in model.control_graph.instances
