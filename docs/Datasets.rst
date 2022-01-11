========
Datasets
========

Flatmap sources held in the Physiome Model Repository (PMR) may be exported as a SPARC Dataset provided a JSON-formatted file describing the sources is referenced from the flatmap's manifest. The JSON description provides values for the resulting ``description.xlsx`` file in the exported dataset. An example:

.. code-block:: json

    {
        "title": "Rat flatmap",
        "description": "Files for the rat flatmap.",
        "species": "NCBITaxon:10114",
        "keywords": [
            "SPARC",
            "flatmap",
            "rattus"
        ],
        "contributors": [
            {
                "name": "Brooks, David",
                "orcid": "0000-0002-6758-2186",
                "affiliation": "Auckland Bioengineering Institute",
                "role": "Creator",
                "contact": "Yes"
            },
            {
                "name": "Ebrahimi, Nazanin",
                "orcid": "0000-0001-7183-2638",
                "affiliation": "Auckland Bioengineering Institute",
                "role": "Creator",
                "contact": "Yes"
            },
            {
                "name": "Hunter, Peter",
                "orcid": "0000-0001-9665-4145",
                "affiliation": "Auckland Bioengineering Institute",
                "role": "Principle Investigator"
            }
        ],
        "funding": "OT3OD025349"
    }


The JSON description is referred to in the flatmap's manifest with the key ``description``. Assuming the above is saved as ``description.json``, the manifest would contain:

.. code-block:: json

    {

        "description": "description.json",

    }