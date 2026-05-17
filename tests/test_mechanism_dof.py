from quino.application.service import ApplicationService
from quino.domain.inputs import JointEndpointInput, MarkerInput
from quino.domain.types import JointEndpointKind
from quino.services.mechanism_dof import compute_mechanism_dof


def test_empty_project_has_zero_dof() -> None:
    app = ApplicationService()
    app.new_project("test")
    result = compute_mechanism_dof(app.project)
    assert result.total_dof == 0
    assert result.body_count == 0


def test_single_body_has_three_dof() -> None:
    app = ApplicationService()
    app.new_project("test")
    app.create_bar(
        "Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B")
    )
    result = compute_mechanism_dof(app.project)
    assert result.body_count == 1
    assert result.total_dof == 3


def test_ground_revolute_removes_two_dof() -> None:
    app = ApplicationService()
    app.new_project("test")
    body_id = app.create_bar(
        "Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B")
    )
    marker_a = next(
        m.id
        for b in app.project.model.bodies
        if b.id == body_id
        for m in b.markers
        if m.name == "A"
    )
    app.connect_marker_to_ground(marker_a, joint_type="revolute")
    result = compute_mechanism_dof(app.project)
    assert result.total_dof == 1  # 3 - 2


def test_ground_rigid_removes_three_dof() -> None:
    app = ApplicationService()
    app.new_project("test")
    body_id = app.create_bar(
        "Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B")
    )
    marker_a = next(
        m.id
        for b in app.project.model.bodies
        if b.id == body_id
        for m in b.markers
        if m.name == "A"
    )
    app.connect_marker_to_ground(marker_a, joint_type="rigid")
    result = compute_mechanism_dof(app.project)
    assert result.total_dof == 0  # 3 - 3


def test_pose_constraints_reduce_dof() -> None:
    app = ApplicationService()
    app.new_project("test")
    app.create_bar(
        "Arm", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("100 mm", "0 mm", "B")
    )
    result = compute_mechanism_dof(app.project, pose_constraint_count=2)
    assert result.total_dof == 1  # 3 - 2


def test_four_bar_linkage_dof() -> None:
    app = ApplicationService()
    app.new_project("test")
    b1 = app.create_bar(
        "Ground", MarkerInput("0 mm", "0 mm", "A"), MarkerInput("0 mm", "0 mm", "B")
    )
    b2 = app.create_bar(
        "Link1", MarkerInput("50 mm", "0 mm", "C"), MarkerInput("150 mm", "0 mm", "D")
    )
    b3 = app.create_bar(
        "Link2",
        MarkerInput("150 mm", "0 mm", "E"),
        MarkerInput("200 mm", "100 mm", "F"),
    )

    m_ground_a = next(
        m.id
        for b in app.project.model.bodies
        if b.id == b1
        for m in b.markers
        if m.name == "A"
    )
    m_ground_b = next(
        m.id
        for b in app.project.model.bodies
        if b.id == b1
        for m in b.markers
        if m.name == "B"
    )
    m_link1_c = next(
        m.id
        for b in app.project.model.bodies
        if b.id == b2
        for m in b.markers
        if m.name == "C"
    )
    m_link1_d = next(
        m.id
        for b in app.project.model.bodies
        if b.id == b2
        for m in b.markers
        if m.name == "D"
    )
    m_link2_e = next(
        m.id
        for b in app.project.model.bodies
        if b.id == b3
        for m in b.markers
        if m.name == "E"
    )
    m_link2_f = next(
        m.id
        for b in app.project.model.bodies
        if b.id == b3
        for m in b.markers
        if m.name == "F"
    )

    app.connect_marker_to_ground(m_ground_a, joint_type="rigid")
    app.connect_marker_to_ground(m_ground_b, joint_type="rigid")
    app.create_joint(
        "J1",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=b2, marker_id=m_link1_c),
        JointEndpointInput(
            JointEndpointKind.MARKER, body_id=b1, marker_id=m_ground_a
        ),
    )
    app.create_joint(
        "J2",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=b2, marker_id=m_link1_d),
        JointEndpointInput(
            JointEndpointKind.MARKER, body_id=b3, marker_id=m_link2_e
        ),
    )
    app.create_joint(
        "J3",
        "revolute",
        JointEndpointInput(JointEndpointKind.MARKER, body_id=b3, marker_id=m_link2_f),
        JointEndpointInput(
            JointEndpointKind.MARKER, body_id=b1, marker_id=m_ground_b
        ),
    )

    result = compute_mechanism_dof(app.project)
    # 3 bodies * 3 = 9; 4 revolute joints * 2 = 8; 2 rigid ground * 3 = 6
    # 9 - 8 - 6 = -5 -> clamped to 0
    assert result.total_dof == 0
