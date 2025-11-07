#===============================================================================

"""
This script analyzes log files from the flatmap generation process to identify missing
nodes and paths that prevent the complete rendering of connectivity paths on the map.
It cross-references these missing elements with the map source and locates possible
reasons for the missing elements. It then produces four CSV reports:
    - A list of minimal nodes required to complete path rendering
    - A list of all missing nodes
    - A list of missing paths and their corresponding minimal nodes
    - A list of inconsistencies between SVG tags, properties, aliases, and proxies

Usage:
python tools/flatmap_diagnostic.py \
    --manifest-files manifest.json [manifest2.json ...] \
    --log-files map.log [map2.log ...] \
    --output-dir output/

Arguments:
    --manifest-files  One or more JSON manifest files of the map source
    --log-files       One or more log files from the generated map
    --output-dir      Directory to save the output CSV files (default: current directory)

Output files:
    - {map-ids}-node_complete.csv  : Full list of missing nodes
    - {map-ids}-node_minimal.csv   : Minimal set of nodes required for path rendering
    - {map-ids}-paths_minimal.csv  : Minimal nodes per path
    - {manifest-ids}-source_check.csv: Inconsistencies in SVG tags, properties, aliases, and proxies

Requirements:
    - networkx
    - rdflib
    - mapknowledge
    All dependencies except pandas are installable using standard `uv sync` when installing mapmaker.
"""

#===============================================================================

from collections import defaultdict
import json
import sys
import networkx as nx
import rdflib
from mapknowledge.namespaces import NAMESPACES
from mapknowledge import KnowledgeStore
from pathlib import Path
from lxml import etree
import re
import subprocess
import tempfile
from urllib.parse import urlparse

#===============================================================================

RAW_URL = 'https://raw.githubusercontent.com/SciCrunch/NIF-Ontology'
NPO_TTL = 'ttl/npo.ttl'

#===============================================================================

SUPERCLASSES_CHECK = {
    'UBERON:0001630': 'muscle organ',
    'UBERON:0000014': 'zone of skin',
    'UBERON:0004905': 'articulation/join',
    'UBERON:0006984': 'anatomical surface',
    'UBERON:0002398': 'manus',
    'UBERON:0005913': 'zone of bone organ',
    'UBERON:0007651': 'anatomical junction',
    'FMA:65132': 'nerve',
    'UBERON:0001021': 'nerve'
}

#===============================================================================

RDFS = rdflib.Namespace("http://www.w3.org/2000/01/rdf-schema#")
q_superclasses = """
    PREFIX rdfs: <{rdfs}>
    SELECT ?superclass WHERE {{
    {cls} rdfs:subClassOf+ ?superclass .
    }}
"""

q_subclasses = """
    PREFIX rdfs: <{rdfs}>
    SELECT ?subclass WHERE {{
    ?subclass rdfs:subClassOf+ {cls} .
    }}
"""

#===============================================================================

