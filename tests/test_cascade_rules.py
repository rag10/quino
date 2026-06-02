from quino.services.cascade_rules import should_cascade_value


def test_cascades_when_child_matches_old_parent():
    assert should_cascade_value(old_parent=5, child=5) is True


def test_does_not_cascade_when_child_diverges():
    assert should_cascade_value(old_parent=5, child=2) is False


def test_cascades_for_equal_expression_objects():
    class Expr:
        def __init__(self, e): self.e = e
        def __eq__(self, other): return isinstance(other, Expr) and self.e == other.e
    assert should_cascade_value(old_parent=Expr("9.81"), child=Expr("9.81")) is True
    assert should_cascade_value(old_parent=Expr("9.81"), child=Expr("0")) is False
