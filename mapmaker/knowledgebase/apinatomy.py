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
#
# Acknowledgements:
#   This code is based on ``connectivity pairs`` from
#   `here <https://github.com/SciCrunch/sparc-curation/blob/master/docs/queries.org#connectivity-based>`_
#   and ``pyontutils.core`` and ``nifstd_tools.simplify`` in
#   https://github.com/tgbugs/pyontutils and has been reworked to remove the need
#   to install the full ``pyontutils`` package along with its dependencies.
#
#===============================================================================

import networkx as nx
from rdflib.extras import external_graph_libs as egl

#===============================================================================

from pyontutils.core import OntGraph, Edge

#===============================================================================

class nifstd:
    @staticmethod
    def sub(edge, match=None):
        return edge['sub'] == match if match is not None else edge['sub']

    @staticmethod
    def pred(edge, match=None):
        return edge['pred'] == match if match is not None else edge['pred']

    @staticmethod
    def obj(edge, match=None):
        return edge['obj'] == match if match is not None else edge['obj']

    @staticmethod
    def ematch(blob, select, match, *matches, matchf=lambda ms: True):
        return [edge for edge in blob['edges'] if select(edge, match) and matchf(matches)]

    @staticmethod
    def listIn(container, maybe_contained, *, strict=True):
        """ strictly sublists no equality here """
        lc = len(container)
        lmc = len(maybe_contained)
        if lc > lmc or not strict and lc == lmc:
            z = maybe_contained[0]
            if z in container:
                substart = container.index(z)
                subcontained = maybe_contained[1:]
                if not subcontained:
                    return substart
                ssp1 = substart + 1
                subcontainer = container[ssp1:]
                maybe = nifstd.listIn(subcontainer, subcontained, strict=False)
                if maybe is None or maybe > 0:
                    maybe = nifstd.listIn(subcontainer, maybe_contained, strict=False)
                    if maybe is not None:
                        return ssp1 + maybe
                else:
                    return substart

    @staticmethod
    def zap(ordered_nodes, predicates, oe2, blob):
        """ don't actually zap, wait until the end so that all
            deletions happen after all additions """
        e = Edge((ordered_nodes[0].toPython(),  ##<<<<
                '-'.join(predicates),
                ordered_nodes[-1].toPython()))
        new_e = e.asOboGraph()   ## <<<<<<<<<<
        blob['edges'].append(new_e)
        to_remove = [e.asOboGraph() for e in oe2]
        return to_remove

    @staticmethod
    def simplify(collapse, blob):
        to_remove = []
        for coll in collapse:
            exclude = set(p for p in coll)
            candidates = [e for e in blob['edges'] if e['pred'] in exclude]
            for c in candidates:
                # make sure we can remove the edges later
                # if they have meta the match will fail
                if 'meta' in c:
                    c.pop('meta')
            if candidates:
                edges = [Edge.fromOboGraph(c) for c in candidates]
                g = OntGraph().populate_from_triples(e.asRdf() for e in edges)
                nxg = egl.rdflib_to_networkx_multidigraph(g)
                connected = list(nx.weakly_connected_components(nxg))  # FIXME may not be minimal
                ends = [e.asRdf()[-1] for e in edges if e.p == coll[-1]]
                for c in connected:
                    #log.debug('\n' + pformat(c))
                    nxgt = nx.MultiDiGraph()
                    nxgt.add_edges_from(nxg.edges(c, keys=True))
                    ordered_nodes = list(nx.topological_sort(nxgt))
                    paths = [p
                             for n in nxgt.nodes()
                             for e in ends
                             for p in list(nx.all_simple_paths(nxgt, n, e))
                             if len(p) == len(coll) + 1]
                    for path in sorted(paths):
                        ordered_edges = nxgt.edges(path, keys=True)
                        oe2 = [Edge.fromNx(e) for e in ordered_edges if all([n in path for n in e[:2]])]
                        predicates = [e.p for e in oe2]
                        #log.debug('\n' + pformat(oe2))
                        if predicates == coll: #in collapse:
                            to_remove.extend(nifstd.zap(path, predicates, oe2, blob))
                        else:  # have to retain this branch to handle cases where the end predicate is duplicated
                            #log.error('\n' + pformat(predicates) +
                            #            '\n' + pformat(coll))
                            for preds in [coll]:
                                sublist_start = nifstd.listIn(predicates, preds)
                                if sublist_start is not None:
                                    i = sublist_start
                                    j = i + len(preds)
                                    npath = path[i:j + 1]  # + 1 to include final node
                                    oe2 = oe2[i:j]
                                    predicates = predicates[i:j]
                                    to_remove.extend(nifstd.zap(npath, predicates, oe2, blob))
        for r in to_remove:
            if r in blob['edges']:
                blob['edges'].remove(r)
        #log.debug('\n' + pformat(blob['edges']))
        return blob  # note that this is in place modification so sort of supruflous

