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

import pandas

#===============================================================================

from mapmaker.knowledgebase import KnowledgeStore
from mapmaker.knowledgebase.pubmed import pubmed_knowledge

#===============================================================================

COLUMNS = [
    'model',
    'neuron',
    'label',
    'synonym',
    'pubmed',
    'doi',
    'title',
    'authors',
    'journal',
    'date',
]

#===============================================================================

def publication_records(model, store):
    for neuron in store.entity_knowledge(model)['paths']:
        data = store.entity_knowledge(neuron['id'])
        if len(data['publications']) == 0:
            yield {
                'model': model,
                'neuron': neuron['id'],
                'label': data['long-label'],
                'synonym': data['label'],
                'pubmed': None,
                'doi': None,
                'title': None,
                'authors': None,
                'journal': None,
                'date': None,
            }
        else:
            for publication in data['publications']:
                pubmed = pubmed_knowledge(publication)
                yield {
                    'model': model,
                    'neuron': neuron['id'],
                    'label': data['long-label'],
                    'synonym': data['label'],
                    'pubmed': publication,
                    'doi': pubmed.get('doi'),
                    'title': pubmed.get('title'),
                    'authors': ', '.join(pubmed.get('authors', [])),
                    'journal': pubmed.get('source'),
                    'date': pubmed.get('date'),
                }

#===============================================================================

def publications_to_xlsx(model, database_dir, output_file):
    store = KnowledgeStore(database_dir)
    rows = list(publication_records(model, store))
    pandas.DataFrame(
        columns = COLUMNS,
        data = rows,
    ).to_excel(output_file)

#===============================================================================

if __name__ == '__main__':
    publications_to_xlsx(
        'https://apinatomy.org/uris/models/keast-bladder',
        '/Users/dave/Flatmaps/map-server/flatmaps',
        'publication_records.xlsx'
    )

#===============================================================================
