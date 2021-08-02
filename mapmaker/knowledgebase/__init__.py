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

import sqlite3
import datetime

from pathlib import Path

#===============================================================================

from mapmaker.utils import log

from .scicrunch import SciCrunch

#===============================================================================

KNOWLEDGE_BASE = 'knowledgebase.db'

LABELS_DB = 'labels.sqlite'

#===============================================================================

KNOWLEDGE_SCHEMA = """
    begin;
    -- will auto convert datetime.datetime objects
    create table flatmaps(id text primary key, models text, created timestamp);
    create unique index flatmaps_index on flatmaps(id);
    create index flatmaps_models_index on flatmaps(models);

    create table flatmap_entities (flatmap text, entity text);
    create index flatmap_entities_flatmap_index on flatmap_entities(flatmap);
    create index flatmap_entities_entity_index on flatmap_entities(entity);

    create table labels (entity text primary key, label text);
    create unique index labels_index on labels(entity);

    create table publications (entity text, publication text);
    create index publications_entity_index on publications(entity);
    create index publications_publication_index on publications(publication);
    commit;
"""

#===============================================================================

class KnowledgeBase(object):
    def __init__(self, store_directory):
        store = Path(store_directory, KNOWLEDGE_BASE)
        initialise = not store.exists()
        self.__db = sqlite3.connect(store, detect_types=sqlite3.PARSE_DECLTYPES|sqlite3.PARSE_COLNAMES)
        if initialise:
            self.__initialise(store_directory)
        self.__entity_knowledge = {}     # Cache lookups
        self.__scicrunch = SciCrunch()

    def close(self):
        self.__db.close()

    def __initialise(self, store_directory):
        self.__db.executescript(KNOWLEDGE_SCHEMA)
        labels_db = Path(store_directory, LABELS_DB)
        if labels_db.exists():
            with self.__db:
                self.__db.executemany('insert into labels(entity, label) values (?, ?)',
                    sqlite3.connect(labels_db).execute('select entity, label from labels').fetchall())

    #---------------------------------------------------------------------------

    def add_flatmap(self, flatmap):
        self.__db.execute('begin')
        self.__db.execute('replace into flatmaps(id, models, created) values (?, ?, ?)',
            (flatmap.id, flatmap.models, flatmap.created))
        self.__db.execute('delete from flatmap_entities where flatmap=?', (flatmap.id, ))
        self.__db.executemany('insert into flatmap_entities(flatmap, entity) values (?, ?)',
            ((flatmap.id, entity) for entity in flatmap.entities))
        self.__db.execute('commit')

    #---------------------------------------------------------------------------

    def entity_knowledge(self, entity):
        # First check local cache
        if entity in self.__entity_knowledge:
            return self.__entity_knowledge[entity]
        knowledge = {}
        row = self.__db.execute('select label from labels where entity=?', (entity,)).fetchone()
        if row is not None:
            knowledge['label'] = row[0]
        else:  # Consult SciCrunch if we don't know the entity's label
            knowledge = self.__scicrunch.get_knowledge(entity)
            if 'label' in knowledge:
                self.__db.execute('replace into labels values (?, ?)', (entity, knowledge['label']))
            # We don't return the list of publications to thenmap maker but just save them
            # in the knowledge base
            publications = knowledge.pop('publications', [])
            with self.__db:
                self.__db.execute('delete from publications where entity = ?', (entity, ))
                self.__db.executemany('insert into publications(entity, publication) values (?, ?)',
                    ((entity, publication) for publication in publications))
        # Use the entity's value as its label if none is defined
        if 'label' not in knowledge:
            knowledge['label'] = entity
        # Cache local knowledge
        self.__entity_knowledge[entity] = knowledge

        return knowledge

#===============================================================================
