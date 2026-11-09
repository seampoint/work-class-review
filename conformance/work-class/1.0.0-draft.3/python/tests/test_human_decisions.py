from __future__ import annotations

import base64
import copy
import json
from pathlib import Path
import sys
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'vendor'), str(ROOT.parent / 'review')]

from cdmo_fixture import cdmo_authority, cdmo_base, cdmo_trace
from authority_fixture import authority_specimen
from consumer import Consumer
from implementation import authority, completion, dispatch_gate, human_decisions, lifecycle, recovery, source_corrections, source_observations, work_class
from implementation.common import PIN, Refusal, canonical, digest


def leaf(request, index=0):
    return request['decision_bases'][index]['evidence']['authority_input']


def refresh_authenticated(request, kind, old_digest, record):
    row = next(row for row in request['host_selection']['authenticated_records'] if row['kind'] == kind and row['record_digest'] == old_digest)
    row['record_digest'] = digest('authority-' + kind.lower(), record)
    request['host_selection']['authenticated_records'].sort(key=canonical)


class HumanDecisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.supplied, cls.expected, _ = cdmo_authority()

    def supplied_input(self):
        return copy.deepcopy(self.supplied)

    def evaluate(self, request):
        return authority.evaluate_authority(request, PIN)

    def test_historical_signers_remain_evidence_and_outer_acts_stay_ordinary(self):
        request = self.supplied_input()
        result = self.evaluate(request)
        self.assertEqual(result, self.expected)
        for basis, row in zip(request['decision_bases'], result['decision_results']):
            own = basis['evidence']['authority_input']
            occupancy = next(item for item in own['occupancies'] if item['id'] == own['proposal']['executor']['occupancy'])
            self.assertLess(occupancy['validity']['valid_until'], own['clock']['instant'])
            self.assertEqual(row['result']['status'], 'EVIDENCE_VALID')
            self.assertNotIn('EXECUTOR_OCCUPANCY', {item['purpose'] for item in row['result']['checks']})
            self.assertNotIn(basis['evidence']['decision_act_digest'], result['act_digests'])

    def test_evidence_only_definition_can_read_back_but_cannot_execute(self):
        own = leaf(self.supplied_input())
        definition = {'schema': authority.AUTH_PREFIX + 'authority-definition', **{key: own[key] for key in ('source', 'work_class', 'envelope')}}
        self.assertEqual(authority.validate_definition(definition)['status'], 'ACCEPTED')
        artifact = {'specification_pin': PIN, 'kind': 'AUTHORITY_DEFINITION', 'artifact_bytes_base64': base64.b64encode(canonical(definition)).decode()}
        self.assertEqual(Consumer().readback(artifact)['status'], 'READBACK')
        result = Consumer().evaluate({'kind': 'AUTHORITY', 'request': own})
        self.assertEqual(result['code'], 'SCHEMA_INVALID')
        del own['work_class']['authority_profile']
        self.assertEqual(self.evaluate(own)['code'], 'DEPENDENCY_MISMATCH')

    def test_nested_decision_collection_is_rejected_by_closed_leaf_schema(self):
        request = self.supplied_input()
        leaf(request)['decision_bases'] = []
        self.assertEqual(self.evaluate(request)['code'], 'SCHEMA_INVALID')

    def test_parameterized_envelope_supports_exactly_one_operation(self):
        request, _ = authority_specimen(shared_budget=False)
        definition = {'schema': authority.AUTH_PREFIX + 'authority-definition', **{key: request[key] for key in ('source', 'work_class', 'envelope')}}
        additional = copy.deepcopy(definition['work_class']['steps'][0])
        additional.update(id='unrelated-administrative-step', operation='unrelated-administrative-operation')
        definition['work_class']['steps'].append(additional)
        definition['work_class']['steps'].sort(key=lambda row: row['id'])
        envelope = definition['envelope']
        envelope['work_class_digest'] = digest('authority-work-class', definition['work_class'])
        envelope['operations'].append({'step': additional['id'], 'interface': additional['interface'], 'operation': additional['operation']})
        envelope['operations'].sort(key=lambda row: row['step'])
        bound = copy.deepcopy(envelope['limits']['per_action'][0])
        bound.update(id='unrelated-amount-limit', step=additional['id'])
        envelope['limits']['per_action'].append(bound)
        envelope['limits']['per_action'].sort(key=lambda row: row['id'])
        self.assertEqual(authority.validate_definition(definition), {'status': 'REFUSED', 'code': 'UNSUPPORTED_RELATION', 'path': '', 'reasons': [], 'failed_checks': []})
        envelope['bindings'] = []
        envelope['scope']['subjects'] = [{'kind': 'CONSTANT', 'value': 'constant-review-subject'}]
        envelope['scope']['resources'] = [{'kind': 'CONSTANT', 'value': 'constant-review-resource'}]
        self.assertEqual(authority.validate_definition(definition)['status'], 'ACCEPTED')

    def test_binding_step_matches_the_sole_envelope_operation(self):
        request, _ = authority_specimen(shared_budget=False)
        definition = {'schema': authority.AUTH_PREFIX + 'authority-definition', **{key: request[key] for key in ('source', 'work_class', 'envelope')}}
        additional = copy.deepcopy(definition['work_class']['steps'][0])
        additional.update(id='unrelated-administrative-step', operation='unrelated-administrative-operation')
        definition['work_class']['steps'].append(additional)
        definition['work_class']['steps'].sort(key=lambda row: row['id'])
        definition['envelope']['work_class_digest'] = digest('authority-work-class', definition['work_class'])
        definition['envelope']['bindings'][0]['step'] = additional['id']
        self.assertEqual(authority.validate_definition(definition), {'status': 'REFUSED', 'code': 'REFERENCE_INVALID', 'path': '', 'reasons': [], 'failed_checks': []})

    def test_wrong_leaf_clock_source_is_binding_failure_before_current_policy(self):
        request = self.supplied_input()
        leaf(request)['clock']['source'] = 'another-clock'
        request['observations'] = []
        self.assertEqual(self.evaluate(request)['code'], 'BINDING_MISMATCH')

    def test_known_nominal_bridge_failure_precedes_pin_and_duplicate_failures(self):
        request = self.supplied_input()
        duplicate = copy.deepcopy(request['decision_bases'][0])
        request['decision_bases'].insert(0, duplicate)
        changed = next(row for row in duplicate['evidence']['authority_input']['work_class']['types'] if row['id'] == 'IDENTITY')
        changed['kind'] = 'STRING'
        self.assertEqual(self.evaluate(request)['code'], 'TYPE_INVALID')

    def test_leaf_missing_query_precedes_outer_current_revocation(self):
        request = self.supplied_input()
        root_digest = digest('authority-root', request['host_selection']['root'])
        row = next(row for row in request['observations'] if row['query'].get('subject_digest') == root_digest and row['query']['at'] == request['clock']['instant'])
        row['revoked'] = True
        leaf(request)['observations'].pop()
        result = self.evaluate(request)
        self.assertEqual(result['code'], 'EVIDENCE_UNAVAILABLE')
        self.assertEqual(len(result['decision_results']), len(request['decision_bases']))
        self.assertEqual(result['decision_results'][0]['result']['code'], 'EVIDENCE_UNAVAILABLE')

    def test_leaf_dependency_failure_precedes_outer_application_failure(self):
        request = self.supplied_input()
        leaf(request)['specification_pin'] = 'sha256:' + '0' * 64
        request['proposal']['executor']['actor'] = 'another-executor'
        self.assertEqual(self.evaluate(request)['code'], 'DEPENDENCY_MISMATCH')

    def test_leaf_wrapper_digest_mismatch_precedes_act_inventory_failure(self):
        request = self.supplied_input()
        request['decision_bases'][0]['evidence']['decision_act_digest'] = 'sha256:' + '0' * 64
        leaf(request)['returns'] = []
        leaf(request)['host_selection']['authenticated_records'] = [row for row in leaf(request)['host_selection']['authenticated_records'] if row['kind'] != 'RETURN']
        self.assertEqual(self.evaluate(request)['code'], 'BINDING_MISMATCH')

    def test_leaf_executor_coordinates_are_bound_before_act_authorization(self):
        for coordinate in ('actor', 'role', 'principal', 'occupancy'):
            with self.subTest(coordinate=coordinate):
                request = self.supplied_input()
                evidence = request['decision_bases'][0]['evidence']
                decision = next(row for row in leaf(request)['acts'] if row['kind'] == 'INSTANCE_DECISION')
                decision[coordinate] += '-different'
                evidence['decision_act_digest'] = digest('authority-act', decision)
                leaf(request)['acts'].sort(key=lambda row: digest('authority-act', row))
                self.assertEqual(self.evaluate(request)['code'], 'BINDING_MISMATCH')

    def separation_context(self):
        base = cdmo_base()
        authority_basis = base['authority_input']
        result = base['authority_result']
        definition = base['definition']
        current = copy.deepcopy(base['proposal_event']['occurrence'])
        prior = copy.deepcopy(current)
        prior['occurrence_id'] = 'sha256:' + '1' * 64
        current['predecessor_occurrence_ids'] = [prior['occurrence_id']]
        requirement = {'id': 'prior-reviewer', 'relation': 'DISTINCT_ACTOR', 'prior_step_id': prior['step_id'],
                       'prior_act_kind': 'INSTANCE_DECISION', 'current_act_kind': 'INSTANCE_DECISION', 'selection': 'UNIQUE_COMPLETED_ANCESTOR'}
        definition['steps'][0]['prior_actor_separations'] = [requirement]
        selected = human_decisions.selected_gate_bases(authority_basis, result)[0]
        separation = {'kind': 'SEPARATION', 'authority_basis': authority_basis, 'authority_result': result,
                      'basis': {'requirement_id': requirement['id'], 'relation': 'DISTINCT_ACTOR',
                                'prior_occurrence_id': prior['occurrence_id'], 'current_occurrence_id': current['occurrence_id'],
                                'prior_act': copy.deepcopy(selected), 'current_act': copy.deepcopy(selected)}}
        receipt = {'sequence': '2', 'authority_result_digest': digest('authority-result', result)}
        state = {'instance_id': authority_basis['proposal']['instance'], 'active': [{'occurrence': current}],
                 'completed': [{'occurrence': prior}], 'clocks': [base['clock_event']['clock']],
                 'receipts': [{'sequence': '1', 'details': [{'kind': 'CLOCK', 'source': authority_basis['clock']['source'], 'revision': '1'}]}]}
        return receipt, separation, current, state, definition

    def test_retained_separation_accepts_only_the_gate_selected_leaf(self):
        values = self.separation_context()
        self.assertTrue(lifecycle._separation_current_integrity(*values))
        separation = values[1]
        gate = separation['authority_basis']['envelope']['gate']['decision_requirement']
        other = next(row['evidence'] for row in separation['authority_basis']['decision_bases'] if row['requirement_id'] != gate)
        act = next(row for row in other['authority_input']['acts'] if digest('authority-act', row) == other['decision_act_digest'])
        separation['basis']['current_act'] = {'act_digest': other['decision_act_digest'], 'act': act}
        self.assertFalse(lifecycle._separation_current_integrity(*values))

    def test_retained_separation_carrier_presence_matches_nonempty_decisions(self):
        values = self.separation_context()
        del values[1]['authority_basis']
        self.assertFalse(lifecycle._separation_current_integrity(*values))
        values = self.separation_context()
        values[1]['authority_result']['decision_results'] = []
        self.assertFalse(lifecycle._separation_current_integrity(*values))
        del values[1]['authority_basis']
        ordinary = values[1]['authority_result']['act_digests'][0]
        values[1]['basis']['current_act']['act_digest'] = ordinary
        self.assertTrue(lifecycle._separation_current_integrity(*values))

    def test_retained_separation_checks_declared_kind_and_historical_clock(self):
        for alteration in ('declaration', 'clock', 'budgets'):
            with self.subTest(alteration=alteration):
                values = self.separation_context()
                if alteration == 'declaration':
                    values[4]['steps'][0]['prior_actor_separations'][0]['current_act_kind'] = 'GRANT'
                elif alteration == 'clock':
                    values[3]['clocks'][0]['observed_time'] = '2026-10-06T12:11:00Z'
                else:
                    values[4]['steps'][0]['shared_budgets'] = ['unbound-shared-budget']
                self.assertFalse(lifecycle._separation_current_integrity(*values))

    def correction_context(self):
        request = json.loads((ROOT.parent / 'specimens/pharmaceutical-batch-disposition/correction/business-input.json').read_bytes())
        current = request['correction']['correction_authority_input']
        step = next(row for row in request['definition']['steps'] if row['id'] == request['original_permit']['occurrence']['step_id'])
        fields = {row['name']: row['value'] for row in request['correction']['corrected_fields']}
        return request, step, fields, request['original_permit']['authority_basis'], current

    def check_correction_context(self, values):
        return source_corrections._business_context(*values, True)

    def test_correction_missing_fresh_decision_basis_is_evidence_unavailable(self):
        for requirement in ('alder-decision', 'cedar-decision'):
            with self.subTest(requirement=requirement):
                request = self.correction_context()[0]
                current = request['correction']['correction_authority_input']
                current['decision_bases'] = [row for row in current['decision_bases'] if row['requirement_id'] != requirement]
                self.assertEqual(Consumer().check_evidence(request), {'status': 'EVIDENCE_INVALID', 'profile': 'LINEAR', 'role': 'REVIEW_EVIDENCE', 'specification_pin': PIN, 'code': 'EVIDENCE_UNAVAILABLE', 'path': ''})

    def test_correction_result_digest_binding_precedes_current_authority(self):
        for missing_basis in (False, True):
            with self.subTest(missing_basis=missing_basis):
                request, step, *_ = self.correction_context()
                current = request['correction']['correction_authority_input']
                name = step['completion']['correction_policy']['result_digest_field']
                field = next(row for row in current['proposal']['fields'] if row['name'] == name)
                field['value']['value'] = 'sha256:' + '0' * 64
                if missing_basis:
                    current['decision_bases'] = [row for row in current['decision_bases'] if row['requirement_id'] != 'alder-decision']
                self.assertEqual(Consumer().check_evidence(request), {'status': 'EVIDENCE_INVALID', 'profile': 'LINEAR', 'role': 'REVIEW_EVIDENCE', 'specification_pin': PIN, 'code': 'BINDING_MISMATCH', 'path': ''})

    def test_correction_decision_ids_cannot_swap_original_requirements(self):
        values = self.correction_context()
        old = values[3]['decision_bases']
        fresh = values[4]['decision_bases']
        for target, source in zip(fresh, reversed(old)):
            target['evidence'] = copy.deepcopy(source['evidence'])
        with self.assertRaisesRegex(Refusal, 'BINDING_MISMATCH'):
            self.check_correction_context(values)

    def test_correction_act_identity_and_digest_cannot_reuse_another_original(self):
        for reuse in ('id', 'digest'):
            with self.subTest(reuse=reuse):
                values = self.correction_context()
                old = values[3]['decision_bases'][1]['evidence']
                fresh = values[4]['decision_bases'][0]['evidence']
                old_act = next(row for row in old['authority_input']['acts'] if digest('authority-act', row) == old['decision_act_digest'])
                if reuse == 'digest':
                    fresh['authority_input'] = copy.deepcopy(old['authority_input'])
                    fresh['decision_act_digest'] = old['decision_act_digest']
                else:
                    new_act = next(row for row in fresh['authority_input']['acts'] if digest('authority-act', row) == fresh['decision_act_digest'])
                    new_act['id'] = old_act['id']
                    fresh['decision_act_digest'] = digest('authority-act', new_act)
                with self.assertRaisesRegex(Refusal, 'BINDING_MISMATCH'):
                    self.check_correction_context(values)

    def test_correction_fresh_act_ids_are_unique_across_requirements(self):
        values = self.correction_context()
        for row in values[4]['decision_bases']:
            evidence = row['evidence']
            act = next(item for item in evidence['authority_input']['acts'] if digest('authority-act', item) == evidence['decision_act_digest'])
            act['id'] = 'new-shared-issuance-id'
            evidence['decision_act_digest'] = digest('authority-act', act)
        with self.assertRaisesRegex(Refusal, 'BINDING_MISMATCH'):
            self.check_correction_context(values)

    def test_correction_issue_identity_cannot_reuse_another_original(self):
        values = self.correction_context()
        declaration = values[4]['envelope']['decision_requirements'][0]
        old_declaration = values[3]['envelope']['decision_requirements'][1]
        old = next(row['evidence'] for row in values[3]['decision_bases'] if row['requirement_id'] == old_declaration['id'])
        identity = next(row['value'] for row in old['authority_input']['proposal']['fields'] if row['name'] == old_declaration['identity_field'])
        proposal_field = next(row['value']['field'] for row in declaration['context_bindings'] if row['field'] == declaration['identity_field'])
        binding = next(row['value']['field'] for row in values[1]['completion']['correction_policy']['business_context_bindings'] if row['proposal_field'] == proposal_field)
        values[2][binding] = copy.deepcopy(identity)
        next(row for row in values[4]['proposal']['fields'] if row['name'] == proposal_field)['value'] = copy.deepcopy(identity)
        with self.assertRaisesRegex(Refusal, 'BINDING_MISMATCH'):
            self.check_correction_context(values)

    def test_business_decisions_cannot_select_any_correction_control(self):
        controls = ('original_id_field', 'original_digest_field', 'original_revision_field', 'changes_digest_field', 'result_digest_field')
        for control in controls:
            with self.subTest(control=control):
                values = self.correction_context()
                policy = values[1]['completion']['correction_policy']
                declaration = policy['business_decision_requirements'][0]
                binding = next(row for row in declaration['context_bindings'] if row['field'] == 'batch_id')
                binding['value'] = {'kind': 'PROPOSAL_FIELD', 'field': policy[control]}
                values[4]['envelope']['decision_requirements'] = copy.deepcopy(policy['business_decision_requirements'])
                with self.assertRaisesRegex(Refusal, 'BINDING_MISMATCH'):
                    self.check_correction_context(values)

    def test_current_leaf_revocation_retains_complete_refusal(self):
        request = self.supplied_input()
        own = leaf(request)
        root_digest = digest('authority-root', own['host_selection']['root'])
        row = next(row for row in own['observations'] if row['query']['subject_digest'] == root_digest and row['query']['at'] == own['clock']['instant'])
        row['revoked'] = True
        result = self.evaluate(request)
        self.assertIn('DECISION_NOT_EFFECTIVE', result['reasons'])
        selected = result['decision_results'][0]
        self.assertEqual(selected['result']['status'], 'REFUSED')
        self.assertEqual(selected['result_digest'], digest('authority-result', selected['result']))
        self.assertTrue(selected['result']['failed_checks'])

    def test_current_outer_executor_occupancy_remains_required(self):
        request = self.supplied_input()
        occupancy = next(row for row in request['occupancies'] if row['id'] == request['proposal']['executor']['occupancy'])
        old = digest('authority-occupancy', occupancy)
        occupancy['validity']['valid_until'] = '2026-10-06T12:05:00Z'
        refresh_authenticated(request, 'OCCUPANCY', old, occupancy)
        result = self.evaluate(request)
        self.assertTrue(any(row['purpose'] == 'EXECUTOR_OCCUPANCY' and row['reason'] == 'ACT_EXPIRED' for row in result['failed_checks']))
        self.assertTrue(all(row['result']['status'] == 'EVIDENCE_VALID' for row in result['decision_results']))

    def test_leaf_byte_limit_has_exact_boundary(self):
        request = self.supplied_input()
        own = leaf(request)
        row = own['observations'][0]
        row['evidence_ref'] = 'x'
        row['evidence_ref'] += 'x' * (262144 - len(canonical(own)))
        self.assertEqual(len(canonical(own)), 262144)
        self.assertEqual(self.evaluate(request)['status'], 'READY_FOR_RESERVATION')
        row['evidence_ref'] += 'x'
        self.assertEqual(self.evaluate(request)['code'], 'LIMIT_EXCEEDED')

    def test_total_byte_limit_applies_before_policy(self):
        request = self.supplied_input()
        request['observations'][0]['evidence_ref'] = 'x' * 1048576
        leaf(request)['observations'].pop()
        self.assertEqual(self.evaluate(request)['code'], 'LIMIT_EXCEEDED')

    def test_outer_byte_limit_has_exact_boundary(self):
        request = self.supplied_input()
        row = request['observations'][0]
        row['evidence_ref'] = 'x'
        row['evidence_ref'] += 'x' * (1048576 - len(canonical(request)))
        self.assertEqual(len(canonical(request)), 1048576)
        self.assertEqual(self.evaluate(request)['status'], 'READY_FOR_RESERVATION')
        row['evidence_ref'] += 'x'
        self.assertEqual(self.evaluate(request)['code'], 'LIMIT_EXCEEDED')

    def test_refresh_preserves_every_nonvolatile_byte_and_member_presence(self):
        before = self.supplied_input()
        after = copy.deepcopy(before)
        for own in [after, *(leaf(after, index) for index in range(len(after['decision_bases'])))]:
            own['clock']['instant'] = '2026-10-06T12:11:00Z'
            own['observations'] = []
            own['evaluation_point'] = 'DISPATCH'
        self.assertTrue(dispatch_gate.immutable_binding(before, after))
        leaf(after)['source']['revision'] = 'changed-revision'
        self.assertFalse(dispatch_gate.immutable_binding(before, after))
        self.assertFalse(dispatch_gate.immutable_binding({}, {'decision_bases': []}))

    def test_authorization_expiry_clips_to_current_leaf_cutoff(self):
        request = self.supplied_input()
        result = copy.deepcopy(self.expected)
        result['decision_results'][0]['result']['effective_until'] = '2026-10-06T12:10:30Z'
        gate = request['work_class']['steps'][0]['dispatch_gate']
        with mock.patch.object(authority, 'evaluate_authority', return_value=result):
            end = dispatch_gate.expiry({'expires_at': '2026-10-06T12:15:00Z'}, request, gate, request['clock']['instant'])
        self.assertEqual(end, '2026-10-06T12:10:30Z')

    def test_retained_key_backed_state_accepts_clock2_and_rejects_rehashed_leaf_cutoff(self):
        trace = cdmo_trace()
        state = trace['permitted']['state']
        permit = state['permits'][0]
        definition = trace['base']['definition']
        self.assertTrue(dispatch_gate.basis_integrity(state, definition, permit))
        deploy = trace['base']['deploy_input']
        request = {**{key: deploy[key] for key in ('specification_pin', 'profile', 'role')}, 'definition': definition,
                   'definition_digest': trace['base']['definition_digest'], 'state': state, 'state_digest': trace['permitted']['state_digest'],
                   'event': trace['base']['dispatch_clock_event']}
        self.assertEqual(Consumer().step(request), trace['base']['dispatch_clock_result'])
        selected = permit['authority_result']['decision_results'][0]
        selected['result']['effective_until'] = '2026-10-06T12:10:30Z'
        selected['result_digest'] = digest('authority-result', selected['result'])
        permit['authority_result_digest'] = digest('authority-result', permit['authority_result'])
        self.assertFalse(dispatch_gate.basis_integrity(state, definition, permit))

    def test_external_gate_translates_exact_predicate_and_identity(self):
        request = self.supplied_input()
        contexts = {row['requirement_id']: {'request': row['evidence']['authority_input'], 'evidence': row['evidence'], 'declaration': next(item for item in request['envelope']['decision_requirements'] if item['id'] == row['requirement_id'])} for row in request['decision_bases']}
        self.assertEqual(human_decisions._phase_three(request, contexts), [])
        request['envelope']['gate']['criteria'][0]['predicate']['right']['value']['value'] = 'ANOTHER_STATUS'
        self.assertIn('BINDING_MISMATCH', human_decisions._phase_three(request, contexts))

    def test_all_admitted_leaf_actors_are_excluded_from_recovery_control(self):
        request = self.supplied_input()
        permit = {'authority_basis': request}
        expected = {act['actor'] for basis in request['decision_bases'] for act in basis['evidence']['authority_input']['acts']}
        actors = human_decisions.permit_actors(permit)
        self.assertEqual(actors, expected)
        self.assertGreater(len(actors), len(request['decision_bases']))
        self.assertTrue(actors <= recovery._controller_excluded({'authority': request}))

    def test_available_source_is_required_for_historical_revision_binding(self):
        request = self.supplied_input()
        target = request['work_class']['steps'][0]['completion']['authorization_revision_bindings'][0]['requirement_id']
        selected = next(row for row in request['envelope']['source_observation_requirements'] if row['id'] == target)
        selected.update(expected_status='ABSENT', fields=[], relations=[])
        self.assertEqual(source_observations.declaration_admission(request['work_class'], request['envelope']), 'UNSUPPORTED_RELATION')

    def test_renamed_completion_bindings_sort_by_request_field(self):
        definition = cdmo_base()['definition']
        self.assertEqual(work_class.validate(definition), digest('work-class-definition', definition))
        bindings = definition['steps'][0]['completion']['evidence_bindings']
        self.assertTrue(any(row['request_field'] != row['evidence_field'] for row in bindings))
        bindings.sort(key=lambda row: row['evidence_field'].encode())
        with self.assertRaisesRegex(Refusal, 'DEFINITION_INVALID'):
            work_class.validate(definition)


