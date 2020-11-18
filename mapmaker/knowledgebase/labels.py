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

import os
import sqlite3

#===============================================================================

import openpyxl
import requests

#===============================================================================

ILX_ENDPOINT = 'http://uri.interlex.org/base/ilx_{:0>7}.json'

VOCAB_ENDPOINT = 'https://scigraph.olympiangods.org/scigraph/vocabulary/id/{}.json'
SCIGRAPH_ONTOLOGIES = ['UBERON']

#===============================================================================

class LabelDatabase(object):
    def __init__(self, map_base, refresh=False):
        database = os.path.join(map_base, 'labels.sqlite')
        if refresh:
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
        label = entity
        ontology = entity.split(':')[0]
        if ontology in SCIGRAPH_ONTOLOGIES:
            try:
                response = requests.get(VOCAB_ENDPOINT.format(entity))
                if response:
                    label = response.json().get('labels', [entity])[0]
                    self.set_label(entity, label)
            except:
                print("Couldn't access", VOCAB_ENDPOINT.format(entity))
        elif ontology == 'ILX':
            endpoint = ILX_ENDPOINT.format(entity.strip().split(':')[-1])
            try:
                response = requests.get(endpoint)
                if response:
                    triples = response.json().get('triples')
                    for triple in triples:
                        if triple[1] == 'rdfs:label':
                            self.set_label(entity, triple[2])
            except:
                print("Couldn't access {} for {}".format(endpoint, entity))
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
    def __init__(self, mapping_spreadsheet, label_database):
        self.__label_data = label_database
        self.__map = {}
        if mapping_spreadsheet is not None:
            for sheet in openpyxl.load_workbook(mapping_spreadsheet):
                col_indices = {}
                for (n, row) in enumerate(sheet.rows):
                    if n == 0:
                        for cell in row:
                            if cell.value in ['Power point identifier',
                                              'Preferred ID',
                                              'UBERON ID']:
                                col_indices[cell.value] = cell.column - 1
                        if len(col_indices) < 3:
                            print("Sheet '{}' doean't have a valid header row -- data ignored".format(sheet.title))
                            break
                    else:
                        pp_id = row[col_indices['Power point identifier']].value
                        preferred = row[col_indices['Preferred ID']].value
                        if preferred == '-': preferred = ''

                        uberon = row[col_indices['UBERON ID']].value
                        if uberon == '-': uberon = ''

                        if pp_id and (preferred or uberon):
                            self.__map[pp_id.strip()] = (preferred if preferred else uberon).strip()
        #print(self.__map)

    def properties(self, cls):
        props = {}
        if cls in self.__map:
            props['models'] = self.__map[cls]
            props['label'] = self.__label_data.get_label(props['models'])
        else:
            props['label'] = cls
        return props

    def label(self, entity):
        return self.__label_data.get_label(entity)
