import json
from mapmaker.knowledgebase import KnowledgeStore

def main():
    knowledge_store = KnowledgeStore('/Users/dave/Flatmaps/map-server/flatmaps')
    with open('anatomical_map.json', 'r') as fp:
        anatomical_map = json.loads(fp.read())
    named_map = {}
    for cls, term in anatomical_map.items():
        if isinstance(term, dict):
            if 'name' not in term:
                term['name'] = knowledge_store.label(term['term'])
            named_map[cls] = term
        else:
            label = knowledge_store.label(term)
            if label == term:
                label = "term is unknown in SciCrunch..."
            named_map[cls] = {
                'term': term,
                'name': label
        }
    with open('anatomical_map_with_names.json', 'w') as fp:
        fp.write(json.dumps(named_map, indent=4))

if __name__ == '__main__':
    main()
