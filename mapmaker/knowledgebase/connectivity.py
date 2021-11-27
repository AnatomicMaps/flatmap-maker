#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019-21  David Brooks
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

import dataclasses
from dataclasses import dataclass
from typing import List

#===============================================================================

import nifstd_tools.simplify as nif

#===============================================================================

def neurons_for_model_cypher(model_id):
    # From https://github.com/SciCrunch/sparc-curation/blob/master/docs/queries.org#neru-model-populations
    # See also https://github.com/SciCrunch/sparc-curation/blob/master/docs/queries.org#neru-model-populations-and-references
    return """
        MATCH (start:Ontology {{iri: "{MODEL_ID}"}})
        <-[:isDefinedBy]-(external:Class)
        -[:subClassOf*]->(:Class {{iri: "http://uri.interlex.org/tgbugs/uris/readable/NeuronEBM"}}) // FIXME
        RETURN external
    """.format(MODEL_ID=model_id)

#===============================================================================

class ConnectivityParser(object):
    ANNOTATES = 'apinatomy:annotates'
    CLONEOF = 'apinatomy:cloneOf'
    INTERNALIN = 'apinatomy:internalIn'
    LYPHS = 'apinatomy:lyphs'
    NEXT = 'apinatomy:next'
    NEXTS = 'apinatomy:next*'
    PUBLICATIONS = 'apinatomy:publications'

    def __init__(self):
        self.__known_terms = set()

    @property
    def known_terms(self):
        return sorted(list(self.__known_terms))

    @staticmethod
    def isLayer(blob, s):
        return nif.ematch(blob, (lambda e, m: nif.sub(e, m) and nif.pred(e, nif.layerIn)), s)

    @staticmethod
    def reclr(blob, start_link):
        # recurse up the hierarchy until fasIn endIn intIn terminates
        collect = []
        layer = []
        col = True

        def select_ext(e, m, collect=collect):
            nonlocal col
            if nif.sub(e, m):
                if nif.pred(e, ConnectivityParser.CLONEOF):  # should be zapped during simplify
                    return nif.ematch(blob, select_ext, nif.obj(e))
                if (nif.pred(e, nif.ext)
                 or nif.pred(e, nif.ie)
                 or nif.pred(e, nif.ies)):
                    external = nif.obj(e)
                    if col:
                        if layer:
                            l = layer.pop()
                        else:
                            l = None
                        r = [b for b in blob['nodes'] if b['id'] == external][0]['id']  # if this is empty we are in big trouble
                        collect.append((l, r))
                    else:
                        l = [b for b in blob['nodes'] if b['id'] == external][0]['id']
                        layer.append(l)
                    return external

        def select(e, m):
            nonlocal col
            if nif.sub(e, m):
                if (nif.pred(e, nif.layerIn)
                 or nif.pred(e, nif.fasIn)
                 or nif.pred(e, nif.endIn)
                 or nif.pred(e, ConnectivityParser.INTERNALIN)):
                    col = not ConnectivityParser.isLayer(blob, nif.obj(e))
                    nif.ematch(blob, select_ext, nif.obj(e))
                    nif.ematch(blob, select, nif.obj(e))

        nif.ematch(blob, select, start_link)
        return collect

    @staticmethod
    def layer_regions(blob, start):
        direct = [nif.obj(t) for t in
                  nif.ematch(blob, (lambda e, m: nif.sub(e, m)
                                    and (nif.pred(e, ConnectivityParser.INTERNALIN)
                                      or nif.pred(e, nif.endIn)
                                      or nif.pred(e, nif.fasIn))),
                             start)]
        layers = [nif.obj(t) for d in direct for t in
                  nif.ematch(blob, (lambda e, m: nif.sub(e, m)
                                    and ConnectivityParser.isLayer(blob, m)
                                    and (nif.pred(e, nif.ie)
                                      or nif.pred(e, nif.ies)
                                      or nif.pred(e, nif.ext))),
                             d)]
        lregs = []
        if layers:
            ldir = [nif.obj(t) for d in direct for t in
                    nif.ematch(blob, (lambda e, m: nif.sub(e, m)
                                      and nif.pred(e, nif.layerIn)),
                               d)]
            lregs = [nif.obj(t) for d in ldir for t in
                     nif.ematch(blob, (lambda e, m: nif.sub(e, m)
                                       and not ConnectivityParser.isLayer(blob, m)
                                       and (nif.pred(e, nif.ie)
                                         or nif.pred(e, nif.ext))),
                                d)]
        regions = [nif.obj(t) for d in direct for t in
                   nif.ematch(blob, (lambda e, m: nif.sub(e, m)
                                     and not ConnectivityParser.isLayer(blob, m)
                                     and (nif.pred(e, nif.ie)
                                       or nif.pred(e, nif.ies)
                                       or nif.pred(e, nif.ext))),
                              d)]

        lrs = ConnectivityParser.reclr(blob, start)

        assert not (lregs and regions), (lregs, regions)  # not both
        regions = lregs if lregs else regions
        return start, tuple(lrs)

    def __add_node_pair_terms(self, node_pairs):
    #===========================================
        for pair in node_pairs:
            for term in pair:
                if term is not None:
                    self.__known_terms.add(term)

    def parse_connectivity(self, data):
    #==================================
        blob, *_ = nif.apinat_deblob(data)
        starts = [nif.obj(e) for e in blob['edges'] if nif.pred(e, self.LYPHS)]
        nexts = [(nif.sub(t), nif.obj(t)) for start in starts for t in
                  nif.ematch(blob, (lambda e, m: nif.pred(e, self.NEXT)
                                              or nif.pred(e, self.NEXTS)), None)]
        nodes = sorted(set([tuple([self.layer_regions(blob, e) for e in p]) for p in nexts]))
        connectivity = list(set((n0[1:][0], n1[1:][0]) for n0, n1 in nodes if n0[1:] != n1[1:]))
        for n0, n1 in connectivity:
            self.__add_node_pair_terms(n0)
            self.__add_node_pair_terms(n1)
        return connectivity

    def neuron_knowledge(self, neuron, data):
    #========================================
        knowledge = {
            'id': neuron,
            'label': neuron
        }
        for node in data['nodes']:
            if node.get('id') == neuron:
                knowledge['label'] = node['meta'].get('synonym', [neuron])[0]
                knowledge['long-label'] = node['lbl']
                break
        apinatomy_neuron = None
        for edge in data['edges']:
            if nif.sub(edge, neuron) and nif.pred(edge, self.ANNOTATES):
                apinatomy_neuron = nif.obj(edge)
                break
        if apinatomy_neuron is not None:
            publications = []
            for edge in data['edges']:
                if nif.sub(edge, apinatomy_neuron) and nif.pred(edge, self.PUBLICATIONS):
                    publications.append(nif.obj(edge))
            knowledge['publications'] = publications
        knowledge['connectivity'] = self.parse_connectivity(data)
        return knowledge

    @staticmethod
    def model_knowledge(model, data):
    #================================
        # Process result of ``neurons_for_model_cypher(model_id)``
        knowledge = {
            'id': model,
            'paths': []
        }
        for node in data['nodes']:
            if 'Class' in node.get('meta', {}).get('types', []):
                path_id = node['id']
                knowledge['paths'].append({
                    'id': path_id,
                    'models': path_id,
                })
        return knowledge

#===============================================================================
