"""The committed concept lattices (lattices/<name>/) load into cuberag.Lattice and agree with nodes.csv.

Needs only the public CSVs in lattices/, not data/.
"""
import json
from pathlib import Path

import pandas as pd
import pytest

from cuberag.lattice import Lattice

LATTICES = Path(__file__).resolve().parents[1] / "lattices"
NAMES = sorted(p.name for p in LATTICES.iterdir() if (p / "edges.csv").exists())


def load(name):
    nodes = pd.read_csv(LATTICES / name / "nodes.csv", dtype={"node_id": str})
    edges = pd.read_csv(LATTICES / name / "edges.csv", dtype=str)
    lat = Lattice(zip(edges["child"], edges["parent"]), top="TOP", concepts=nodes["node_id"])
    return nodes, edges, lat


def test_lattices_exist():
    assert {"maude_device", "maude_patient", "asrs_anomaly"} <= set(NAMES)


@pytest.mark.parametrize("name", NAMES)
def test_loads_and_matches_nodes(name):
    nodes, edges, lat = load(name)
    assert lat.nodes == frozenset(nodes["node_id"])
    assert lat.down("TOP") == lat.nodes                    # everything rolls up to TOP
    assert set(edges["placement"]) <= {"primary", "secondary"}
    prim = edges[edges["placement"] == "primary"]
    assert prim["child"].is_unique and set(prim["child"]) == set(nodes["node_id"]) - {"TOP"}
    assert json.loads((LATTICES / name / "checks.json").read_text())["valid"]


@pytest.mark.parametrize("name", NAMES)
def test_every_edge_is_an_order_relation(name):
    _, edges, lat = load(name)
    for c, p in zip(edges["child"], edges["parent"]):
        assert lat.leq(c, p) and not lat.leq(p, c)


def test_patient_lattice_is_a_dag_with_imdrf_secondary_placements():
    _, edges, lat = load("maude_patient")
    assert (edges["placement"] == "secondary").sum() > 0
    assert lat.leq("E0116", "E2330")                       # Headache <= Pain (secondary placement)
    assert lat.leq("E0116", "E01")                         # and <= Nervous System (primary)
    assert "E0116" in lat.down("E2330")


def test_mapping_targets_are_nodes():
    for name in NAMES:
        nodes = set(pd.read_csv(LATTICES / name / "nodes.csv", dtype=str)["node_id"])
        m = pd.read_csv(LATTICES / name / "mapping.csv", dtype=str)
        assert m["node_id"].isin(nodes).all(), name
