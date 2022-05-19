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

from pathlib import Path
import sqlite3

#===============================================================================

import mapknowledge

from mapmaker.settings import settings

#===============================================================================

KNOWLEDGE_BASE = 'knowledgebase.db'

LABELS_DB = 'labels.sqlite'

#===============================================================================

FLATMAP_SCHEMA = """
    begin;
    -- will auto convert datetime.datetime objects
    create table flatmaps(id text primary key, models text, created timestamp);
    create unique index flatmaps_index on flatmaps(id);
    create index flatmaps_models_index on flatmaps(models);

    create table flatmap_entities (flatmap text, entity text);
    create index flatmap_entities_flatmap_index on flatmap_entities(flatmap);
    create index flatmap_entities_entity_index on flatmap_entities(entity);
    commit;
"""

#===============================================================================

class KnowledgeStore(mapknowledge.KnowledgeStore):
    def __init__(self, store_directory, knowledge_base=KNOWLEDGE_BASE, create=True, read_only=False):
        new_db = not Path(store_directory, knowledge_base).resolve().exists()
        if create and new_db:
            super().__init__(store_directory,
                             knowledge_base=knowledge_base,
                             clean_connectivity=settings.get('cleanConnectivity', False),
                             create=create,
                             read_only=False)
            self.db.executescript(FLATMAP_SCHEMA)
            labels_db = Path(store_directory, LABELS_DB).resolve()
            if labels_db.exists():
                with self.db:
                    self.db.executemany('insert into labels(entity, label) values (?, ?)',
                        sqlite3.connect(labels_db).execute('select entity, label from labels').fetchall())
            if read_only:
                super().open(read_only=True)
        else:
            super().__init__(store_directory,
                             knowledge_base=knowledge_base,
                             clean_connectivity=settings.get('cleanConnectivity', False),
                             create=create,
                             read_only=read_only)

    def add_flatmap(self, flatmap):
    #==============================
        self.db.execute('begin')
        self.db.execute('replace into flatmaps(id, models, created) values (?, ?, ?)',
            (flatmap.id, flatmap.models, flatmap.created))
        self.db.execute('delete from flatmap_entities where flatmap=?', (flatmap.id, ))
        self.db.executemany('insert into flatmap_entities(flatmap, entity) values (?, ?)',
            ((flatmap.id, entity) for entity in flatmap.entities))
        self.db.commit()

    def flatmap_entities(self, flatmap):
    #===================================
        select = ['select distinct entity from flatmap_entities']
        if flatmap is not None:
            select.append('where flatmap=?')
        select.append('order by entity')
        if flatmap is not None:
            return [row[0] for row in self.db.execute(' '.join(select), (flatmap,))]
        else:
            return [row[0] for row in self.db.execute(' '.join(select))]

#===============================================================================

def get_label(entity):
    return get_knowledge(entity).get('label', entity)

def get_knowledge(entity):
    return settings['KNOWLEDGE_STORE'].entity_knowledge(entity)

def update_references(entity, publications):
    settings['KNOWLEDGE_STORE'].update_references(entity, publications)

#===============================================================================