#===============================================================================

class Apinatomy:
    axon = 'SAO:280355188'
    dendrite = 'SAO:420754792'
    BAG = 'apinatomy:BAG'
    annotates = 'apinatomy:annotates'
    cloneOf = 'apinatomy:cloneOf'
    endsIn = 'apinatomy:endsIn'
    external = 'apinatomy:external'
    fasciculatesIn = 'apinatomy:fasciculatesIn'
    inheritedExternal = 'apinatomy:inheritedExternal'
    inheritedExternal_s = 'apinatomy:inheritedExternal*'
    internalIn = 'apinatomy:internalIn'
    layerIn = 'apinatomy:layerIn'
    lyphs = 'apinatomy:lyphs'
    next = 'apinatomy:next'
    next_s = 'apinatomy:next*'
    publications = 'apinatomy:publications'
    topology_s = 'apinatomy:topology*'

    @staticmethod
    def neurons_for_model_cypher(model_id):
        # From https://github.com/SciCrunch/sparc-curation/blob/master/docs/queries.org#neru-model-populations
        # See also https://github.com/SciCrunch/sparc-curation/blob/master/docs/queries.org#neru-model-populations-and-references
        return """
            MATCH (start:Ontology {{iri: "{MODEL_ID}"}})
            <-[:isDefinedBy]-(external:Class)
            -[:subClassOf*]->(:Class {{iri: "http://uri.interlex.org/tgbugs/uris/readable/NeuronEBM"}}) // FIXME
            RETURN external
        """.format(MODEL_ID=model_id)

    @staticmethod
    def deblob(blob, remove_converge=False):
        # FIXME I think we may be over or under simplifying just a bit
        # somehow getting double links at the end of the chain

        # FIXME issue here is that chain roots -> levels goes to all levels of the chain which is NOT
        # what we want, TODO need to filter out cases where the target of levels is pointed to by next
        # this is implemented downstream from here I think
        blob['edges'] = [
            e for e in blob['edges'] if not nifstd.pred(e, 'apinatomy:levels') or
            (nifstd.pred(e, 'apinatomy:levels') and
             not nifstd.ematch(
                blob,
                lambda ei, m: (nifstd.obj(ei, m) and nifstd.pred(ei, 'apinatomy:next')),
                nifstd.obj(e))
        )]

        #[e for e in blob['edges'] if pred(e, 'apinatomy:rootOf')]

        blob = nifstd.simplify(
            [['apinatomy:target', 'apinatomy:rootOf', 'apinatomy:levels'],
             ['apinatomy:conveyingLyph', 'apinatomy:topology'],
             ['apinatomy:conveys', 'apinatomy:source', 'apinatomy:sourceOf'],
             ['apinatomy:conveys', 'apinatomy:target', 'apinatomy:sourceOf'],
             ['apinatomy:cloneOf', 'apinatomy:inheritedExternal'],
             ['apinatomy:conveyingLyph', 'apinatomy:inheritedExternal'],],
            blob)
        edges = blob['edges']
        nindex = {n['id']:n for n in blob['nodes']}  # FIXME silent errors ;_;
        for e in edges:
            if e['pred'] in (
                    'apinatomy:target-apinatomy:rootOf-apinatomy:levels',
                    'apinatomy:conveys-apinatomy:source-apinatomy:sourceOf',
                    'apinatomy:conveys-apinatomy:target-apinatomy:sourceOf',):
                e['pred'] = 'apinatomy:next*'
            if e['pred'] == 'apinatomy:conveyingLyph-apinatomy:topology':
                e['pred'] = 'apinatomy:topology*'
            if e['pred'] in (
                    'apinatomy:conveyingLyph-apinatomy:inheritedExternal',
                    'apinatomy:cloneOf-apinatomy:inheritedExternal',):
                e['pred'] = 'apinatomy:inheritedExternal*'
            if nifstd.pred(e, Apinatomy.topology_s):
                # move topology to be a property not a node to make the layout cleaner
                nindex[nifstd.sub(e)]['topology'] = nifstd.obj(e)

        if remove_converge:
            # remove topology edges
            edges = blob['edges'] = [e for e in edges if not nifstd.pred(e, top)]
            # remove process type edges
            edges = blob['edges'] = [e for e in edges if not (nifstd.obj(e, Apinatomy.axon)
                                                           or nifstd.obj(e, Apinatomy.dendrite))]

        blob['edges'] = [dict(s) for s in set(frozenset({k:v for k, v in d.items()
                                                         if k != 'meta'}.items()) for d in blob['edges'])]
        sos = set(sov for e in blob['edges'] for sov in (e['sub'], e['obj']))
        blob['nodes'] = [n for n in blob['nodes'] if n['id'] in sos]
        somas = [e for e in edges if e['pred'] == Apinatomy.internalIn]
        externals = [e for e in edges if e['pred'] == Apinatomy.external]
        ordering_edges = [e for e in edges if e['pred'] == Apinatomy.next]
        return blob, edges, somas, externals, ordering_edges

    @staticmethod
    def isLayer(blob, match):
        return nifstd.ematch(
            blob,
            lambda e, m: (nifstd.sub(e, m) and nifstd.pred(e, Apinatomy.layerIn)),
            match)

    @staticmethod
    def reclr(blob, start_link):
        # recurse up the hierarchy until fasIn endIn intIn terminates
        collect = []
        layer = []
        col = True

        def select_ext(e, m, collect=collect):
            nonlocal col
            if nifstd.sub(e, m):
                if nifstd.pred(e, Apinatomy.cloneOf):  # should be zapped during simplify
                    return nifstd.ematch(blob, select_ext, nifstd.obj(e))
                if (nifstd.pred(e, Apinatomy.external)
                 or nifstd.pred(e, Apinatomy.inheritedExternal)
                 or nifstd.pred(e, Apinatomy.inheritedExternal_s)):
                    external = nifstd.obj(e)
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
            if nifstd.sub(e, m):
                if (nifstd.pred(e, Apinatomy.layerIn)
                 or nifstd.pred(e, Apinatomy.fasciculatesIn)
                 or nifstd.pred(e, Apinatomy.endsIn)
                 or nifstd.pred(e, Apinatomy.internalIn)):
                    col = not Apinatomy.isLayer(blob, nifstd.obj(e))
                    nifstd.ematch(blob, select_ext, nifstd.obj(e))
                    nifstd.ematch(blob, select, nifstd.obj(e))

        nifstd.ematch(blob, select, start_link)
        return collect

    @staticmethod
    def layer_regions(blob, start):
        direct = [nifstd.obj(t) for t in
                  nifstd.ematch(blob, (lambda e, m: nifstd.sub(e, m)
                                    and (nifstd.pred(e, Apinatomy.internalIn)
                                      or nifstd.pred(e, Apinatomy.endsIn)
                                      or nifstd.pred(e, Apinatomy.fasciculatesIn))),
                             start)]
        layers = [nifstd.obj(t) for d in direct for t in
                  nifstd.ematch(blob, (lambda e, m: nifstd.sub(e, m)
                                    and Apinatomy.isLayer(blob, m)
                                    and (nifstd.pred(e, Apinatomy.inheritedExternal)
                                      or nifstd.pred(e, Apinatomy.inheritedExternal_s)
                                      or nifstd.pred(e, Apinatomy.external))),
                             d)]
        lregs = []
        if layers:
            ldir = [nifstd.obj(t) for d in direct for t in
                    nifstd.ematch(blob, (lambda e, m: nifstd.sub(e, m)
                                      and nifstd.pred(e, Apinatomy.layerIn)),
                               d)]
            lregs = [nifstd.obj(t) for d in ldir for t in
                     nifstd.ematch(blob, (lambda e, m: nifstd.sub(e, m)
                                       and not Apinatomy.isLayer(blob, m)
                                       and (nifstd.pred(e, Apinatomy.inheritedExternal)
                                         or nifstd.pred(e, Apinatomy.external))),
                                d)]
        regions = [nifstd.obj(t) for d in direct for t in
                   nifstd.ematch(blob, (lambda e, m: nifstd.sub(e, m)
                                     and not Apinatomy.isLayer(blob, m)
                                     and (nifstd.pred(e, Apinatomy.inheritedExternal)
                                       or nifstd.pred(e, Apinatomy.inheritedExternal_s)
                                       or nifstd.pred(e, Apinatomy.external))),
                              d)]

        lrs = Apinatomy.reclr(blob, start)

        assert not (lregs and regions), (lregs, regions)  # not both
        regions = lregs if lregs else regions
        return start, tuple(lrs)

    @staticmethod
    def parse_connectivity(data):
    #============================
        blob, *_ = Apinatomy.deblob(data)
        starts = [nifstd.obj(e) for e in blob['edges'] if nifstd.pred(e, Apinatomy.lyphs)]
        nexts = [(nifstd.sub(t), nifstd.obj(t)) for start in starts for t in
                  nifstd.ematch(blob, (lambda e, m: nifstd.pred(e, Apinatomy.next)
                                              or nifstd.pred(e, Apinatomy.next_s)), None)]
        nodes = sorted(set([tuple([Apinatomy.layer_regions(blob, e) for e in p]) for p in nexts]))

        def anatomical_layer(pair_list):
            if pair_list[0][0] is None:
                anatomical_id = pair_list[0][1]
                layers = []
            else:
                anatomical_id = pair_list[0][0]
                layers = [pair_list[0][1]]
            layers += [ layer for pair in pair_list[1:] for layer in pair ]
            return (anatomical_id, tuple(layers))

        return list(set((anatomical_layer(n0[1:][0]), anatomical_layer(n1[1:][0])) for n0, n1 in nodes if n0[1:] != n1[1:]))

    #===========================================================================

    @staticmethod
    def neuron_knowledge(neuron, data):
    #==================================
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
            if nifstd.sub(edge, neuron) and nifstd.pred(edge, Apinatomy.annotates):
                apinatomy_neuron = nifstd.obj(edge)
                break
        if apinatomy_neuron is not None:
            publications = []
            for edge in data['edges']:
                if nifstd.sub(edge, apinatomy_neuron) and nifstd.pred(edge, Apinatomy.publications):
                    publications.append(nifstd.obj(edge))
            knowledge['publications'] = publications
        knowledge['connectivity'] = Apinatomy.parse_connectivity(data)
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
                    # 'type': ???? <<<<<<<<<<<<<<<<<<<<<<<<<<
                })
        return knowledge

#===============================================================================
