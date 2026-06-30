#===============================================================================
#
#  Flatmap viewer and annotation tools
#
#  Copyright (c) 2020, 2021  David Brooks
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

import cssselect2
import tinycss2

#===============================================================================

from mapmaker.utils import log

#===============================================================================

UNIMPLEMENTED_STYLE_ATTRIBUTES = ['filter']

# See https://developer.mozilla.org/en-US/docs/Web/SVG/Reference/Element/g#attributes
GEOMETRIC_STYLE_ATTRIBUTES = [
    'cx', 'cy', 'r',
    'rx', 'ry',
    'd',
    'x', 'y', 'width', 'height'
]

NON_INHERITED_STYLE_ATTRIBUTES = GEOMETRIC_STYLE_ATTRIBUTES + [
    'id', 'class'
]

# See https://developer.mozilla.org/en-US/docs/Web/SVG/Reference/Attribute#presentation_attributes
PRESENTATION_STYLE_ATTRIBUTES = [
    'alignment-baseline', 'baseline-shift', 'clip', 'clip-path', 'clip-rule', 'color',
    'color-interpolation', 'color-interpolation-filters', 'cursor', 'direction', 'display',
    'dominant-baseline', 'fill', 'fill-opacity', 'fill-rule', 'filter', 'flood-color',
    'flood-opacity', 'font-family', 'font-size', 'font-size-adjust', 'font-stretch',
    'font-style', 'font-variant', 'font-weight', 'font-width', 'glyph-orientation-horizontal',
    'glyph-orientation-vertical', 'image-rendering', 'letter-spacing', 'lighting-color',
    'marker-end', 'marker-mid', 'marker-start', 'mask', 'mask-type', 'opacity', 'overflow',
    'pointer-events', 'shape-rendering', 'stop-color', 'stop-opacity', 'stroke', 'stroke-dasharray',
    'stroke-dashoffset', 'stroke-linecap', 'stroke-linejoin', 'stroke-miterlimit', 'stroke-opacity',
    'stroke-width', 'text-anchor', 'text-decoration', 'text-overflow', 'text-rendering',
    'transform', 'transform-origin', 'unicode-bidi', 'vector-effect', 'visibility', 'white-space',
    'word-spacing', 'writing-mode'
]


#===============================================================================

class ElementStyleDict(dict):
    def __init__(self, element, style_dict={}):
        super().__init__(style_dict)   # Copies dict
        attributes = dict(element.attrib)
        if 'style' in attributes:
            style_attribute = attributes.pop('style')
            local_style = {}
            for declaration in tinycss2.parse_declaration_list(
                style_attribute,
                skip_comments=True, skip_whitespace=True):
                local_style[declaration.lower_name] = ' '.join(
                    [t.serialize() for t in declaration.value])
            super().update(local_style)
        for key, value in attributes.items():
            if key not in GEOMETRIC_STYLE_ATTRIBUTES:
                if key not in PRESENTATION_STYLE_ATTRIBUTES or key not in self:
                    self[key] = value

#===============================================================================

class StyleMatcher(cssselect2.Matcher):
    '''Parse CSS and add rules to the matcher.'''
    def __init__(self, style_element):
        super().__init__()
        rules = tinycss2.parse_stylesheet(style_element.text
                    if style_element is not None else '',
                    skip_comments=True, skip_whitespace=True)
        for rule in rules:
            selectors = cssselect2.compile_selector_list(rule.prelude)
            declarations = [obj for obj in tinycss2.parse_declaration_list(
                                               rule.content,
                                               skip_whitespace=True)
                            if obj.type == 'declaration']
            for selector in selectors:
                self.add_selector(selector, declarations)

    def __match(self, element):
    #==========================
        styling = {}
        matches = super().match(element)
        if matches:
            for match in matches:
                specificity, order, pseudo, declarations = match
                for declaration in declarations:
                    styling[declaration.lower_name] = declaration.value
        return styling

    def element_style(self, wrapped_element, parent_style=None) -> ElementStyleDict:
    #===============================================================================
        if parent_style is None:
            element_style = {}
        else:
            element_style = { key: value for key, value in parent_style.items()
                                if key not in NON_INHERITED_STYLE_ATTRIBUTES}
        for key, value in self.__match(wrapped_element).items():
            if key in UNIMPLEMENTED_STYLE_ATTRIBUTES:
                log.warning("'{}: {}' not implemented".format(key, value))
            else:
                element_style[key] = ' '.join([t.serialize() for t in value])
        element_style = ElementStyleDict(wrapped_element.etree_element, element_style)
        if (color := element_style.get('color')) is not None:
            element_style['currentColor'] = color
        if parent_style is not None:
            if element_style.get('fill') == 'currentColor':
                element_style['fill'] = parent_style.get('fill', element_style.get('currentColor'))
            if element_style.get('stroke') == 'currentColor':
                element_style['stroke'] = parent_style.get('stroke', element_style.get('currentColor'))
        return element_style

#===============================================================================

def wrap_element(element) -> cssselect2.ElementWrapper:
#======================================================
    return cssselect2.ElementWrapper.from_xml_root(element)

#===============================================================================
