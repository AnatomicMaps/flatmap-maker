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

from pyparsing import alphanums, nums, printables, Combine, delimitedList, Group, Keyword
from pyparsing import Optional, ParseException, Suppress, Word, ZeroOrMore, ParseResults

#===============================================================================

class Parser(object):
    FREE_TEXT = Word(printables + ' ', excludeChars='()')
    INTEGER = Word(nums)

    ID_TEXT = Word(alphanums, alphanums+':/_-.')

    ONTOLOGY_SUFFIX = (Keyword('ABI')
                     | Keyword('FM')
                     | Keyword('FMA')
                     | Keyword('ILX')
                     | Keyword('MA')
                     | Keyword('NCBITaxon')
                     | Keyword('UBERON')
                     )
    ONTOLOGY_ID = Combine(ONTOLOGY_SUFFIX + ':' + ID_TEXT)

    IDENTIFIER = Group(Keyword('id') + Suppress('(') + ID_TEXT + Suppress(')'))
    MODELS = Group(Keyword('models') + Suppress('(') + ONTOLOGY_ID + Suppress(')'))
    ZOOM_LEVEL = INTEGER

#===============================================================================

    BACKGROUND = Group(Keyword('background-for') + Suppress('(') + ID_TEXT + Suppress(')'))
    DESCRIPTION = Group(Keyword('description') + Suppress('(') + FREE_TEXT + Suppress(')'))
    OUTLINE = Group(Keyword('outline') + Suppress('(') + ID_TEXT + Suppress(')'))
    SELECTION_FLAGS = Group(Keyword('not-selectable') | Keyword('selected') | Keyword('queryable'))
    ZOOM = Group(Keyword('zoom') + Suppress('(')
                                   + Group(ZOOM_LEVEL + Suppress(',') + ZOOM_LEVEL + Suppress(',') + ZOOM_LEVEL)
                                 + Suppress(')'))

    LAYER_DIRECTIVES = BACKGROUND | DESCRIPTION | IDENTIFIER | MODELS | OUTLINE | SELECTION_FLAGS | ZOOM
    LAYER_DIRECTIVE = '.' + ZeroOrMore(LAYER_DIRECTIVES)

#===============================================================================

    @staticmethod
    def layer_directive(s):
        result = {}
        try:
            parsed = Parser.LAYER_DIRECTIVE.parseString(s, parseAll=True)
            result['selectable'] = True
            for directive in parsed[1:]:
                if directive[0] == 'not-selectable':
                    result['selectable'] = False
                elif Parser.SELECTION_FLAGS.matches(directive[0]):
                    result[directive[0]] = True
                elif directive[0] == 'zoom':
                    result['zoom'] = [int(z) for z in directive[1]]
                else:
                    result[directive[0]] = directive[1]

        except ParseException:
            result['error'] = 'Syntax error in layer directive'
        return result

#===============================================================================

#    LABEL = Group(Keyword('label') + Suppress('(') + FREE_TEXT + Suppress(')'))
#    LAYER = Group(Keyword('layer') + Suppress('(') + ONTOLOGY_ID + Suppress(')'))
    ## WIP: DETAILS = Group(Keyword('details') + Suppress('(') + Suppress(')'))  ## Zoom start, slide/layer ID
    ## Details are positioned within polygon's boundary on a layer "above" the polygon's
    ## fill layer. Say positioned on an invisible place holder that is grouped with the polygon??

    CLASS = Group(Keyword('class') + Suppress('(') + ID_TEXT + Suppress(')'))
    DETAILS = Group(Keyword('details') + Suppress('(') + ID_TEXT + Suppress(',') + ZOOM_LEVEL + Suppress(')'))
    PATH = Group(Keyword('path') + Suppress('(') + ID_TEXT + Suppress(')'))
    STYLE = Group(Keyword('style') + Suppress('(') + INTEGER + Suppress(')'))

    FEATURE_PROPERTIES = CLASS | IDENTIFIER | STYLE

    SHAPE_FLAGS = Group(Keyword('boundary')
                      | Keyword('children')
                      | Keyword('closed')
                      | Keyword('interior')
                      )

    DEPRECATED_FLAGS = Group(Keyword('siblings')
                           | Keyword('marker')
                           )

    FEATURE_FLAGS = Group(Keyword('group')
                        | Keyword('invisible')
                        | Keyword('divider')
                        | Keyword('region')
                      )

    SHAPE_MARKUP = '.' + ZeroOrMore(DEPRECATED_FLAGS
                                  | DETAILS
                                  | FEATURE_FLAGS
                                  | FEATURE_PROPERTIES
                                  | PATH
                                  | SHAPE_FLAGS)

