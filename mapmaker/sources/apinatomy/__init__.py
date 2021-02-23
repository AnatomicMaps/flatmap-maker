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


#===============================================================================
'''
def print_node(indent, node, objects, nodes, pair_rel):
    for o in objects[node]:
        predicate = pair_rel[(node, o)]
        print(indent + '|--' + predicate + ((nodes[o] + " (" + o + ")" ) if nodes[o] else o))
        next_level = indent + '|   '
        print_node(next_level, o, objects, nodes, pair_rel)
'''
#===============================================================================

class ApiNATOMY(object):
    def __init__(self, soma_processes, model):
        self.__uri = APINATOMY_MODEL_BASE.format(model)

        # Filter out edges not in our model
        soma_processes['edges'] = [e for e in soma_processes['edges']
                                     if 'meta' in e
                                    and 'Annotation' in e['meta'].get('owlType', [])
                                    and self.__uri in e['meta'].get('isDefinedBy', [])]

        self.__nodes = {n['id']:n['lbl'] for n in soma_processes['nodes']}

        CYCLE = 'CYCLE DETECTED'
        self.__nodes[CYCLE] = CYCLE  # make sure we can look up the cycle

        self.__edgerep = ['{} {} {}'.format(self.__nodes[e['sub']], e['pred'], self.__nodes[e['obj']])
                            for e in soma_processes['edges']]
        # note that if there are multiple relations between s & p then last one wins
        # sorting by the predicate should help keep it a bit more stable
        self.__pair_rel = {(e['sub'], e['obj']): e['pred'] + '>'
                            for e in sorted(soma_processes['edges'], key = lambda e: e['pred'])}

        self.__objects = defaultdict(list)  # note: not all nodes are objects!
        for edge in soma_processes['edges']:
            self.__objects[edge['obj']].append(edge['sub'])

        self.__subjects = defaultdict(list)
        for edge in soma_processes['edges']:
            self.__subjects[edge['sub']].append(edge['obj'])

        self.__objects, self.__subjects = self.__subjects, self.__objects   # flip for the tree

        ss, so = set(self.__subjects), set(self.__objects)
        roots = so - ss
        leaves = ss - so

        if len(roots) == 1:
            root = next(iter(roots))
        else:
            root = '*ROOT*'
            self.__nodes[root] = 'ROOT'
            self.__objects[root] = list(roots)

        # root node will be soma (NLX:154731)   ### WHY ????
        self.__graph = nx.DiGraph()

        print("Soma routes:")
        # eventually we would do all soma's
        for neuron in self.__objects[root]:
            self.__trace_route(neuron)

    def __find_object(self, subject, predicate):
        for o in self.__objects[subject]:
            if self.__pair_rel[(subject, o)] == predicate:
                return o
        return ''

    def __get_primary_info(self, id):
        if id:
            # default name is the label if one is provided, otherwise the raw id is used
            name = self.__nodes[id] if self.__nodes[id] else id
            # if an external identifier is defined, that should be preferred
            external_id = self.__find_object(id, 'apinatomy:external>')
        else:
            name = "UNKOWN"
            external_id = "REALLY_UNKNOWN"
        return external_id, name

    def __get_primary_name(self, id):
        external_id, name = self.__get_primary_info(id)
        if external_id:
            name = external_id + "(" + name + ")"
        return name

    def __get_flatmap_node(self, node):
        flatmap_node = {
            'id': node,
        }
        # layered type or direct?
        layer = self.__find_object(node, 'apinatomy:layerIn>')
        if layer:
            clone = self.__find_object(node, 'apinatomy:cloneOf>')
            supertype = self.__find_object(clone, 'apinatomy:supertype>')
            external_id, name = self.__get_primary_info(supertype)
            # the external (ontology) ID for this node
            flatmap_node['external_id'] = external_id
            # the (potentially) human readable name for this node
            flatmap_node['name'] = name

            # the containing layer?
            external_id, name = self.__get_primary_info(layer)
            flatmap_node['layer_in'] = {
                'id': layer,
                'external_id': external_id,
                'name': name
            }
        else:
            external_id, name = self.__get_primary_info(node)
            # the external (ontology) ID for this node
            flatmap_node['external_id'] = external_id
            # the (potentially) human readable name for this node
            flatmap_node['name'] = name
        return flatmap_node

    def __trace_route_part(self, indent, part):
        # is there a flatmap "node" for this part?
        node = self.__find_object(part, 'apinatomy:fasciculatesIn>')
        if node:
            flatmap_node = self.__get_flatmap_node(node)
            s = flatmap_node['external_id'] + "(" + flatmap_node['name'] + ")"
            if 'layer_in' in flatmap_node:
                l = flatmap_node['layer_in']
                s = s + " [in layer: " + l['external_id'] + "(" + l['name'] + ")"
            print('{} {}'.format(indent, s))
            self.__graph.add_node(node, **flatmap_node)
        # are the more parts in this route?
        next_part = self.__find_object(part, 'apinatomy:next>')
        if next_part:
            new_indent = '  ' + indent
            np = self.__trace_route_part(new_indent, next_part)
            self.__graph.add_edge(node, np)
        else:
            # if the chain merges into another chain?
            next_part = self.__find_object(part, 'apinatomy:nextChainStartLevels>')
            if next_part:
                new_indent = '  ' + indent
                np = self.__trace_route_part(new_indent, next_part)
                self.__graph.add_edge(node, np)
        return node

    def __trace_route(self, neuron):
        print("")
        print("Neuron: {} ({})".format(self.__nodes[neuron], neuron))
        conveys = self.__find_object(neuron, 'apinatomy:conveys>')
        if conveys == '':
            return
        target = self.__find_object(conveys, 'apinatomy:target>')
        target_root = self.__find_object(target, 'apinatomy:rootOf>')

        source = self.__find_object(conveys, 'apinatomy:source>')
        source_root = self.__find_object(source, 'apinatomy:rootOf>')
        print("  Conveys {} ==> {}".format(
            self.__get_primary_name(source_root),
            self.__get_primary_name(target_root)
        ))

        print("  Target: " + self.__get_primary_name(target_root))
        part = self.__find_object(target, 'apinatomy:sourceOf>')
        self.__trace_route_part('    -->', part)

        print("  Source: " + self.__get_primary_name(source_root))
        part = self.__find_object(source, 'apinatomy:sourceOf>')
        self.__trace_route_part('    -->', part)

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

    ApiNATOMY(soma_processes, args.model)

#===============================================================================
