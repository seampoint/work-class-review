"""Static admission for draft-2 work-class definitions."""

from __future__ import annotations

from collections import defaultdict
import re

from .common import PIN, Refusal, canonical, digest, utf8_sorted_unique, valid_instant


PROFILE_RANK = {"LINEAR": 0, "CHOICE_LOOPS": 1, "DEADLINES": 2, "PARALLEL_FANOUT": 3}
STRUCTURAL = {"PARALLEL_SPLIT", "PARALLEL_JOIN", "FANOUT_JOIN", "TERMINAL"}
PROPOSAL = {"OPERATION", "FANOUT_EXPAND"}


def _inventory(rows, key="id"):
    values = [row[key] for row in rows]
    if not utf8_sorted_unique(values):
        raise Refusal("DEFINITION_INVALID")
    return {row[key]: row for row in rows}


def _set(values):
    if not utf8_sorted_unique(values):
        raise Refusal("DEFINITION_INVALID")


def _typed(value, types):
    declaration = types.get(value["type_ref"])
    if declaration is None:
        return False
    payload = value["value"]; kind = declaration["kind"]
    if kind in {"IDENTITY","STRING"}:
        return isinstance(payload,str) and (kind != "IDENTITY" or bool(payload))
    if kind == "BOOLEAN":
        return type(payload) is bool
    if not isinstance(payload,str):
        return False
    pattern = r"^(0|[1-9][0-9]*)$" if declaration["nonnegative"] else r"^(0|-?[1-9][0-9]*)$"
    if kind == "DECIMAL":
        pattern = r"^(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$" if declaration["nonnegative"] else r"^-?(0|[1-9][0-9]*)(\.[0-9]*[1-9])?$"
    return re.fullmatch(pattern,payload) is not None and payload != "-0"


def _acyclic(graph, nodes=None, omitted_edge=None):
    nodes=set(graph) if nodes is None else set(nodes);visiting=set();visited=set()
    def visit(node):
        if node in visiting: return False
        if node in visited: return True
        visiting.add(node)
        for target in graph[node]:
            if omitted_edge==(node,target) or target not in nodes: continue
            if not visit(target): return False
        visiting.remove(node);visited.add(node);return True
    return all(visit(node) for node in nodes)


def _region(graph, head, join, forbidden_heads=()):
    forbidden=set(forbidden_heads)-{head};result=set();pending=[head]
    while pending:
        node=pending.pop()
        if node==join or node in result: continue
        if node in forbidden: raise Refusal("DEFINITION_INVALID")
        result.add(node);pending.extend(graph[node])
    return result


