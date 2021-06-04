Making a new release
====================

* Build documentation and then commit changes::

    $ cd docs
    $ sphinx-apidoc -f -o _source -e  ../mapmaker
    $ make html

* Update ``__version__`` in ``mapmaker/__init__.py``.
* Update the package name in ``README.rst`` to reflect the new version.
* Update ``README.rst`` with any changed usage instructions.
* Run ``$ pipenv-setup sync`` to update ``setup.py``.
* Commit ``mapmaker/__init__.py``, ``README.rst``, and ``setup.py``.
* With the new version identifier::

    $ git tag VERSION
    $ git push origin
    $ git push origin VERSION
    # We don't want untracked files bundled into the release
    $ git stash --include-untracked
    $ python setup.py bdist_wheel
    $ git stash pop

* On Github, at https://github.com/dbrnz/flatmap-maker/releases/new, create a release
  using the new VERSION tag and upload the generated wheel to it.