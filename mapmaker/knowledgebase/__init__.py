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

#===============================================================================

class AnatomicalMap(object):
    """
    Map ``class`` identifiers in Powerpoint to anatomical entities.

    The mapping is specified in a CSV file:

        - Has a header row which **must** include columns ``Power point identifier``, ``Preferred ID``, and `UBERON``.
        - A shape's ``class`` is used as the key into the ``Power point identifier`` column to obtain a preferred anatomical identifier for the shape.
        - If no ``Preferred ID`` is defined then the UBERON identifier is used.
        - The shape's label is set from its anatomical identifier; if none was assigned then the label is set to the shape's class.
    """
    def __init__(self, mapping_spreadsheet):
        # Use a local database to cache labels retrieved from knowledgebase
        self.__label_cache = LabelDatabase()
        self.__map = {}
        if mapping_spreadsheet is not None:
            for sheet in openpyxl.load_workbook(FilePath(mapping_spreadsheet).get_BytesIO()):
                col_indices = {}
                for (n, row) in enumerate(sheet.rows):
                    if n == 0:
                        for cell in row:
                            if cell.value in ['Power point identifier',
                                              'Preferred ID',
                                              'UBERON ID']:
                                col_indices[cell.value] = cell.column - 1
                        if len(col_indices) < 3:
                            log.warn("Sheet '{}' doean't have a valid header row -- data ignored".format(sheet.title))
                            break
                    else:
                        pp_id = row[col_indices['Power point identifier']].value
                        preferred = row[col_indices['Preferred ID']].value
                        if preferred == '-': preferred = ''

                        uberon = row[col_indices['UBERON ID']].value
                        if uberon == '-': uberon = ''

                        if pp_id and (preferred or uberon):
                            self.__map[pp_id.strip()] = (preferred if preferred else uberon).strip()

    def properties(self, cls):
        props = {}
        if cls in self.__map:
            props['models'] = self.__map[cls]
            props['label'] = self.__label_cache.get_label(props['models'])
        else:
            props['label'] = cls
        return props

    def label(self, entity):
        return self.__label_cache.get_label(entity)
