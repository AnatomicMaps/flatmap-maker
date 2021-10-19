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

import mapmaker.knowledgebase.connectivity as connectivity

from mapmaker.settings import settings
from mapmaker.utils import log, request_json

#===============================================================================

INTERLEX_ONTOLOGIES = ['ILX', 'NLX']

CONNECTIVITY_ONTOLOGIES = [ 'ilxtr' ]

SCIGRAPH_ONTOLOGIES = ['FMA', 'NCBITaxon', 'UBERON']

#===============================================================================

SCICRUNCH_CONNECTIVITY = 'http://sparc-data.scicrunch.io:9000/scigraph/dynamic/demos/apinat/neru-4/{}.json'

SCICRUNCH_INTERLEX_VOCAB = 'https://scicrunch.org/api/1/ilx/search/curie/{}'
SCICRUNCH_SCIGRAPH_VOCAB = 'https://scicrunch.org/api/1/sparc-scigraph/vocabulary/id/{}.json'

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
            ontology = entity.split(':')[0]
            if   ontology in INTERLEX_ONTOLOGIES:
                data = request_json('{}?api_key={}'.format(
                        SCICRUNCH_INTERLEX_VOCAB.format(entity),
                        self.__scigraph_key))
                if data is not None:
                    knowledge['label'] = data.get('data', {}).get('label', entity)

            elif ontology in CONNECTIVITY_ONTOLOGIES:
                data = request_json('{}?api_key={}'.format(
                        SCICRUNCH_CONNECTIVITY.format(entity),
                        self.__scigraph_key))
                if data is not None:
                    knowledge = connectivity.knowledge(entity, data)

            elif ontology in SCIGRAPH_ONTOLOGIES:
                data = request_json('{}?api_key={}'.format(
                        SCICRUNCH_SCIGRAPH_VOCAB.format(entity),
                        self.__scigraph_key))
                if data is not None:
                    knowledge['label'] = data.get('labels', [entity])[0]

        if len(knowledge) == 0 and entity not in self.__unknown_entities:
            log.warn('Unknown anatomical entity: {}'.format(entity))
            self.__unknown_entities.append(entity)

        return knowledge

#===============================================================================