class HumanDecisionBoundaryTests(unittest.TestCase):
    def test_registry_controller_excludes_exact_admitted_ordinary_gate_actor(self):
        acts = [{'kind': 'GRANT', 'actor': 'grantor', 'role': 'owner'},
                {'kind': 'ORGANISATIONAL_ATTESTATION', 'actor': 'attester', 'role': 'attester'},
                {'kind': 'INSTANCE_DECISION', 'actor': 'releaser', 'role': 'release'},
                {'kind': 'VERIFY', 'actor': 'verifier', 'role': 'verify'},
                {'kind': 'INSTANCE_DECISION', 'actor': 'other-role', 'role': 'other'},
                {'kind': 'INSTANCE_DECISION', 'actor': 'unadmitted', 'role': 'release'}]
        admitted = [digest('authority-act', row) for row in acts[:-1]]
        for inventory in (None, []):
            for kind, role, expected in [('DECIDE', 'release', {'executor', 'releaser'}),
                                         ('VERIFY', 'verify', {'executor', 'verifier'}),
                                         ('NONE', None, {'executor'})]:
                with self.subTest(inventory=inventory, gate=kind):
                    ordinary = {'proposal': {'executor': {'actor': 'executor'}},
                                'envelope': {'gate': {'kind': kind, 'role': role}}, 'acts': acts}
                    if inventory is not None:
                        ordinary['decision_bases'] = inventory
                    self.assertEqual(recovery._controller_excluded({'authority': ordinary,
                                     'authority_result': {'act_digests': admitted}}), expected)

    def test_registry_controller_preserves_nonempty_independent_actor_exclusions(self):
        ordinary = {'proposal': {'executor': {'actor': 'executor'}},
                    'acts': [{'kind': 'GRANT', 'actor': 'grantor'}, {'kind': 'ORGANISATIONAL_ATTESTATION', 'actor': 'attester'}],
                    'decision_bases': [{'evidence': {'authority_input': {'acts': [{'actor': 'independent-human'}, {'actor': 'leaf-attester'}]}}}]}
        self.assertEqual(recovery._controller_excluded({'authority': ordinary}),
                         {'executor', 'grantor', 'attester', 'independent-human', 'leaf-attester'})

    def test_recovery_controller_source_cases_match_complete_public_results(self):
        for index in range(1, 25):
            path = ROOT.parent / 'cases/recovery-authority' / ('C3-RCTRL-' + str(index).zfill(3) + '.json')
            case = json.loads(path.read_text())
            with self.subTest(case=case['id']):
                self.assertEqual(Consumer().call(case['operation'], case['input']), case['expected'])

    def test_work_controller_excludes_selected_gate_and_preserves_nonempty_decisions(self):
        for kind, role, actor in [('DECIDE', 'release', 'releaser'), ('VERIFY', 'verify', 'verifier'), ('NONE', None, None)]:
            acts = [{'kind': 'GRANT', 'actor': 'grantor', 'role': 'owner'},
                    {'kind': 'ORGANISATIONAL_ATTESTATION', 'actor': 'attester', 'role': 'attester'}]
            if actor is not None:
                acts.append({'kind': 'INSTANCE_DECISION' if kind == 'DECIDE' else 'VERIFY', 'actor': actor, 'role': role})
            bases = [{'act': act, 'act_digest': digest('authority-act', act)} for act in acts]
            result = {'act_digests': [row['act_digest'] for row in bases]}
            permit = {'executor': {'participant_id': 'executor'}, 'authority_act_bases': bases, 'authority_result': result}
            expected = {'executor'} | ({actor} if actor is not None else set())
            self.assertEqual(recovery._work_controller_excluded(permit), expected)
            for inventory in (None, []):
                with self.subTest(gate=kind, inventory=inventory):
                    basis = {'proposal': {'executor': {'actor': 'executor'}}, 'envelope': {'gate': {'kind': kind, 'role': role}}, 'acts': acts}
                    if inventory is not None:
                        basis['decision_bases'] = inventory
                    permit['authority_basis'] = basis
                    self.assertEqual(recovery._work_controller_excluded(permit), expected)
            permit['authority_basis']['decision_bases'] = [{'evidence': {'authority_input': {'acts': [{'actor': 'independent-human'}, {'actor': 'leaf-attester'}]}}}]
            self.assertEqual(recovery._work_controller_excluded(permit), {act['actor'] for act in acts} | {'executor', 'independent-human', 'leaf-attester'})

    def test_effective_until_uses_selected_connected_capacity_intervals(self):
        interval = lambda start, end: {'valid_from': '2026-10-06T12:' + start + ':00Z', 'valid_until': '2026-10-06T12:' + end + ':00Z'}
        selected = {'id': 'selected', 'validity': interval('00', '15'), 'reliance': {'kind': 'SURVIVE_EXPIRY', 'validity': interval('15', '35')}}
        request = {'clock': {'instant': '2026-10-06T12:10:00Z'}, 'envelope': {'temporal_validity': interval('00', '50')}, 'host_selection': {'root': {'prior_acts_survive_expiry': False, 'validity': interval('00', '45'), 'channels': []}}, 'capacities': [selected, {'id': 'unused', 'validity': interval('00', '11'), 'reliance': {'kind': 'CURRENT_ONLY'}}]}
        context = {'request': request, 'acts': {'selected': [{'capacity': 'selected'}], 'returns': {}}}
        self.assertEqual(human_decisions.effective_until(context), '2026-10-06T12:35:00Z')
        selected['reliance']['validity']['valid_from'] = '2026-10-06T12:16:00Z'
        self.assertEqual(human_decisions.effective_until(context), '2026-10-06T12:15:00Z')
        selected['reliance'] = {'kind': 'CURRENT_ONLY'}
        self.assertEqual(human_decisions.effective_until(context), '2026-10-06T12:15:00Z')

    def test_recovery_resolves_effect_to_exact_attempt_across_occurrence_permits(self):
        permits = [{'permit_id': name, 'occurrence': {'occurrence_id': 'same'}} for name in ('older', 'newer')]
        def dispatch(permit, event, attempt, authorization):
            return {'permit_digest': permit, 'event_id': event, 'dispatch_digest': event, 'dispatch_attempt_digest': attempt, 'attempt': {'attempt_id': attempt}, 'authorization_digest': authorization, 'native_request': {}, 'connector': {}}
        state = {'receipts': [{'event_id': 'old-send', 'sequence': '1'}, {'event_id': 'new-send', 'sequence': '2'}], 'dispatches': [dispatch('older', 'old-send', 'attempt-1', 'auth-1'), dispatch('newer', 'new-send', 'attempt-2', 'auth-2')]}
        evidence = {'native_operation_id': 'effect-2'}
        disposition = {'evidence': {'attempts': [{'id': 'attempt-2', 'attempt_digest': 'attempt-2', 'effect_ids': ['effect-2']}]}}
        selected, retained = recovery._recovery_dispatch(state, permits, evidence, disposition)
        self.assertEqual(selected['permit_id'], 'newer')
        self.assertEqual(retained['authorization_digest'], 'auth-2')
        disposition['evidence']['attempts'].append({'id': 'attempt-1', 'attempt_digest': 'attempt-1', 'effect_ids': ['effect-2']})
        self.assertIsNone(recovery._recovery_dispatch(state, permits, evidence, disposition))

    def test_completion_uses_historical_source_revision_and_checks_status_request_equality(self):
        typed = lambda value, ref='TEXT': {'type_ref': ref, 'value': value}
        types = {'TEXT': {'id': 'TEXT', 'kind': 'STRING', 'unit': None, 'nonnegative': False}, 'TIME': {'id': 'TIME', 'kind': 'INSTANT', 'unit': None, 'nonnegative': False}}
        carrier = {'status_field': 'status', 'status_type_ref': 'TEXT', 'status_request_field': 'desired_status', 'evidence_bindings': [{'request_field': 'desired_status', 'evidence_field': 'status'}], 'additional_fields': [], 'authorization_revision_bindings': [{'evidence_field': 'quality_revision', 'type_ref': 'TEXT', 'requirement_id': 'quality'}], 'provider_record_identity': {'field': 'record', 'type_ref': 'TEXT'}, 'event_time_identity': {'field': 'at', 'type_ref': 'TIME'}, 'success_values': [typed('APPROVED'), typed('RELEASED')], 'failure_values': [], 'route_label_field': None}
        step = {'kind': 'OPERATION', 'completion': carrier}
        permit = {'native_request': {'fields': [{'name': 'desired_status', 'value': typed('APPROVED')}]}}
        now = '2026-10-06T12:10:00Z'
        values = {'status': typed('APPROVED'), 'quality_revision': typed('QG-42'), 'record': typed('event-1'), 'at': typed(now, 'TIME')}
        evidence = {'provider_record_id': 'event-1', 'provider_revision': '9', 'event_time': now, 'collections': [], 'actual_fields': [{'name': key, 'value': value} for key, value in sorted(values.items())]}
        authorization = {'authorization_fence': {'provider_revision': 'LATEST-UNRELATED', 'sources': [{'requirement_id': 'quality', 'expected_status': 'AVAILABLE', 'provider_revision': 'QG-42'}]}}
        self.assertEqual(completion.fields(step, permit, evidence, types, authorization), ('MATCHED', None, True))
        evidence['actual_fields'][-1]['value'] = typed('RELEASED')
        self.assertEqual(completion.fields(step, permit, evidence, types, authorization)[0], 'UNEXPECTED')
        evidence['actual_fields'][-1]['value'] = typed('APPROVED')
        evidence['actual_fields'][1]['value'] = typed('LATEST-UNRELATED')
        self.assertEqual(completion.fields(step, permit, evidence, types, authorization)[0], 'UNEXPECTED')


if __name__ == '__main__':
    unittest.main()
