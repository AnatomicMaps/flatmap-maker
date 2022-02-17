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

import os

#===============================================================================

from mapmaker.utils import log, request_json

from .apinatomy import Apinatomy

#===============================================================================

INTERLEX_ONTOLOGIES = ['ILX', 'NLX']

CONNECTIVITY_ONTOLOGIES = [ 'ilxtr' ]

SPARC_ONTOLOGIES = ['CL', 'EMAPA', 'FMA', 'NCBITaxon', 'UBERON']

APINATOMY_MODEL_PREFIX = 'https://apinatomy.org/uris/models/'

#===============================================================================

SCICRUNCH_API = 'https://scicrunch.org/api/1'

SCICRUNCH_SPARC_API = f'{SCICRUNCH_API}/sparc-scigraph'

SCICRUNCH_SPARC_CONNECTIVITY = 'http://sparc-data.scicrunch.io:9000/scigraph'
SCICRUNCH_SPARC_CYPHER = f'{SCICRUNCH_SPARC_CONNECTIVITY}/cypher/execute'

#===============================================================================

SCICRUNCH_INTERLEX_VOCAB = f'{SCICRUNCH_API}/ilx/search/curie/{{TERM}}'

SCICRUNCH_SPARC_VOCAB = f'{SCICRUNCH_SPARC_API}/vocabulary/id/{{TERM}}.json'

#===============================================================================

SCICRUNCH_SPARC_APINATOMY = f'{SCICRUNCH_SPARC_CONNECTIVITY}/dynamic/demos/apinat'

SCICRUNCH_CONNECTIVITY_MODELS = f'{SCICRUNCH_SPARC_APINATOMY}/modelList.json'

SCICRUNCH_CONNECTIVITY_NEURONS = f'{SCICRUNCH_SPARC_APINATOMY}/neru-5/{{NEURON_ID}}.json'

#===============================================================================

class SciCrunch(object):
    def __init__(self):
        self.__unknown_entities = []
        self.__scigraph_key = os.environ.get('SCICRUNCH_API_KEY')
        if self.__scigraph_key is None:
            log.warn('Undefined SCICRUNCH_API_KEY: SciCrunch knowledge will not be looked up')

    def get_knowledge(self, entity):
        knowledge = {}
        if self.__scigraph_key is not None:
            params = {
                'api_key': self.__scigraph_key,
                'limit': 9999,
            }
            ontology = entity.split(':')[0]
            if   ontology in INTERLEX_ONTOLOGIES:
                data = request_json(SCICRUNCH_INTERLEX_VOCAB.format(TERM=entity),
                                    params=params)
                if data is not None:
                    knowledge['label'] = data.get('data', {}).get('label', entity)
            elif ontology in CONNECTIVITY_ONTOLOGIES:
                data = request_json(SCICRUNCH_CONNECTIVITY_NEURONS.format(NEURON_ID=entity),
                                    params=params)
                if data is not None:
                    knowledge = Apinatomy.neuron_knowledge(entity, data)
            elif ontology in SPARC_ONTOLOGIES:
                data = request_json(SCICRUNCH_SPARC_VOCAB.format(TERM=entity),
                                    params=params)
                if data is not None:
                    knowledge['label'] = data.get('labels', [entity])[0]
            elif entity.startswith(APINATOMY_MODEL_PREFIX):
                params['cypherQuery'] = Apinatomy.neurons_for_model_cypher(entity)
                data = request_json(SCICRUNCH_SPARC_CYPHER,
                                    params=params)
                if data is not None:
                    knowledge = Apinatomy.model_knowledge(entity, data)
        if len(knowledge) == 0 and entity not in self.__unknown_entities:
            log.warn('Unknown anatomical entity: {}'.format(entity))
            self.__unknown_entities.append(entity)
        return knowledge

#===============================================================================
