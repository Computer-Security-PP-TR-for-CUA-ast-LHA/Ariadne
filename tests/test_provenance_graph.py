"""Contract tests for the complete provenance graph subsystem."""
import json
from pathlib import Path
import tempfile
import unittest

from cua_guard.provenance import (
    DependencyGraph, EdgeType, NodeKind, ProvenanceError, ProvenanceRecorder,
    affected_node_ids, affected_subgraph, ancestors, build_dependency_graph,
    find_producing_step, read_json, topological_order, validate_graph,
    write_json, write_svg,
)
from cua_guard.recovery.adapters import snapshot_from_provenance
from cua_guard.recovery.contracts import RecoveryError, Version, digest
from cua_guard.recovery.graph import VersionGraph


def records():
    steps = [
        {'step_id': 's_read1', 'step_type': 'memory_read',
         'next_step_ids': ['s_claim'], 'used_ids': ['m_root']},
        {'step_id': 's_claim', 'step_type': 'claim',
         'next_step_ids': ['s_update'],
         'used_ids': ['s_read1', 'user_input_1']},
        {'step_id': 's_update', 'step_type': 'memory_update',
         'next_step_ids': ['s_delete'], 'used_ids': ['m_root'],
         'generated_memory_ids': ['m_new'],
         'invalidated_memory_ids': ['m_root']},
        {'step_id': 's_delete', 'step_type': 'memory_delete',
         'next_step_ids': ['s_consolidate'],
         'invalidated_memory_ids': ['m_old']},
        {'step_id': 's_consolidate', 'step_type': 'memory_consolidate',
         'next_step_ids': ['s_read2'], 'used_ids': ['m_new'],
         'generated_memory_ids': ['m_cons'],
         'invalidated_memory_ids': ['m_new']},
        {'step_id': 's_read2', 'step_type': 'memory_read'},
    ]
    memories = [
        {'memory_id': 'm_root', 'status': 'active'},
        {'memory_id': 'm_old', 'status': 'superseded'},
        {'memory_id': 'm_new', 'status': 'active',
         'derived_from': ['m_root'], 'supersedes': 'm_old'},
        {'memory_id': 'm_cons', 'status': 'active',
         'derived_from': ['m_new']},
    ]
    return steps, memories, ['first request', 'second request']


def graph():
    return build_dependency_graph('task-1', *records())


