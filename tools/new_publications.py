from pprint import pprint

from mapmaker.knowledgebase import CONNECTIVITY_ONTOLOGIES, KNOWLEDGE_BASE, KnowledgeStore, SciCrunch

def update_publications(database_dir, knowledge_base=KNOWLEDGE_BASE):
    remote_kb = SciCrunch()
    local_kb = KnowledgeStore(database_dir, knowledge_base=knowledge_base)

    for entity in local_kb.flatmap_entities(None):
        if entity.split(':')[0] in CONNECTIVITY_ONTOLOGIES:
            knowledge = remote_kb.get_knowledge(entity)
            pprint(knowledge)
            local_kb.update_publications(entity, knowledge.get('publications', []))

    local_kb.close()

if __name__ == '__main__':
#=========================
    update_publications('/Users/dave/Flatmaps/map-server/flatmaps', 'prod_kb_v2.db')


## Need to also update labels for neuron paths...
