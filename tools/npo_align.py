#===============================================================================

from pathlib import Path
from tqdm import tqdm
import json
import pandas as pd
from sentence_transformers import SentenceTransformer, util
import torch
from xml.dom import minidom
import re
import itertools

#===============================================================================

from mapknowledge import KnowledgeStore

#===============================================================================

BIOBERT = 'gsarti/biobert-nli'
biobert_model = SentenceTransformer(BIOBERT)
store = KnowledgeStore()

#===============================================================================

class PathError(Exception):
    pass

#===============================================================================

def search_term(query, term_embeddings, term_ids, term_names, k=5):
    query = query.lower()
    query_emb = biobert_model.encode(query)
    cos_scores = util.cos_sim(query_emb, term_embeddings)[0]        
    top_results = torch.topk(cos_scores, k=k)
    results = []
    for score, idx in zip(top_results[0], top_results[1]):
        results += [(term_ids[idx], term_names[idx], score.item())]
    return results

def align_missing_nodes(manifest_file, missing_file, output_dir):
        
        ### Loading anatomical map
        #anatomical_terms = 
        # {'urinary_1': {'term': 'UBERON:0001008', 'name': 'renal system'},
        #  'urinary_2': {'term': 'UBERON:0001255', 'name': 'urinary bladder'},
        #  ...
        # }

        manifest_file = Path(manifest_file)
        with open(manifest_file, 'r') as f:
            manifest = json.load(f)

        anatomical_file = manifest_file.parent/manifest.get('anatomicalMap')
        with open(anatomical_file, 'r') as f:
            anatomical_terms = json.load(f)
            
        ### Loading property and stored in anatomical term
        # load property
        property_file = manifest_file.parent/manifest.get('properties')
        with open(property_file, 'r') as f:
            properties = json.load(f)
            
        # load from features key
        for key, val in properties['features'].items():
            if (_model:=val.get('models')) is not None:
                anatomical_terms[key] = {'term': _model, 'name': val.get('name')}
            elif (_class:=val.get('class')) is not None:
                if (_anat:=anatomical_terms.get(_class)) is not None:
                    anatomical_terms[key] = _anat  
                else:
                    pass
                    # print(key) # probably unused anatomy  -- no model or term
                    
        # load from features networks->centrelines for those having models
        for network in properties['networks'][0]['centrelines']:
            if (_model:=network.get('models')) is not None:
                anatomical_terms[network['id']] = {'term':network.get('models')}
                
        ### Complete anatomical_terms with no name and check it's concistency
        output_dir = Path(output_dir)
        prop_path = output_dir/'collected_property.json'
        anaterms = {}
        if prop_path.exists():
            with open(prop_path, 'r') as f:
                anaterms = json.load(f)

        for term_id in tqdm(set([anaterm['term'] for anaterm in anatomical_terms.values()])):
            if term_id not in anaterms:
                anaterms[term_id] = store.label(term_id)

        with open(prop_path, 'w') as f:
            json.dump(anaterms, f, )
            
        ## Select anaterms that available in svg only
        ### Get all id used in csv file
        if manifest.get('kind', '') != 'functional':
            svg_file = manifest_file.parent/(manifest.get('sources')[0].get('href'))
            doc = minidom.parse(str(svg_file))  # parseString also exists
            svg_used_ids = [path.firstChild.nodeValue[path.firstChild.nodeValue.index('id(')+3:path.firstChild.nodeValue.index(')')].strip() for path in doc.getElementsByTagName('title') if 'id(' in path.firstChild.nodeValue]
            doc.unlink()
            
            ### Filter anaterms that only available in svg
            # Get terms_ids and term_names
            term_ids, term_names = [], []
            for idx in set(svg_used_ids) & set(anatomical_terms.keys()):
                term_id = anatomical_terms[idx]['term']
                if term_id not in term_ids:
                    term_ids += [term_id]
                    term_names += [anaterms.get(term_id, term_id).lower()]
            
            ## generate term embedding
            term_embeddings = biobert_model.encode(term_names)
            
            def get_candidates(name):
                k = 5
                candidates = [[st] for st in search_term(name, term_embeddings, term_ids, term_names, k)]

                phrase_candidates = []
                if len(phrases:=name.split(' IN ')) > 1:
                    term_candidates = [search_term(phrase, term_embeddings, term_ids, term_names, k) for phrase in phrases]
                    phrase_candidates = list(itertools.product(*term_candidates))
                
                of_candidates = []
                if len(phrases:= re.split(r' IN | of ',name)) > 1:
                    term_candidates = [search_term(phrase, term_embeddings, term_ids, term_names, k) for phrase in phrases]
                    of_candidates = list(itertools.product(*term_candidates))
                    
                nodes = []
                for candidate in (candidates+phrase_candidates+of_candidates):
                    node = list(zip(*candidate))
                    node[0] = [key for key, _ in itertools.groupby(node[0])]
                    node[0] = (node[0][0], tuple(node[0][1:] if len(node[0])>1 else []))
                    node[1] = [key for key, _ in itertools.groupby(node[1])]
                    node[2] = sum(node[2])/len(node[2])
                    nodes += [node]

                # return sorted list
                sorted_nodes = sorted(nodes, key=lambda x: x[2], reverse=True)
                selected_nodes, tmp = [], set()
                for node in sorted_nodes:
                    if node[0] not in tmp:
                        selected_nodes += [node]
                        tmp.add(node[0])
                    if len(selected_nodes) == k: break
                return selected_nodes            


            ### load missing NPO nodes in flatmap
            missing_file = Path(missing_file)
            df_missing = pd.read_csv(missing_file)
            df_missing['Align candidates'] = df_missing['Node Name'].apply(lambda x: get_candidates(x))
            df_missing = df_missing.explode('Align candidates')
            df_missing[['Align candidates', 'Candidate name', 'Score']] = df_missing['Align candidates'].apply(pd.Series)
            df_missing['Selected'] = ''
            df_missing['Note'] = ''
            df_missing.to_csv(output_dir/f"{missing_file.name.split('.')[0]}_alignment.csv")

#===============================================================================

def main():
    import argparse
    import sys

    parser = argparse.ArgumentParser(description="Checking nodes and edges completeness in the generated flatmap")
    parser.add_argument('--manifest', dest='manifest', metavar='MANIFEST', help='Path of flatmap manifest')
    parser.add_argument('--output-dir', dest='output_dir', metavar='OUTPUT_DIR', help='Directory to store the check results')
    parser.add_argument('--missing-file', dest='missing_file', metavar='MISSING_FILE', help='The missing node file generated by npo_check.py')
    
    try:
        args = parser.parse_args()

        align_missing_nodes(args.manifest, args.missing_file, args.output_dir)
    except PathError as error:
        sys.stderr.write(f'{error}\n')
        sys.exit(1)
    sys.exit(0)

#===============================================================================

if __name__ == '__main__':
    main()

#===============================================================================

# To run this script, poetry install with alignment option is mandatory
#   poetry install --with alignments

# This script will generate candidates of missing node allignments. 
# The results then will be curated by expert to identify alias

# Command:
# python ./npo_align.py --manifest `manifest file` \
#                       --output-dir 'a directory to save csv file' 
#                       --missing-file `file name sucha as npo_rat_missing_nodes.csv`

# Results:
#   {missing file name}_alignment.csv

# After curating this file, the identified alias can be merged with connectivity_terms.json using npo_alias.py
