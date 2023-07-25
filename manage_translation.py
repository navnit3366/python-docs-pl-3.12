#!/usr/bin/env python
#
# This python file contains utility scripts to manage Python docs Polish translation.
# It has to be run inside the python-docs-pl git root directory.
#
# Inspired by django-docs-translations script by claudep.
#
# The following commands are available:
#
# * fetch: fetch translations from transifex.com and strip source lines from the
#          files.
# * recreate_tx_config: recreate configuration for all resources.

from argparse import ArgumentParser
import os
from contextlib import chdir
from dataclasses import dataclass
from difflib import SequenceMatcher
from itertools import combinations
from pathlib import Path
from subprocess import call
import sys
from tempfile import TemporaryDirectory
from typing import Self, Generator, Iterable
from warnings import warn

from polib import pofile
from transifex.api import transifex_api

LANGUAGE = 'pl'


def fetch():
    """
    Fetch translations from Transifex, remove source lines.
    """
    if (code := call("tx --version", shell=True)) != 0:
        sys.stderr.write("The Transifex client app is required.\n")
        exit(code)
    lang = LANGUAGE
    _call(f'tx pull -l {lang} --minimum-perc=1 --force --skip')
    for file in Path().rglob('*.po'):
        _call(f'msgcat --no-location -o {file} {file}')


def _call(command: str):
    if (return_code := call(command, shell=True)) != 0:
        exit(return_code)


PROJECT_SLUG = 'python-newest'
VERSION = '3.12'


def recreate_tx_config():
    """
    Regenerate Transifex client config for all resources.
    """
    with TemporaryDirectory() as directory:
        with chdir(directory):
            _clone_cpython_repo(VERSION)
            _build_gettext()
            with chdir(Path(directory) / 'cpython/Doc/locales'):
                _create_txconfig()
                _update_txconfig_resources()
                with open('.tx/config', 'r') as file:
                    contents = file.read()
        contents = contents.replace('./<lang>/LC_MESSAGES/', '')
        with open('.tx/config', 'w') as file:
            file.write(contents)


def _clone_cpython_repo(version: str):
    _call(f'git clone -b {version} --single-branch https://github.com/python/cpython.git --depth 1')


def _build_gettext():
    _call(
        "make -C cpython/Doc/ ALLSPHINXOPTS='-E -b gettext -D gettext_compact=0 -d build/.doctrees . locales/pot' build"
    )


def _create_txconfig():
    _call('sphinx-intl create-txconfig')


def _update_txconfig_resources():
    _call(
        f'sphinx-intl update-txconfig-resources --transifex-organization-name python-doc '
        f'--transifex-project-name={PROJECT_SLUG} --locale-dir . --pot-dir pot'
    )


@dataclass
class ResourceLanguageStatistics:
    name: str
    total_words: int
    translated_words: int
    total_strings: int
    translated_strings: int

    @classmethod
    def from_api_entry(cls, data: transifex_api.ResourceLanguageStats) -> Self:
        return cls(
            name=data.id.removeprefix(f'o:python-doc:p:{PROJECT_SLUG}:r:').removesuffix(f':l:{LANGUAGE}'),
            total_words=data.attributes['total_words'],
            translated_words=data.attributes['translated_words'],
            total_strings=data.attributes['total_strings'],
            translated_strings=data.attributes['translated_strings'],
        )


def _get_tx_token() -> str:
    if os.path.exists('.tx/api-key'):
        with open('.tx/api-key') as f:
            transifex_api_key = f.read()
    else:
        transifex_api_key = os.getenv('TX_TOKEN', '')
    return transifex_api_key


def _get_resources() -> list[transifex_api.Resource]:
    transifex_api.setup(auth=_get_tx_token())
    return transifex_api.Resource.filter(project=f'o:python-doc:p:{PROJECT_SLUG}').all()


def get_resource_language_stats() -> list[ResourceLanguageStatistics]:
    transifex_api.setup(auth=_get_tx_token())
    resources = transifex_api.ResourceLanguageStats.filter(
        project=f'o:python-doc:p:{PROJECT_SLUG}', language=f'l:{LANGUAGE}'
    ).all()
    return [ResourceLanguageStatistics.from_api_entry(entry) for entry in resources]


def progress_from_resources(resources: Iterable[ResourceLanguageStatistics]) -> float:
    pairs = ((e.translated_words, e.total_words) for e in resources)
    translated_total, total_total = (sum(counts) for counts in zip(*pairs))
    return translated_total / total_total * 100


def get_number_of_translators():
    translators = set(_fetch_translators())
    _remove_bot(translators)
    _check_for_aliases(translators)
    return len(translators)


def _fetch_translators() -> Generator[str, None, None]:
    for file in Path().rglob('*.po'):
        header = pofile(file).header.splitlines()
        for translator_record in header[header.index('Translators:') + 1:]:
            translator, _year = translator_record.split(', ')
            yield translator


def _remove_bot(translators: set[str]) -> None:
    translators.remove("Transifex Bot <>")


def _check_for_aliases(translators) -> None:
    for pair in combinations(translators, 2):
        if (ratio := SequenceMatcher(lambda x: x in '<>@', *pair).ratio()) > 0.64:
            warn(
                f"{pair} are similar ({ratio:.3f}). Please add them to aliases list or bump the limit."
            )


def language_switcher(entry: ResourceLanguageStatistics) -> bool:
    language_switcher_resources_prefixes = ('bugs', 'tutorial', 'library--functions')
    return any(entry.name.startswith(prefix) for prefix in language_switcher_resources_prefixes)


if __name__ == "__main__":
    RUNNABLE_SCRIPTS = ('fetch', 'recreate_tx_config')

    parser = ArgumentParser()
    parser.add_argument('cmd', choices=RUNNABLE_SCRIPTS)
    options = parser.parse_args()

    eval(options.cmd)()
