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

from typing import Any, Optional

#===============================================================================

# Exports
from flatmapknowledge import KnowledgeStore

#===============================================================================

from mapmaker.settings import settings

#===============================================================================

class AnatomicalNode(tuple):
    def __new__ (cls, termlist: list):
        return super().__new__(cls, (termlist[0], tuple(termlist[1])))

    @property
    def name(self) -> str:
        return '/'.join(reversed((self[0],) + self[1]))

    @property
    def full_name(self) -> str:
        if len(self[1]) == 0:
            return entity_name(self[0])
        else:
            layer_names = ', '.join([entity_name(entity) for entity in self[1] if entity is not None])
            return f'{entity_name(self[0])} in {layer_names}'

    def normalised(self):
        return (self[0], *self[1])

    ## We need to get the label for each anatomical term in the list of nodes
    ## as they may be looked up by the viewer in upstream/downstream code...

#===============================================================================

def connectivity_models(source: str) -> dict[str, dict[str, str]]:
    return settings['KNOWLEDGE_STORE'].connectivity_models(source)

def get_label(entity: str) -> str:
    return get_knowledge(entity).get('label', entity)

def get_knowledge(entity: str) -> dict[str, Any]:
    return settings['KNOWLEDGE_STORE'].entity_knowledge(entity)

def sckan_build() -> Optional[dict]:
    if (scicrunch := settings['KNOWLEDGE_STORE'].scicrunch) is not None:
        return scicrunch.build()

#===============================================================================

def entity_name(entity: Optional[str]) -> str:
    if entity is None:
        return 'None'
    return get_label(entity)

#===============================================================================
