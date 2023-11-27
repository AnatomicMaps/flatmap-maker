#===============================================================================

from pathlib import Path
from tqdm import tqdm
import json
import pandas as pd
import ast

#===============================================================================

from mapmaker import MapMaker
from mapknowledge import KnowledgeStore

#===============================================================================

class PathError(Exception):
    pass

#===============================================================================

store_npo = KnowledgeStore(npo=True)
store_sckan = KnowledgeStore()

map_node_name = {}

def load_npo_connectivities(file_location, clean_connectivity):
    # load all connectivities from npo
    # currently we use NPO rather than scicrunch due to neuron-nlp availability
    phenotypes = {
        ('ilxtr:SensoryPhenotype',): 'sensory',
        ('ilxtr:IntrinsicPhenotype',): 'intracardiac',
        ('ilxtr:ParasympatheticPhenotype', 'ilxtr:PostGanglionicPhenotype'): 'post-ganglionic parasympathetic',
        ('ilxtr:PostGanglionicPhenotype', 'ilxtr:SympatheticPhenotype'): 'post-ganglionic sympathetic',
        ('ilxtr:ParasympatheticPhenotype', 'ilxtr:PreGanglionicPhenotype'): 'pre-ganglionic parasympathetic',
        ('ilxtr:PreGanglionicPhenotype', 'ilxtr:SympatheticPhenotype'): 'pre-ganglionic sympathetic',
    }
    knowledge_file = Path(file_location)/'npo_knowledge.json'
    
    if knowledge_file.exists() and not clean_connectivity:
        with open(knowledge_file, 'r') as f:
            npo_connectivities = json.load(f)
    else:
        npo_connectivities = {}
        for model in store_npo.connectivity_models('NPO'):
            conns = store_npo.entity_knowledge(model)
            for conn in tqdm(conns['paths']):
                npo_connectivities[conn['id']] = store_npo.entity_knowledge(conn['id'])
                conn_phenotype = tuple(sorted(npo_connectivities[conn['id']]['phenotypes']))
                npo_connectivities[conn['id']]['phenotypes'] = phenotypes.get(conn_phenotype, str(conn_phenotype))
        with open(knowledge_file, 'w') as f:
            json.dump(npo_connectivities, f, indent=4)
    
    return npo_connectivities

def get_missing_nodes(map_log, save_file):
    nodes_to_neuron_types = {}
    for k, v in map_log.items():
        for node in v.get('missing_nodes', []):
            nodes_to_neuron_types[node] = nodes_to_neuron_types.get(node, []) + [k]
            
    df = pd.DataFrame(columns=['Node', 'Node Name', 'Appear in'])
    for node, k_types in tqdm(nodes_to_neuron_types.items()):
        name = get_node_name(node)
        name = ' IN '.join(name)
        df.loc[len(df)] = [
            node,
            name,
            '\n'.join(list(set(k_types)))
        ]
    df = df.sort_values('Appear in')
    df.to_csv(f'{save_file}', index=False)
    return df

def load_log_file(log_file, npo_knowledge):
    # a function to load log file
    missing_nodes = {} # node:label
    missing_segments = {} # neuron_path:segment
    map_log = {}
    with open(log_file, 'r') as f:
        while line := f.readline():
            tag = 'Cannot find feature for connectivity node '
            if tag in line:
                line = line.split(tag)[-1].split(') (')
                missing_nodes[ast.literal_eval(f'{line[0]})')] = f'({line[1]}'.strip()
                
            tag = 'Cannot find any sub-segments of centreline for '
            if tag in line:
                path_id = line[33:].split(': ')[0]
                if path_id not in missing_segments: missing_segments[path_id] = []
                missing_segments[path_id] += [line.split(tag)[-1][1:-2]]
        
    for path_id, connectivities in npo_knowledge.items():
        map_log[path_id] = {}
        nodes, edges = set(), set()
        m_edges = set()
        for edge in connectivities['connectivity']:
            node_0 = (edge[0][0], tuple(edge[0][1]))
            node_1 = (edge[1][0], tuple(edge[1][1]))
            flat_nodes = set([edge[0][0]] + list(edge[0][1]) + [edge[1][0]] + list(edge[1][1]))
            nodes.add(node_0)
            nodes.add(node_1)
            edges.add((node_0, node_1))
            
            # check if nodes are in the missing list
            if node_0 in missing_nodes or node_1 in missing_nodes:
                m_edges.add((node_0, node_1))
            # check if edge contain missing segment
            if len(set(missing_segments.get(path_id, [])) & flat_nodes) > 1:
                m_edges.add((node_0, node_1))
        m_nodes = nodes & set(missing_nodes.keys())
        r_nodes = nodes - set(missing_nodes.keys())
        r_edges = edges - m_edges
        complete = 'Complete' if len(m_nodes)==0 and len(m_edges)==0 else 'Partial'
        map_log[path_id] = {
            'original_nodes': nodes,
            'missing_nodes': m_nodes,
            'rendered_nodes': r_nodes,
            'original_edges': edges,
            'missing_edges': m_edges,
            'rendered_edges': r_edges,
            'completeness': complete,
            'missing_segment': missing_segments.get(path_id, [])
        }
    
    return map_log

