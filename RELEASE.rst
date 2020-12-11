Making a new release
====================

* Update `__version__` in `mapmaker/__init__.py`.
* Update the package name in `README.rst` to reflect the new version.
* Update `README.rst` with any changed usage instructions.
* Run `$ pipenv-setup sync` to update `setup.py`.
* Commit `mapmaker/__init__.py`, `README.rst`, and `setup.py`.
* `$ git tag VERSION` with the new version.
* `$ git push dbrnz`
* `$ git push dbrnz VERSION`
* `$ git stash --include-untracked` so that no untracked files are bundled in the release.
* `$ python setup.py bdist_wheel`.
* On Github create a new release using the new VERSION tag and upload the generated wheel to the release.