#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020 - 2022 David Brooks
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

from typing import Self, TypeVar

T = TypeVar('T')

#===============================================================================

class TreeList(list[T|'TreeList[T]']):
    """
    A ``tree`` structure implemented as a list with branches (sub-trees) being embedded lists.
    """

    def __getitem__(self, key):
        return super().__getitem__(key)

    def append(self, element: T|'TreeList[T]'):
        super().append(element)

    def flatten(self, skip=0) -> list[T]:
        """
        Return leaves of the tree as a ``list`` in depth-first order.
        """
        flattened = []
        for element in self[skip:]:
            if isinstance(element, TreeList):
                flattened.extend(element.flatten(skip=skip))
            else:
                flattened.append(element)
        return flattened

#===============================================================================