#===============================================================================

    @staticmethod
    def shape_markup(name_text):
        markup = {}
        try:
            parsed = Parser.SHAPE_MARKUP.parseString(name_text, parseAll=True)
            for prop in parsed[1:]:
                if (Parser.FEATURE_FLAGS.matches(prop[0])
                 or Parser.SHAPE_FLAGS.matches(prop[0])):
                    markup[prop[0]] = True
                elif Parser.DEPRECATED_FLAGS.matches(prop[0]):
                    markup['warning'] = "'{}' property is deprecated".format(prop[0])
                elif prop[0] == 'details':
                    markup[prop[0]] = prop[1]
                    markup['maxzoom'] = int(prop[2]) - 1
                else:
                    markup[prop[0]] = prop[1]
        except ParseException:
            markup['error'] = 'Syntax error in shape markup'
        return markup

    @staticmethod
    def ignore_property(name):
        return Parser.DEPRECATED_FLAGS.matches(name) or Parser.SHAPE_FLAGS.matches(name)

#===============================================================================

    NERVES = delimitedList(ID_TEXT)

    PATH_LINES_GROUP = ID_TEXT  | Group(Suppress('(') +  delimitedList(ID_TEXT) + Suppress(')'))
    PATH_LINES = delimitedList(PATH_LINES_GROUP)

    ROUTE_NODE_GROUP = ID_TEXT  | Group(Suppress('(') +  delimitedList(ID_TEXT) + Suppress(')'))
    ROUTE_NODES = delimitedList(ROUTE_NODE_GROUP)

#===============================================================================

    @staticmethod
    def path_lines(line_ids):
        try:
            path_lines = Parser.PATH_LINES.parseString(line_ids, parseAll=True)
        except ParseException:
            raise ValueError('Syntax error in path lines list: {}'.format(line_ids))
        return path_lines

    @staticmethod
    def route_nodes(node_ids):
        try:
            route_nodes = Parser.ROUTE_NODES.parseString(node_ids, parseAll=True)
        except ParseException:
            raise ValueError('Syntax error in route node list: {}'.format(node_ids))
        return route_nodes

    @staticmethod
    def nerves(node_ids):
        try:
            nerves = Parser.NERVES.parseString(node_ids, parseAll=True)
        except ParseException:
            raise ValueError('Syntax error in nerve list: {}'.format(node_ids))
        return nerves

#===============================================================================

if __name__ == '__main__':

    def test(method, text):
        parsed = method(text)
        print('{} --> {}'.format(text, parsed))

    test(Parser.layer_directive, '.id(LAYER) models(NCBITaxon:1)')
    test(Parser.layer_directive, '.selected')
    test(Parser.shape_properties, '.boundary')
    test(Parser.shape_properties, '.id(ID) class(FEATURE)')
    test(Parser.shape_properties, '.models(FM:1)')
    test(Parser.shape_properties, '.models(FMA:1)')
    test(Parser.shape_properties, '.models(UBERON:1)')
    test(Parser.shape_properties, '.models (N1)')

    test(Parser.shape_properties, '.path(P1, P2, P3, P4, P5, P6, P7, P8)')
    test(Parser.shape_properties, '.route(urinary_5, keast_2, S50_L6_B, S50_L6_T, S45_L6, C1, S44_L6)')
    test(Parser.shape_properties, '.route(urinary_5, keast_2, S50_L6_B, S50_L6_T, S45_L6, C1, S44_L6, (S42_L6, S38_L6, S37_L6, S34_L6, S33_L6, S42_L6))')
    test(Parser.shape_properties, '.path(P1, P2, P3, P4, P5, P6, P7, P8) route (urinary_5, keast_2, S50_L6_B, S50_L6_T, S45_L6, C1, S44_L6, (S42_L6, S38_L6, S37_L6, S34_L6, S33_L6, S42_L6))')

#===============================================================================
