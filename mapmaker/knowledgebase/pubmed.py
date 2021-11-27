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

import os

import time

#===============================================================================

import requests
import xmltodict

#===============================================================================

NCBI_API_KEY = os.environ.get('NCBI_API_KEY')

PUBMED_SUMMARY_ENDPOINT = 'https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi'

PUBMED_IDS = ['pmid', 'pubmed']

#===============================================================================

# Now more than 9 lookups per second...
LOOKUP_PERIOD = 0.11

last_lookup = time.time()

#===============================================================================

def pubmed_knowledge(entity):
    knowledge = {
        'id': entity
    }
    parts = entity.split(':')
    if len(parts) == 2 and parts[0].lower() in PUBMED_IDS:
        # We need to rate limit use of the PubMed service
        global last_lookup
        now = time.time()
        if (now - last_lookup) < LOOKUP_PERIOD:
            time.sleep(LOOKUP_PERIOD - (now - last_lookup))
        last_lookup = now
        print(entity)
        response = requests.get(
            PUBMED_SUMMARY_ENDPOINT,
            params = {
                'db': 'pubmed',
                'id': parts[1],
                'api_key': NCBI_API_KEY
            })
        if response.status_code == requests.codes.ok:
            summary = xmltodict.parse(response.text)
            authors = []
            for item in summary['eSummaryResult']['DocSum']['Item']:
                if   item['@Name'] == 'PubDate':
                    knowledge['date'] = item['#text']
                if   item['@Name'] == 'Source':
                    knowledge['source'] = item['#text']
                elif item['@Name'] == 'AuthorList':
                    for author in item['Item']:
                        if author['@Name'] == 'Author':
                            authors.append(author['#text'])
                elif item['@Name'] == 'Title':
                    knowledge['title'] = item['#text']
                elif item['@Name'] == 'ArticleIds':
                    for article in item['Item']:
                        if article['@Name'] == 'doi':
                            knowledge['doi'] = 'https://doi.org/' + article['#text']
                            break
            if len(authors):
                knowledge['authors'] = authors
    return knowledge

#===============================================================================

if __name__ == '__main__':

    from pprint import pprint

    pprint(pubmed_knowledge('PUBMED:2713886'))

#===============================================================================