class CompleteGraphTests(unittest.TestCase):
    def test_builder_emits_three_node_kinds_and_all_ten_edges(self):
        built = graph()
        self.assertEqual(
            {node.node_kind for node in built.nodes.values()},
            set(NodeKind),
        )
        labels = {
            label
            for destinations in built.forward_edges.values()
            for edge_labels in destinations.values()
            for label in edge_labels
        }
        self.assertEqual(labels, {edge.value for edge in EdgeType})
        self.assertEqual(
            built.edge_types('s_read1', 's_claim'), {'chain', 'cite'},
        )
        self.assertEqual(built.step_turn['s_read1'], 1)
        self.assertEqual(built.step_turn['s_read2'], 2)
        self.assertEqual(built.n_turns, 2)
        self.assertTrue(validate_graph(built).valid)

    def test_queries_are_typed_deterministic_and_chain_safe(self):
        built = graph()
        reached = affected_node_ids(built, 'm_root')
        self.assertIn('m_new', reached)
        self.assertIn('m_cons', reached)
        self.assertNotIn('s_delete', reached)  # only a chain path from s_update
        self.assertEqual(len(reached), len(set(reached)))
        self.assertIn(
            'm_root',
            ancestors(built, ('m_cons',), edge_types={'derive'}),
        )
        self.assertEqual(find_producing_step(built, 'm_new'), 's_update')
        order = topological_order(built)
        self.assertLess(order.index('s_update'), order.index('m_new'))
        sliced = affected_subgraph(built, 'm_root')
        self.assertIn('m_root', sliced.nodes)
        self.assertNotIn('m_old', sliced.nodes)

    def test_missing_reference_is_visible_and_fails_validation(self):
        steps, memories, session = records()
        steps[0]['used_ids'].append('m_missing')
        built = build_dependency_graph('task-1', steps, memories, session)
        self.assertEqual(built.coverage, 'partial')
        self.assertTrue(any('m_missing' in ref for ref in built.missing_refs))
        report = validate_graph(built)
        self.assertFalse(report.valid)
        with self.assertRaisesRegex(ProvenanceError, 'incomplete_graph'):
            report.raise_for_errors()

    def test_json_roundtrip_and_svg_export(self):
        built = graph()
        with tempfile.TemporaryDirectory() as directory:
            json_path = write_json(built, Path(directory) / 'graph.json')
            loaded = read_json(json_path)
            self.assertEqual(loaded.to_dict(), built.to_dict())
            svg_path = write_svg(
                built, Path(directory) / 'graph.svg',
                roots={'m_root'}, affected=set(affected_node_ids(built, 'm_root')),
            )
            svg = svg_path.read_text(encoding='utf-8')
            self.assertIn('aria-label="Provenance graph task-1"', svg)
            self.assertIn('derive', svg)
            self.assertIn('m_root', svg)

    def test_deserialization_recomputes_semantic_type(self):
        payload = graph().to_dict()
        payload['nodes']['s_claim']['semantic_type'] = 'tool_action'
        loaded = DependencyGraph.from_dict(json.loads(json.dumps(payload)))
        self.assertEqual(loaded.nodes['s_claim'].semantic_type, 'claim')

    def test_documented_ten_edge_fixture_is_valid(self):
        fixture = (
            Path(__file__).parents[1] / 'docs' / 'provenance' / 'fixtures'
            / 'complete-ten-edge.json'
        )
        loaded = read_json(fixture)
        labels = {
            label
            for destinations in loaded.forward_edges.values()
            for edge_labels in destinations.values()
            for label in edge_labels
        }
        self.assertEqual(labels, {edge.value for edge in EdgeType})

    def test_recorder_builds_the_same_graph_contract(self):
        recorder = ProvenanceRecorder('recorded-task')
        recorder.record_user_input('remember this')
        recorder.record_step(
            's_read', 'memory_read', used_ids=('m_seed',),
            next_step_ids=('s_write',),
        )
        recorder.record_step(
            's_write', 'memory_write', used_ids=('m_seed',),
            generated_memory_ids=('m_copy',),
        )
        recorder.record_memory('m_seed')
        recorder.record_memory('m_copy', derived_from=('m_seed',))
        built = recorder.build()
        self.assertTrue(validate_graph(built).valid)
        with self.assertRaisesRegex(ProvenanceError, 'recorder_sealed'):
            recorder.record_user_input('late')


class RecoveryProjectionTests(unittest.TestCase):
    def versions(self):
        return (
            Version('m_root', 'memory/root', 'root', digest('root'), ('external',)),
            Version('m_old', 'memory/old', 'old', digest('old'), ('external',)),
            Version('m_new', 'memory/new', 'new', digest('new'), ('external',)),
            Version('m_cons', 'memory/cons', 'cons', digest('cons'), ('external',)),
        )

    def test_projection_preserves_recovery_schema(self):
        snapshot = snapshot_from_provenance(
            'scope-1', 7, self.versions(), graph(),
        )
        VersionGraph(snapshot)
        nodes = {version.version_id: version for version in snapshot.versions}
        self.assertEqual(nodes['m_new'].parents, ('m_root',))
        self.assertEqual(nodes['m_cons'].parents, ('m_new',))
        self.assertIn(
            ('m_old', 'm_new', 'supersedes'),
            {(edge.source, edge.target, edge.kind) for edge in snapshot.edges},
        )

    def test_projection_rejects_missing_memory_version(self):
        with self.assertRaisesRegex(RecoveryError, 'provenance_version_mismatch'):
            snapshot_from_provenance(
                'scope-1', 7, self.versions()[:-1], graph(),
            )


if __name__ == '__main__':
    unittest.main()