class SourceValidation:
    def __init__(self, manifest_file, sckan_knowledge):
        manifest_file = Path(manifest_file)
        with open(manifest_file, 'r') as f:
            self.__manifest = json.load(f)

        self.__sckan_knowledge = sckan_knowledge

        # set storing issues
        self.issue_header = ('Type', 'Object code', 'Object location', 'Issue')
        self.__issues = set()

        # svg info
        # check class, id
        self.__svg_tags = {'id':[], 'class':[]}
        for svg_source in self.__manifest['sources']:
            tree = etree.parse(manifest_file.with_name(svg_source['href']))
            root = tree.getroot()
            ns = {'svg': 'http://www.w3.org/2000/svg'}
            for t in root.findall('.//svg:title', namespaces=ns):
                for tag in self.__svg_tags:
                    if(matched := re.search(fr'{tag}\(([^)]+)\)', t.text.strip())):
                        self.__svg_tags[tag].append(matched.group(1))

        # anatomical_map info
        with open(manifest_file.with_name(self.__manifest['anatomicalMap']), 'r') as fp:
            self.__anatomical_map = json.load(fp)

        # property info
        with open(manifest_file.with_name(self.__manifest['properties']), 'r') as fp:
            self.__properties = json.load(fp)
            self.__properties['networks'] = {
                c['id']: c
                for network in self.__properties.get('networks', [])
                for nt in ['centrelines', 'no-centrelines'] if nt in network
                for c in network[nt]
            }
            self.__properties['points'] = [
                p
                for network in self.__properties.get('networks', {}).values()
                for point in network['connects']
                for p in point.split('/')
            ]
            self.__properties['terms'] = defaultdict(list)
            self.__properties['a_classes'] = defaultdict(list)
            for feature_id, feature in self.__properties.get('features', {}).items():
                if (term := feature.get('models')) or (term := self.__anatomical_map.get(feature.get('class'), {}).get('term')):
                    self.__properties['terms'][term].append(feature_id)
                if (class_name := feature.get('class')) and (class_name != 'auto-hide'):
                    self.__properties['a_classes'][class_name].append(feature_id)

        # alias info
        self.__have_aliases, self.__alias_of = {}, {}
        if self.__manifest['connectivityTerms']:
            with open(manifest_file.with_name(self.__manifest['connectivityTerms']), 'r') as fp:
                for alias in json.load(fp):
                    id = alias.get('id') if isinstance(alias.get('id'), str) else (alias.get('id')[0], tuple(alias.get('id')[1]))
                    self.__have_aliases[id] = []
                    for aliased in alias['aliases']:
                        aliased = aliased if isinstance(aliased, str) else (aliased[0], tuple(aliased[1]))
                        self.__have_aliases[id].append(aliased)
                        self.__alias_of[aliased] = self.__alias_of.get(aliased, []) + [id]

        # proxy info
        self.__have_proxies, self.__proxy_of = {}, {}
        if self.__manifest['proxyFeatures']:
            with open(manifest_file.with_name(self.__manifest['proxyFeatures']), 'r') as fp:
                proxies = json.load(fp)
                for proxy in proxies:
                    self.__have_proxies[proxy['feature']] = []
                    for proxied in proxy['proxies']:
                        self.__have_proxies[proxy['feature']].append(proxied)
                        self.__proxy_of[proxied] = self.__proxy_of.get(proxied, []) + [proxy['feature']]

    def __record_issue(self, type, object_code, object_location, issue):
        self.__issues.add((type, object_code, object_location, issue))

    def __is_node_or_term_in_property_or_proxy(self, node_or_term):
        if isinstance(node_or_term, str):
            return node_or_term in self.__properties['terms'] or node_or_term in self.__have_proxies
        elif isinstance(node_or_term, tuple):
            for term in [node_or_term[0]] + list(node_or_term[1]):
                if term not in self.__properties['terms'] and term not in self.__have_proxies:
                    return False
            return True

    def __svg_validation(self):
        for id in set(self.__svg_tags['id']):
            if (id in self.__properties['features']
                or id in self.__properties['networks']
                or id in self.__properties['points']):
                continue
            else:
                self.__record_issue('id', id, 'SVG', 'SVG id not in properties')
            if self.__svg_tags['id'].count(id) > 1:
                self.__record_issue('id', id, 'SVG', 'Multiple SVG ids found')

        for c in set(self.__svg_tags['class']):
            if c not in self.__anatomical_map:
                self.__record_issue('class', c, 'SVG', 'SVG class not in anatomical map')

    def __alias_validation(self):
        # validating alias_of to sckan_knowledge
        for k, v in self.__alias_of.items():
            if len(v) > 1:
                self.__record_issue('alias', k, 'Connectivity Terms', f'Alias term maps to multiple ids: {v}')
            if k not in self.__sckan_knowledge['nodes'] and k not in self.__sckan_knowledge['terms']:
                self.__record_issue('alias', k, 'Connectivity Terms', f'Alias term not in sckan knowledge nodes or terms')
        # validating have_aliases to properties and anatomical_map
        for k in self.__have_aliases:
            if not self.__is_node_or_term_in_property_or_proxy(k):
                self.__record_issue('aliased', k, 'Connectivity Terms', f'Aliased term not in properties and proxies')

    def __proxy_validation(self):
        # validating have_proxies to sckan_knowledge
        for k in self.__have_proxies:
            if k not in self.__sckan_knowledge['terms']:
                self.__record_issue('proxied', k, 'Proxy Features', f'Proxied feature not in sckan knowledge terms')

        # validating proxy_of to properties
        for k in self.__proxy_of:
            if k not in self.__properties['terms']:
                self.__record_issue('proxy', k, 'Proxy Features', f'Proxy term not in properties')

    def __anatomical_map_validation(self):
        for k in self.__anatomical_map:
            if k not in self.__properties['a_classes'] and k not in self.__svg_tags['class']:
                self.__record_issue('class', k, 'Anatomical Map', 'Anatomical map class not in properties features and SVG')

    def __properties_validation(self):
        # validating classes in properties
        for k, v in self.__properties['classes'].items():
            if (k in self.__anatomical_map or v.get('models')) and (k in self.__svg_tags['class'] or k in self.__properties['a_classes']):
                continue
            if k not in self.__svg_tags['class'] and k not in self.__properties['a_classes']:
                self.__record_issue('class', k, 'Properties', 'Properties class not in SVG and property features')
            elif k not in self.__anatomical_map and not v.get('models'):
                self.__record_issue('class', k, 'Properties', 'Properties class not in anatomical map and has no models')

        # validating anatomical classes in properties
        for k in self.__properties['a_classes']:
            if k not in self.__anatomical_map and k not in self.__properties['classes']:
                self.__record_issue('feature class', k, 'Properties', 'Properties anatomical class not in anatomical map, and property classes')

        # validating networks in properties
        for k in self.__properties['networks']:
            if k not in self.__svg_tags['id']:
                self.__record_issue('network', k, 'Properties', 'Properties network id not in SVG')

        # validating points in properties
        for k in self.__properties['points']:
            if k not in self.__svg_tags['id']:
                self.__record_issue('point', k, 'Properties', 'Properties point id not in SVG')

        # validating features in properties
        for k in self.__properties['features']:
            if k not in self.__svg_tags['id']:
                self.__record_issue('id', k, 'Properties', 'Properties feature id not in SVG')
            if not self.__properties['features'][k].get('models') and self.__anatomical_map.get(self.__properties['features'][k].get('class'), {}).get('term') is None:
                self.__record_issue('id', k, 'Properties', 'Properties feature id has no models and its class has no term in anatomical map')

    def analize(self):
        self.__svg_validation()
        self.__alias_validation()
        self.__proxy_validation()
        self.__anatomical_map_validation()
        self.__properties_validation()

    def get_issues(self):
        return sorted(self.__issues, key=lambda x: (x[2], x[3]))

    def get_manifest_id(self):
        return self.__manifest['id']


