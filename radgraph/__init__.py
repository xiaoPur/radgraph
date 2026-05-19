__all__ = [
    "RadGraph",
    "F1RadGraph",
    "get_radgraph_processed_annotations",
    "build_report_knowledge",
    "load_iuxray_reports",
    "parse_mesh_terms",
    "run_iuxray_extraction",
]


def __getattr__(name):
    if name in {"RadGraph", "F1RadGraph"}:
        from .radgraph import F1RadGraph, RadGraph

        return {"RadGraph": RadGraph, "F1RadGraph": F1RadGraph}[name]

    if name == "get_radgraph_processed_annotations":
        from .radgpt import get_radgraph_processed_annotations

        return get_radgraph_processed_annotations

    if name in {
        "build_report_knowledge",
        "load_iuxray_reports",
        "parse_mesh_terms",
        "run_iuxray_extraction",
    }:
        from .iuxray import (
            build_report_knowledge,
            load_iuxray_reports,
            parse_mesh_terms,
            run_iuxray_extraction,
        )

        return {
            "build_report_knowledge": build_report_knowledge,
            "load_iuxray_reports": load_iuxray_reports,
            "parse_mesh_terms": parse_mesh_terms,
            "run_iuxray_extraction": run_iuxray_extraction,
        }[name]

    raise AttributeError(f"module 'radgraph' has no attribute {name!r}")
