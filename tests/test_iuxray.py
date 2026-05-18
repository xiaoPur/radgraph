import csv
import importlib.util
import json
from pathlib import Path


def load_iuxray_module():
    module_path = Path(__file__).resolve().parents[1] / "radgraph" / "iuxray.py"
    spec = importlib.util.spec_from_file_location("iuxray_module", module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def write_csv(path, fieldnames, rows):
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_parse_mesh_terms_extracts_attributes():
    iuxray = load_iuxray_module()

    parsed = iuxray.parse_mesh_terms(
        "Opacity/lung/apex/left/irregular;Pleural Effusion/right/small;normal"
    )

    assert parsed == [
        {
            "raw": "Opacity/lung/apex/left/irregular",
            "finding": "Opacity",
            "attributes": ["lung", "apex", "left", "irregular"],
            "anatomy": ["lung", "apex"],
            "laterality": ["left"],
            "severity": [],
            "modifiers": ["irregular"],
        },
        {
            "raw": "Pleural Effusion/right/small",
            "finding": "Pleural Effusion",
            "attributes": ["right", "small"],
            "anatomy": [],
            "laterality": ["right"],
            "severity": ["small"],
            "modifiers": [],
        },
    ]


def test_load_reports_creates_sections_and_links_projection_images(tmp_path):
    iuxray = load_iuxray_module()
    reports_csv = tmp_path / "indiana_reports.csv"
    projections_csv = tmp_path / "indiana_projections.csv"

    write_csv(
        reports_csv,
        [
            "uid",
            "MeSH",
            "Problems",
            "image",
            "indication",
            "comparison",
            "findings",
            "impression",
        ],
        [
            {
                "uid": "1",
                "MeSH": "Opacity/lung/base/left/mild",
                "Problems": "Opacity;Pulmonary Atelectasis",
                "image": "Xray Chest PA and Lateral",
                "indication": "Evaluate for infection",
                "comparison": "None.",
                "findings": "No XXXX of pneumothorax. Mild left basilar opacity.",
                "impression": "Possible atelectasis.",
            }
        ],
    )
    write_csv(
        projections_csv,
        ["uid", "filename", "projection"],
        [
            {"uid": "1", "filename": "1_frontal.png", "projection": "Frontal"},
            {"uid": "1", "filename": "1_lateral.png", "projection": "Lateral"},
        ],
    )

    reports = iuxray.load_iuxray_reports(reports_csv, projections_csv)

    assert len(reports) == 1
    report = reports[0]
    assert report["uid"] == "1"
    assert report["problems"] == ["Opacity", "Pulmonary Atelectasis"]
    assert report["mesh"][0]["finding"] == "Opacity"
    assert report["text_sections"] == [
        {
            "name": "findings",
            "text": "No evidence of pneumothorax. Mild left basilar opacity.",
        },
        {"name": "impression", "text": "Possible atelectasis."},
    ]
    assert report["images"]["frontal"] == ["1_frontal.png"]
    assert report["images"]["lateral"] == ["1_lateral.png"]


def test_build_report_knowledge_merges_labels_sections_and_images():
    iuxray = load_iuxray_module()
    report = {
        "uid": "7",
        "image": "Xray Chest PA and Lateral",
        "indication": "Dyspnea",
        "comparison": "None",
        "problems": ["Pleural Effusion"],
        "mesh": [
            {
                "raw": "Pleural Effusion/right/small",
                "finding": "Pleural Effusion",
                "attributes": ["right", "small"],
                "anatomy": [],
                "laterality": ["right"],
                "severity": ["small"],
                "modifiers": [],
            }
        ],
        "images": {
            "all": [{"filename": "7_frontal.png", "projection": "Frontal"}],
            "frontal": ["7_frontal.png"],
            "lateral": [],
        },
        "text_sections": [
            {"name": "impression", "text": "Small right pleural effusion."}
        ],
    }
    section_results = [
        {
            "name": "impression",
            "text": "Small right pleural effusion.",
            "radgraph_annotations": {"0": {"entities": {}}},
            "processed_annotations": [
                {
                    "observation": "small effusion",
                    "observation_start_ix": [0, 3],
                    "observation_end_ix": [0, 3],
                    "located_at": ["right pleural"],
                    "located_at_start_ix": [[1, 2]],
                    "tags": ["definitely present"],
                    "suggestive_of": None,
                }
            ],
        }
    ]

    knowledge = iuxray.build_report_knowledge(report, section_results)

    assert knowledge["uid"] == "7"
    assert knowledge["sections"][0]["processed_annotations"][0]["observation"] == "small effusion"
    edge_triples = {
        (edge["source"], edge["relation"], edge["target"])
        for edge in knowledge["knowledge_graph"]["edges"]
    }
    assert ("report:7", "has_problem", "problem:pleural_effusion") in edge_triples
    assert ("report:7", "has_mesh", "mesh:pleural_effusion_right_small") in edge_triples
    assert ("report:7", "linked_image", "image:7_frontal_png") in edge_triples
    assert (
        "observation:7:impression:0",
        "located_at",
        "anatomy:right_pleural",
    ) in edge_triples


def test_run_iuxray_extraction_writes_jsonl_with_fake_radgraph(tmp_path):
    iuxray = load_iuxray_module()
    reports_csv = tmp_path / "reports.csv"
    output_jsonl = tmp_path / "knowledge.jsonl"

    write_csv(
        reports_csv,
        [
            "uid",
            "MeSH",
            "Problems",
            "image",
            "indication",
            "comparison",
            "findings",
            "impression",
        ],
        [
            {
                "uid": "1",
                "MeSH": "Cardiomegaly/mild",
                "Problems": "Cardiomegaly",
                "image": "Chest",
                "indication": "Pain",
                "comparison": "",
                "findings": "Mild cardiomegaly.",
                "impression": "",
            },
            {
                "uid": "2",
                "MeSH": "normal",
                "Problems": "normal",
                "image": "Chest",
                "indication": "",
                "comparison": "",
                "findings": "",
                "impression": "",
            },
        ],
    )

    class FakeRadGraph:
        def __call__(self, texts):
            return {
                "0": {
                    "text": texts[0],
                    "entities": {
                        "1": {
                            "tokens": "cardiomegaly",
                            "label": "Observation::definitely present",
                            "start_ix": 1,
                            "end_ix": 1,
                            "relations": [],
                        }
                    },
                    "data_source": None,
                    "data_split": "inference",
                }
            }

    def fake_processor(_annotations):
        return {
            "processed_annotations": [
                {
                    "observation": "mild cardiomegaly",
                    "observation_start_ix": [0, 1],
                    "observation_end_ix": [0, 1],
                    "located_at": [],
                    "located_at_start_ix": [],
                    "tags": ["definitely present"],
                    "suggestive_of": None,
                }
            ]
        }

    stats = iuxray.run_iuxray_extraction(
        reports_csv=reports_csv,
        output_jsonl=output_jsonl,
        radgraph=FakeRadGraph(),
        processor=fake_processor,
    )

    lines = [json.loads(line) for line in output_jsonl.read_text(encoding="utf-8").splitlines()]
    assert stats == {"total_reports": 2, "processed_reports": 1, "skipped_reports": 1}
    assert len(lines) == 1
    assert lines[0]["uid"] == "1"
    assert lines[0]["sections"][0]["name"] == "findings"
    assert lines[0]["knowledge_graph"]["nodes"][0]["id"] == "report:1"