#===============================================================================

def analyse_flatmap_source(manifest_files, sckan_knowledge, output_dir='.'):
    svs = []
    manifest_ids = []
    for manifest_file in manifest_files:
        parsed = urlparse(manifest_file)
        if parsed.scheme in ("http", "https"):
            # github url
            parts = urlparse(manifest_file).path.strip("/").split("/")
            user, repo, _, commit, *file_parts = parts
            repo_url = f"https://github.com/{user}/{repo}.git"
            file_relative = "/".join(file_parts)
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp_path = Path(tmpdir)

                try:
                # Clone specific commit
                    subprocess.run(["git", "init"], cwd=tmp_path, check=True)
                    subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=tmp_path, check=True)
                    subprocess.run(["git", "fetch", "--depth", "1", "origin", commit], cwd=tmp_path, check=True)
                    subprocess.run(["git", "checkout", "FETCH_HEAD"], cwd=tmp_path, check=True)
                except subprocess.CalledProcessError as e:
                    print(f"Error: Could not clone or checkout {repo_url} at commit {commit}")
                    print("Specify the manifest file locally instead.")
                    sys.exit(1)

                # Path to the file
                file_path = tmp_path / file_relative
                sv = SourceValidation(file_path, sckan_knowledge)
                sv.analize()
                manifest_ids.append(sv.get_manifest_id())
                svs.append(sv)
        else:
            # local file
            sv = SourceValidation(manifest_file, sckan_knowledge)
            sv.analize()
            manifest_ids.append(sv.get_manifest_id())
            svs.append(sv)

    output_dir = Path(output_dir)
    with open(output_dir / f"{'-'.join(manifest_ids)}-source_check.csv", 'w') as fp:
        fp.write(f"{','.join(svs[0].issue_header)},Source\n")
        sources = [sv.get_manifest_id() for sv in svs]
        for issue in svs[0].get_issues():
            if all(issue in sv.get_issues() for sv in svs):
                fp.write(f"{','.join([f'\"{str(term)}\"' if "'" in str(term) else str(term) for term in issue])},{';'.join(sources)}\n")
        print(f"Written {output_dir / f'{'-'.join(manifest_ids)}-source_check.csv'}")

#===============================================================================

def identify_missing_nodes(sckan_knowledge, log_data_list, map_type, g_rdf, output_dir='.'):
    # group and aggregate paths
    missing_paths = {log_data['path'] for log_data in log_data_list if log_data.get('msg') == 'Path is not rendered due to partial rendering'}
    missing_nodes = defaultdict(dict)
    for log_data in log_data_list:
        if log_data.get('msg') == 'Cannot find feature for connectivity node':
            node_key = (log_data['node'][0], tuple(log_data['node'][1]))
            if node_key not in missing_nodes:
                missing_nodes[node_key] = {
                    'name': log_data['name'],
                    'map': tuple()
                }
            if log_data.get('map'):
                missing_nodes[node_key]['map'] += (log_data['map'],)

    path_dicts = {}
    for path_kn in sckan_knowledge['knowledge']:
        if edges := path_kn.get('connectivity'):
            conn = [((src[0], tuple(src[1])), (dst[0], tuple(dst[1]))) for src, dst in edges]
            G = nx.Graph()
            G.add_edges_from(conn)
            degrees = dict(G.degree())  # type: ignore
            min_degree = min(degrees.values())
            path_dicts[path_kn['id']] = {
                'terminals': set([node for node, deg in degrees.items() if deg == min_degree]),
                'nodes': set(degrees.keys()),
                'phenotypes': path_kn.get('phenotypes')
            }

    for node, node_dict in missing_nodes.items():
        types, children = [], []
        for term_id in [node[0], *node[1]]:
            # superclass info
            superclasses = [
                NAMESPACES.curie(str(row.superclass))
                for row in g_rdf.query(q_superclasses.format(rdfs=RDFS, cls=term_id))
            ]
            if (superclass:=list(set(superclasses) & set(SUPERCLASSES_CHECK.keys()))):
                types += [superclass[0]]
            elif superclasses:
                types += [superclasses[0]]
            else:
                types += ['']
            # subclass info
            subclasses = [
                NAMESPACES.curie(str(row.subclass))
                for row in g_rdf.query(q_subclasses.format(rdfs=RDFS, cls=term_id))
            ]
            if subclasses:
                children.extend([subclasses[0]])
            else:
                children.extend([])
        node_dict['superclasses'] = tuple(types)
        node_dict['superclass labels'] = tuple(
            SUPERCLASSES_CHECK.get(sp, labels[0] if (labels:=[str(l) for l in g_rdf.objects(rdflib.URIRef(NAMESPACES.uri(sp)), RDFS.label)]) else '-')
            for sp in types
        )
        node_dict['subclasses'] = tuple(children)
        node_dict['subclass labels'] = tuple(
            tuple(
                labels[0] if (labels:=[str(l) for l in g_rdf.objects(rdflib.URIRef(NAMESPACES.uri(sc)), RDFS.label)]) else '-'
                for sc in children
            )
        )

    # check missing_paths', missing terminals minimal completion
    output_dir = Path(output_dir)

    path_minimal_columns = ['Path', 'Phenotypes', 'Needed node', 'Node label', 'Superclass', 'Superclass label', 'Subclass', 'Subclass label', 'Maps']
    path_minimal_nodes = []
    for path_id in missing_paths:
        if path_id not in path_dicts:
            continue
        # check terminals
        terminal_needed, terminal_label, terminal_superclass, superclass_label, terminal_subclass, subclass_label, maps = [], [], [], [], [], [], []
        for node in path_dicts[path_id]['terminals'] & set(missing_nodes.keys()):
            terminal_needed += [node]
            terminal_label += [missing_nodes[node]['name']]
            terminal_superclass += [missing_nodes[node]['superclasses']]
            superclass_label += [missing_nodes[node]['superclass labels']]
            terminal_subclass += [missing_nodes[node]['subclasses']]
            subclass_label += [missing_nodes[node]['subclass labels']]
            maps += [missing_nodes[node]['map']]
        path_minimal_nodes.append([path_id, path_dicts[path_id]['phenotypes'], terminal_needed, terminal_label, terminal_superclass, superclass_label, terminal_subclass, subclass_label, maps])

    with open(output_dir / (map_type + '-paths_minimal.csv'), 'w') as fp:
        fp.write(f"{','.join(path_minimal_columns)}\n")
        for row in path_minimal_nodes:
            fp.write(f"{row[0]},\"{row[1]}\",\"{row[2]}\",\"{row[3]}\",\"{row[4]}\",\"{row[5]}\",\"{row[6]}\",\"{row[7]}\",\"{str(row[8])}\"\n")
        print(f"Written {output_dir / (map_type + '-paths_minimal.csv')}")

    # check minimal nodes
    node_minimal_columns = ['Needed node', 'Node label', 'Superclass', 'Superclass label', 'Subclass', 'Subclass label', 'Paths', 'Phenotypes', 'Maps']
    node_minimal_dict = defaultdict(lambda: {'Paths': [], 'Phenotypes': [], 'Maps': []})
    for path_id, phenotypes, needed_nodes, node_labels, superclasses, superclass_labels, subclasses, subclass_labels, maps_list in path_minimal_nodes:
        for i, needed_node in enumerate(needed_nodes):
            node_minimal_dict[needed_node]['Needed node'] = needed_node
            node_minimal_dict[needed_node]['Node label'] = node_labels[i]
            node_minimal_dict[needed_node]['Superclass'] = superclasses[i]
            node_minimal_dict[needed_node]['Superclass label'] = superclass_labels[i]
            node_minimal_dict[needed_node]['Subclass'] = subclasses[i]
            node_minimal_dict[needed_node]['Subclass label'] = subclass_labels[i]
            node_minimal_dict[needed_node]['Paths'] += [path_id]
            node_minimal_dict[needed_node]['Phenotypes'] += [phenotypes]
            node_minimal_dict[needed_node]['Maps'].extend(maps_list)

    with open(output_dir / (map_type + '-node_minimal.csv'), 'w') as fp:
        fp.write(f"{','.join(node_minimal_columns)}\n")
        for node, data in node_minimal_dict.items():
            unique_maps = list(set(data['Maps']))
            fp.write(f"\"{data['Needed node']}\",\"{data['Node label']}\",\"{data['Superclass']}\",\"{data['Superclass label']}\",\"{data['Subclass']}\",\"{data['Subclass label']}\",\"{data['Paths']}\",\"{data['Phenotypes']}\",\"{unique_maps}\"\n")
        print(f"Written {output_dir / (map_type + '-node_minimal.csv')}")

    # check complete nodes
    node_complete_columns = ['Needed node', 'Node label', 'Superclass', 'Superclass label', 'Subclass', 'Subclass label', 'Paths', 'Phenotypes']
    node_complete_dicts = defaultdict(lambda: {'Paths': [], 'Phenotypes': []})
    for path_id in path_dicts:
        for node in path_dicts[path_id]['nodes'] & set(missing_nodes.keys()):
            node_complete_dicts[node]['Needed node'] = node
            node_complete_dicts[node]['Node label'] = missing_nodes[node]['name']
            node_complete_dicts[node]['Superclass'] = missing_nodes[node]['superclasses']
            node_complete_dicts[node]['Superclass label'] = missing_nodes[node]['superclass labels']
            node_complete_dicts[node]['Subclass'] = missing_nodes[node]['subclasses']
            node_complete_dicts[node]['Subclass label'] = missing_nodes[node]['subclass labels']
            node_complete_dicts[node]['Paths'] += [path_id]
            node_complete_dicts[node]['Phenotypes'] += [path_dicts[path_id]['phenotypes']]

    with open(output_dir / (map_type + '-node_complete.csv'), 'w') as fp:
        fp.write(f"{','.join(node_complete_columns)}\n")
        for node, data in node_complete_dicts.items():
            fp.write(f"\"{data['Needed node']}\",\"{data['Node label']}\",\"{data['Superclass']}\",\"{data['Superclass label']}\",\"{data['Subclass']}\",\"{data['Subclass label']}\",\"{data['Paths']}\",\"{data['Phenotypes']}\"\n")
        print(f"Written {output_dir / (map_type + '-node_complete.csv')}")

#===============================================================================

def loading_sources(generated_folders):
    # Load log files into a list of dictionaries

    log_data_list = []
    map_type = []
    sckan_version = None
    store_directory = '.'
    map_sources = []
    for generated_folder in generated_folders:
        generated_folder = Path(generated_folder)
        log_file = generated_folder / 'mapmaker.log.json'
        with open(log_file, 'r') as f:
            log_data = [json.loads(line) for line in f]
            # Extract map type
            map_name = next((entry.get('id') for entry in log_data if entry['msg'] == 'Making map'), None)
            map_type.append(str(map_name))

            # Standardize log entries, add 'map' field and convert 'node' lists to tuples
            for log_entry in log_data:
                log_entry['map'] = map_name
                if 'node' in log_entry and isinstance(log_entry['node'], list):
                    log_entry['node'] = (log_entry['node'][0], tuple(log_entry['node'][1]))
                if sckan_version is None and log_entry['msg'].startswith('Using knowledge source'):
                    sckan_version = log_entry['msg'].split(': ')[-1]
                if log_entry['msg'].startswith('Map Knowledge version') and ' cache ' in log_entry['msg']:
                    store_directory = log_entry['msg'].split(' cache ')[-1]
        log_data_list.extend(log_data)

        # Collect map sources
        with open(generated_folder / 'index.json', 'r') as f:
            index_data = json.load(f)
            map_sources.append(index_data.get('source', 'unknown'))

    map_type = '-'.join(map_type)

    # Load NPO ontology graph
    g = rdflib.Graph()
    try:
        g.parse(f'{RAW_URL}/{sckan_version}/{NPO_TTL}', format='turtle')
    except Exception as e:
        print(f"Warning: Could not load NPO ontology: {e}")

    # Load sckan knowledge
    store = KnowledgeStore(
        sckan_version=sckan_version,
        store_directory=Path(store_directory).parent
    )
    sckan_knowledge = {'source': sckan_version, 'knowledge': [], 'nodes': set(), 'terms': set()}
    for path in store.connectivity_paths():
        path_kn = store.entity_knowledge(path)
        sckan_knowledge['knowledge'].append(path_kn)
        for edge in path_kn['connectivity']:
            for node in edge:
                sckan_knowledge['nodes'].add((node[0], tuple(node[1])))
                sckan_knowledge['terms'].update([node[0], *node[1]])
    store.close()



    return sckan_knowledge, log_data_list, map_type, g, map_sources

#===============================================================================

def main():
    import logging
    logging.basicConfig(level=logging.INFO)

    import argparse
    parser = argparse.ArgumentParser(description='Extract missing nodes and paths for the rendered map.')
    parser.add_argument('--manifest-files', nargs='*', default=None, help='Optional manifest file(s) of a flatmap source')
    parser.add_argument('--map-folders', required=True, nargs='+', help='Folders containing log files of the generated map')
    parser.add_argument('--output-dir', help='Output directory for the results', default='.')
    args = parser.parse_args()

    # load sources
    sckan_knowledge, log_data_list, map_type, g_rdf, map_sources = loading_sources(args.map_folders)

    # identify missing nodes and paths
    identify_missing_nodes(sckan_knowledge, log_data_list, map_type, g_rdf, args.output_dir)

    # analyse flatmap source
    if args.manifest_files:
        analyse_flatmap_source(args.manifest_files, sckan_knowledge, args.output_dir)
    else:
        analyse_flatmap_source(map_sources, sckan_knowledge, args.output_dir)

#===============================================================================

if __name__ == '__main__':
#=========================
    main()
#===============================================================================