def validate(definition):
    if definition["specification_pin"] != PIN:
        raise Refusal("BINDING_MISMATCH")
    participants = _inventory(definition["participants"])
    objects = _inventory(definition["objects"])
    types = _inventory(definition["types"])
    steps = _inventory(definition["steps"])
    choices = _inventory(definition["choices"], "step_id")
    occurrence_limits = _inventory(definition["occurrence_limits"], "step_id")
    loops = _inventory(definition["loops"])
    deadlines = _inventory(definition["deadlines"])
    blocks = _inventory(definition["parallel_blocks"])
    fanouts = _inventory(definition["fanouts"])
    _set(definition["shared_budgets"])
    _set(definition["source"]["obligations"])
    if any(row["type_ref"] not in types for row in objects.values()):
        raise Refusal("REFERENCE_INVALID")
    if definition["root"] not in steps:
        raise Refusal("REFERENCE_INVALID")

    relationships = definition["relationships"]
    encoded_relationships = [canonical(row) for row in relationships]
    if len(encoded_relationships) != len(set(encoded_relationships)):
        raise Refusal("DEFINITION_INVALID")
    outgoing = defaultdict(list)
    incoming = defaultdict(list)
    for edge in relationships:
        if edge["from"] not in steps or edge["to"] not in steps:
            raise Refusal("REFERENCE_INVALID")
        outgoing[edge["from"]].append(edge)
        incoming[edge["to"]].append(edge)

    proposal_steps = []
    all_budgets = set()
    for step_id, step in steps.items():
        fields = _inventory(step["fields"], "name")
        _set(step["required_credentials"])
        _set(step["authority_requirements"])
        _set(step["shared_budgets"])
        effect_bindings = _inventory(step["prior_effect_bindings"])
        separations = _inventory(step["prior_actor_separations"])
        if step["kind"] in STRUCTURAL:
            nulls = (step["executor_role"], step["interface"], step["operation"], step["scope_fields"], step["permit_seconds"], step["failure_behavior"], step["completion"])
            if any(value is not None for value in nulls) or fields or step["required_credentials"] or step["authority_requirements"] or step["shared_budgets"] or effect_bindings or separations:
                raise Refusal("DEFINITION_INVALID")
        else:
            proposal_steps.append(step_id)
            all_budgets.update(step["shared_budgets"])
            if (
                step["executor_role"] is None or step["interface"] is None or step["operation"] is None
                or step["scope_fields"] is None or step["permit_seconds"] is None
                or int(step["permit_seconds"]) <= 0 or step["failure_behavior"] is None
                or step["completion"] is None or len(step["authority_requirements"]) != 1
            ):
                raise Refusal("DEFINITION_INVALID")
            if step["executor_role"] not in {row["role"] for row in participants.values()}:
                raise Refusal("REFERENCE_INVALID")
            if any(row["type_ref"] not in types for row in fields.values()):
                raise Refusal("REFERENCE_INVALID")
            scope = step["scope_fields"]
            _set(scope["subjects"]); _set(scope["resources"])
            if not scope["subjects"] or not scope["resources"] or not set(scope["subjects"] + scope["resources"]) <= set(fields):
                raise Refusal("REFERENCE_INVALID")
            completion = step["completion"]
            if completion["status_type_ref"] not in types:
                raise Refusal("REFERENCE_INVALID")
            completion_values=completion["success_values"] + completion["failure_values"]
            if any(value["type_ref"] not in types for value in completion_values):
                raise Refusal("REFERENCE_INVALID")
            if any(not _typed(value, types) or value["type_ref"] != completion["status_type_ref"] for value in completion_values):
                raise Refusal("DEFINITION_INVALID")
            successes = [canonical(value) for value in completion["success_values"]]
            failures = [canonical(value) for value in completion["failure_values"]]
            if successes != sorted(set(successes)) or failures != sorted(set(failures)) or set(successes) & set(failures):
                raise Refusal("DEFINITION_INVALID")
            bindings = completion["evidence_bindings"]
            request_names = [row["request_field"] for row in bindings]
            evidence_names = [row["evidence_field"] for row in bindings]
            if request_names != sorted(request_names, key=str.encode) or set(request_names) != set(fields) or len(evidence_names) != len(set(evidence_names)):
                raise Refusal("DEFINITION_INVALID")
            names = evidence_names + [completion["status_field"]]
            if completion["route_label_field"] is not None:
                names.append(completion["route_label_field"])
            if len(names) != len(set(names)):
                raise Refusal("DEFINITION_INVALID")
            target_fields = [row["target_request_field"] for row in effect_bindings.values()]
            if len(target_fields) != len(set(target_fields)):
                raise Refusal("DEFINITION_INVALID")
            choice=choices.get(step_id)
            route_pair=(step["completion"]["route_label_field"],step["completion"]["route_label_type_ref"])
            if choice is None and route_pair!=(None,None) or choice is not None and (step["kind"]!="OPERATION" or None in route_pair):
                raise Refusal("DEFINITION_INVALID")
        for binding in effect_bindings.values():
            source = steps.get(binding["source_step_id"])
            if source is None or binding["target_request_field"] not in fields:
                raise Refusal("REFERENCE_INVALID")
            if source["kind"] not in PROPOSAL or source["completion"] is None:
                raise Refusal("DEFINITION_INVALID")
            source_binding = [row for row in source["completion"]["evidence_bindings"] if row["evidence_field"] == binding["source_evidence_field"]]
            if len(source_binding) != 1:
                raise Refusal("REFERENCE_INVALID")
            source_field = next((row for row in source["fields"] if row["name"] == source_binding[0]["request_field"]), None)
            if source_field is None or source_field["type_ref"] != fields[binding["target_request_field"]]["type_ref"]:
                raise Refusal("DEFINITION_INVALID")
        for separation in separations.values():
            prior = steps.get(separation["prior_step_id"])
            if prior is None:
                raise Refusal("REFERENCE_INVALID")
            if prior["kind"] not in PROPOSAL or len(prior["authority_requirements"]) != 1:
                raise Refusal("DEFINITION_INVALID")

    if steps[definition["root"]]["kind"] not in PROPOSAL:
        raise Refusal("DEFINITION_INVALID")
    if sorted(all_budgets, key=str.encode) != definition["shared_budgets"]:
        raise Refusal("DEFINITION_INVALID")

    for step_id, step in steps.items():
        edges = outgoing[step_id]
        kinds = defaultdict(list)
        for edge in edges:
            kinds[edge["kind"]].append(edge)
        failure_count = len(kinds["FAILURE"])
        if step["kind"] in PROPOSAL:
            if failure_count != (1 if step["failure_behavior"] == "FAILURE_EDGE" else 0):
                raise Refusal("DEFINITION_INVALID")
            if step_id in choices:
                if kinds["SEQUENCE"] or len(kinds["LABEL"]) != len(choices[step_id]["label_values"]):
                    raise Refusal("DEFINITION_INVALID")
            elif step["kind"] == "OPERATION" and (len(kinds["SEQUENCE"]) != 1 or kinds["LABEL"]):
                raise Refusal("DEFINITION_INVALID")
            elif step["kind"] == "FANOUT_EXPAND" and (kinds["SEQUENCE"] or kinds["LABEL"]):
                raise Refusal("DEFINITION_INVALID")
        elif step["kind"] in {"PARALLEL_JOIN", "FANOUT_JOIN"}:
            if len(edges) != 1 or len(kinds["SEQUENCE"]) != 1:
                raise Refusal("DEFINITION_INVALID")
        elif edges:
            raise Refusal("DEFINITION_INVALID")

    for step_id, choice in choices.items():
        step = steps.get(step_id)
        if step is None:
            raise Refusal("REFERENCE_INVALID")
        carrier = step["completion"]
        if carrier is None or carrier["route_label_field"] is None or carrier["route_label_type_ref"] != choice["label_type_ref"]:
            raise Refusal("DEFINITION_INVALID")
        labels = [canonical(value) for value in choice["label_values"]]
        edges = [canonical(edge["label"]) for edge in outgoing[step_id] if edge["kind"] == "LABEL"]
        if labels != edges or any(value["type_ref"] != choice["label_type_ref"] or not _typed(value,types) for value in choice["label_values"]):
            raise Refusal("DEFINITION_INVALID")

    deadlines_by_step=defaultdict(list)
    for deadline in deadlines.values():
        if deadline["step_id"] not in proposal_steps:
            raise Refusal("REFERENCE_INVALID")
        deadlines_by_step[deadline["step_id"]].append(deadline)
        due = deadline["due"]
        if due["kind"] == "ABSOLUTE_INSTANT" and not valid_instant(due["instant"]):
            raise Refusal("DEFINITION_INVALID")
        if due["kind"] == "ELAPSED_DURATION" and int(due["value"])<=0:
            raise Refusal("DEFINITION_INVALID")
        if due["kind"] == "ELAPSED_FROM_ANCESTOR":
            if due["anchor_step_id"] not in steps: raise Refusal("REFERENCE_INVALID")
            if int(due["value"])<=0: raise Refusal("DEFINITION_INVALID")
        expiry = [row for row in outgoing[deadline["step_id"]] if row["kind"] == "EXPIRY"]
        if deadline["expiry_target"] is None:
            if expiry:
                raise Refusal("DEFINITION_INVALID")
        elif len(expiry) != 1 or expiry[0]["deadline_ref"] != deadline["id"] or expiry[0]["to"] != deadline["expiry_target"]:
            raise Refusal("DEFINITION_INVALID")
    if any(len(rows)>1 for rows in deadlines_by_step.values()): raise Refusal("DEFINITION_INVALID")
    for edge in relationships:
        if edge["kind"]=="EXPIRY":
            declared=deadlines.get(edge["deadline_ref"])
            if declared is None:
                raise Refusal("REFERENCE_INVALID")
            if declared["step_id"]!=edge["from"] or declared["expiry_target"]!=edge["to"]:
                raise Refusal("DEFINITION_INVALID")

    profile = PROFILE_RANK[definition["profile"]]
    if profile < 1 and (choices or loops): raise Refusal("UNSUPPORTED_FEATURE")
    if profile < 2 and deadlines: raise Refusal("UNSUPPORTED_FEATURE")
    if profile < 3 and (blocks or fanouts): raise Refusal("UNSUPPORTED_FEATURE")
    if profile < 3 and any(row["kind"] in {"PARALLEL_SPLIT","PARALLEL_JOIN","FANOUT_EXPAND","FANOUT_JOIN"} for row in steps.values()):
        raise Refusal("UNSUPPORTED_FEATURE")
    if definition["root"] not in occurrence_limits or int(occurrence_limits[definition["root"]]["maximum"])<=0:
        raise Refusal("DEFINITION_INVALID")
    if int(definition["limits"]["maximum_activations"]) <= 0:
        raise Refusal("DEFINITION_INVALID")
    for name, value in definition["limits"].items():
        if int(value) > (1024 if name == "maximum_fanout_objects" else 4096):
            raise Refusal("LIMIT_EXCEEDED")

    graph = {step_id: [edge["to"] for edge in outgoing[step_id]] for step_id in steps}
    split_owners=defaultdict(int);parallel_join_owners=defaultdict(int)
    regions=[]
    for block in blocks.values():
        if steps.get(block["split_step_id"], {}).get("kind") != "PARALLEL_SPLIT" or steps.get(block["join_step_id"], {}).get("kind") != "PARALLEL_JOIN":
            raise Refusal("REFERENCE_INVALID")
        split_owners[block["split_step_id"]]+=1;parallel_join_owners[block["join_step_id"]]+=1
        branch_ids=[branch["id"] for branch in block["branches"]]
        if len(branch_ids)!=len(set(branch_ids)) or len(incoming[block["split_step_id"]])!=1:
            raise Refusal("DEFINITION_INVALID")
        heads = [branch["head_step_id"] for branch in block["branches"]]
        if len(heads) != len(set(heads)) or any(head not in steps for head in heads):
            raise Refusal("REFERENCE_INVALID")
        if any(steps[head]["kind"] not in PROPOSAL for head in heads): raise Refusal("DEFINITION_INVALID")
        graph[block["split_step_id"]].extend(heads)
    fanout_expand_owners=defaultdict(int);fanout_join_owners=defaultdict(int)
    for fanout in fanouts.values():
        if steps.get(fanout["expand_step_id"], {}).get("kind") != "FANOUT_EXPAND" or steps.get(fanout["join_step_id"], {}).get("kind") != "FANOUT_JOIN" or fanout["region_head_step_id"] not in steps:
            raise Refusal("REFERENCE_INVALID")
        fanout_expand_owners[fanout["expand_step_id"]]+=1;fanout_join_owners[fanout["join_step_id"]]+=1
        if fanout["object_type_ref"] not in types:
            raise Refusal("REFERENCE_INVALID")
        head_fields={row["name"]:row for row in steps[fanout["region_head_step_id"]]["fields"]}
        if fanout["object_request_field"] not in head_fields or head_fields[fanout["object_request_field"]]["type_ref"]!=fanout["object_type_ref"]:
            raise Refusal("DEFINITION_INVALID")
        graph[fanout["expand_step_id"]].append(fanout["region_head_step_id"])
    if any(
        (step["kind"]=="PARALLEL_SPLIT" and split_owners[step_id]!=1)
        or (step["kind"]=="PARALLEL_JOIN" and parallel_join_owners[step_id]!=1)
        or (step["kind"]=="FANOUT_EXPAND" and fanout_expand_owners[step_id]!=1)
        or (step["kind"]=="FANOUT_JOIN" and fanout_join_owners[step_id]!=1)
        for step_id,step in steps.items()
    ):
        raise Refusal("DEFINITION_INVALID")
    loop_back_edges={
        (loop["back_edge_from_step_id"],loop["entry_step_id"])
        for loop in loops.values()
    }
    for block in blocks.values():
        heads=[branch["head_step_id"] for branch in block["branches"]]
        for head in heads:
            if any((edge["from"],edge["to"]) not in loop_back_edges for edge in incoming[head]):
                raise Refusal("DEFINITION_INVALID")
        branch_regions=[]
        for head in heads:
            visited=_region(graph,head,block["join_step_id"],heads)
            branch_regions.append(visited);regions.append(("PARALLEL",block["id"],visited))
            if any(not graph[node] for node in visited): raise Refusal("DEFINITION_INVALID")
            reverse={block["join_step_id"]};changed=True
            while changed:
                changed=False
                for node,targets in graph.items():
                    if node not in reverse and any(target in reverse for target in targets):
                        reverse.add(node);changed=True
            if not visited <= reverse: raise Refusal("DEFINITION_INVALID")
        if any(left & right for index,left in enumerate(branch_regions) for right in branch_regions[index+1:]): raise Refusal("DEFINITION_INVALID")
        allowed=set().union(*branch_regions)
        if any(edge["from"] not in allowed for edge in incoming[block["join_step_id"]]): raise Refusal("DEFINITION_INVALID")
    for fanout in fanouts.values():
        head=fanout["region_head_step_id"]
        if any((edge["from"],edge["to"]) not in loop_back_edges for edge in incoming[head]):
            raise Refusal("DEFINITION_INVALID")
        reverse={fanout["join_step_id"]};changed=True
        while changed:
            changed=False
            for node,targets in graph.items():
                if node not in reverse and any(target in reverse for target in targets):
                    reverse.add(node);changed=True
        visited=_region(graph,head,fanout["join_step_id"])
        regions.append(("FANOUT",fanout["id"],visited))
        if any(not graph[node] for node in visited): raise Refusal("DEFINITION_INVALID")
        if not visited <= reverse: raise Refusal("DEFINITION_INVALID")
        if any(edge["from"] not in visited for edge in incoming[fanout["join_step_id"]]): raise Refusal("DEFINITION_INVALID")
    for index,(_,_,left) in enumerate(regions):
        for _,_,right in regions[index+1:]:
            if left & right and not (left<right or right<left or left==right): raise Refusal("DEFINITION_INVALID")
    for step_id in proposal_steps:
        enclosing_fanouts=[fanouts[construct_id] for kind,construct_id,region in regions if kind=="FANOUT" and step_id in region]
        object_fields=[row["object_request_field"] for row in enclosing_fanouts]
        if len(object_fields)!=len(set(object_fields)): raise Refusal("DEFINITION_INVALID")
    reached = set(); stack = [definition["root"]]
    while stack:
        node = stack.pop()
        if node in reached: continue
        reached.add(node); stack.extend(graph[node])
    if reached != set(steps):
        raise Refusal("DEFINITION_INVALID")
    # COMPOSITION 5.1: an ancestor anchor must exist and be unique at every activation of the deadline's step.
    for deadline in deadlines.values():
        if deadline["due"]["kind"]!="ELAPSED_FROM_ANCESTOR": continue
        anchor=deadline["due"]["anchor_step_id"]
        if steps[anchor]["kind"] not in PROPOSAL or anchor==deadline["step_id"] or any(anchor in loop["member_step_ids"] for loop in loops.values()):
            raise Refusal("DEFINITION_INVALID")
        if any(kind=="FANOUT" and anchor in region and deadline["step_id"] not in region for kind,_,region in regions):
            raise Refusal("DEFINITION_INVALID")
        bypass=set() if definition["root"]==anchor else {definition["root"]};pending=list(bypass)
        while pending:
            for target in graph[pending.pop()]:
                if target!=anchor and target not in bypass: bypass.add(target);pending.append(target)
        if deadline["step_id"] in bypass: raise Refusal("DEFINITION_INVALID")

    index = 0; indices = {}; low = {}; stack = []; on_stack = set(); components = []
    def strong(node):
        nonlocal index
        indices[node] = low[node] = index; index += 1; stack.append(node); on_stack.add(node)
        for target in graph[node]:
            if target not in indices:
                strong(target); low[node] = min(low[node], low[target])
            elif target in on_stack:
                low[node] = min(low[node], indices[target])
        if low[node] == indices[node]:
            component = set()
            while True:
                member = stack.pop(); on_stack.remove(member); component.add(member)
                if member == node: break
            components.append(component)
    for node in steps:
        if node not in indices: strong(node)
    cyclic = [component for component in components if len(component) > 1 or any(target == next(iter(component)) for target in graph[next(iter(component))])]
    declared_components = []
    for loop in loops.values():
        members = set(loop["member_step_ids"])
        if loop["entry_step_id"] not in members or loop["back_edge_from_step_id"] not in members:
            raise Refusal("UNSUPPORTED_FEATURE")
        if members not in cyclic or members in declared_components:
            raise Refusal("UNSUPPORTED_FEATURE")
        if any(member not in occurrence_limits for member in members if steps[member]["kind"] in PROPOSAL):
            raise Refusal("UNSUPPORTED_FEATURE")
        if any(int(occurrence_limits[member]["maximum"]) <= 0 for member in members if steps[member]["kind"] in PROPOSAL):
            raise Refusal("DEFINITION_INVALID")
        back = [edge for edge in outgoing[loop["back_edge_from_step_id"]] if edge["to"] == loop["entry_step_id"]]
        other_entry = [edge for member in members for edge in outgoing[member] if edge["to"] == loop["entry_step_id"] and member != loop["back_edge_from_step_id"]]
        if len(back) != 1 or other_entry:
            raise Refusal("UNSUPPORTED_FEATURE")
        if not _acyclic(graph,members,(loop["back_edge_from_step_id"],loop["entry_step_id"])):
            raise Refusal("UNSUPPORTED_FEATURE")
        if any(members & region and not members<=region for _,_,region in regions):
            raise Refusal("UNSUPPORTED_FEATURE")
        declared_components.append(members)
    if any(component not in declared_components for component in cyclic):
        raise Refusal("UNSUPPORTED_FEATURE")
    forbidden_cycle_nodes={row["expand_step_id"] for row in fanouts.values()}|{row["join_step_id"] for row in fanouts.values()}
    if any(component & forbidden_cycle_nodes for component in cyclic): raise Refusal("UNSUPPORTED_FEATURE")
    for step_id in proposal_steps:
        depth=sum(step_id in region for _,_,region in regions)+sum(step_id in set(loop["member_step_ids"]) for loop in loops.values())
        if depth>64: raise Refusal("DEFINITION_INVALID")
    return digest("work-class-definition", definition)