def get_node_name(node):
    if node[0] is not None:
        name = store_npo.label(node[0])
        name = [store_sckan.label(node[0]) if name == node[0] else name]
    else:
        name = [node[0]]
    for n in node[1]:
        if n is not None:
            loc = store_npo.label(n)
            loc = store_sckan.label(n) if n == loc else loc
        else:
            loc = n
        name += [loc]
    map_node_name[node] = (name[0], tuple(name[1:] if len(name)>1 else ()))
    return name

def organised_and_save_map_log(map_log, save_file):
    # a function to organised data into dataframe and then save it as csv file
    ### complete neuron:
    df = pd.DataFrame(columns=['Neuron NPO', 'Completeness', 'Missing Nodes', 'Missing Node Name', 'Missing Edges', 'Missing Edge Name', 'Missing Segments', 'Missing Segment Name', 'Rendered Edges', 'Rendered Edge Name'])
    keys = [
        'missing_nodes',
        'missing_edges',
        'missing_segments',
        'rendered_edges'
    ]
    
    for neuron, value in tqdm(map_log.items()):
        info = {}
        for key in keys:
            info[key] = '\n'.join([str(mn) for mn in list(value.get(key,[]))])
            
            if len(value.get(key,[]))>0:
                if key not in ['missing_edges', 'rendered_edges']:
                    names = [map_node_name[node] for node in value.get(key,[])]
                else:
                    names = []
                    for edge in value.get(key,[]):
                        if edge[0] not in map_node_name: get_node_name(edge[0])
                        if edge[1] not in map_node_name: get_node_name(edge[1])
                        names += [(map_node_name[edge[0]], map_node_name[edge[1]])]
            else:
                names = ''
            info[key+'_name'] = '\n'.join([str(mnn) for mnn in names])
        df.loc[len(df)] = [neuron, value['completeness']] + list(info.values())
                           
    df = df.sort_values('Completeness')
    df.to_csv(f'{save_file}', index=False)
    return df

#===============================================================================

def check_npo_in_flatmap(manifest, artefac_dir, output_dir, species, clean_connectivity):
    manifest = Path(manifest)
    log_file = Path(artefac_dir)/(f"{species}.{manifest.name.split('.')[0]}.log")
    if log_file.exists():
        log_file.unlink()
    options = {
        'source': manifest,
        'output': artefac_dir,
        'ignoreGit': True,
        'debug': True,
        'logFile': log_file,
        'cleanConnectivity': clean_connectivity
    }
    mapmaker = MapMaker(options)
    mapmaker.make()

    npo_connectivities = load_npo_connectivities(artefac_dir, clean_connectivity)
    map_log = load_log_file(log_file=log_file, npo_knowledge=npo_connectivities)

    missing_node_file = Path(output_dir)/f'npo_{species}_missing_nodes.csv'
    rendered_file = Path(output_dir)/f'npo_{species}_rendered.csv'

    get_missing_nodes(map_log, missing_node_file)
    organised_and_save_map_log(map_log, rendered_file)


def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Checking nodes and edges completeness in the generated flatmap")
    parser.add_argument('--manifest', dest='manifest', metavar='MANIFEST', help='Path of flatmap manifest')
    parser.add_argument('--artefac-dir', dest='artefac_dir', metavar='ARTEFAC_DIR', help='Directory to store artifac files to check NPO completeness')
    parser.add_argument('--output-dir', dest='output_dir', metavar='OUTPUT_DIR', help='Directory to store the check results')
    parser.add_argument('--species', dest='species', metavar='SPECIES', help='The species of the checked flatmap')
    parser.add_argument('--clean-connectivity', dest='cleanConnectivity', action='store_true', help='Run mapmaker as a clean connectivity')

    try:
        args = parser.parse_args()
        check_npo_in_flatmap(args.manifest, args.artefac_dir, args.output_dir, args.species, args.cleanConnectivity)
    except PathError as error:
        sys.stderr.write(f'{error}\n')
        sys.exit(1)
    sys.exit(0)

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================

# Documentation
# after running the environment with `poetry shell`, run this script

# Command:
# python ./npo_check.py --manifest `manifest file` \
#                       --artefac-dir `any directory to store generated files` \
#                       --output-dir 'a directory to save csv file' 
#                       --species `such as rat, female, male, etc`

# Results:
#   - npo_{species}_missing.csv
#   - npo_{species}_rendered.csv

# in order to generate candidate alignment, run npo_align.py file
