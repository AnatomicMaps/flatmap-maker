#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2021  David Brooks
#
#  Licensed under the Apache License, Version 2.0 (the "License");
#  you may not use this file except in compliance with the License.
#  You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
#  Unless required by applicable law or agreed to in writing, software
#  distributed under the License is distributed on an "AS IS" BASIS,
#  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
#  See the License for the specific language governing permissions and
#  limitations under the License.
#
#===============================================================================
#
# Based on https://github.com/nickerso/sparc-curation/blob/apinatomy2flatmap/sparcur_internal/apinatomy2flatmap.py
#
#===============================================================================

import json
from collections import defaultdict as base_dd

class defaultdict(base_dd):
    __str__ = dict.__str__
    __repr__ = dict.__repr__

#===============================================================================

import networkx as nx

#===============================================================================

APINATOMY_MODEL_BASE = 'https://apinatomy.org/uris/models/{}'

#===============================================================================

CYCLE = 'CYCLE DETECTED'

def process_nodes(j, direction):
    nodes = {n['id']:n['lbl'] for n in j['nodes']}
    nodes[CYCLE] = CYCLE  # make sure we can look up the cycle
    edgerep = ['{} {} {}'.format(nodes[e['sub']], e['pred'], nodes[e['obj']]) for e in j['edges']]
    # note that if there are multiple relations between s & p then last one wins
    # sorting by the predicate should help keep it a bit more stable
    pair_rel = {(e['sub'], e['obj'])
                if direction == 'OUTGOING' else
                (e['obj'], e['sub']):
                e['pred'] + '>'
                if direction == 'OUTGOING' else
                '<' + e['pred']
                for e in sorted(j['edges'], key = lambda e: e['pred'])}

    objects = defaultdict(list)  # note: not all nodes are objects!
    for edge in j['edges']:
        objects[edge['obj']].append(edge['sub'])

    subjects = defaultdict(list)
    for edge in j['edges']:
        subjects[edge['sub']].append(edge['obj'])

    if direction == 'OUTGOING':  # flip for the tree
        objects, subjects = subjects, objects
    elif direction == 'BOTH':  # FIXME BOTH needs help!
        from pprint import pprint
        pprint(subjects)
        pprint(objects)
        pass

    ss, so = set(subjects), set(objects)
    roots = so - ss
    leaves = ss - so

    root = None
    if len(roots) == 1:
        root = next(iter(roots))
    else:
        root = '*ROOT*'
        nodes[root] = 'ROOT'
        objects[root] = list(roots)

    return nodes, objects, subjects, edgerep, root, roots, leaves, pair_rel

#===============================================================================

def print_node(indent, node, objects, nodes, pair_rel):
    for o in objects[node]:
        predicate = pair_rel[(node, o)]
        print(indent + '|--' + predicate + ((nodes[o] + " (" + o + ")" ) if nodes[o] else o))
        next_level = indent + '|   '
        print_node(next_level, o, objects, nodes, pair_rel)

#===============================================================================

def find_object(subject, predicate, objects, pair_rel):
    for o in objects[subject]:
        if pair_rel[(subject, o)] == predicate:
            return o
    return ''

#===============================================================================

def get_primary_info(id, nodes, objects, pair_rel):
    if id:
        # default name is the label if one is provided, otherwise the raw id is used
        name = nodes[id] if nodes[id] else id
        # if an external identifier is defined, that should be preferred
        external_id = find_object(id, 'apinatomy:external>', objects, pair_rel)
    else:
        name = "UNKOWN"
        external_id = "REALLY_UNKNOWN"
    return external_id, name

#===============================================================================

def get_primary_name(id, nodes, objects, pair_rel):
    external_id, name = get_primary_info(id, nodes, objects, pair_rel)
    if external_id:
        name = external_id + "(" + name + ")"
    return name

#===============================================================================

def get_flatmap_node(node, nodes, objects, pair_rel):
    flatmap_node = {
        'id': node,
    }
    # layered type or direct?
    layer = find_object(node, 'apinatomy:layerIn>', objects, pair_rel)
    if layer:
        clone = find_object(node, 'apinatomy:cloneOf>', objects, pair_rel)
        supertype = find_object(clone, 'apinatomy:supertype>', objects, pair_rel)
        external_id, name = get_primary_info(supertype, nodes, objects, pair_rel)
        # the external (ontology) ID for this node
        flatmap_node['external_id'] = external_id
        # the (potentially) human readable name for this node
        flatmap_node['name'] = name

        # the containing layer?
        external_id, name = get_primary_info(layer, nodes, objects, pair_rel)
        flatmap_node['layer_in'] = {
            'id': layer,
            'external_id': external_id,
            'name': name
        }
    else:
        external_id, name = get_primary_info(node, nodes, objects, pair_rel)
        # the external (ontology) ID for this node
        flatmap_node['external_id'] = external_id
        # the (potentially) human readable name for this node
        flatmap_node['name'] = name
    return flatmap_node

