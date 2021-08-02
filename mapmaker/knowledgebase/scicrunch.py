#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2019  David Brooks
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

import json
import os
import sqlite3

#===============================================================================

import openpyxl
import requests

from mapmaker.settings import settings
from mapmaker.utils import FilePath, log

#===============================================================================

INTERLEX_ONTOLOGIES = ['ILX', 'NLX']

SCIGRAPH_ONTOLOGIES = ['FMA', 'UBERON']

#===============================================================================

SCICRUNCH_API_KEY = "xBOrIfnZTvJQtobGo8XHRvThdMYGTxtf"
SCICRUNCH_INTERLEX_VOCAB = 'https://scicrunch.org/api/1/ilx/search/curie/{}'
SCICRUNCH_SCIGRAPH_VOCAB = 'https://scicrunch.org/api/1/sparc-scigraph/vocabulary/id/{}.json'

#===============================================================================

LOOKUP_TIMEOUT = 5    # seconds

#===============================================================================

def request_json(endpoint):
    try:
        response = requests.get(endpoint, timeout=LOOKUP_TIMEOUT)
        if response.status_code == requests.codes.ok:
            try:
                return response.json()
            except json.JSONDecodeError:
                error = 'invalid JSON returned'
        else:
            error = 'status: {}'.format(response.status_code)
    except requests.exceptions.RequestException as exception:
        error = 'exception: {}'.format(exception)
    log.warn("Couldn't access {}: {}".format(endpoint, error))
    return None

#===============================================================================

class LabelDatabase(object):
    def __init__(self):
        database = os.path.join(settings.get('output'), 'labels.sqlite')
        if settings.get('refreshLabels', False):
            try:
                os.remove(database)
            except FileNotFoundError:
                pass
        new_db = not os.path.exists(database)
        self.__db = sqlite3.connect(database)
        self.__cursor = self.__db.cursor()
        if new_db:
            self.__cursor.execute('CREATE TABLE labels (entity text, label text)')
            self.__db.commit()
        self.__unknown_entities = []

    def close(self):
        self.__db.close()

    def set_label(self, entity, label):
        self.__cursor.execute('REPLACE INTO labels(entity, label) VALUES (?, ?)', (entity, label))
        self.__db.commit()

    def get_label(self, entity):
        self.__cursor.execute('SELECT label FROM labels WHERE entity=?', (entity,))
        row = self.__cursor.fetchone()
        if row is not None:
            return row[0]
        label = None
        ontology = entity.split(':')[0]
        if   ontology in INTERLEX_ONTOLOGIES:
            data = request_json('{}?api_key={}'.format(
                    SCICRUNCH_INTERLEX_VOCAB.format(entity),
                    SCICRUNCH_API_KEY))
            if data is not None:
                label = data.get('data', {}).get('label', entity)
        elif ontology in SCIGRAPH_ONTOLOGIES:
            data = request_json('{}?api_key={}'.format(
                    SCICRUNCH_SCIGRAPH_VOCAB.format(entity),
                    SCICRUNCH_API_KEY))
            if data is not None:
                label = data.get('labels', [entity])[0]
        elif entity not in self.__unknown_entities:
            log.warn('Unknown anatomical entity: {}'.format(entity))
            self.__unknown_entities.append(entity)
        if label is None:
            label = entity
        else:
            self.set_label(entity, label)
        return label



