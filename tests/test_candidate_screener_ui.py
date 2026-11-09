"""Guard against Streamlit magic displaying raw DeltaGenerator objects."""
import ast
from pathlib import Path


PAGE = Path(__file__).resolve().parents[1] / "pages" / "1_수급_전환_검색.py"


def test_progress_update_is_not_a_bare_conditional_expression():
    tree = ast.parse(PAGE.read_text(encoding="utf-8"))
    suspicious = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Expr)
        and isinstance(node.value, ast.IfExp)
        and any(
            isinstance(child, ast.Call)
            and isinstance(child.func, ast.Attribute)
            and child.func.attr == "progress"
            for child in ast.walk(node.value)
        )
    ]
    assert not suspicious, "Streamlit magic will render returned DeltaGenerator"


def test_progress_update_is_an_assignment_and_still_shows_counter():
    tree = ast.parse(PAGE.read_text(encoding="utf-8"))
    progress_assignments = [
        node for node in ast.walk(tree)
        if isinstance(node, (ast.Assign, ast.AnnAssign))
        and isinstance(node.value, ast.Call)
        and isinstance(node.value.func, ast.Attribute)
        and node.value.func.attr == "progress"
    ]
    assert progress_assignments, "Keep user-visible progress without printing widget objects"
    source = PAGE.read_text(encoding="utf-8")
    assert '후보 {i}/{count}종목 확인' in source