#===============================================================================

def trace_route_part(indent, part, nodes, objects, pair_rel, graph):
    # is there a flatmap "node" for this part?
    node = find_object(part, 'apinatomy:fasciculatesIn>', objects, pair_rel)
    if node:
        flatmap_node = get_flatmap_node(node, nodes, objects, pair_rel)
        s = flatmap_node['external_id'] + "(" + flatmap_node['name'] + ")"
        if 'layer_in' in flatmap_node:
            l = flatmap_node['layer_in']
            s = s + " [in layer: " + l['external_id'] + "(" + l['name'] + ")"
        print('{} {}'.format(indent, s))
        graph.add_node(node, **flatmap_node)
    # are the more parts in this route?
    next_part = find_object(part, 'apinatomy:next>', objects, pair_rel)
    if next_part:
        new_indent = '  ' + indent
        np = trace_route_part(new_indent, next_part, nodes, objects, pair_rel, graph)
        graph.add_edge(node, np)
    else:
        # if the chain merges into another chain?
        next_part = find_object(part, 'apinatomy:nextChainStartLevels>', objects, pair_rel)
        if next_part:
            new_indent = '  ' + indent
            np = trace_route_part(new_indent, next_part, nodes, objects, pair_rel, graph)
            graph.add_edge(node, np)
    return node

#===============================================================================

def trace_route(neuron, nodes, objects, pair_rel, graph):
    print("")
    print("Neuron: {} ({})".format(nodes[neuron], neuron))
    conveys = find_object(neuron, 'apinatomy:conveys>', objects, pair_rel)
    if conveys == '':
        return
    target = find_object(conveys, 'apinatomy:target>', objects, pair_rel)
    target_root = find_object(target, 'apinatomy:rootOf>', objects, pair_rel)
    source = find_object(conveys, 'apinatomy:source>', objects, pair_rel)
    source_root = find_object(source, 'apinatomy:rootOf>', objects, pair_rel)
    print("  Conveys {} ==> {}".format(
        get_primary_name(source_root, nodes, objects, pair_rel),
        get_primary_name(target_root, nodes, objects, pair_rel)
    ))
    print("  Target: " + get_primary_name(target_root, nodes, objects, pair_rel))
    part = find_object(target, 'apinatomy:sourceOf>', objects, pair_rel)
    trace_route_part('    -->', part, nodes, objects, pair_rel, graph)
    print("  Source: " + get_primary_name(source_root, nodes, objects, pair_rel))
    part = find_object(source, 'apinatomy:sourceOf>', objects, pair_rel)
    trace_route_part('    -->', part, nodes, objects, pair_rel, graph)

#===============================================================================

def main(soma_processes, model):
    model_uri = APINATOMY_MODEL_BASE.format(model)

    j = dict(soma_processes)

    # Filter out edges not in our model
    j['edges'] = [e for e in j['edges'] if 'meta' in e
                                       and 'Annotation' in e['meta'].get('owlType', [])
                                       and model_uri in e['meta'].get('isDefinedBy', [])]

    direction = 'OUTGOING'
    (nodes, objects, subjects, edgerep, root, roots, leaves, pair_rel) = process_nodes(j, direction)

    # root node will be soma (NLX:154731)
    graph = nx.DiGraph()
    print("")
    print("Soma routes:")
    # eventually we would do all soma's
    for neuron in objects[root]:
        trace_route(neuron, nodes, objects, pair_rel, graph)

#===============================================================================

if __name__ == '__main__':
    import argparse
    import requests

    parser = argparse.ArgumentParser(description='Generate flatmap connectivity from ApiNATOMY KB (via JSON export from SciCrunch)')
    parser.add_argument('--model', required=True,
                        help='name of ApiNATOMY model')
    parser.add_argument('--soma-processes', metavar='PATH',
                        help='the path to the JSON export file')
    args = parser.parse_args()

    if args.soma_processes is None:
        response = requests.get('http://sparc-data.scicrunch.io:9000/scigraph/dynamic/demos/apinat/soma-processes.json')
        soma_processes = response.json()
    else:
        with open(args.soma_processes) as fp:
            soma_processes = json.load(fp)

    main(soma_processes, args.model)

#===============================================================================
