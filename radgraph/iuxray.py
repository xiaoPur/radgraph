import argparse
import csv
import json
import re
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional


LATERALITY_TERMS = {"left", "right", "bilateral", "bilaterally"}

SEVERITY_TERMS = {
    "borderline",
    "trace",
    "tiny",
    "small",
    "minimal",
    "mild",
    "slight",
    "moderate",
    "large",
    "severe",
    "massive",
    "marked",
}

ANATOMY_TERMS = {
    "abdomen",
    "apex",
    "apices",
    "aorta",
    "base",
    "bases",
    "bone",
    "bronchial",
    "cardiophrenic angle",
    "cervical vertebrae",
    "chest",
    "clavicle",
    "costophrenic angle",
    "diaphragm",
    "heart",
    "hilum",
    "hilar",
    "lingula",
    "lower lobe",
    "lung",
    "lungs",
    "mediastinum",
    "middle lobe",
    "pleura",
    "ribs",
    "spine",
    "stomach",
    "thoracic aorta",
    "thoracic vertebrae",
    "upper lobe",
    "vertebrae",
}


def clean_report_text(text: Optional[str]) -> str:
    """Normalize IU-Xray report text while preserving radiology meaning."""
    if text is None:
        return ""

    cleaned = str(text)
    cleaned = cleaned.replace("\\n", " ").replace("\\f", " ").replace("\n", " ")
    cleaned = re.sub(r"\bx-XXXX\b", "x-ray", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"\bXXXX[-\s]?year[-\s]?old\b", "patient", cleaned, flags=re.IGNORECASE
    )
    cleaned = re.sub(r"\bNo\s+XXXX\s+of\b", "No evidence of", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"\bXXXX\b", "", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    cleaned = re.sub(r"\s+([,.;:])", r"\1", cleaned)
    return cleaned.strip()


def parse_semicolon_terms(value: Optional[str], drop_normal: bool = True) -> List[str]:
    if value is None:
        return []
    terms = []
    for term in str(value).split(";"):
        term = term.strip()
        if not term:
            continue
        if drop_normal and term.lower() == "normal":
            continue
        terms.append(term)
    return terms


def parse_mesh_terms(mesh_value: Optional[str]) -> List[Dict[str, object]]:
    parsed_terms = []
    for raw_term in parse_semicolon_terms(mesh_value):
        parts = [part.strip() for part in raw_term.split("/") if part.strip()]
        if not parts:
            continue

        finding = parts[0]
        attributes = parts[1:]
        anatomy = []
        laterality = []
        severity = []
        modifiers = []

        for attr in attributes:
            attr_key = attr.lower()
            if attr_key in LATERALITY_TERMS:
                laterality.append(attr)
            elif attr_key in SEVERITY_TERMS:
                severity.append(attr)
            elif attr_key in ANATOMY_TERMS:
                anatomy.append(attr)
            else:
                modifiers.append(attr)

        parsed_terms.append(
            {
                "raw": raw_term,
                "finding": finding,
                "attributes": attributes,
                "anatomy": anatomy,
                "laterality": laterality,
                "severity": severity,
                "modifiers": modifiers,
            }
        )
    return parsed_terms


def slugify(value: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", value.lower()).strip("_")
    return slug or "unknown"


def load_projection_index(projections_csv: Optional[Path]) -> Dict[str, Dict[str, List]]:
    if projections_csv is None:
        return {}

    projections_csv = Path(projections_csv)
    if not projections_csv.exists():
        return {}

    index: Dict[str, Dict[str, List]] = {}
    with projections_csv.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            uid = str(row.get("uid", "")).strip()
            if not uid:
                continue

            filename = str(row.get("filename", "")).strip()
            projection = str(row.get("projection", "")).strip()
            entry = index.setdefault(uid, {"all": [], "frontal": [], "lateral": []})
            entry["all"].append({"filename": filename, "projection": projection})

            projection_key = projection.lower()
            if "lateral" in projection_key:
                entry["lateral"].append(filename)
            elif any(name in projection_key for name in ("frontal", "pa", "ap")):
                entry["frontal"].append(filename)

    return index


def make_text_sections(row: Dict[str, str]) -> List[Dict[str, str]]:
    sections = []
    seen_texts = set()
    for section_name in ("findings", "impression"):
        text = clean_report_text(row.get(section_name))
        if not text or text in seen_texts:
            continue
        seen_texts.add(text)
        sections.append({"name": section_name, "text": text})
    return sections


def load_iuxray_reports(
    reports_csv: Path,
    projections_csv: Optional[Path] = None,
    limit: Optional[int] = None,
) -> List[Dict]:
    reports_csv = Path(reports_csv)
    projection_index = load_projection_index(projections_csv)
    reports = []

    with reports_csv.open("r", newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            uid = str(row.get("uid", "")).strip()
            if not uid:
                continue

            reports.append(
                {
                    "uid": uid,
                    "image": clean_report_text(row.get("image")),
                    "indication": clean_report_text(row.get("indication")),
                    "comparison": clean_report_text(row.get("comparison")),
                    "problems": parse_semicolon_terms(row.get("Problems")),
                    "mesh": parse_mesh_terms(row.get("MeSH")),
                    "images": projection_index.get(
                        uid, {"all": [], "frontal": [], "lateral": []}
                    ),
                    "text_sections": make_text_sections(row),
                }
            )

            if limit is not None and len(reports) >= limit:
                break

    return reports


def add_node(nodes: List[Dict], node_ids: set, node: Dict) -> None:
    if node["id"] in node_ids:
        return
    node_ids.add(node["id"])
    nodes.append(node)


def add_edge(edges: List[Dict], edge_ids: set, edge: Dict) -> None:
    edge_key = (
        edge["source"],
        edge["relation"],
        edge["target"],
        edge.get("section"),
        edge.get("evidence"),
    )
    if edge_key in edge_ids:
        return
    edge_ids.add(edge_key)
    edges.append(edge)


def build_report_knowledge(report: Dict, section_results: List[Dict]) -> Dict:
    uid = report["uid"]
    nodes: List[Dict] = []
    edges: List[Dict] = []
    node_ids = set()
    edge_ids = set()
    report_id = f"report:{uid}"

    add_node(nodes, node_ids, {"id": report_id, "type": "report", "uid": uid})

    for problem in report.get("problems", []):
        problem_id = f"problem:{slugify(problem)}"
        add_node(nodes, node_ids, {"id": problem_id, "type": "problem", "name": problem})
        add_edge(edges, edge_ids, {"source": report_id, "relation": "has_problem", "target": problem_id})

    for mesh_term in report.get("mesh", []):
        mesh_id = f"mesh:{slugify(mesh_term['raw'])}"
        add_node(nodes, node_ids, {"id": mesh_id, "type": "mesh", **mesh_term})
        add_edge(edges, edge_ids, {"source": report_id, "relation": "has_mesh", "target": mesh_id})

    for image in report.get("images", {}).get("all", []):
        filename = image.get("filename", "")
        if not filename:
            continue
        image_id = f"image:{slugify(filename)}"
        add_node(
            nodes,
            node_ids,
            {
                "id": image_id,
                "type": "image",
                "filename": filename,
                "projection": image.get("projection", ""),
            },
        )
        add_edge(edges, edge_ids, {"source": report_id, "relation": "linked_image", "target": image_id})

    for section_result in section_results:
        section_name = section_result["name"]
        section_id = f"section:{uid}:{slugify(section_name)}"
        add_node(
            nodes,
            node_ids,
            {
                "id": section_id,
                "type": "section",
                "name": section_name,
                "text": section_result.get("text", ""),
            },
        )
        add_edge(edges, edge_ids, {"source": report_id, "relation": "has_section", "target": section_id})

        for ix, observation in enumerate(section_result.get("processed_annotations", [])):
            observation_id = f"observation:{uid}:{slugify(section_name)}:{ix}"
            add_node(
                nodes,
                node_ids,
                {
                    "id": observation_id,
                    "type": "observation",
                    "name": observation.get("observation"),
                    "tags": observation.get("tags", []),
                    "section": section_name,
                    "start_ix": observation.get("observation_start_ix", []),
                    "end_ix": observation.get("observation_end_ix", []),
                },
            )
            add_edge(
                edges,
                edge_ids,
                {"source": section_id, "relation": "has_observation", "target": observation_id},
            )
            add_edge(
                edges,
                edge_ids,
                {"source": report_id, "relation": "has_observation", "target": observation_id},
            )

            for anatomy in observation.get("located_at") or []:
                anatomy_id = f"anatomy:{slugify(anatomy)}"
                add_node(nodes, node_ids, {"id": anatomy_id, "type": "anatomy", "name": anatomy})
                add_edge(
                    edges,
                    edge_ids,
                    {
                        "source": observation_id,
                        "relation": "located_at",
                        "target": anatomy_id,
                        "section": section_name,
                    },
                )

            for suggestion in observation.get("suggestive_of") or []:
                suggestion_id = f"suggestion:{slugify(suggestion)}"
                add_node(
                    nodes,
                    node_ids,
                    {"id": suggestion_id, "type": "suggestion", "name": suggestion},
                )
                add_edge(
                    edges,
                    edge_ids,
                    {
                        "source": observation_id,
                        "relation": "suggestive_of",
                        "target": suggestion_id,
                        "section": section_name,
                    },
                )

    return {
        "uid": uid,
        "image": report.get("image", ""),
        "indication": report.get("indication", ""),
        "comparison": report.get("comparison", ""),
        "problems": report.get("problems", []),
        "mesh": report.get("mesh", []),
        "images": report.get("images", {"all": [], "frontal": [], "lateral": []}),
        "sections": section_results,
        "knowledge_graph": {"nodes": nodes, "edges": edges},
    }


def default_processor(annotations: Dict) -> Dict:
    from radgraph import get_radgraph_processed_annotations

    return get_radgraph_processed_annotations(annotations)


def build_radgraph(
    model_type: str,
    cuda: Optional[int] = None,
    model_cache_dir: Optional[str] = None,
    tokenizer_cache_dir: Optional[str] = None,
):
    from radgraph import RadGraph

    kwargs = {"model_type": model_type}
    if cuda is not None:
        kwargs["cuda"] = cuda
    if model_cache_dir is not None:
        kwargs["model_cache_dir"] = model_cache_dir
    if tokenizer_cache_dir is not None:
        kwargs["tokenizer_cache_dir"] = tokenizer_cache_dir
    return RadGraph(**kwargs)


def processed_uids_from_jsonl(output_jsonl: Path) -> set:
    if not output_jsonl.exists():
        return set()
    processed = set()
    with output_jsonl.open("r", encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            uid = item.get("uid")
            if uid:
                processed.add(str(uid))
    return processed


def run_iuxray_extraction(
    reports_csv: Path,
    output_jsonl: Path,
    projections_csv: Optional[Path] = None,
    model_type: str = "modern-radgraph-xl",
    cuda: Optional[int] = None,
    model_cache_dir: Optional[str] = None,
    tokenizer_cache_dir: Optional[str] = None,
    limit: Optional[int] = None,
    resume: bool = False,
    continue_on_error: bool = True,
    radgraph=None,
    processor: Callable[[Dict], Dict] = default_processor,
) -> Dict[str, int]:
    reports = load_iuxray_reports(reports_csv, projections_csv=projections_csv, limit=limit)
    output_jsonl = Path(output_jsonl)
    output_jsonl.parent.mkdir(parents=True, exist_ok=True)
    already_done = processed_uids_from_jsonl(output_jsonl) if resume else set()

    if radgraph is None:
        radgraph = build_radgraph(
            model_type=model_type,
            cuda=cuda,
            model_cache_dir=model_cache_dir,
            tokenizer_cache_dir=tokenizer_cache_dir,
        )

    mode = "a" if resume else "w"
    stats = {"total_reports": len(reports), "processed_reports": 0, "skipped_reports": 0}

    with output_jsonl.open(mode, encoding="utf-8") as out:
        for report in reports:
            if report["uid"] in already_done:
                stats["skipped_reports"] += 1
                continue
            if not report["text_sections"]:
                stats["skipped_reports"] += 1
                continue

            section_results = []
            for section in report["text_sections"]:
                try:
                    annotations = radgraph([section["text"]])
                    processed = processor(annotations)
                    section_results.append(
                        {
                            "name": section["name"],
                            "text": section["text"],
                            "radgraph_annotations": annotations,
                            "processed_annotations": processed.get("processed_annotations", []),
                        }
                    )
                except Exception as exc:
                    if not continue_on_error:
                        raise
                    section_results.append(
                        {
                            "name": section["name"],
                            "text": section["text"],
                            "error": str(exc),
                            "radgraph_annotations": None,
                            "processed_annotations": [],
                        }
                    )

            knowledge = build_report_knowledge(report, section_results)
            out.write(json.dumps(knowledge, ensure_ascii=False) + "\n")
            out.flush()
            stats["processed_reports"] += 1

    return stats


def parse_args(argv: Optional[Iterable[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Extract IU-Xray report knowledge with RadGraph.")
    parser.add_argument("--reports-csv", required=True, help="Path to indiana_reports.csv")
    parser.add_argument("--output-jsonl", required=True, help="Output JSONL path")
    parser.add_argument("--projections-csv", help="Optional path to indiana_projections.csv")
    parser.add_argument("--model-type", default="modern-radgraph-xl")
    parser.add_argument("--cuda", type=int, default=None, help="GPU id, or -1 for CPU")
    parser.add_argument("--model-cache-dir", default=None)
    parser.add_argument("--tokenizer-cache-dir", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--stop-on-error", action="store_true")
    return parser.parse_args(argv)


def main(argv: Optional[Iterable[str]] = None) -> int:
    args = parse_args(argv)
    stats = run_iuxray_extraction(
        reports_csv=Path(args.reports_csv),
        projections_csv=Path(args.projections_csv) if args.projections_csv else None,
        output_jsonl=Path(args.output_jsonl),
        model_type=args.model_type,
        cuda=args.cuda,
        model_cache_dir=args.model_cache_dir,
        tokenizer_cache_dir=args.tokenizer_cache_dir,
        limit=args.limit,
        resume=args.resume,
        continue_on_error=not args.stop_on_error,
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
