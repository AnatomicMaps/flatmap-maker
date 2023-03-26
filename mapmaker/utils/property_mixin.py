#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020 - 2023 David Brooks
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

class PropertyMixin:
    def __init__(self, properties: Optional[dict[str, Any]]=None):
        self.__properties = {}
        if properties is not None:
            self.__properties.update(properties)

    @property
    def properties(self):
        return self.__properties

    def pop_property(self, key: str, default: Any=None) -> Any:
        return self.__properties.pop(key, default)

    def get_property(self, key: str, default: Any=None) -> Any:
        return self.__properties.get(key, default)

    def has_property(self, key: str) -> bool:
        return self.__properties.get(key, '') != ''

    def set_property(self, key: str, value: Any) -> None:
        if value is None:
            self.pop_property(key)
        else:
            self.__properties[key] = value

#===============================================================================
